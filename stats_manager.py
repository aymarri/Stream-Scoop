"""
stats_manager.py — Download statistics and analytics.

Features:
  - Total downloads by type (video/audio/subtitles/thumbnail)
  - Downloads per day / week / month chart (ASCII)
  - Most downloaded domains
  - Estimated total storage used (from log)
  - Streak tracking (days with at least one download)
  - Export stats to CSV#
"""

import os
import re
import csv
from collections import defaultdict
from datetime import datetime, timedelta
from time import sleep

import colorama
from colorama import Fore

from utilities import clear_screen, resolve_path, _fmt_bytes, _fmt_duration
from colours import get_next_colour

colorama.init(autoreset=True)


# ─────────────────────────────────────────────────────────────────
#  Log parsing
# ─────────────────────────────────────────────────────────────────

_LOG_RE = re.compile(
    r'\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s+'
    r'(?P<type>[^|]+?)\s*\|\s*'
    r'(?P<url>[^|]+?)\s*\|\s*'
    r'(?P<path>[^|]+)'
    r'(?:\s*\|\s*(?P<dur>.+))?'
)


def _parse_log(log_path: str) -> list:
    """Return list of dicts for each log entry."""
    if not os.path.isfile(log_path):
        return []
    entries = []
    with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = _LOG_RE.match(line.strip())
            if m:
                entries.append({
                    'ts':   datetime.strptime(m.group('ts'), '%Y-%m-%d %H:%M:%S'),
                    'type': m.group('type').strip(),
                    'url':  m.group('url').strip(),
                    'path': m.group('path').strip(),
                    'dur':  m.group('dur').strip() if m.group('dur') else '',
                })
    return entries


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc
        # Strip www.
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain or 'unknown'
    except Exception:
        return 'unknown'


def _duration_str_to_seconds(dur_str: str) -> float:
    """Convert '2m 30s' or '1h 5m 3s' to seconds."""
    total = 0.0
    for m in re.finditer(r'(\d+)([hms])', dur_str):
        val, unit = int(m.group(1)), m.group(2)
        if unit == 'h':
            total += val * 3600
        elif unit == 'm':
            total += val * 60
        elif unit == 's':
            total += val
    return total


# ─────────────────────────────────────────────────────────────────
#  ASCII chart
# ─────────────────────────────────────────────────────────────────

def _ascii_bar_chart(data: dict, title: str, bar_width: int = 30,
                     max_labels: int = 20) -> None:
    """Print a horizontal ASCII bar chart."""
    if not data:
        print(Fore.YELLOW + "  No data.")
        return

    # Limit to top N
    sorted_items = sorted(data.items(), key=lambda x: -x[1])[:max_labels]
    max_val = max(v for _, v in sorted_items) or 1
    max_label = max(len(str(k)) for k, _ in sorted_items)

    print(Fore.CYAN + f"\n  {title}")
    print(Fore.LIGHTBLACK_EX + "  " + "─" * (max_label + bar_width + 15))
    for label, val in sorted_items:
        filled = int(val / max_val * bar_width)
        bar    = '█' * filled + '░' * (bar_width - filled)
        col    = get_next_colour()
        print(col + f"  {str(label):<{max_label}}  {bar}  {val}")
    print(Fore.LIGHTBLACK_EX + "  " + "─" * (max_label + bar_width + 15))


def _ascii_timeline(entries: list, days: int = 30) -> None:
    """Print daily download count for the last N days."""
    today  = datetime.now().date()
    counts: dict = defaultdict(int)
    for e in entries:
        day = e['ts'].date()
        if (today - day).days < days:
            counts[day] += 1

    max_count = max(counts.values(), default=1)
    print(Fore.CYAN + f"\n  Downloads per day (last {days} days)")
    print(Fore.LIGHTBLACK_EX + "  " + "─" * (days + 15))

    HEIGHT = 8
    # Build grid
    grid = []
    for row in range(HEIGHT, 0, -1):
        line = "  "
        threshold = max_count * row / HEIGHT
        for d in range(days, -1, -1):
            day = today - timedelta(days=d)
            cnt = counts.get(day, 0)
            if cnt >= threshold:
                line += get_next_colour() + '█'
            else:
                line += Fore.LIGHTBLACK_EX + '░'
        grid.append(line)

    for i, line in enumerate(grid):
        label = f"{max_count * (HEIGHT - i) // HEIGHT:>3}" if i % 2 == 0 else "   "
        print(Fore.LIGHTBLACK_EX + label + " " + line)

    # X axis — show dates every 7 days
    x_axis = "       "
    for d in range(days, -1, -1):
        day = today - timedelta(days=d)
        if d % 7 == 0:
            x_axis += day.strftime('%m/%d')[:4]
        else:
            x_axis += ' '
    print(Fore.LIGHTBLACK_EX + x_axis)


# ─────────────────────────────────────────────────────────────────
#  Stats computation
# ─────────────────────────────────────────────────────────────────

def _compute_stats(entries: list) -> dict:
    if not entries:
        return {}

    # By type
    by_type: dict = defaultdict(int)
    for e in entries:
        dl_type = e['type'].split()[0].lower()  # "Video", "Audio", etc.
        by_type[dl_type] += 1

    # By domain
    by_domain: dict = defaultdict(int)
    for e in entries:
        by_domain[_extract_domain(e['url'])] += 1

    # By day of week
    by_dow: dict = defaultdict(int)
    dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    for e in entries:
        by_dow[dow_names[e['ts'].weekday()]] += 1

    # By hour
    by_hour: dict = defaultdict(int)
    for e in entries:
        by_hour[e['ts'].hour] += 1

    # Total duration downloaded
    total_dur = 0.0
    for e in entries:
        total_dur += _duration_str_to_seconds(e.get('dur', ''))

    # Streak calculation
    today  = datetime.now().date()
    days_with_dl = set(e['ts'].date() for e in entries)
    streak = 0
    day = today
    while day in days_with_dl:
        streak += 1
        day -= timedelta(days=1)

    # First and last download
    sorted_e = sorted(entries, key=lambda x: x['ts'])
    first_dl = sorted_e[0]['ts'] if sorted_e else None
    last_dl  = sorted_e[-1]['ts'] if sorted_e else None

    # Average downloads per day (over active period)
    if first_dl and last_dl:
        active_days = max((last_dl.date() - first_dl.date()).days + 1, 1)
        avg_per_day = len(entries) / active_days
    else:
        avg_per_day = 0

    return {
        'total':       len(entries),
        'by_type':     dict(by_type),
        'by_domain':   dict(by_domain),
        'by_dow':      dict(by_dow),
        'by_hour':     dict(by_hour),
        'total_dur':   total_dur,
        'streak':      streak,
        'first_dl':    first_dl,
        'last_dl':     last_dl,
        'avg_per_day': avg_per_day,
    }


def _print_summary(stats: dict) -> None:
    print(Fore.CYAN + "\n  ─── OVERVIEW ─────────────────────────────────────────────")
    print(Fore.WHITE  + f"  Total downloads     : {stats['total']}")
    print(Fore.WHITE  + f"  Current streak      : {stats['streak']} day(s)")
    print(Fore.WHITE  + f"  Avg downloads/day   : {stats['avg_per_day']:.1f}")
    if stats.get('total_dur'):
        print(Fore.WHITE + f"  Total download time : {_fmt_duration(stats['total_dur'])}")
    if stats.get('first_dl'):
        print(Fore.WHITE + f"  First download      : {stats['first_dl'].strftime('%Y-%m-%d')}")
    if stats.get('last_dl'):
        print(Fore.WHITE + f"  Latest download     : {stats['last_dl'].strftime('%Y-%m-%d %H:%M')}")


def _export_csv(entries: list, out_path: str) -> None:
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['timestamp', 'type', 'url', 'path', 'duration'])
        writer.writeheader()
        for e in entries:
            writer.writerow({
                'timestamp': e['ts'].strftime('%Y-%m-%d %H:%M:%S'),
                'type':      e['type'],
                'url':       e['url'],
                'path':      e['path'],
                'duration':  e.get('dur', ''),
            })
    print(Fore.GREEN + f"\n  Exported {len(entries)} entries to:\n  {out_path}")


# ─────────────────────────────────────────────────────────────────
#  Main entry point
# ─────────────────────────────────────────────────────────────────

def run_stats_manager(cfg: dict) -> None:
    """Main entry point for download statistics."""
    default_path = cfg.get('default_path',
                           os.path.join(os.path.expanduser('~'), 'Downloads', 'StreamScoop'))
    log_path = os.path.join(default_path, 'download_history.txt')

    entries = _parse_log(log_path)
    stats   = _compute_stats(entries)

    while True:
        clear_screen()
        print(Fore.CYAN + " Download Statistics ".center(70, "="))
        if not entries:
            print(Fore.YELLOW + "\n  No download history found.")
            print(Fore.LIGHTBLACK_EX + f"  Log file: {log_path}")
            input(Fore.LIGHTBLACK_EX + "\n  Press ENTER to return to menu…")
            return

        _print_summary(stats)

        print(Fore.CYAN + "\n  ─── MENU ─────────────────────────────────────────────────")
        ops = [
            ("1", "Downloads by type (bar chart)"),
            ("2", "Downloads by domain (bar chart)"),
            ("3", "Downloads by day of week"),
            ("4", "Downloads by hour of day"),
            ("5", "Timeline — last 30 days"),
            ("6", "Timeline — last 90 days"),
            ("7", "Export history to CSV"),
            ("b", "Back to main menu"),
        ]
        for key, label in ops:
            print(get_next_colour() + f"  [{key}] {label}")
        print()

        choice = input(Fore.WHITE + "Choice: ").strip().lower()

        if choice == 'b' or not choice:
            return

        if choice == '1':
            _ascii_bar_chart(stats.get('by_type', {}), "Downloads by Type")

        elif choice == '2':
            top_domains = dict(
                sorted(stats.get('by_domain', {}).items(), key=lambda x: -x[1])[:15]
            )
            _ascii_bar_chart(top_domains, "Top 15 Domains")

        elif choice == '3':
            order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            dow   = {k: stats.get('by_dow', {}).get(k, 0) for k in order}
            _ascii_bar_chart(dow, "Downloads by Day of Week", bar_width=25, max_labels=7)

        elif choice == '4':
            hour_data = {f"{h:02}:00": stats.get('by_hour', {}).get(h, 0) for h in range(24)}
            _ascii_bar_chart(hour_data, "Downloads by Hour", bar_width=20, max_labels=24)

        elif choice == '5':
            _ascii_timeline(entries, days=30)

        elif choice == '6':
            _ascii_timeline(entries, days=90)

        elif choice == '7':
            out_path = os.path.join(default_path, 'download_history_export.csv')
            _export_csv(entries, out_path)

        else:
            print(Fore.RED + "  Invalid choice.")
            sleep(0.5)
            continue

        input(Fore.LIGHTBLACK_EX + "\n  Press ENTER to continue…")
