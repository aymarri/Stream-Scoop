"""
thumbnail_dl.py — Download video thumbnails.

Features:
  - Download highest-res thumbnail available
  - Pick from multiple thumbnail sizes
  - Batch thumbnail downloading
  - Convert to different image formats (jpg, png, webp)
"""#

import os
import urllib.request
import urllib.error
from time import sleep

import yt_dlp as YT
import colorama
from colorama import Fore

from utilities import (
    clear_screen, get_cookies, handle_error, log_download,
    ensure_writable_dir, resolve_path, notify,
)
from colours import get_next_colour

colorama.init(autoreset=True)


def _fetch_info(url: str, cookie_file) -> dict:
    opts = {'quiet': True, 'no_warnings': True}
    if cookie_file:
        opts['cookiefile'] = cookie_file
    with YT.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _get_thumbnails(info: dict) -> list:
    """Return sorted thumbnail list (best quality last → pick from end)."""
    thumbs = info.get('thumbnails') or []
    # Sort by resolution descending
    def _res(t):
        w = t.get('width') or 0
        h = t.get('height') or 0
        return w * h

    sorted_t = sorted(thumbs, key=_res, reverse=True)
    # Also add the main thumbnail_url if not already present
    main = info.get('thumbnail')
    if main and not any(t.get('url') == main for t in sorted_t):
        sorted_t.insert(0, {'url': main, 'width': None, 'height': None, 'id': 'main'})

    return sorted_t


def _download_thumbnail(thumb_url: str, out_path: str) -> bool:
    """Download a thumbnail URL to out_path. Returns True on success."""
    try:
        req = urllib.request.Request(
            thumb_url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()

        with open(out_path, 'wb') as f:
            f.write(data)
        return True
    except Exception as e:
        print(Fore.RED + f"  Download failed: {e}")
        return False


def _convert_image(src: str, target_fmt: str) -> str:
    """Convert image using ffmpeg. Returns new path or src on failure."""
    import subprocess as sp
    base, _ = os.path.splitext(src)
    dst     = f"{base}.{target_fmt}"
    try:
        sp.run(
            ['ffmpeg', '-y', '-i', src, dst],
            check=True, stdout=sp.PIPE, stderr=sp.PIPE
        )
        os.remove(src)
        return dst
    except Exception:
        return src


def _ext_from_url(url: str) -> str:
    """Guess image extension from URL."""
    u = url.lower().split('?')[0]
    for ext in ('webp', 'jpg', 'jpeg', 'png', 'gif'):
        if u.endswith(f'.{ext}'):
            return 'jpg' if ext == 'jpeg' else ext
    return 'jpg'


def download_thumbnail_for_url(url: str, save_path: str, cfg: dict,
                                cookie_file, auto: bool = False) -> bool:
    """
    Download thumbnail(s) for a single URL.
    auto=True picks the highest resolution without asking.
    Returns True if at least one thumbnail was saved.
    """
    try:
        print(Fore.LIGHTBLACK_EX + "  Fetching video info…")
        info      = _fetch_info(url, cookie_file)
        title     = info.get('title', 'thumbnail')
        safe_title = ''.join(c if c.isalnum() or c in ' _-' else '_' for c in title)[:60]
        thumbs    = _get_thumbnails(info)

        if not thumbs:
            print(Fore.RED + "  No thumbnails available.")
            return False

        print(Fore.CYAN + f"\n  {title[:60]}")
        print(Fore.LIGHTBLACK_EX + f"  {len(thumbs)} thumbnail(s) found\n")

        if auto:
            chosen = [thumbs[0]]  # highest resolution
        else:
            # Show available thumbnails
            for i, t in enumerate(thumbs, 1):
                w = t.get('width') or '?'
                h = t.get('height') or '?'
                tid = t.get('id') or str(i)
                print(get_next_colour() + f"  {i:>3}. {w}×{h:}  [{tid}]")

            print(Fore.LIGHTBLACK_EX + "\n  Enter number(s) (e.g. 1,2,3), 'all', or 'best': ", end='')
            raw = input().strip().lower()

            if raw in ('', 'best'):
                chosen = [thumbs[0]]
            elif raw == 'all':
                chosen = thumbs
            else:
                chosen = []
                for part in raw.split(','):
                    try:
                        idx = int(part.strip()) - 1
                        if 0 <= idx < len(thumbs):
                            chosen.append(thumbs[idx])
                    except ValueError:
                        pass
                if not chosen:
                    chosen = [thumbs[0]]

        # Ask for output format
        if not auto:
            print(Fore.WHITE + "\n  Convert to format? [1] Keep original  [2] JPG  [3] PNG  [4] WEBP")
            fmt_choice = input(Fore.WHITE + "  Choice (1): ").strip()
            convert_to = {
                '2': 'jpg',
                '3': 'png',
                '4': 'webp',
            }.get(fmt_choice)
        else:
            convert_to = None

        ensure_writable_dir(save_path)
        saved_count = 0

        for i, t in enumerate(chosen):
            thumb_url = t.get('url')
            if not thumb_url:
                continue

            ext      = _ext_from_url(thumb_url)
            suffix   = f"_{i+1}" if len(chosen) > 1 else ""
            filename = f"{safe_title}{suffix}.{ext}"
            out_path = os.path.join(save_path, filename)

            print(Fore.LIGHTBLACK_EX + f"  Downloading: {filename}…", end='', flush=True)
            if _download_thumbnail(thumb_url, out_path):
                if convert_to and convert_to != ext:
                    out_path = _convert_image(out_path, convert_to)
                print(Fore.GREEN + " ✓")
                saved_count += 1
            else:
                print(Fore.RED + " ✗")

        if saved_count:
            print(Fore.GREEN + f"\n  ✓ {saved_count} thumbnail(s) saved to: {save_path}")
            log_download(url, save_path, 'Thumbnail', auto_log=cfg.get('auto_log', False))
            if cfg.get('notify_on_complete'):
                notify("Stream Scoop", f"Thumbnail saved: {title[:40]}")
            return True

        return False

    except Exception as e:
        handle_error(e)
        return False


def run_thumbnail_downloader(cfg: dict) -> None:
    """Main entry point for the thumbnail downloader."""
    clear_screen()
    print(Fore.CYAN + " Thumbnail Downloader ".center(60, "="))
    print(Fore.LIGHTBLACK_EX + "  Save high-resolution thumbnails from any video URL.\n")

    cookie_file = get_cookies()

    # Save path
    default_path = cfg.get('default_path',
                           os.path.join(os.path.expanduser('~'), 'Downloads', 'StreamScoop'))
    print(Fore.LIGHTBLUE_EX + f"\nDefault download path: {default_path}")
    c = input("Use default path? (Y/n): ").strip().lower()
    if c in ('n', 'no'):
        raw       = input(Fore.WHITE + "Custom path: ").strip()
        save_path = resolve_path(raw)
    else:
        save_path = default_path

    if not ensure_writable_dir(save_path):
        print(Fore.RED + f"Cannot write to '{save_path}'. Aborting.")
        sleep(1)
        return

    # URL collection
    print(Fore.LIGHTGREEN_EX
          + f"\nPaste URLs one by one. Type {Fore.WHITE}'done'{Fore.LIGHTGREEN_EX} or "
            f"{Fore.WHITE}'d'{Fore.LIGHTGREEN_EX} when finished.\n")
    urls = []
    while True:
        print(Fore.LIGHTRED_EX + "URL: ", end='')
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

    # Auto mode for multiple URLs
    auto = False
    if len(urls) > 1:
        ans = input(Fore.CYAN + f"\nAuto-select best quality for all {len(urls)} URLs? (Y/n): ").strip().lower()
        auto = ans in ('', 'y', 'yes')

    total    = len(urls)
    success  = 0
    failed   = 0

    for n, url in enumerate(urls, 1):
        if total > 1:
            print(Fore.CYAN + f"\n{'─'*54}")
            print(Fore.CYAN + f"  Thumbnail {n}/{total}")

        ok = download_thumbnail_for_url(url, save_path, cfg, cookie_file, auto=auto or (total > 1))
        if ok:
            success += 1
        else:
            failed += 1

    if total > 1:
        print(Fore.CYAN + f"\n{'─'*54}")
        print(Fore.GREEN + f"  ✓ {success} saved" + (f"  {Fore.RED}✗ {failed} failed" if failed else ""))

    input(Fore.LIGHTBLACK_EX + "\nPress ENTER to return to menu…")
