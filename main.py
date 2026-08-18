"""
main.py — Stream Scoop entry point.

BUG FIX: concurrent.py was renamed → concurrent_dl.py.
  The old name shadowed Python's stdlib `concurrent` module,
  causing: ImportError: cannot import name 'ThreadPoolExecutor' from 'concurrent'

Menu:
  1  Download Video
  2  Download Audio Only
  3  Download Subtitles
  4  Download Video + Subtitles
  5  ★ Concurrent Download
  6  Search & Download
  7  Format Inspector
  8  Thumbnail Downloader
  9  Batch Manager (import from file / saved queues)
  10 Local File Converter (FFmpeg)
  11 Archive Manager
  12 Download Statistics
  13 View Download History
  14 Settings##
  q  Quit
"""

import os
import sys
import signal
import subprocess as sp
from time import sleep

import colorama as clr
from colorama import Fore
import yt_dlp as YT

from config import load_config, show_settings
from download_logic import (
    download_video_audio,
    download_audio_only,
    download_subtitles,
    download_video_audio_subtitles,
    select_playlist_entries,
)
from concurrent_dl import run_concurrent_session          # ← fixed import name
from utilities import (
    clear_screen, handle_error, get_cookies, ask_use_aria2c,
    check_ytdlp_update, view_history, ensure_writable_dir, resolve_path,
)
from colours import get_next_colour

# New feature modules
from format_inspector  import run_format_inspector
from thumbnail_dl      import run_thumbnail_downloader
from batch_manager     import run_batch_manager
from file_converter    import run_file_converter
from archive_manager   import run_archive_manager
from stats_manager     import run_stats_manager
from search_dl         import run_search_downloader

clr.init(autoreset=True)

VERSION = "2.0.0"


# ─────────────────────────────────────────────────────────────────
#  Signal handler
# ─────────────────────────────────────────────────────────────────

def _signal_handler(sig, frame):
    print(f'\n{Fore.LIGHTMAGENTA_EX}Received {signal.Signals(sig).name} — exiting.')
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────
#  Dependency check
# ─────────────────────────────────────────────────────────────────

def check_dependencies() -> tuple:
    print(get_next_colour() + "Checking dependencies...\n")
    sleep(0.4)

    ffmpeg_ok  = False
    aria2c_ok  = False
    ffprobe_ok = False

    try:
        sp.run(['ffmpeg', '-version'], stdout=sp.PIPE, stderr=sp.PIPE, check=True)
        ffmpeg_ok = True
    except (sp.CalledProcessError, FileNotFoundError):
        pass

    try:
        sp.run(['ffprobe', '-version'], stdout=sp.PIPE, stderr=sp.PIPE, check=True)
        ffprobe_ok = True
    except (sp.CalledProcessError, FileNotFoundError):
        pass

    try:
        sp.run(['aria2c', '--version'], stdout=sp.PIPE, stderr=sp.PIPE, check=True)
        aria2c_ok = True
    except (sp.CalledProcessError, FileNotFoundError):
        pass

    return ffmpeg_ok, aria2c_ok, ffprobe_ok


# ─────────────────────────────────────────────────────────────────
#  Save-path prompt  (used by sequential modes)
# ─────────────────────────────────────────────────────────────────

def get_save_path(cfg: dict) -> str:
    default = cfg.get('default_path',
                      os.path.join(os.path.expanduser('~'), 'Downloads', 'StreamScoop'))
    print(Fore.LIGHTBLUE_EX + f"\nDefault download path: {default}")

    while True:
        choice = input("Use default path? (Y/n): ").strip().lower()

        if choice in ('', 'y', 'yes'):
            path = default
        elif choice in ('n', 'no'):
            raw  = input(Fore.WHITE + "\nCustom path: ").strip()
            path = resolve_path(raw)
            print(Fore.LIGHTGREEN_EX + f"Using: {path}")
            sleep(0.5)
        else:
            print(Fore.RED + "Enter Y or n.")
            continue

        if not os.path.exists(path):
            ans = input(
                Fore.YELLOW + f"'{path}' doesn't exist. Create it? (Y/n): "
            ).strip().lower()
            if ans in ('', 'y', 'yes'):
                if not ensure_writable_dir(path):
                    print(Fore.RED + "Cannot create directory. Try another path.")
                    continue
            else:
                continue
        elif not os.path.isdir(path):
            print(Fore.RED + f"'{path}' is not a directory.")
            continue

        if not ensure_writable_dir(path):
            print(Fore.RED + f"'{path}' is not writable.")
            continue

        sleep(0.4)
        return path


# ─────────────────────────────────────────────────────────────────
#  URL collection  (used by sequential modes)
# ─────────────────────────────────────────────────────────────────

def get_urls() -> list:
    print(Fore.LIGHTGREEN_EX
          + f"Enter URLs one per line. Type {Fore.WHITE}'done'{Fore.LIGHTGREEN_EX}"
            f" or {Fore.WHITE}'d'{Fore.LIGHTGREEN_EX} to finish:")
    urls = []
    while True:
        print(Fore.LIGHTRED_EX + "\nPaste URL: ", end='')
        url = input().strip()
        if url.lower() in ('done', 'd'):
            if not urls:
                print(Fore.YELLOW + "Add at least one URL.")
                continue
            break
        if url:
            urls.append(url)
            print(Fore.LIGHTGREEN_EX + f"  Added ({len(urls)} total).")
        else:
            print(Fore.RED + "URL cannot be empty.")
    return urls


# ─────────────────────────────────────────────────────────────────
#  Playlist expansion  (used by sequential modes)
# ─────────────────────────────────────────────────────────────────

def expand_urls(urls: list, cookie_file, allow_selection: bool = True) -> list:
    expanded = []
    for url in urls:
        print(Fore.LIGHTBLACK_EX + f"\nResolving: {url[:70]}...")
        try:
            opts = {
                'quiet': True,
                'extract_flat': 'in_playlist',
                'cookiefile': cookie_file,
            }
            with YT.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if 'entries' in info:
                entries = [e for e in info['entries'] if e.get('url')]
                print(Fore.LIGHTGREEN_EX
                      + f"  Playlist: {len(entries)} videos — \"{info.get('title','')}\"")
                if allow_selection:
                    entries = select_playlist_entries(entries)
                expanded.extend(e['url'] for e in entries)
            else:
                expanded.append(url)

        except Exception as e:
            print(Fore.YELLOW + f"  Warning: could not resolve — {e}")
            print(Fore.YELLOW + "  Using URL as-is.")
            expanded.append(url)

    return expanded


# ─────────────────────────────────────────────────────────────────
#  Banner
# ─────────────────────────────────────────────────────────────────

def _print_banner() -> None:
    lines = [
        "   _____ _                            ___",
        "  / ____| |                          / ____|",
        " | (___ | |_ _ __ ___  __ _ _ __ _ | (___   ___ ___   ___  _ __",
        "  \\___ \\| __| '__/ _ \\/ _` | '_ (_)  \\___ \\ / __/ _ \\ / _ \\| '_ \\",
        "  ____) | |_| | |  __/ (_| | | | |   ____) | (_| (_) | (_) | |_) |",
        " |_____/ \\__|_|  \\___|\\__,_|_| |_|  |_____/ \\___\\___/ \\___/| .__/",
        "                                                              | |",
        f"                                                              |_|  v{VERSION}",
    ]
    colours = [get_next_colour() for _ in lines]
    # Dump all lines dim, then sweep back up and reprint each bright
    for line in lines:
        print(Fore.LIGHTBLACK_EX + line)
    print()
    total = len(lines) + 1
    print(f'\033[{total}A', end='', flush=True)
    for col, line in zip(colours, lines):
        print('\033[2K' + col + line, flush=True)
        sleep(0.011)
    print()


# ─────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────

def main():
    clear_screen()
    signal.signal(signal.SIGINT, _signal_handler)

    cfg = load_config()

    # ── Dependency check ──────────────────────────────────────
    ffmpeg_ok, aria2c_ok, ffprobe_ok = check_dependencies()

    print((Fore.LIGHTGREEN_EX if ffmpeg_ok else Fore.LIGHTRED_EX)
          + f"FFmpeg  : {'✓' if ffmpeg_ok else '✗ NOT FOUND — required!'}")
    sleep(0.15)
    print((Fore.LIGHTGREEN_EX if ffprobe_ok else Fore.LIGHTYELLOW_EX)
          + f"FFprobe : {'✓' if ffprobe_ok else '— not found (optional, from ffmpeg suite)'}")
    sleep(0.15)
    print((Fore.LIGHTGREEN_EX if aria2c_ok else Fore.LIGHTYELLOW_EX)
          + f"aria2c  : {'✓' if aria2c_ok else '— not installed (optional, faster downloads)'}")
    sleep(0.2)

    if not ffmpeg_ok:
        print(Fore.RED    + "\nFFmpeg is required for merging video+audio streams.")
        print(Fore.YELLOW + "Install: https://ffmpeg.org/download.html")
        print(Fore.YELLOW + "  Windows: winget install ffmpeg  OR  choco install ffmpeg")
        print(Fore.YELLOW + "  macOS:   brew install ffmpeg")
        print(Fore.YELLOW + "  Linux:   sudo apt install ffmpeg")
        input(Fore.LIGHTBLACK_EX + "\nPress ENTER to exit…")
        sys.exit(1)

    if not aria2c_ok:
        print(Fore.LIGHTBLACK_EX
              + "\nTip: install aria2c for potentially faster multi-part downloads.\n")
        sleep(0.6)

    if cfg.get('auto_check_updates', True):
        check_ytdlp_update()

    # ── Main menu loop ────────────────────────────────────────
    while True:
        clear_screen()
        _print_banner()

        print(get_next_colour() + " Main Menu ".center(60, "─"))

        menu_items = [
            ("1",  "Download Video"),
            ("2",  "Download Audio Only"),
            ("3",  "Download Subtitles"),
            ("4",  "Download Video + Subtitles"),
            ("5",  "★  Concurrent Download  (all-at-once with live dashboard)"),
            ("─",  ""),
            ("6",  "Search & Download  (YouTube / SoundCloud / etc.)"),
            ("7",  "Format Inspector  (see every available format)"),
            ("8",  "Thumbnail Downloader"),
            ("9",  "Batch Manager  (import from file / resume saved queue)"),
            ("10", "Local File Converter  (FFmpeg trim, convert, extract audio…)"),
            ("─",  ""),
            ("11", "Archive Manager  (skip already-downloaded videos)"),
            ("12", "Download Statistics"),
            ("13", "View Download History"),
            ("14", "Settings"),
            ("─",  ""),
            ("q",  "Quit"),
        ]

        rendered = []
        for key, label in menu_items:
            if key == chr(9472):
                rendered.append(Fore.LIGHTBLACK_EX + '  ' + chr(9472) * 50)
            else:
                rendered.append(get_next_colour() + f'  [{key:>2}] {label}')
        # Print all dim first so the terminal doesn't jump
        for row in rendered:
            import re as _re; plain = _re.sub(r'\033\[[0-9;]*m', '', row); print(Fore.LIGHTBLACK_EX + plain)
        # Sweep back and reprint each row at full brightness
        print(f'\033[{len(rendered)}A', end='', flush=True)
        for row in rendered:
            print('\033[2K' + row, flush=True)
            sleep(0.006)

        print()
        choice = input(Fore.WHITE + "Choice: ").strip().lower()

        # ── Quit ──────────────────────────────────────────────
        if choice in ('q', 'quit', 'exit'):
            print(Fore.LIGHTBLUE_EX + "Bye! 👋")
            sys.exit(0)

        # ── History ───────────────────────────────────────────
        if choice == '13':
            path = cfg.get('default_path',
                           os.path.join(os.path.expanduser('~'), 'Downloads', 'StreamScoop'))
            view_history(path)
            continue

        # ── Settings ─────────────────────────────────────────
        if choice == '14':
            cfg = show_settings(cfg)
            continue

        # ── Concurrent mode ─────────────────────────────────
        if choice == '5':
            run_concurrent_session(cfg, aria2c_ok)
            continue

        # ── Search & Download ────────────────────────────────
        if choice == '6':
            run_search_downloader(cfg, aria2c_ok)
            continue

        # ── Format Inspector ─────────────────────────────────
        if choice == '7':
            run_format_inspector(cfg)
            continue

        # ── Thumbnail Downloader ──────────────────────────────
        if choice == '8':
            run_thumbnail_downloader(cfg)
            continue

        # ── Batch Manager ────────────────────────────────────
        if choice == '9':
            run_batch_manager(cfg, aria2c_ok)
            continue

        # ── File Converter ───────────────────────────────────
        if choice == '10':
            run_file_converter(cfg)
            continue

        # ── Archive Manager ──────────────────────────────────
        if choice == '11':
            run_archive_manager(cfg)
            continue

        # ── Statistics ───────────────────────────────────────
        if choice == '12':
            run_stats_manager(cfg)
            continue

        # ── Sequential download modes ─────────────────────────
        if choice not in ('1', '2', '3', '4'):
            print(Fore.RED + "Enter 1–14 or q.")
            sleep(0.8)
            continue

        cookie_file = get_cookies()

        use_aria2c = False
        if choice in ('1', '2', '4'):
            use_aria2c = ask_use_aria2c(aria2c_ok)

        save_path = get_save_path(cfg)
        clear_screen()
        urls = get_urls()

        allow_sel = (choice in ('1', '2', '4'))
        urls = expand_urls(urls, cookie_file, allow_selection=allow_sel)

        if not urls:
            print(Fore.RED + "No valid URLs to download.")
            sleep(1)
            continue

        # Auto-quality for batch
        auto_q = None
        pref = cfg.get('preferred_quality')
        if pref and len(urls) > 1 and choice in ('1', '4'):
            try:
                auto_q = int(str(pref).replace('p', ''))
                print(Fore.LIGHTBLACK_EX + f"Batch mode: auto-selecting {auto_q}p.")
                sleep(0.6)
            except (ValueError, TypeError):
                auto_q = None

        total = len(urls)
        for n, url in enumerate(urls, 1):
            if total > 1:
                print(Fore.CYAN + f"\n{'─'*54}")
                print(Fore.CYAN + f"  Video {n}/{total}")
                print(Fore.CYAN + f"{'─'*54}")

            try:
                if choice == '1':
                    download_video_audio(url, save_path, cfg, cookie_file,
                                         use_aria2c, auto_quality=auto_q)
                elif choice == '2':
                    download_audio_only(url, save_path, cfg, cookie_file, use_aria2c)
                elif choice == '3':
                    download_subtitles(url, save_path, cfg, cookie_file)
                elif choice == '4':
                    download_video_audio_subtitles(url, save_path, cfg,
                                                    cookie_file, use_aria2c)
            except Exception as e:
                handle_error(e)
                if total > 1:
                    print(Fore.YELLOW + "Continuing with next URL…")

            # Sleep interval between sequential downloads
            if cfg.get('sleep_interval') and n < total:
                interval = cfg['sleep_interval']
                print(Fore.LIGHTBLACK_EX + f"Waiting {interval}s before next download…")
                sleep(interval)

        print(Fore.GREEN + f"\n✓ All done. ({total} item{'s' if total > 1 else ''})")
        input(Fore.LIGHTBLACK_EX + "Press ENTER to return to menu…")


if __name__ == '__main__':
    main()