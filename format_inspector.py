"""
format_inspector.py — Inspect all available formats for any URL.

Shows a detailed table of every video/audio format yt-dlp can see,
with codec, resolution, bitrate, filesize, and format ID.##
No downloading happens.
"""

import os
from time import sleep

import yt_dlp as YT
import colorama
from colorama import Fore

from utilities import clear_screen, get_cookies, handle_error, _fmt_bytes, resolve_path, ensure_writable_dir
from colours import get_next_colour

colorama.init(autoreset=True)


def _fetch_formats(url: str, cookie_file) -> dict:
    opts = {
        'quiet':       True,
        'no_warnings': True,
    }
    if cookie_file:
        opts['cookiefile'] = cookie_file
    with YT.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _fmt_codec(codec: str) -> str:
    if not codec or codec == 'none':
        return '—'
    return codec.split('.')[0][:10]


def _print_formats_table(info: dict) -> None:
    title    = info.get('title', 'Unknown')
    duration = info.get('duration')
    formats  = info.get('formats', [])

    dur_str = ''
    if duration:
        m, s = divmod(int(duration), 60)
        h, m = divmod(m, 60)
        dur_str = f"  [{h}:{m:02}:{s:02}]" if h else f"  [{m}:{s:02}]"

    clear_screen()
    print(Fore.CYAN + f"\n  {title[:70]}{dur_str}")
    print(Fore.CYAN + f"  {len(formats)} formats available\n")

    # ── Video formats ──────────────────────────────────────────
    video_fmts = [
        f for f in formats
        if f.get('vcodec') and f.get('vcodec') != 'none'
        and f.get('format_note') != 'storyboard'
    ]
    audio_fmts = [
        f for f in formats
        if (f.get('vcodec') == 'none' or not f.get('vcodec'))
        and f.get('acodec') and f.get('acodec') != 'none'
    ]

    if video_fmts:
        print(Fore.YELLOW + "  ─── VIDEO FORMATS ────────────────────────────────────────────────────")
        print(Fore.LIGHTBLACK_EX
              + f"  {'ID':<14}  {'Res':>8}  {'FPS':>5}  {'VCodec':<10}  "
                f"{'ACodec':<10}  {'TBR':>7}  {'Size':>10}  {'Note':<18}")
        print(Fore.LIGHTBLACK_EX + "  " + "─" * 92)
        for f in sorted(video_fmts, key=lambda x: -(x.get('height') or 0)):
            fid    = f.get('format_id', '?')[:14]
            height = f.get('height') or 0
            width  = f.get('width') or 0
            fps    = f.get('fps') or 0
            vcodec = _fmt_codec(f.get('vcodec', ''))
            acodec = _fmt_codec(f.get('acodec', ''))
            tbr    = f.get('tbr') or 0
            fsize  = f.get('filesize') or f.get('filesize_approx') or 0
            note   = (f.get('format_note') or '')[:18]
            res    = f"{width}x{height}" if width and height else (f"{height}p" if height else "?")
            col    = get_next_colour()
            print(col
                  + f"  {fid:<14}  {res:>8}  {fps:>5.0f}  {vcodec:<10}  "
                    f"{acodec:<10}  {tbr:>7.0f}  {_fmt_bytes(fsize):>10}  {note:<18}")

    if audio_fmts:
        print()
        print(Fore.YELLOW + "  ─── AUDIO-ONLY FORMATS ───────────────────────────────────────────────")
        print(Fore.LIGHTBLACK_EX
              + f"  {'ID':<14}  {'Codec':<10}  {'ABR':>7}  {'ASR':>7}  {'Size':>10}  {'Ext':<6}  {'Note':<18}")
        print(Fore.LIGHTBLACK_EX + "  " + "─" * 80)
        for f in sorted(audio_fmts, key=lambda x: -(x.get('abr') or 0)):
            fid    = f.get('format_id', '?')[:14]
            acodec = _fmt_codec(f.get('acodec', ''))
            abr    = f.get('abr') or 0
            asr    = f.get('asr') or 0
            fsize  = f.get('filesize') or f.get('filesize_approx') or 0
            ext    = (f.get('ext') or '')[:6]
            note   = (f.get('format_note') or '')[:18]
            col    = get_next_colour()
            print(col
                  + f"  {fid:<14}  {acodec:<10}  {abr:>7.0f}  {asr:>7}  "
                    f"{_fmt_bytes(fsize):>10}  {ext:<6}  {note:<18}")

    # ── Subtitle tracks ────────────────────────────────────────
    subs      = info.get('subtitles', {})
    auto_subs = info.get('automatic_captions', {})
    if subs or auto_subs:
        print()
        print(Fore.YELLOW + "  ─── SUBTITLE TRACKS ──────────────────────────────────────────────────")
        for lang, fmts in sorted(subs.items()):
            exts = ', '.join(f.get('ext', '?') for f in fmts)
            print(Fore.LIGHTCYAN_EX + f"  Manual  {lang.upper():<8}  ({exts})")
        for lang, fmts in sorted(auto_subs.items()):
            exts = ', '.join(f.get('ext', '?') for f in fmts)
            print(Fore.LIGHTBLACK_EX + f"  Auto    {lang.upper():<8}  ({exts})")

    # ── Chapters ────────────────────────────────────────────────
    chapters = info.get('chapters') or []
    if chapters:
        print()
        print(Fore.YELLOW + "  ─── CHAPTERS ─────────────────────────────────────────────────────────")
        for i, ch in enumerate(chapters, 1):
            start = ch.get('start_time', 0)
            end   = ch.get('end_time', start)
            ch_title = ch.get('title', f'Chapter {i}')
            m1, s1 = divmod(int(start), 60)
            h1, m1 = divmod(m1, 60)
            t1 = f"{h1}:{m1:02}:{s1:02}" if h1 else f"{m1}:{s1:02}"
            print(get_next_colour() + f"  {i:>3}. {t1}  {ch_title[:60]}")

    # ── Thumbnails ──────────────────────────────────────────────
    thumbs = info.get('thumbnails') or []
    if thumbs:
        print()
        print(Fore.YELLOW + "  ─── THUMBNAILS ───────────────────────────────────────────────────────")
        for t in thumbs[-3:]:  # show last 3 (usually highest quality)
            w = t.get('width') or '?'
            h = t.get('height') or '?'
            url_ = (t.get('url') or '')[:60]
            print(Fore.LIGHTBLACK_EX + f"  {w}×{h}  {url_}")


def _export_formats(info: dict, save_path: str) -> None:
    """Export format list to a text file."""
    title    = info.get('title', 'video').replace('/', '-').replace('\\', '-')
    filename = os.path.join(save_path, f"formats_{title[:40]}.txt")
    formats  = info.get('formats', [])

    lines = [
        f"Format Inspector — {info.get('title', 'Unknown')}\n",
        f"URL: {info.get('webpage_url', '?')}\n",
        "=" * 80 + "\n\n",
        f"{'Format ID':<16} {'Resolution':>10} {'FPS':>5} {'VCodec':<10} "
        f"{'ACodec':<10} {'TBR':>8} {'Filesize':>12} {'Note'}\n",
        "─" * 80 + "\n",
    ]
    for f in formats:
        fid    = f.get('format_id', '?')
        height = f.get('height') or 0
        width  = f.get('width') or 0
        fps    = f.get('fps') or 0
        vcodec = _fmt_codec(f.get('vcodec', ''))
        acodec = _fmt_codec(f.get('acodec', ''))
        tbr    = f.get('tbr') or 0
        fsize  = f.get('filesize') or f.get('filesize_approx') or 0
        note   = f.get('format_note') or ''
        res    = f"{width}x{height}" if width and height else (f"{height}p" if height else "—")
        lines.append(
            f"{fid:<16} {res:>10} {fps:>5.0f} {vcodec:<10} "
            f"{acodec:<10} {tbr:>8.0f} {_fmt_bytes(fsize):>12} {note}\n"
        )

    ensure_writable_dir(save_path)
    with open(filename, 'w', encoding='utf-8') as fh:
        fh.writelines(lines)
    print(Fore.GREEN + f"\n  Saved to: {filename}")


def run_format_inspector(cfg: dict) -> None:
    """Main entry point — inspect formats for one or more URLs."""
    clear_screen()
    print(Fore.CYAN + " Format Inspector ".center(60, "="))
    print(Fore.LIGHTBLACK_EX + "  See every available format for any URL before downloading.\n")

    cookie_file = get_cookies()

    while True:
        print(Fore.LIGHTGREEN_EX + "\nEnter URL to inspect (or 'back' to return): ", end='')
        url = input().strip()
        if url.lower() in ('back', 'b', ''):
            return

        print(Fore.LIGHTBLACK_EX + "  Fetching format list…")
        try:
            info = _fetch_formats(url, cookie_file)
        except Exception as e:
            handle_error(e)
            continue

        _print_formats_table(info)

        default_path = cfg.get('default_path',
                               os.path.join(os.path.expanduser('~'), 'Downloads', 'StreamScoop'))
        print()
        ans = input(Fore.YELLOW + "  Export format list to file? (y/N): ").strip().lower()
        if ans in ('y', 'yes'):
            _export_formats(info, default_path)
            sleep(1)

        print()
        ans2 = input(Fore.CYAN + "  Inspect another URL? (y/N): ").strip().lower()
        if ans2 not in ('y', 'yes'):
            return
