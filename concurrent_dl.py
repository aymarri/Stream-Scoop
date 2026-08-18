"""
concurrent_dl.py — Concurrent download manager for Stream Scoop.

NOTE: This file was renamed from concurrent.py → concurrent_dl.py.
The original name shadowed Python's stdlib `concurrent` package, causing
  "ImportError: cannot import name 'ThreadPoolExecutor' from 'concurrent'"

Flow:
  1. User adds URLs one by one.
  2. For each URL, the script fetches info and walks them through
     every setting interactively (quality, mode, clip range, etc.).
  3. Once all videos are configured, a confirmation table is shown.
  4. User hits ENTER — all downloads fire simultaneously.
  5. A live dashboard redraws every 0.3 s showing each download's
     status, progress bar, speed, ETA, and elapsed time.
  6. When everything is done a summary table is printed.##
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed   # stdlib — works now!

import colorama
from colorama import Fore, Style
import yt_dlp as YT

from utilities import (
    clear_screen, ensure_writable_dir, resolve_path,
    get_cookies, ask_use_aria2c, PROGRESS,
    _fmt_bytes, _fmt_duration, _fmt_eta,
)
from download_logic import configure_video_job, _run_job, select_playlist_entries
from colours import get_next_colour

colorama.init(autoreset=True)


# ─────────────────────────────────────────────────────────────────
#  ANSI helpers
# ─────────────────────────────────────────────────────────────────

def _move_up(n: int) -> str:
    return f"\033[{n}A" if n > 0 else ""

def _clear_line() -> str:
    return "\033[2K\r"

def _hide_cursor() -> None:
    print("\033[?25l", end='', flush=True)

def _show_cursor() -> None:
    print("\033[?25h", end='', flush=True)


# ─────────────────────────────────────────────────────────────────
#  Progress bar renderer
# ─────────────────────────────────────────────────────────────────

BAR_WIDTH = 22

STATUS_COLOUR = {
    'queued':      Fore.LIGHTBLACK_EX,
    'starting':    Fore.YELLOW,
    'fetching':    Fore.YELLOW,
    'downloading': Fore.CYAN,
    'merging':     Fore.MAGENTA,
    'done':        Fore.GREEN,
    'error':       Fore.RED,
}

STATUS_ICON = {
    'queued':      '○',
    'starting':    '◌',
    'fetching':    '◌',
    'downloading': '▶',
    'merging':     '⚙',
    'done':        '✓',
    'error':       '✗',
}

SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
_spin_idx = 0


def _render_bar(pct: float, width: int = BAR_WIDTH) -> str:
    filled = int(width * pct / 100)
    bar    = '█' * filled + '░' * (width - filled)
    return bar


def _render_slot(slot: dict, idx: int) -> list:
    """Return 2 lines for one download slot."""
    status  = slot.get('status', 'queued')
    title   = slot.get('title', '…')[:42]
    pct     = slot.get('pct', 0.0)
    speed   = slot.get('speed', 0.0)
    eta     = slot.get('eta')
    elapsed = slot.get('elapsed', 0.0)
    total   = slot.get('total', 0)
    dl      = slot.get('downloaded', 0)
    error   = slot.get('error', '')

    colour = STATUS_COLOUR.get(status, Fore.WHITE)
    icon   = STATUS_ICON.get(status, '?')

    line1 = (
        Fore.LIGHTBLACK_EX + f" [{idx+1:>2}] "
        + colour + icon + " "
        + Fore.WHITE + f"{title:<42}"
    )

    if status == 'done':
        bar   = _render_bar(100)
        stats = Fore.GREEN + f" 100%  Done in {_fmt_duration(elapsed)}"
        line2 = Fore.LIGHTBLACK_EX + "       " + Fore.GREEN + bar + stats

    elif status == 'error':
        line2 = Fore.LIGHTBLACK_EX + "       " + Fore.RED + f"✗ Error: {error[:55]}"

    elif status in ('queued',):
        line2 = Fore.LIGHTBLACK_EX + "       " + "Waiting in queue…"

    elif status in ('starting', 'fetching'):
        global _spin_idx
        spin  = SPINNER[_spin_idx % len(SPINNER)]
        line2 = Fore.LIGHTBLACK_EX + "       " + Fore.YELLOW + f"{spin} Preparing…"

    elif status == 'merging':
        bar   = _render_bar(100)
        line2 = Fore.LIGHTBLACK_EX + "       " + Fore.MAGENTA + bar + " Merging…"

    else:  # downloading
        bar      = _render_bar(pct)
        pct_str  = f"{pct:5.1f}%"
        spd_str  = _fmt_bytes(speed) + "/s" if speed else "  ?/s "
        eta_str  = _fmt_eta(eta)
        size_str = f"{_fmt_bytes(dl)}/{_fmt_bytes(total)}" if total else _fmt_bytes(dl)
        line2 = (
            Fore.LIGHTBLACK_EX + "       "
            + Fore.CYAN + bar
            + Fore.WHITE + f" {pct_str}"
            + Fore.YELLOW + f"  {spd_str}"
            + Fore.LIGHTBLACK_EX + f"  ETA {eta_str}"
            + Fore.LIGHTBLACK_EX + f"  {size_str}"
        )

    return [line1, line2]


# ─────────────────────────────────────────────────────────────────
#  Live dashboard loop (runs in its own thread)
# ─────────────────────────────────────────────────────────────────

def _dashboard_loop(n_slots: int, stop_event: threading.Event) -> None:
    global _spin_idx
    _hide_cursor()

    blank_lines = n_slots * 2 + 3
    print("\n" * blank_lines, end='', flush=True)

    try:
        while not stop_event.is_set():
            _spin_idx += 1
            slots = PROGRESS.get_all()

            done  = sum(1 for s in slots if s.get('status') == 'done')
            error = sum(1 for s in slots if s.get('status') == 'error')
            total = len(slots)

            lines = []

            lines.append(
                Fore.CYAN
                + f" Stream Scoop — {done}/{total} done"
                + (f"  {Fore.RED}{error} error(s)" if error else "")
                + " ".ljust(20)
            )
            lines.append(Fore.CYAN + "─" * 74)

            for i, slot in enumerate(slots):
                lines.extend(_render_slot(slot, i))

            lines.append(Fore.LIGHTBLACK_EX + "  Press Ctrl+C to cancel all." + " " * 30)

            output = _move_up(blank_lines)
            for line in lines:
                output += _clear_line() + line + "\n"

            print(output, end='', flush=True)
            blank_lines = len(lines)

            time.sleep(0.3)

    finally:
        _show_cursor()


# ─────────────────────────────────────────────────────────────────
#  Final summary table
# ─────────────────────────────────────────────────────────────────

def _print_summary(slots: list, wall_time: float) -> None:
    print()
    print(Fore.CYAN + " Download Summary ".center(74, "="))
    print(Fore.LIGHTBLACK_EX + f"  Total wall time: {_fmt_duration(wall_time)}\n")

    for i, s in enumerate(slots):
        status  = s.get('status', '?')
        title   = s.get('title', '?')[:45]
        elapsed = s.get('elapsed', 0.0)
        colour  = STATUS_COLOUR.get(status, Fore.WHITE)
        icon    = STATUS_ICON.get(status, '?')
        error   = s.get('error', '')

        line = (
            Fore.LIGHTBLACK_EX + f"  [{i+1:>2}] "
            + colour + f"{icon} {title:<45} "
        )
        if status == 'done':
            line += Fore.GREEN + f"  {_fmt_duration(elapsed)}"
        elif status == 'error':
            line += Fore.RED + f"  {error[:30]}"
        print(line)

    print(Fore.CYAN + "=" * 74)


# ─────────────────────────────────────────────────────────────────
#  URL collection + playlist expansion
# ─────────────────────────────────────────────────────────────────

def _collect_urls(cookie_file) -> list:
    print(Fore.LIGHTGREEN_EX
          + f"\nPaste URLs one by one. Type {Fore.WHITE}'done'{Fore.LIGHTGREEN_EX}"
            f" or {Fore.WHITE}'d'{Fore.LIGHTGREEN_EX} when finished.\n")
    raw_urls = []
    while True:
        print(Fore.LIGHTRED_EX + "URL: ", end='')
        url = input().strip()
        if url.lower() in ('done', 'd'):
            if not raw_urls:
                print(Fore.YELLOW + "Add at least one URL.")
                continue
            break
        if url:
            raw_urls.append(url)
            print(Fore.LIGHTGREEN_EX + f"  Added ({len(raw_urls)} total).")
        else:
            print(Fore.RED + "URL cannot be empty.")

    all_urls = []
    for url in raw_urls:
        print(Fore.LIGHTBLACK_EX + f"\nResolving {url[:70]}...")
        try:
            opts = {'quiet': True, 'extract_flat': 'in_playlist',
                    'cookiefile': cookie_file}
            with YT.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            if 'entries' in info:
                entries = [e for e in info['entries'] if e.get('url')]
                print(Fore.LIGHTGREEN_EX
                      + f"  Playlist: {len(entries)} videos — \"{info.get('title','')}\"")
                entries = select_playlist_entries(entries)
                all_urls.extend(e['url'] for e in entries)
            else:
                all_urls.append(url)
        except Exception as e:
            print(Fore.YELLOW + f"  Could not resolve, using as-is ({e})")
            all_urls.append(url)

    return all_urls


# ─────────────────────────────────────────────────────────────────
#  Confirmation table before firing downloads
# ─────────────────────────────────────────────────────────────────

def _show_queue(jobs: list) -> None:
    clear_screen()
    print(Fore.CYAN + f" Download Queue — {len(jobs)} item(s) ".center(74, "="))

    mode_label = {
        'video':      'Video',
        'audio':      'Audio only',
        'subtitles':  'Subtitles',
        'video+subs': 'Video + Subs',
    }

    for i, job in enumerate(jobs, 1):
        title  = job.get('title', '?')[:40]
        mode   = mode_label.get(job.get('mode', '?'), job.get('mode', '?'))
        height = job.get('height')
        afmt   = job.get('audio_fmt')
        clip   = ''
        if job.get('start_t') or job.get('end_t'):
            clip = f"  [clip {job.get('start_t','0')}→{job.get('end_t','end')}]"

        quality = ''
        if height:
            quality = f"  {height}p"
        elif afmt:
            quality = f"  {afmt.get('bitrate',0):.0f}kbps"

        aria = "  [aria2c]" if job.get('use_aria2c') else ""

        print(get_next_colour()
              + f"  {i:>3}. {title:<40}"
              + Fore.WHITE + f"  {mode:<14}{quality}{clip}{aria}")

    print(Fore.CYAN + "=" * 74)


# ─────────────────────────────────────────────────────────────────
#  Main entry point called from main.py
# ─────────────────────────────────────────────────────────────────

def run_concurrent_session(cfg: dict, aria2c_ok: bool) -> None:
    """
    Full concurrent download session:
      1. Get cookies + aria2c choice
      2. Get save path
      3. Collect + expand URLs
      4. Configure each job interactively
      5. Show queue, confirm
      6. Run all jobs concurrently with live dashboard
      7. Print summary
    """
    # Clear the PROGRESS store for a fresh session
    PROGRESS.clear()

    cookie_file = get_cookies()
    use_aria2c  = ask_use_aria2c(aria2c_ok)

    default_path = cfg.get('default_path',
                           os.path.join(os.path.expanduser('~'), 'Downloads', 'StreamScoop'))
    print(Fore.LIGHTBLUE_EX + f"\nDefault download path: {default_path}")
    while True:
        c = input("Use default path? (Y/n): ").strip().lower()
        if c in ('', 'y', 'yes'):
            save_path = default_path
            break
        if c in ('n', 'no'):
            raw       = input(Fore.WHITE + "Custom path: ").strip()
            save_path = resolve_path(raw)
            break
        print(Fore.RED + "Enter Y or n.")

    if not ensure_writable_dir(save_path):
        ans = input(Fore.YELLOW
                    + f"'{save_path}' doesn't exist / not writable. Create? (Y/n): "
                    ).strip().lower()
        if ans in ('', 'y', 'yes'):
            if not ensure_writable_dir(save_path):
                print(Fore.RED + "Cannot create directory. Aborting.")
                return
        else:
            return

    urls = _collect_urls(cookie_file)
    if not urls:
        print(Fore.RED + "No URLs. Returning to menu.")
        return

    jobs = []
    print()
    for i, url in enumerate(urls):
        job = configure_video_job(
            url, save_path, cfg, cookie_file, use_aria2c,
            job_num=i + 1, total_jobs=len(urls)
        )
        if job is None:
            print(Fore.YELLOW + f"  Skipped URL {i+1}.")
        else:
            jobs.append(job)

    if not jobs:
        print(Fore.RED + "All URLs skipped. Returning to menu.")
        return

    _show_queue(jobs)

    max_concurrent = cfg.get('max_concurrent_downloads', 3)
    print(Fore.LIGHTBLACK_EX
          + f"\n  {len(jobs)} download(s) will run with up to "
            f"{max_concurrent} at a time.")
    print(Fore.YELLOW + "\n  Press ENTER to start, or 'q' to cancel: ", end='')
    ans = input().strip().lower()
    if ans == 'q':
        print(Fore.YELLOW + "Cancelled.")
        return

    for i, job in enumerate(jobs):
        PROGRESS.update(i, title=job.get('title', '?')[:45], status='queued')

    stop_event    = threading.Event()
    dashboard_thr = threading.Thread(
        target=_dashboard_loop,
        args=(len(jobs), stop_event),
        daemon=True
    )
    dashboard_thr.start()

    wall_start = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
            futures = {
                pool.submit(_run_job, job, i): i
                for i, job in enumerate(jobs)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    future.result()
                except Exception as e:
                    PROGRESS.update(idx, status='error', error=str(e)[:80])

    except KeyboardInterrupt:
        print(Fore.LIGHTMAGENTA_EX + "\n\nInterrupted — waiting for active downloads to stop…")
    finally:
        wall_time = time.perf_counter() - wall_start
        stop_event.set()
        dashboard_thr.join(timeout=1.5)

    clear_screen()
    _print_summary(PROGRESS.get_all(), wall_time)

    done_count  = sum(1 for s in PROGRESS.get_all() if s.get('status') == 'done')
    error_count = sum(1 for s in PROGRESS.get_all() if s.get('status') == 'error')
    print()
    if error_count:
        print(Fore.YELLOW + f"  {done_count} succeeded, {error_count} failed.")
    else:
        print(Fore.GREEN + f"  ✓ All {done_count} download(s) completed successfully!")

    print(Fore.LIGHTMAGENTA_EX + f"  Files saved to: {save_path}")
    input(Fore.LIGHTBLACK_EX + "\nPress ENTER to return to menu…")
