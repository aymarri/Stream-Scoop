"""
search_dl.py — Search and download.

Uses yt-dlp's built-in search support (ytsearch, scsearch, etc.)
to find videos without leaving the app.

Features:
  - Search YouTube / SoundCloud / other supported platforms
  - View search results with title, uploader, duration, views
  - Pick one or multiple results to download#
  - Queue search results for concurrent download
  - Show video card before downloading
"""

from time import sleep

import yt_dlp as YT
import colorama
from colorama import Fore

from utilities import (
    clear_screen, get_cookies, ask_use_aria2c, handle_error,
    resolve_path, ensure_writable_dir,
)
from download_logic import (
    download_video_audio, download_audio_only,
    _print_video_info, build_quality_list, build_audio_list,
    fetch_info, _num_input, _fmt_bytes,
)
from colours import get_next_colour

colorama.init(autoreset=True)


SEARCH_PREFIXES = {
    '1': ('ytsearch',  'YouTube'),
    '2': ('scsearch',  'SoundCloud'),
    '3': ('ytmsearch', 'YouTube Music'),
    '4': ('spsearch',  'Spotify (via yt-dlp)'),
}

MAX_RESULTS = 15


def _do_search(query: str, prefix: str, cookie_file, n: int = MAX_RESULTS) -> list:
    """Run a search and return list of result dicts."""
    search_url = f"{prefix}{n}:{query}"
    opts = {
        'quiet':        True,
        'no_warnings':  True,
        'extract_flat': True,
    }
    if cookie_file:
        opts['cookiefile'] = cookie_file

    with YT.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(search_url, download=False)

    if not info or 'entries' not in info:
        return []
    return [e for e in info['entries'] if e]


def _format_duration(seconds) -> str:
    if not seconds:
        return '?'
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def _display_results(results: list, platform: str, query: str) -> None:
    clear_screen()
    print(Fore.CYAN + f" Search Results — {platform} — \"{query}\" ".center(74, "="))
    print(Fore.LIGHTBLACK_EX
          + f"\n  {'#':>3}  {'Title':<45}  {'Uploader':<20}  {'Dur':>7}  {'Views':>10}")
    print(Fore.LIGHTBLACK_EX + "  " + "─" * 90)

    for i, r in enumerate(results, 1):
        title     = (r.get('title') or '?')[:44]
        uploader  = (r.get('uploader') or r.get('channel') or '?')[:19]
        dur       = _format_duration(r.get('duration'))
        views     = r.get('view_count')
        views_str = f"{views:,}" if views else '—'
        col       = get_next_colour()
        print(col + f"  {i:>3}. {title:<45}  {uploader:<20}  {dur:>7}  {views_str:>10}")

    print(Fore.LIGHTBLACK_EX + "  " + "─" * 90)


def _pick_results(results: list) -> list:
    """Ask user which results to download. Returns list of selected entries."""
    print(Fore.YELLOW
          + "\n  Enter number(s) to download (e.g. 1  or  1,3,5  or  1-5  or  all): ", end='')
    raw = input().strip().lower()

    if not raw or raw == 'all':
        return results

    selected = []
    for part in raw.split(','):
        part = part.strip()
        if '-' in part:
            lo, _, hi = part.partition('-')
            try:
                for n in range(int(lo), int(hi) + 1):
                    if 1 <= n <= len(results):
                        selected.append(results[n - 1])
            except ValueError:
                pass
        else:
            try:
                n = int(part)
                if 1 <= n <= len(results):
                    selected.append(results[n - 1])
            except ValueError:
                pass

    return selected if selected else []


def _download_search_results(results: list, mode: str, save_path: str,
                              cfg: dict, cookie_file, use_aria2c: bool) -> None:
    total = len(results)
    for n, r in enumerate(results, 1):
        url = r.get('url') or r.get('webpage_url') or r.get('id')
        if not url:
            print(Fore.RED + f"  [{n}/{total}] No URL for this result, skipping.")
            continue

        # Ensure the URL is a proper URL
        if not url.startswith('http'):
            # For YouTube: construct from ID
            extractor = r.get('ie_key', '').lower()
            if 'youtube' in extractor or not extractor:
                url = f"https://www.youtube.com/watch?v={url}"
            elif 'soundcloud' in extractor:
                url = f"https://soundcloud.com/{url}"

        if total > 1:
            print(Fore.CYAN + f"\n{'─'*60}")
            title = r.get('title', url[:40])
            print(Fore.CYAN + f"  [{n}/{total}] {title[:55]}")
            print(Fore.CYAN + "─" * 60)

        pref_q = cfg.get('preferred_quality')
        auto_q = None
        if pref_q:
            try:
                auto_q = int(str(pref_q).replace('p', ''))
            except (ValueError, TypeError):
                pass

        try:
            if mode == 'audio':
                download_audio_only(url, save_path, cfg, cookie_file, use_aria2c)
            else:
                download_video_audio(url, save_path, cfg, cookie_file,
                                     use_aria2c, auto_quality=auto_q)
        except Exception as e:
            handle_error(e)
            if total > 1:
                print(Fore.YELLOW + "  Continuing…")


def run_search_downloader(cfg: dict, aria2c_ok: bool) -> None:
    """Main entry point for search & download."""
    clear_screen()
    print(Fore.CYAN + " Search & Download ".center(60, "="))
    print(Fore.LIGHTBLACK_EX + "  Search any platform and download directly.\n")

    # Platform choice
    print(Fore.YELLOW + "  Select platform:")
    for key, (_, name) in SEARCH_PREFIXES.items():
        print(get_next_colour() + f"  [{key}] {name}")

    plat_choice = input(Fore.WHITE + "\n  Platform (1): ").strip() or '1'
    prefix, platform = SEARCH_PREFIXES.get(plat_choice, ('ytsearch', 'YouTube'))

    cookie_file = get_cookies()
    use_aria2c  = ask_use_aria2c(aria2c_ok)

    # Save path
    default_path = cfg.get('default_path',
                           os.path.join(__import__('os').path.expanduser('~'),
                                        'Downloads', 'StreamScoop'))
    print(Fore.LIGHTBLUE_EX + f"\nDefault path: {default_path}")
    c = input("Use default path? (Y/n): ").strip().lower()
    if c in ('n', 'no'):
        raw       = input(Fore.WHITE + "Custom path: ").strip()
        save_path = resolve_path(raw)
    else:
        save_path = default_path
    ensure_writable_dir(save_path)

    # Download mode
    print(Fore.YELLOW + "\n  Download mode:")
    print(Fore.WHITE + "  [1] Video  [2] Audio only")
    mode_choice = input(Fore.WHITE + "  Choice (1): ").strip() or '1'
    mode = 'audio' if mode_choice == '2' else 'video'

    # Search loop
    while True:
        print()
        print(Fore.LIGHTGREEN_EX + f"  Enter search query on {platform} (or 'back' to return): ", end='')
        query = input().strip()
        if query.lower() in ('back', 'b', ''):
            return

        # How many results?
        print(Fore.WHITE + f"  Number of results (1–{MAX_RESULTS}, default 10): ", end='')
        try:
            n_results = int(input().strip() or '10')
            n_results = max(1, min(n_results, MAX_RESULTS))
        except ValueError:
            n_results = 10

        print(Fore.LIGHTBLACK_EX + f"  Searching {platform} for \"{query}\"…")
        try:
            results = _do_search(query, prefix, cookie_file, n=n_results)
        except Exception as e:
            handle_error(e)
            continue

        if not results:
            print(Fore.YELLOW + "  No results found.")
            sleep(1)
            continue

        _display_results(results, platform, query)
        selected = _pick_results(results)

        if not selected:
            print(Fore.YELLOW + "  Nothing selected.")
            sleep(0.5)
            continue

        print(Fore.GREEN + f"\n  Downloading {len(selected)} result(s)…")
        _download_search_results(selected, mode, save_path, cfg, cookie_file, use_aria2c)

        print(Fore.GREEN + f"\n  ✓ Done. Files saved to: {save_path}")
        print()
        ans = input(Fore.CYAN + "  Search again? (Y/n): ").strip().lower()
        if ans in ('n', 'no'):
            return
