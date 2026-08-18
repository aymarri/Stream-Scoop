"""
utilities.py — Shared helpers for Stream Scoop.

Additions over original:
  - ProgressStore.clear() method (needed when starting a new concurrent session)
  - Proxy support helpers
  - Better unique_filename (avoids yt-dlp template conflicts)
  - _fmt_speed helper
  - Enhanced error messages#
"""

import os
import sys
import subprocess as sp
import threading
from time import sleep, perf_counter
from datetime import datetime
from colorama import init, Fore

init(autoreset=True)


# ──────────────────────────────────────────────
#  Screen
# ──────────────────────────────────────────────

def clear_screen() -> None:
    if sys.platform == 'win32':
        os.system('cls')
    else:
        os.system('clear')


# ──────────────────────────────────────────────
#  Cookie helper
# ──────────────────────────────────────────────

def get_cookies():
    while True:
        print(Fore.LIGHTBLUE_EX + "\n(🍪) Cookies file path (press ENTER to skip): ", end='')
        raw = input()
        cookie_file = raw.strip().strip('"\'').strip()

        if not cookie_file:
            print(Fore.LIGHTYELLOW_EX + "Proceeding without cookies.")
            sleep(0.6)
            return None

        cookie_file = os.path.expanduser(os.path.expandvars(cookie_file))

        if os.path.isfile(cookie_file):
            print(Fore.LIGHTGREEN_EX + f"Using cookies: {cookie_file}")
            sleep(0.6)
            return cookie_file

        print(Fore.LIGHTRED_EX + f"File not found: '{cookie_file}' — try again.")


# ──────────────────────────────────────────────
#  aria2c helper
# ──────────────────────────────────────────────

def ask_use_aria2c(aria2c_installed: bool) -> bool:
    if not aria2c_installed:
        return False
    while True:
        choice = input(Fore.LIGHTCYAN_EX + "\nUse aria2c for faster downloads? (Y/n): ").strip().lower()
        if choice in ('', 'y', 'yes'):
            print(Fore.LIGHTGREEN_EX + "Using aria2c.")
            sleep(0.5)
            return True
        if choice in ('n', 'no'):
            print(Fore.LIGHTYELLOW_EX + "Using yt-dlp's built-in downloader.")
            sleep(0.5)
            return False
        print(Fore.RED + "Enter Y or n.")


# ──────────────────────────────────────────────
#  Thread-safe progress state (used by dashboard)
# ──────────────────────────────────────────────

class ProgressStore:
    """
    Shared state for all concurrent downloads.
    Each slot keyed by an integer index (0, 1, 2 …).
    """
    def __init__(self):
        self._lock  = threading.Lock()
        self._slots: dict = {}

    def update(self, idx: int, **kwargs) -> None:
        with self._lock:
            if idx not in self._slots:
                self._slots[idx] = {
                    'title':      '…',
                    'status':     'queued',
                    'pct':        0.0,
                    'speed':      0.0,
                    'eta':        None,
                    'downloaded': 0,
                    'total':      0,
                    'elapsed':    0.0,
                    'error':      '',
                }
            self._slots[idx].update(kwargs)

    def get_all(self) -> list:
        with self._lock:
            return [dict(v) for v in self._slots.values()]

    def get(self, idx: int) -> dict:
        with self._lock:
            return dict(self._slots.get(idx, {}))

    def clear(self) -> None:
        """Reset all slots — call before starting a new concurrent session."""
        with self._lock:
            self._slots.clear()


# Singleton used by download workers and the dashboard
PROGRESS = ProgressStore()


# ──────────────────────────────────────────────
#  Progress hook factory (concurrent-aware)
# ──────────────────────────────────────────────

def create_progress_hook(slot_idx=None):
    """
    Returns (hook_fn, get_duration_fn).

    If slot_idx is given the hook writes into the shared PROGRESS store
    (used for concurrent dashboard mode).
    Otherwise it prints an inline progress line (sequential mode).
    """
    state = {'start': None, 'end': None}

    def hook(d: dict) -> None:
        if d['status'] == 'downloading':
            if state['start'] is None:
                state['start'] = perf_counter()

            downloaded = d.get('downloaded_bytes', 0) or 0
            total      = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            speed      = d.get('speed') or 0
            eta        = d.get('eta')
            elapsed    = perf_counter() - (state['start'] or perf_counter())

            if slot_idx is not None:
                pct = downloaded / total * 100 if total else 0
                PROGRESS.update(
                    slot_idx,
                    status='downloading',
                    pct=pct,
                    speed=speed,
                    eta=eta,
                    downloaded=downloaded,
                    total=total,
                    elapsed=elapsed,
                )
            else:
                pct_s = f"{downloaded / total * 100:.1f}%" if total else "?%"
                spd   = _fmt_bytes(speed) + "/s" if speed else "?/s"
                eta_s = f"ETA {eta}s" if eta is not None else ""
                dl    = _fmt_bytes(downloaded)
                tot   = f"/ {_fmt_bytes(total)}" if total else ""
                line  = (
                    f"\r  {Fore.CYAN}{pct_s:>6}"
                    f"  {Fore.WHITE}{dl}{tot}"
                    f"  {Fore.YELLOW}{spd}"
                    f"  {Fore.LIGHTBLACK_EX}{eta_s}"
                )
                print(line, end='', flush=True)

        elif d['status'] == 'finished':
            state['end'] = perf_counter()
            if slot_idx is not None:
                elapsed = perf_counter() - (state['start'] or perf_counter())
                PROGRESS.update(slot_idx, status='merging', pct=100.0, elapsed=elapsed)
            else:
                print()

        elif d['status'] == 'error':
            if slot_idx is not None:
                PROGRESS.update(slot_idx, status='error')

    def get_duration():
        if state['start'] and state['end']:
            return state['end'] - state['start']
        return None

    return hook, get_duration


# ──────────────────────────────────────────────
#  Bytes / duration / speed formatters
# ──────────────────────────────────────────────

def _fmt_bytes(n: float) -> str:
    if not n:
        return "0 B"
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_duration(seconds) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {sec}s"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _fmt_eta(seconds) -> str:
    if seconds is None:
        return "--:--"
    s = int(seconds)
    m, sec = divmod(s, 60)
    h, m   = divmod(m, 60)
    if h:
        return f"{h}:{m:02}:{sec:02}"
    return f"{m:02}:{sec:02}"


def _fmt_speed(bps: float) -> str:
    """Format download speed."""
    return _fmt_bytes(bps) + "/s"


# ──────────────────────────────────────────────
#  Download log
# ──────────────────────────────────────────────

_log_lock = threading.Lock()

def log_download(url: str, save_path: str, download_type: str,
                 duration=None, auto_log: bool = False) -> bool:
    if not auto_log:
        while True:
            choice = input(Fore.LIGHTMAGENTA_EX + "\nLog this download? (Y/n): ").strip().lower()
            if choice in ('', 'y', 'yes'):
                break
            if choice in ('n', 'no'):
                return False
            print(Fore.RED + "Enter Y or n.")

    log_file = os.path.join(save_path, 'download_history.txt')
    os.makedirs(save_path, exist_ok=True)

    timestamp    = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    duration_str = _fmt_duration(duration) if duration else ''

    entry = f"[{timestamp}] {download_type} | {url} | {save_path}"
    if duration_str:
        entry += f" | {duration_str}"
    entry += "\n"

    with _log_lock:
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(entry)
            return True
        except IOError as e:
            print(Fore.YELLOW + f"Warning: could not write log — {e}")
            return False


# ──────────────────────────────────────────────
#  Download history viewer
# ──────────────────────────────────────────────

def view_history(save_path: str) -> None:
    log_file = os.path.join(save_path, 'download_history.txt')
    if not os.path.isfile(log_file):
        print(Fore.YELLOW + "\nNo download history found.")
        input(Fore.LIGHTBLACK_EX + "Press ENTER to continue...")
        return

    with open(log_file, 'r', encoding='utf-8') as f:
        lines = [l.rstrip() for l in f if l.strip()]

    if not lines:
        print(Fore.YELLOW + "\nDownload history is empty.")
        input(Fore.LIGHTBLACK_EX + "Press ENTER to continue...")
        return

    clear_screen()
    PAGE = 30
    total_pages = max(1, (len(lines) + PAGE - 1) // PAGE)
    cur_page = 0

    while True:
        clear_screen()
        start = cur_page * PAGE
        end   = min(start + PAGE, len(lines))
        print(Fore.CYAN + f" Download History — Page {cur_page+1}/{total_pages}  ({len(lines)} total) ".center(80, "="))
        for i, line in enumerate(lines[start:end], start + 1):
            # Colour-code by type
            if '| Video |' in line or '| Video' in line:
                col = Fore.CYAN
            elif '| Audio' in line:
                col = Fore.LIGHTGREEN_EX
            elif '| Subtitles' in line:
                col = Fore.LIGHTYELLOW_EX
            elif '| Thumbnail' in line:
                col = Fore.LIGHTMAGENTA_EX
            else:
                col = Fore.WHITE
            print(Fore.LIGHTBLACK_EX + f"  {i:>4}. " + col + line)
        print(Fore.CYAN + "=" * 80)
        print(Fore.LIGHTBLACK_EX + "  [A] Prev  [D] Next  [C] Clear history  [ENTER] Back")
        raw = input(Fore.WHITE + "  > ").strip().lower()
        if raw == 'a':
            cur_page = (cur_page - 1) % total_pages
        elif raw == 'd':
            cur_page = (cur_page + 1) % total_pages
        elif raw == 'c':
            confirm = input(Fore.RED + "  Clear ALL history? (yes/N): ").strip().lower()
            if confirm == 'yes':
                with _log_lock:
                    try:
                        open(log_file, 'w').close()
                        print(Fore.GREEN + "  History cleared.")
                        sleep(1)
                    except IOError:
                        print(Fore.RED + "  Could not clear history.")
                        sleep(1)
                return
        else:
            break


# ──────────────────────────────────────────────
#  Unique filename
# ──────────────────────────────────────────────

def unique_filename(title: str) -> str:
    """
    Returns a yt-dlp outtmpl-safe string.
    We pass through yt-dlp template variables like %(title)s unchanged,
    and only add a timestamp suffix to avoid collisions.
    """
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{title}_{ts}"


# ──────────────────────────────────────────────
#  Path helpers
# ──────────────────────────────────────────────

def resolve_path(raw: str) -> str:
    path = raw.strip().strip('"\'').strip()
    return os.path.expandvars(os.path.expanduser(path))


def ensure_writable_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, '.write_test')
        with open(test, 'w') as f:
            f.write('')
        os.remove(test)
        return True
    except (OSError, IOError):
        return False


# ──────────────────────────────────────────────
#  Desktop notification
# ──────────────────────────────────────────────

def notify(title: str, message: str) -> None:
    try:
        if sys.platform == 'darwin':
            sp.run(['osascript', '-e',
                    f'display notification "{message}" with title "{title}"'],
                   check=True, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        elif sys.platform == 'win32':
            try:
                from plyer import notification
                notification.notify(title=title, message=message, timeout=5)
            except ImportError:
                pass
        else:
            sp.run(['notify-send', title, message],
                   check=True, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    except Exception:
        pass


# ──────────────────────────────────────────────
#  yt-dlp update check
# ──────────────────────────────────────────────

def check_ytdlp_update() -> None:
    print(Fore.LIGHTBLACK_EX + "Checking yt-dlp for updates...", end='', flush=True)
    try:
        result = sp.run(
            [sys.executable, '-m', 'yt_dlp', '--update'],
            stdout=sp.PIPE, stderr=sp.PIPE, text=True, timeout=15
        )
        out = result.stdout + result.stderr
        if 'up to date' in out.lower():
            print(Fore.GREEN + " up to date.")
        elif 'updated' in out.lower():
            print(Fore.CYAN + " updated!")
        else:
            print(Fore.YELLOW + " (could not determine status)")
    except Exception:
        print(Fore.YELLOW + " (check failed)")
    sleep(0.6)


# ──────────────────────────────────────────────
#  Proxy helpers
# ──────────────────────────────────────────────

def apply_proxy(opts: dict, proxy: str) -> dict:
    """Apply proxy setting to a yt-dlp options dict."""
    if proxy:
        opts['proxy'] = proxy
    return opts


def test_proxy(proxy: str) -> bool:
    """Quick check whether a proxy is reachable."""
    try:
        import urllib.request
        import urllib.error
        handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
        opener  = urllib.request.build_opener(handler)
        opener.open('http://www.youtube.com', timeout=8)
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────
#  Error handler
# ──────────────────────────────────────────────

def handle_error(e: Exception) -> None:
    etype = type(e).__name__
    msg   = str(e)
    lower = msg.lower()

    print(Fore.LIGHTRED_EX + f"\n[{etype}] {msg}")

    hints = [
        (['network', 'connection', 'unable to download webpage', 'timed out', 'ssl'],
         "Check your internet connection."),
        (['age-restricted', 'age restricted', 'sign in', 'login required', 'members only'],
         "Content requires login — provide a cookies file."),
        (['private', 'unavailable', 'not available', 'has been removed', 'no longer available'],
         "Video is private, deleted, or geo-restricted."),
        (['copyright', 'blocked', 'not available in your country'],
         "Content blocked — try a VPN or proxy."),
        (['ffmpeg', 'postprocessing', 'merger'],
         "FFmpeg error — ensure it is installed and in PATH."),
        (['cookies', 'authentication', 'cookie'],
         "Cookies issue — re-export your browser cookies and try again."),
        (['is a live stream', 'live event'],
         "Live streams cannot be downloaded mid-stream."),
        (['invalid url', 'unsupported url', 'no suitable'],
         "Invalid or unsupported URL."),
        (['format', 'no video formats', 'requested format'],
         "No downloadable formats found for the requested quality."),
        (['http error 403'],
         "403 Forbidden — try with cookies or a different IP."),
        (['http error 429'],
         "Rate limited (429) — wait a while or use cookies/proxy."),
        (['http error 404'],
         "404 Not Found — the video may have been deleted."),
        (['socket', 'errno'],
         "Network socket error — check your firewall or proxy settings."),
    ]

    for keywords, hint in hints:
        if any(k in lower for k in keywords):
            print(Fore.YELLOW + f"→ {hint}")
            break
    else:
        print(Fore.YELLOW + "→ Unexpected error. Check the URL and your settings.")

    input(Fore.LIGHTBLACK_EX + "\nPress ENTER to continue...")
