"""
batch_manager.py — Batch download manager.

Features:
  - Import URLs from a plain text file (one URL per line)
  - Import from a JSON file [{url, mode, quality, ...}]
  - Save a queue to JSON for resuming later
  - Resume a previously saved queue
  - Download all imported URLs with a chosen mode
  - Per-URL mode or uniform mode for all
  - Progress tracking and summary#
"""

import json
import os
from time import sleep

import colorama
from colorama import Fore

from utilities import (
    clear_screen, get_cookies, ask_use_aria2c, handle_error,
    ensure_writable_dir, resolve_path, log_download, notify, _fmt_duration,
)
from download_logic import (
    download_video_audio, download_audio_only,
    download_subtitles, download_video_audio_subtitles,
    fetch_info, select_playlist_entries,
)
from colours import get_next_colour

colorama.init(autoreset=True)

QUEUE_DIR = os.path.join(os.path.expanduser('~'), '.stream_scoop_queues')


# ─────────────────────────────────────────────────────────────────
#  File import helpers
# ─────────────────────────────────────────────────────────────────

def _load_txt(path: str) -> list:
    """Load one URL per line from a text file. Skip comments (#) and blanks."""
    urls = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                urls.append({'url': line, 'mode': None})
    return urls


def _load_json(path: str) -> list:
    """
    Load a JSON file. Accepts either:
      - A list of strings (URLs)
      - A list of dicts with at least {'url': '...'}
    """
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("JSON file must contain a top-level list.")

    items = []
    for entry in data:
        if isinstance(entry, str):
            items.append({'url': entry, 'mode': None})
        elif isinstance(entry, dict) and 'url' in entry:
            items.append({
                'url':     entry['url'],
                'mode':    entry.get('mode'),
                'quality': entry.get('quality'),
                'note':    entry.get('note', ''),
            })
        else:
            print(Fore.YELLOW + f"  Skipping invalid entry: {str(entry)[:60]}")
    return items


def _import_from_file(file_path: str) -> list:
    """Auto-detect format and load URLs."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.json':
        return _load_json(file_path)
    else:
        return _load_txt(file_path)


# ─────────────────────────────────────────────────────────────────
#  Queue persistence
# ─────────────────────────────────────────────────────────────────

def _list_saved_queues() -> list:
    if not os.path.isdir(QUEUE_DIR):
        return []
    return [f for f in os.listdir(QUEUE_DIR) if f.endswith('.json')]


def _save_queue(name: str, items: list, save_path: str, mode: str) -> str:
    os.makedirs(QUEUE_DIR, exist_ok=True)
    safe = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in name)[:40]
    path = os.path.join(QUEUE_DIR, f"{safe}.json")
    payload = {
        'name':      name,
        'save_path': save_path,
        'mode':      mode,
        'items':     items,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    return path


def _load_queue(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────
#  Expand playlists in item list
# ─────────────────────────────────────────────────────────────────

def _expand_items(items: list, cookie_file) -> list:
    import yt_dlp as YT
    expanded = []
    for item in items:
        url = item['url']
        print(Fore.LIGHTBLACK_EX + f"  Resolving: {url[:60]}…")
        try:
            opts = {'quiet': True, 'extract_flat': 'in_playlist'}
            if cookie_file:
                opts['cookiefile'] = cookie_file
            with YT.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if 'entries' in info:
                entries = [e for e in info['entries'] if e.get('url')]
                print(Fore.LIGHTGREEN_EX
                      + f"    Playlist: {len(entries)} videos — \"{info.get('title','')}\"")
                entries = select_playlist_entries(entries)
                for e in entries:
                    expanded.append({
                        'url':     e['url'],
                        'mode':    item.get('mode'),
                        'quality': item.get('quality'),
                        'note':    e.get('title', ''),
                    })
            else:
                title = info.get('title', url[:40])
                print(Fore.GREEN + f"    ✓ {title[:50]}")
                item['note'] = item.get('note') or title
                expanded.append(item)

        except Exception as e:
            print(Fore.YELLOW + f"    Could not resolve ({e}), using URL as-is.")
            expanded.append(item)

    return expanded


# ─────────────────────────────────────────────────────────────────
#  Download execution
# ─────────────────────────────────────────────────────────────────

def _run_batch(items: list, save_path: str, mode: str, cfg: dict,
               cookie_file, use_aria2c: bool) -> tuple:
    """
    Run all items with the given mode.
    Returns (success_count, fail_count).
    """
    total   = len(items)
    success = 0
    failed  = 0

    for n, item in enumerate(items, 1):
        url       = item['url']
        item_mode = item.get('mode') or mode
        note      = item.get('note', url[:50])

        print(Fore.CYAN + f"\n{'─'*60}")
        print(Fore.CYAN + f"  [{n}/{total}] " + Fore.WHITE + note[:50])
        print(Fore.LIGHTBLACK_EX + f"  Mode: {item_mode}  |  URL: {url[:50]}")
        print(Fore.CYAN + "─" * 60)

        auto_q = item.get('quality')
        if auto_q and isinstance(auto_q, str):
            try:
                auto_q = int(str(auto_q).replace('p', ''))
            except ValueError:
                auto_q = None

        try:
            if item_mode == 'video':
                download_video_audio(url, save_path, cfg, cookie_file,
                                     use_aria2c, auto_quality=auto_q)
            elif item_mode == 'audio':
                download_audio_only(url, save_path, cfg, cookie_file, use_aria2c)
            elif item_mode == 'subtitles':
                download_subtitles(url, save_path, cfg, cookie_file)
            elif item_mode == 'video+subs':
                download_video_audio_subtitles(url, save_path, cfg, cookie_file, use_aria2c)
            else:
                # default to video
                download_video_audio(url, save_path, cfg, cookie_file,
                                     use_aria2c, auto_quality=auto_q)
            success += 1
        except Exception as e:
            handle_error(e)
            print(Fore.YELLOW + "  Continuing with next item…")
            failed += 1

        if cfg.get('sleep_interval') and n < total:
            interval = cfg['sleep_interval']
            print(Fore.LIGHTBLACK_EX + f"  Waiting {interval}s before next download…")
            sleep(interval)

    return success, failed


# ─────────────────────────────────────────────────────────────────
#  Interactive prompts
# ─────────────────────────────────────────────────────────────────

def _choose_mode() -> str:
    print(Fore.YELLOW + "\n  Download mode for all items:")
    print(Fore.WHITE  + "    [1] Video  [2] Audio only  [3] Subtitles  [4] Video+Subs  [5] Per-URL")
    while True:
        m = input(Fore.WHITE + "  Choice (1): ").strip() or '1'
        if m in ('1', '2', '3', '4', '5'):
            return {'1': 'video', '2': 'audio', '3': 'subtitles', '4': 'video+subs', '5': 'per-url'}[m]
        print(Fore.RED + "  Enter 1–5.")


def _get_save_path(cfg: dict) -> str:
    default = cfg.get('default_path',
                      os.path.join(os.path.expanduser('~'), 'Downloads', 'StreamScoop'))
    print(Fore.LIGHTBLUE_EX + f"\nDefault download path: {default}")
    c = input("Use default? (Y/n): ").strip().lower()
    if c in ('n', 'no'):
        raw = input(Fore.WHITE + "Custom path: ").strip()
        path = resolve_path(raw)
    else:
        path = default
    if not ensure_writable_dir(path):
        print(Fore.YELLOW + f"Cannot write to '{path}'. Using default.")
        ensure_writable_dir(default)
        return default
    return path


def _show_item_list(items: list) -> None:
    print(Fore.CYAN + f"\n  {'#':>4}  {'Mode':<12}  {'Quality':<8}  URL / Title")
    print(Fore.LIGHTBLACK_EX + "  " + "─" * 70)
    for i, item in enumerate(items, 1):
        mode = item.get('mode') or '(default)'
        q    = str(item.get('quality') or '—')
        note = item.get('note') or item['url'][:50]
        col  = get_next_colour()
        print(col + f"  {i:>4}. {mode:<12}  {q:<8}  {note[:50]}")
    print(Fore.LIGHTBLACK_EX + "  " + "─" * 70)
    print(Fore.LIGHTBLACK_EX + f"  Total: {len(items)} item(s)")


# ─────────────────────────────────────────────────────────────────
#  Resume saved queue
# ─────────────────────────────────────────────────────────────────

def _resume_queue_menu(cfg: dict, aria2c_ok: bool) -> None:
    queues = _list_saved_queues()
    if not queues:
        print(Fore.YELLOW + "\n  No saved queues found.")
        sleep(1)
        return

    clear_screen()
    print(Fore.CYAN + " Saved Queues ".center(60, "="))
    for i, q in enumerate(queues, 1):
        name = os.path.splitext(q)[0]
        path = os.path.join(QUEUE_DIR, q)
        try:
            with open(path) as f:
                data = json.load(f)
            count = len(data.get('items', []))
            mode  = data.get('mode', '?')
            print(get_next_colour() + f"  {i:>3}. {name:<40}  {count} items  mode={mode}")
        except Exception:
            print(Fore.RED + f"  {i:>3}. {q} (corrupted)")

    print(Fore.CYAN + "=" * 60)
    print(Fore.LIGHTBLACK_EX + "  Enter number to load, or ENTER to cancel: ", end='')
    raw = input().strip()
    if not raw:
        return

    try:
        idx = int(raw) - 1
        if not (0 <= idx < len(queues)):
            raise ValueError
    except ValueError:
        print(Fore.RED + "Invalid choice.")
        sleep(0.8)
        return

    path    = os.path.join(QUEUE_DIR, queues[idx])
    payload = _load_queue(path)
    items   = payload.get('items', [])
    mode    = payload.get('mode', 'video')
    sp_path = payload.get('save_path', cfg.get('default_path', ''))

    print(Fore.LIGHTGREEN_EX + f"\n  Loaded '{payload.get('name', '?')}' — {len(items)} item(s)")
    _show_item_list(items)

    cookie_file = get_cookies()
    use_aria2c  = ask_use_aria2c(aria2c_ok)

    print(Fore.YELLOW + f"\n  Press ENTER to start downloading to '{sp_path}', or 'q' to cancel: ", end='')
    ans = input().strip().lower()
    if ans == 'q':
        print(Fore.YELLOW + "Cancelled.")
        return

    success, failed = _run_batch(items, sp_path, mode, cfg, cookie_file, use_aria2c)

    print(Fore.CYAN + "\n" + "─" * 60)
    if failed:
        print(Fore.YELLOW + f"  Batch done: {success} succeeded, {failed} failed.")
    else:
        print(Fore.GREEN + f"  ✓ All {success} download(s) completed!")
    input(Fore.LIGHTBLACK_EX + "\nPress ENTER to return to menu…")


# ─────────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────────

def run_batch_manager(cfg: dict, aria2c_ok: bool) -> None:
    """Main entry point for the batch manager."""
    clear_screen()
    print(Fore.CYAN + " Batch Manager ".center(60, "="))
    print(Fore.LIGHTBLACK_EX + "  Download many URLs at once from a file or typed list.\n")

    print(Fore.WHITE + "  [1] Import URLs from a .txt or .json file")
    print(Fore.WHITE + "  [2] Type / paste URLs manually")
    print(Fore.WHITE + "  [3] Resume a saved queue")
    print(Fore.WHITE + "  [b] Back to menu")
    print()

    choice = input(Fore.WHITE + "Choice: ").strip().lower()

    if choice == 'b' or not choice:
        return

    if choice == '3':
        _resume_queue_menu(cfg, aria2c_ok)
        return

    items = []

    if choice == '1':
        print(Fore.LIGHTBLUE_EX + "\n  Enter path to your URL file (.txt or .json): ", end='')
        raw_path = input().strip().strip('"\'')
        file_path = resolve_path(raw_path)

        if not os.path.isfile(file_path):
            print(Fore.RED + f"  File not found: '{file_path}'")
            sleep(1.5)
            return

        try:
            items = _import_from_file(file_path)
            print(Fore.GREEN + f"  Loaded {len(items)} URL(s) from file.")
            sleep(0.5)
        except Exception as e:
            print(Fore.RED + f"  Failed to read file: {e}")
            sleep(1.5)
            return

    elif choice == '2':
        print(Fore.LIGHTGREEN_EX
              + f"\n  Paste URLs one by one. Type {Fore.WHITE}'done'{Fore.LIGHTGREEN_EX} "
                f"or {Fore.WHITE}'d'{Fore.LIGHTGREEN_EX} when finished.\n")
        while True:
            print(Fore.LIGHTRED_EX + "  URL: ", end='')
            url = input().strip()
            if url.lower() in ('done', 'd'):
                if not items:
                    print(Fore.YELLOW + "  Add at least one URL.")
                    continue
                break
            if url:
                items.append({'url': url, 'mode': None})
                print(Fore.LIGHTGREEN_EX + f"  Added ({len(items)} total).")
            else:
                print(Fore.RED + "  URL cannot be empty.")
    else:
        print(Fore.RED + "Invalid choice.")
        sleep(0.8)
        return

    if not items:
        print(Fore.RED + "No URLs to process.")
        sleep(1)
        return

    # Common setup
    cookie_file = get_cookies()
    save_path   = _get_save_path(cfg)
    use_aria2c  = ask_use_aria2c(aria2c_ok)

    # Expand playlists
    print(Fore.LIGHTBLACK_EX + "\n  Resolving URLs and expanding playlists…")
    items = _expand_items(items, cookie_file)
    print(Fore.GREEN + f"  → {len(items)} total item(s) after expansion.")
    sleep(0.5)

    # Choose download mode
    mode = _choose_mode()

    if mode == 'per-url':
        print(Fore.LIGHTBLACK_EX
              + "\n  Per-URL mode: each item uses its 'mode' field from the JSON file,\n"
                "  or defaults to 'video' if not set.")
        mode = 'video'  # fallback when item has no mode

    # Show list and confirm
    _show_item_list(items)

    # Optionally save queue
    print(Fore.YELLOW + f"\n  Save this queue for later? (y/N): ", end='')
    if input().strip().lower() in ('y', 'yes'):
        print(Fore.WHITE + "  Queue name: ", end='')
        qname = input().strip() or "queue"
        q_path = _save_queue(qname, items, save_path, mode)
        print(Fore.GREEN + f"  Saved to: {q_path}")
        sleep(0.5)

    # Confirm start
    print(Fore.YELLOW + f"\n  Start downloading {len(items)} item(s)? (Y/n): ", end='')
    if input().strip().lower() in ('n', 'no'):
        print(Fore.YELLOW + "Cancelled.")
        return

    # Run
    from time import perf_counter
    t0 = perf_counter()
    success, failed = _run_batch(items, save_path, mode, cfg, cookie_file, use_aria2c)
    wall = perf_counter() - t0

    print(Fore.CYAN + "\n" + "=" * 60)
    print(Fore.LIGHTBLACK_EX + f"  Total time: {_fmt_duration(wall)}")
    if failed:
        print(Fore.YELLOW + f"  {success} succeeded, {failed} failed.")
    else:
        print(Fore.GREEN + f"  ✓ All {success} download(s) completed!")
    print(Fore.LIGHTMAGENTA_EX + f"  Files saved to: {save_path}")

    if cfg.get('notify_on_complete'):
        notify("Stream Scoop", f"Batch done: {success} files saved")

    input(Fore.LIGHTBLACK_EX + "\nPress ENTER to return to menu…")
