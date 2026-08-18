"""
archive_manager.py — Archive mode and download tracking.

Features:
  - View the yt-dlp archive file (list of downloaded video IDs)
  - Search the archive
  - Remove entries from the archive
  - Import old history into the archive
  - Clear the archive
  - Show statistics (total archived, by extractor)
"""

import os
import re
from time import sleep
from collections import defaultdict

import colorama
from colorama import Fore

from utilities import clear_screen, resolve_path
from colours import get_next_colour

colorama.init(autoreset=True)


def _load_archive(path: str) -> list:
    """Load yt-dlp archive file lines. Each line: 'extractor video_id'."""#
    if not os.path.isfile(path):
        return []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return [line.strip() for line in f if line.strip()]


def _save_archive(path: str, lines: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def _parse_line(line: str) -> tuple:
    """Parse 'extractor id' → (extractor, id)."""
    parts = line.split(' ', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return ('unknown', line)


def _stats(lines: list) -> dict:
    by_extractor: dict = defaultdict(int)
    for line in lines:
        ext, _ = _parse_line(line)
        by_extractor[ext] += 1
    return dict(by_extractor)


def _view_archive(lines: list, archive_path: str) -> None:
    if not lines:
        print(Fore.YELLOW + "\n  Archive is empty.")
        input(Fore.LIGHTBLACK_EX + "  Press ENTER to continue…")
        return

    PAGE = 40
    total_pages = max(1, (len(lines) + PAGE - 1) // PAGE)
    cur_page = 0
    search   = ''

    while True:
        clear_screen()
        filtered = [l for l in lines if search.lower() in l.lower()] if search else lines
        total_f  = len(filtered)
        total_pages = max(1, (total_f + PAGE - 1) // PAGE)
        cur_page = min(cur_page, max(0, total_pages - 1))

        start = cur_page * PAGE
        end   = min(start + PAGE, total_f)

        print(Fore.CYAN + f" Archive — {len(lines)} entries  (page {cur_page+1}/{total_pages}) ".center(74, "="))
        if search:
            print(Fore.YELLOW + f"  Filtering: '{search}'  ({total_f} matches)")
        print(Fore.LIGHTBLACK_EX + f"\n  {'#':>5}  {'Extractor':<18}  {'Video ID'}")
        print(Fore.LIGHTBLACK_EX + "  " + "─" * 60)

        for i, line in enumerate(filtered[start:end], start + 1):
            ext, vid = _parse_line(line)
            print(get_next_colour() + f"  {i:>5}.  {ext:<18}  {vid}")

        print(Fore.CYAN + "\n" + "─" * 74)
        print(Fore.LIGHTBLACK_EX
              + "  [A] Prev  [D] Next  [/] Search  [C] Clear search  "
                "[R] Remove entry  [ENTER] Back")
        raw = input(Fore.WHITE + "  > ").strip()

        if not raw:
            break
        if raw.lower() == 'a':
            cur_page = max(0, cur_page - 1)
        elif raw.lower() == 'd':
            cur_page = min(total_pages - 1, cur_page + 1)
        elif raw.startswith('/'):
            search = raw[1:].strip()
            cur_page = 0
        elif raw.lower() == 'c':
            search = ''
            cur_page = 0
        elif raw.lower() == 'r':
            print(Fore.WHITE + "  Entry number to remove: ", end='')
            try:
                idx = int(input().strip()) - 1
                if 0 <= idx < len(filtered):
                    entry = filtered[idx]
                    print(Fore.YELLOW + f"  Remove: '{entry}'? (Y/n): ", end='')
                    if input().strip().lower() in ('', 'y', 'yes'):
                        lines.remove(entry)
                        _save_archive(archive_path, lines)
                        print(Fore.GREEN + "  Removed.")
                        sleep(0.5)
                else:
                    print(Fore.RED + "  Invalid number.")
                    sleep(0.5)
            except ValueError:
                print(Fore.RED + "  Invalid input.")
                sleep(0.5)


def _show_stats(lines: list) -> None:
    stats = _stats(lines)
    clear_screen()
    print(Fore.CYAN + " Archive Statistics ".center(60, "="))
    print(Fore.LIGHTBLACK_EX + f"\n  Total archived entries: {len(lines)}\n")
    print(Fore.YELLOW + f"  {'Extractor':<25}  {'Count':>6}")
    print(Fore.LIGHTBLACK_EX + "  " + "─" * 35)
    for ext, count in sorted(stats.items(), key=lambda x: -x[1]):
        col = get_next_colour()
        bar_len = int(count / max(stats.values()) * 20)
        bar = '█' * bar_len
        print(col + f"  {ext:<25}  {count:>6}  {Fore.LIGHTBLACK_EX}{bar}")
    print(Fore.CYAN + "=" * 60)
    input(Fore.LIGHTBLACK_EX + "\n  Press ENTER to continue…")


def _add_url_to_archive(url: str, archive_path: str) -> bool:
    """Manually add a URL's ID to the archive using yt-dlp metadata."""
    try:
        import yt_dlp as YT
        opts = {'quiet': True, 'no_warnings': True}
        with YT.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            extractor = info.get('extractor_key', 'youtube').lower()
            vid_id    = info.get('id', '')
            if not vid_id:
                print(Fore.RED + "  Could not get video ID.")
                return False

            line = f"{extractor} {vid_id}"
            lines = _load_archive(archive_path)
            if line in lines:
                print(Fore.YELLOW + f"  Already in archive: {line}")
                return False

            lines.append(line)
            _save_archive(archive_path, lines)
            print(Fore.GREEN + f"  Added: {line}")
            return True
    except Exception as e:
        print(Fore.RED + f"  Error: {e}")
        return False


def run_archive_manager(cfg: dict) -> None:
    """Main entry point for the archive manager."""
    archive_path = cfg.get(
        'archive_file',
        os.path.join(os.path.expanduser('~'), '.stream_scoop_archive.txt')
    )
    archive_mode = cfg.get('archive_mode', False)

    while True:
        clear_screen()
        lines = _load_archive(archive_path)
        print(Fore.CYAN + " Archive Manager ".center(60, "="))
        print(Fore.LIGHTBLACK_EX + f"  Archive file: {archive_path}")
        print(Fore.LIGHTBLACK_EX + f"  Entries:      {len(lines)}")
        col = Fore.GREEN if archive_mode else Fore.YELLOW
        print(col + f"  Archive mode: {'ENABLED — skipping already-downloaded videos' if archive_mode else 'DISABLED'}\n")

        ops = [
            ("1", f"{'Disable' if archive_mode else 'Enable'} archive mode"),
            ("2", "View / search archive entries"),
            ("3", "Archive statistics by extractor"),
            ("4", "Manually add a URL to archive"),
            ("5", "Import from download_history.txt"),
            ("6", "Clear entire archive"),
            ("b", "Back to main menu"),
        ]
        for key, label in ops:
            print(get_next_colour() + f"  [{key}] {label}")

        print()
        choice = input(Fore.WHITE + "Choice: ").strip().lower()

        if choice == 'b' or not choice:
            return

        if choice == '1':
            cfg['archive_mode'] = not archive_mode
            from config import save_config
            save_config(cfg)
            state = "ENABLED" if cfg['archive_mode'] else "DISABLED"
            print(Fore.GREEN + f"  Archive mode {state}.")
            sleep(0.8)
            archive_mode = cfg['archive_mode']

        elif choice == '2':
            _view_archive(lines, archive_path)

        elif choice == '3':
            _show_stats(lines)

        elif choice == '4':
            print(Fore.WHITE + "\n  URL to add: ", end='')
            url = input().strip()
            if url:
                _add_url_to_archive(url, archive_path)
                sleep(0.8)

        elif choice == '5':
            # Import from download_history.txt
            default_path = cfg.get('default_path',
                                   os.path.join(os.path.expanduser('~'), 'Downloads', 'StreamScoop'))
            hist_file = os.path.join(default_path, 'download_history.txt')

            if not os.path.isfile(hist_file):
                print(Fore.YELLOW + f"  No history file found at '{hist_file}'")
                sleep(1)
                continue

            # Extract URLs from history lines and look up their IDs
            with open(hist_file, 'r', encoding='utf-8', errors='replace') as f:
                hist_lines = f.readlines()

            urls_in_history = []
            for hl in hist_lines:
                # Format: [timestamp] type | url | path | duration
                parts = hl.split('|')
                if len(parts) >= 2:
                    url = parts[1].strip()
                    if url.startswith('http'):
                        urls_in_history.append(url)

            if not urls_in_history:
                print(Fore.YELLOW + "  No URLs found in history.")
                sleep(1)
                continue

            print(Fore.LIGHTBLUE_EX
                  + f"\n  Found {len(urls_in_history)} URL(s) in history.")
            print(Fore.WHITE + "  Add all to archive? This will fetch metadata for each. (Y/n): ", end='')
            if input().strip().lower() in ('n', 'no'):
                continue

            added = 0
            for i, url in enumerate(urls_in_history, 1):
                print(Fore.LIGHTBLACK_EX + f"  [{i}/{len(urls_in_history)}] {url[:60]}…")
                if _add_url_to_archive(url, archive_path):
                    added += 1

            print(Fore.GREEN + f"\n  Added {added} entries to archive.")
            sleep(1)

        elif choice == '6':
            if not lines:
                print(Fore.YELLOW + "  Archive is already empty.")
                sleep(1)
                continue
            print(Fore.RED + f"\n  Clear ALL {len(lines)} entries? Type 'yes' to confirm: ", end='')
            if input().strip().lower() == 'yes':
                _save_archive(archive_path, [])
                print(Fore.GREEN + "  Archive cleared.")
                sleep(0.8)
            else:
                print(Fore.YELLOW + "  Cancelled.")
                sleep(0.5)

        else:
            print(Fore.RED + "  Invalid choice.")
            sleep(0.5)
