"""
download_logic.py

Each download function accepts an optional `slot_idx` parameter.
When set, progress goes to the shared PROGRESS store (concurrent dashboard mode).
When None, an inline progress bar is printed (sequential / solo mode).

Enhancements over original:
  - SponsorBlock support (remove or mark segments)
  - Chapter marker embedding
  - Subtitle muxing into video
  - Archive mode (skip already downloaded)
  - Geo-bypass option
  - Proxy support
  - Better format string building (avoids 'format not available' errors)
  - download_ranges now uses yt_dlp.utils.download_range_func properly##
"""

import os
import sys
import subprocess as sp
from time import sleep, perf_counter

import yt_dlp as YT
import colorama as clr
from colorama import Fore

from utilities import (
    clear_screen, log_download, unique_filename, handle_error,
    create_progress_hook, notify, _fmt_bytes, PROGRESS,
)
from colours import get_next_colour
from config import get_ydl_extra_opts

clr.init(autoreset=True)


# ─────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────

def _base_ydl_opts(cookie_file) -> dict:
    opts = {'quiet': True, 'no_warnings': True, 'noprogress': False}
    if cookie_file:
        opts['cookiefile'] = cookie_file
    return opts


def _apply_config(opts: dict, cfg: dict) -> dict:
    """Merge global config options into a yt-dlp opts dict."""
    if cfg.get('rate_limit'):
        opts['ratelimit'] = cfg['rate_limit']
    if cfg.get('retries'):
        opts['retries'] = cfg['retries']
    if cfg.get('concurrent_fragments'):
        opts['concurrent_fragment_downloads'] = cfg['concurrent_fragments']
    if cfg.get('sleep_interval'):
        opts['sleep_interval'] = cfg['sleep_interval']
    if cfg.get('proxy'):
        opts['proxy'] = cfg['proxy']
    if cfg.get('geo_bypass'):
        opts['geo_bypass'] = True
    if cfg.get('archive_mode') and cfg.get('archive_file'):
        opts['download_archive'] = cfg['archive_file']
    return opts


def _build_postprocessors(cfg: dict, embed_subs: bool = False) -> list:
    pps = []

    # SponsorBlock
    if cfg.get('sponsorblock_remove'):
        cats = cfg.get('sponsorblock_categories', ['sponsor'])
        pps.append({
            'key': 'SponsorBlock',
            'categories': cats,
            'when': 'after_filter',
        })
        pps.append({
            'key': 'ModifyChapters',
            'remove_sponsor_segments': cats,
        })
    elif cfg.get('sponsorblock_mark'):
        cats = cfg.get('sponsorblock_categories', ['sponsor'])
        pps.append({
            'key': 'SponsorBlock',
            'categories': cats,
            'when': 'after_filter',
        })

    # Chapters
    if cfg.get('embed_chapters'):
        pps.append({'key': 'FFmpegMetadata', 'add_chapters': True,
                    'add_metadata': bool(cfg.get('embed_metadata'))})
    elif cfg.get('embed_metadata'):
        pps.append({'key': 'FFmpegMetadata', 'add_metadata': True})

    # Thumbnail
    if cfg.get('embed_thumbnail'):
        pps.append({'key': 'EmbedThumbnail'})

    # Subtitles muxed into video
    if embed_subs or cfg.get('embed_subs'):
        pps.append({'key': 'FFmpegEmbedSubtitle', 'already_have_subtitle': False})

    return pps


def _print_video_info(info: dict) -> None:
    title    = info.get('title', 'Unknown')
    uploader = info.get('uploader') or info.get('channel') or 'Unknown'
    duration = info.get('duration')
    views    = info.get('view_count')
    upload   = info.get('upload_date', '')
    if upload and len(upload) == 8:
        upload = f"{upload[:4]}-{upload[4:6]}-{upload[6:]}"

    dur_str = ''
    if duration:
        m, s = divmod(int(duration), 60)
        h, m = divmod(m, 60)
        dur_str = f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"

    print(Fore.CYAN + "\n┌" + "─" * 56 + "┐")
    print(Fore.CYAN + "│" + Fore.WHITE + f"  {title[:54]:<54}" + Fore.CYAN + "│")
    print(Fore.CYAN + "│" + Fore.LIGHTBLACK_EX
          + f"  {uploader[:28]:<28}  {dur_str:<10}  {upload}"
          + " " * max(0, 56 - 28 - 10 - len(upload) - 6)
          + Fore.CYAN + "│")
    if views:
        view_str = f"  {views:,} views"
        print(Fore.CYAN + "│" + Fore.LIGHTBLACK_EX
              + f"{view_str:<56}" + Fore.CYAN + "│")
    print(Fore.CYAN + "└" + "─" * 56 + "┘")


def _ask_clip_range():
    choice = input(
        Fore.LIGHTYELLOW_EX + "\nDownload a specific clip? (y/N): "
    ).strip().lower()
    if choice not in ('y', 'yes'):
        return None, None
    print(Fore.LIGHTBLACK_EX + "  Format: HH:MM:SS or seconds (e.g. 1:30 or 90)")
    start = input(Fore.WHITE + "  Start time (ENTER = beginning): ").strip() or None
    end   = input(Fore.WHITE + "  End time   (ENTER = end):       ").strip() or None
    return start, end


def _sections_filter(start, end):
    if start is None and end is None:
        return None
    # Use yt_dlp's download_range_func for proper clip extraction
    try:
        from yt_dlp.utils import download_range_func
        start_s = _timestr_to_seconds(start) if start else 0
        end_s   = _timestr_to_seconds(end) if end else float('inf')
        return download_range_func(None, [(start_s, end_s)])
    except Exception:
        # Fallback: old-style sections string
        return f"*{start or '0'}-{end or 'inf'}"


def _timestr_to_seconds(t: str) -> float:
    """Convert HH:MM:SS or MM:SS or raw seconds string to float."""
    try:
        parts = t.split(':')
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        else:
            return float(t)
    except (ValueError, AttributeError):
        return 0.0


def _num_input(prompt: str, max_val: int) -> int:
    while True:
        try:
            idx = int(input(prompt).strip()) - 1
            if 0 <= idx < max_val:
                return idx
            print(Fore.RED + f"Enter 1–{max_val}.")
        except ValueError:
            print(Fore.RED + "Enter a valid number.")


def fetch_info(url: str, cookie_file) -> dict:
    """Extract video metadata without downloading."""
    opts = _base_ydl_opts(cookie_file)
    with YT.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def build_quality_list(info: dict) -> list:
    """Return sorted list of unique video heights with best tbr per height."""
    quality_map: dict = {}
    for f in info.get('formats', []):
        if (f.get('vcodec') == 'none'
                or f.get('format_note') == 'storyboard'
                or f.get('quality') == -1):
            continue
        height = f.get('height') or 0
        tbr    = f.get('tbr') or 0
        fsize  = f.get('filesize') or f.get('filesize_approx') or 0
        vcodec = (f.get('vcodec') or '').split('.')[0]
        if height not in quality_map or tbr > quality_map[height]['tbr']:
            quality_map[height] = {
                'format_id': f['format_id'],
                'height':    height,
                'tbr':       tbr,
                'filesize':  fsize,
                'vcodec':    vcodec,
            }
    return sorted(quality_map.values(), key=lambda x: -x['height'])


def build_audio_list(info: dict) -> list:
    """Return sorted list of audio-only formats."""
    fmts = [
        {
            'format_id': f['format_id'],
            'bitrate':   f.get('abr', 0) or 0,
            'ext':       f.get('ext', 'mp3'),
            'acodec':    (f.get('acodec') or '').split('.')[0],
            'filesize':  f.get('filesize') or f.get('filesize_approx') or 0,
        }
        for f in info.get('formats', [])
        if f.get('vcodec') == 'none' and (f.get('abr') or 0) > 0
    ]
    fmts.sort(key=lambda x: -x['bitrate'])
    return fmts


def _best_format_string(height) -> str:
    """
    Build a robust yt-dlp format string that gracefully falls back if the
    exact height isn't available.
    """
    if height:
        return (
            f"bestvideo[height={height}]+bestaudio/best[height={height}]"
            f"/bestvideo[height<={height}]+bestaudio/bestvideo+bestaudio/best"
        )
    return "bestvideo+bestaudio/best"


# ─────────────────────────────────────────────────────────────────
#  Interactive configuration (called BEFORE concurrent downloads)
# ─────────────────────────────────────────────────────────────────

def configure_video_job(url: str, save_path: str, cfg: dict,
                        cookie_file,
                        use_aria2c: bool,
                        job_num: int, total_jobs: int):
    """
    Fetch info for this URL, show video card, ask all questions interactively,
    and return a fully-configured job dict — WITHOUT starting the download.
    Returns None if the URL should be skipped.
    """
    print(Fore.CYAN + f"\n{'─'*54}")
    print(Fore.CYAN + f"  Configuring job {job_num}/{total_jobs}")
    print(Fore.CYAN + f"{'─'*54}")

    try:
        print(Fore.LIGHTBLACK_EX + "  Fetching video info...")
        info = fetch_info(url, cookie_file)
    except Exception as e:
        print(Fore.RED + f"  Could not fetch info: {e}")
        ans = input(Fore.YELLOW + "  Skip this URL? (Y/n): ").strip().lower()
        if ans in ('', 'y', 'yes'):
            return None
        return {
            'url': url, 'save_path': save_path, 'cfg': cfg,
            'cookie_file': cookie_file, 'use_aria2c': use_aria2c,
            'mode': 'video', 'title': url[:60], 'format_id': None,
            'height': None, 'start_t': None, 'end_t': None,
        }

    title = info.get('title', url[:50])
    _print_video_info(info)

    print(Fore.YELLOW + "\n  What to download?")
    print(Fore.WHITE  + "    [1] Video  [2] Audio only  [3] Subtitles  [4] Video + Subtitles")
    while True:
        m = input(Fore.WHITE + "  Choice (1-4): ").strip()
        if m in ('1', '2', '3', '4'):
            break
        print(Fore.RED + "  Enter 1–4.")
    mode_map = {'1': 'video', '2': 'audio', '3': 'subtitles', '4': 'video+subs'}
    mode = mode_map[m]

    job: dict = {
        'url':         url,
        'save_path':   save_path,
        'cfg':         cfg,
        'cookie_file': cookie_file,
        'use_aria2c':  use_aria2c,
        'mode':        mode,
        'title':       title,
        'info':        info,
        'height':      None,
        'format_id':   None,
        'audio_fmt':   None,
        'sub_lang':    None,
        'sub_ext':     None,
        'sub_is_auto': False,
        'start_t':     None,
        'end_t':       None,
    }

    if mode in ('video', 'video+subs'):
        sorted_q = build_quality_list(info)
        if not sorted_q:
            print(Fore.RED + "  No video formats found — skipping.")
            return None

        pref = cfg.get('preferred_quality')
        if pref:
            try:
                target   = int(str(pref).replace('p', ''))
                selected = min(sorted_q, key=lambda x: abs(x['height'] - target))
                print(Fore.LIGHTBLACK_EX + f"  Auto-selected: {selected['height']}p")
            except (ValueError, TypeError):
                selected = None
        else:
            selected = None

        if selected is None:
            print(Fore.CYAN + "\n  Available qualities:")
            for i, q in enumerate(sorted_q, 1):
                sz    = f"  ~{_fmt_bytes(q['filesize'])}" if q['filesize'] else ''
                codec = f"  [{q['vcodec']}]" if q['vcodec'] else ''
                print(get_next_colour() + f"    {i}. {q['height']}p{codec}{sz}")
            idx      = _num_input("  Choose quality (number): ", len(sorted_q))
            selected = sorted_q[idx]

        job['height']    = selected['height']
        job['format_id'] = selected['format_id']

    if mode == 'audio':
        audio_fmts = build_audio_list(info)
        if not audio_fmts:
            print(Fore.RED + "  No audio formats found — skipping.")
            return None

        print(Fore.CYAN + "\n  Available audio qualities:")
        for i, fmt in enumerate(audio_fmts, 1):
            sz    = f"  ~{_fmt_bytes(fmt['filesize'])}" if fmt['filesize'] else ''
            codec = f"  [{fmt['acodec']}]" if fmt['acodec'] else ''
            print(get_next_colour() + f"    {i}. {fmt['bitrate']:.0f} kbps ({fmt['ext']}){codec}{sz}")
        idx = _num_input("  Choose quality (number): ", len(audio_fmts))
        job['audio_fmt'] = audio_fmts[idx]

    if mode in ('subtitles', 'video+subs'):
        all_subs = []
        for lang, fmts in info.get('subtitles', {}).items():
            for fmt in fmts:
                all_subs.append({'lang': lang, 'ext': fmt.get('ext','vtt'), 'is_auto': False})
        for lang, fmts in info.get('automatic_captions', {}).items():
            for fmt in fmts:
                all_subs.append({'lang': lang, 'ext': fmt.get('ext','vtt'), 'is_auto': True})

        if not all_subs:
            print(Fore.YELLOW + "  No subtitles available for this video.")
            if mode == 'subtitles':
                return None
        else:
            ans = input(Fore.LIGHTCYAN_EX + "  English subtitles only? (Y/n): ").strip().lower()
            if ans in ('', 'y', 'yes'):
                en = [s for s in all_subs if s['lang'].lower().startswith('en')]
                if en:
                    all_subs = en
                else:
                    print(Fore.YELLOW + "  No English subs — showing all.")

            PAGE = 20
            total_pages = max(1, (len(all_subs) + PAGE - 1) // PAGE)
            cur_page = 0
            selected_sub = None
            while selected_sub is None:
                start = cur_page * PAGE
                end   = min(start + PAGE, len(all_subs))
                print(Fore.CYAN + f"\n  Subtitles (page {cur_page+1}/{total_pages}):")
                for i in range(start, end):
                    s  = all_subs[i]
                    tp = 'Auto' if s['is_auto'] else 'Manual'
                    print(get_next_colour() + f"    {i+1:>3}. {s['lang'].upper():8} ({tp}) — {s['ext'].upper()}")
                print(Fore.YELLOW + "  [A] Prev  [D] Next  [number] Select")
                raw = input(Fore.WHITE + "  > ").strip().lower()
                if raw == 'a':
                    cur_page = (cur_page - 1) % total_pages
                elif raw == 'd':
                    cur_page = (cur_page + 1) % total_pages
                else:
                    try:
                        idx = int(raw) - 1
                        if 0 <= idx < len(all_subs):
                            selected_sub = all_subs[idx]
                        else:
                            print(Fore.RED + f"  Enter 1–{len(all_subs)}.")
                    except ValueError:
                        print(Fore.RED + "  Enter a number, A, or D.")

            job['sub_lang']    = selected_sub['lang']
            job['sub_ext']     = selected_sub['ext']
            job['sub_is_auto'] = selected_sub['is_auto']

    if mode in ('video', 'video+subs', 'audio'):
        start_t, end_t = _ask_clip_range()
        job['start_t'] = start_t
        job['end_t']   = end_t

    return job


# ─────────────────────────────────────────────────────────────────
#  Actual download workers (called in threads)
# ─────────────────────────────────────────────────────────────────

def _run_job(job: dict, slot_idx: int) -> None:
    url        = job['url']
    save_path  = job['save_path']
    cfg        = job['cfg']
    mode       = job['mode']
    title      = job['title']

    PROGRESS.update(slot_idx, title=title[:45], status='starting')

    try:
        if mode == 'video':
            _worker_video(job, slot_idx)
        elif mode == 'audio':
            _worker_audio(job, slot_idx)
        elif mode == 'subtitles':
            _worker_subtitles(job, slot_idx)
        elif mode == 'video+subs':
            _worker_video(job, slot_idx)
            _worker_subtitles(job, slot_idx)

        PROGRESS.update(slot_idx, status='done', pct=100.0)
        log_download(url, save_path, mode, auto_log=True)

        if cfg.get('notify_on_complete'):
            notify("Stream Scoop", f"Done: {title[:40]}")

    except Exception as e:
        PROGRESS.update(slot_idx, status='error', error=str(e)[:80])


def _worker_video(job: dict, slot_idx: int) -> None:
    cfg        = job['cfg']
    cookie_file= job['cookie_file']
    use_aria2c = job['use_aria2c']
    url        = job['url']
    save_path  = job['save_path']
    height     = job['height']

    PROGRESS.update(slot_idx, status='downloading')
    hook, _ = create_progress_hook(slot_idx)

    merge_fmt = cfg.get('merge_format', 'mp4')
    naming    = cfg.get('output_naming', '%(title)s')
    dl_opts: dict = {
        'format':              _best_format_string(height),
        'outtmpl':             os.path.join(save_path, f"{naming}_%(id)s.%(ext)s"),
        'restrictfilenames':   True,
        'merge_output_format': merge_fmt,
        'cookiefile':          cookie_file,
        'progress_hooks':      [hook],
        'postprocessors':      _build_postprocessors(cfg),
        'quiet':               True,
        'no_warnings':         True,
        'writethumbnail':      bool(cfg.get('write_thumbnail')),
    }

    section = _sections_filter(job.get('start_t'), job.get('end_t'))
    if section:
        dl_opts['download_ranges']         = section
        dl_opts['force_keyframes_at_cuts'] = True

    if use_aria2c:
        dl_opts['external_downloader'] = 'aria2c'

    _apply_config(dl_opts, cfg)

    with YT.YoutubeDL(dl_opts) as ydl:
        ydl.download([url])

    PROGRESS.update(slot_idx, status='merging')


def _worker_audio(job: dict, slot_idx: int) -> None:
    cfg        = job['cfg']
    cookie_file= job['cookie_file']
    use_aria2c = job['use_aria2c']
    url        = job['url']
    save_path  = job['save_path']
    audio_fmt  = job.get('audio_fmt')

    if not audio_fmt:
        return

    PROGRESS.update(slot_idx, status='downloading')
    hook, _ = create_progress_hook(slot_idx)

    naming = cfg.get('output_naming', '%(title)s')
    dl_opts: dict = {
        'format':            audio_fmt['format_id'],
        'outtmpl':           os.path.join(save_path, f"{naming}_%(id)s.%(ext)s"),
        'restrictfilenames': True,
        'cookiefile':        cookie_file,
        'progress_hooks':    [hook],
        'postprocessors':    _build_postprocessors(cfg),
        'quiet':             True,
        'no_warnings':       True,
    }

    section = _sections_filter(job.get('start_t'), job.get('end_t'))
    if section:
        dl_opts['download_ranges']         = section
        dl_opts['force_keyframes_at_cuts'] = True

    if use_aria2c:
        dl_opts['external_downloader'] = 'aria2c'
    _apply_config(dl_opts, cfg)

    with YT.YoutubeDL(dl_opts) as ydl:
        ydl.download([url])


def _worker_subtitles(job: dict, slot_idx: int) -> None:
    cfg        = job['cfg']
    cookie_file= job['cookie_file']
    url        = job['url']
    save_path  = job['save_path']
    lang       = job.get('sub_lang')
    ext        = job.get('sub_ext', 'vtt')
    is_auto    = job.get('sub_is_auto', False)

    if not lang:
        return

    PROGRESS.update(slot_idx, status='downloading')
    hook, _ = create_progress_hook(slot_idx)
    naming   = cfg.get('output_naming', '%(title)s')

    dl_opts: dict = {
        'writesubtitles':    not is_auto,
        'writeautomaticsub': is_auto,
        'subtitleslangs':    [lang],
        'subtitlesformat':   ext,
        'skip_download':     True,
        'outtmpl':           os.path.join(save_path, f"{naming}_%(id)s"),
        'restrictfilenames': True,
        'cookiefile':        cookie_file,
        'progress_hooks':    [hook],
        'quiet':             True,
        'no_warnings':       True,
    }

    _apply_config(dl_opts, cfg)

    with YT.YoutubeDL(dl_opts) as ydl:
        ydl.download([url])

    if cfg.get('auto_convert_srt') and ext != 'srt':
        title   = job.get('title', 'subtitle')
        sub_base = os.path.join(save_path, f"{title}.{lang}")
        convert_subtitles_to_srt(sub_base, ext)


# ─────────────────────────────────────────────────────────────────
#  SRT conversion
# ─────────────────────────────────────────────────────────────────

def convert_subtitles_to_srt(file_base: str, current_ext: str) -> None:
    subtitle_file = f"{file_base}.{current_ext}"
    srt_file      = f"{file_base}.srt"

    if current_ext == 'srt':
        return
    if not os.path.isfile(subtitle_file):
        return

    try:
        sp.run(
            ['ffmpeg', '-y', '-i', subtitle_file, '-c:s', 'srt', srt_file],
            check=True, stdout=sp.PIPE, stderr=sp.PIPE, text=True
        )
        if os.path.isfile(subtitle_file):
            os.remove(subtitle_file)
        print(Fore.GREEN + f"  → Converted to {srt_file}")
    except sp.CalledProcessError as e:
        print(Fore.RED + f"FFmpeg error during SRT conversion: {e.stderr[-200:]}")
        if os.path.isfile(srt_file):
            os.remove(srt_file)
    except Exception:
        if os.path.isfile(srt_file):
            os.remove(srt_file)


# ─────────────────────────────────────────────────────────────────
#  Sequential single-download wrappers (used in solo mode)
# ─────────────────────────────────────────────────────────────────

def download_video_audio(url, save_path, cfg, cookie_file=None,
                         use_aria2c=False, auto_quality=None):
    try:
        hook, get_dur = create_progress_hook(None)
        print(Fore.LIGHTBLACK_EX + "\nFetching video info...")
        info = fetch_info(url, cookie_file)
        _print_video_info(info)

        sorted_q = build_quality_list(info)
        if not sorted_q:
            raise ValueError("No downloadable video formats found.")

        if auto_quality is not None:
            selected = min(sorted_q, key=lambda x: abs(x['height'] - auto_quality))
            print(Fore.LIGHTBLACK_EX + f"Auto-selected: {selected['height']}p")
        else:
            clear_screen()
            print(Fore.CYAN + "Available Qualities:\n")
            for i, q in enumerate(sorted_q, 1):
                sz    = f"  ~{_fmt_bytes(q['filesize'])}" if q['filesize'] else ''
                codec = f"  [{q['vcodec']}]" if q['vcodec'] else ''
                print(get_next_colour() + f"  {i}. {q['height']}p{codec}{sz}")
            idx      = _num_input("\nChoose quality (number): ", len(sorted_q))
            selected = sorted_q[idx]

        start_t, end_t = _ask_clip_range()
        section = _sections_filter(start_t, end_t)

        naming    = cfg.get('output_naming', '%(title)s')
        merge_fmt = cfg.get('merge_format', 'mp4')
        dl_opts: dict = {
            'format':              _best_format_string(selected['height']),
            'outtmpl':             os.path.join(save_path, f"{naming}_%(id)s.%(ext)s"),
            'restrictfilenames':   True,
            'merge_output_format': merge_fmt,
            'cookiefile':          cookie_file,
            'progress_hooks':      [hook],
            'postprocessors':      _build_postprocessors(cfg),
            'writethumbnail':      bool(cfg.get('write_thumbnail')),
        }
        if section:
            dl_opts['download_ranges']         = section
            dl_opts['force_keyframes_at_cuts'] = True
        if use_aria2c:
            dl_opts['external_downloader'] = 'aria2c'
        _apply_config(dl_opts, cfg)

        clear_screen()
        print(Fore.CYAN + f" Downloading {selected['height']}p Video... ".center(54, "="))
        t0 = perf_counter()
        with YT.YoutubeDL(dl_opts) as ydl:
            ydl.download([url])
        duration = get_dur() or (perf_counter() - t0)

        logged = log_download(url, save_path, 'Video', duration, cfg.get('auto_log', False))
        clear_screen()
        print(Fore.GREEN + "✓ Video downloaded!")
        print(Fore.LIGHTMAGENTA_EX + "Saved to: " + Fore.LIGHTYELLOW_EX + save_path)
        if logged:
            print(Fore.LIGHTBLUE_EX + "Logged in download_history.txt")
        if cfg.get('notify_on_complete'):
            notify("Stream Scoop", f"Done: {info.get('title','')[:40]}")
        input(Fore.LIGHTBLACK_EX + "\nPress ENTER to continue...")
    except Exception as e:
        handle_error(e)


def download_audio_only(url, save_path, cfg, cookie_file=None, use_aria2c=False):
    try:
        hook, get_dur = create_progress_hook(None)
        print(Fore.LIGHTBLACK_EX + "\nFetching video info...")
        info = fetch_info(url, cookie_file)
        _print_video_info(info)

        audio_fmts = build_audio_list(info)
        if not audio_fmts:
            raise ValueError("No audio formats found.")

        clear_screen()
        print(Fore.CYAN + "Available Audio Qualities:\n")
        for i, fmt in enumerate(audio_fmts, 1):
            sz    = f"  ~{_fmt_bytes(fmt['filesize'])}" if fmt['filesize'] else ''
            codec = f"  [{fmt['acodec']}]" if fmt['acodec'] else ''
            print(get_next_colour() + f"  {i}. {fmt['bitrate']:.0f} kbps ({fmt['ext']}){codec}{sz}")

        # Also offer MP3 conversion
        print(get_next_colour() + f"  {len(audio_fmts)+1}. Best quality → convert to MP3")
        print(get_next_colour() + f"  {len(audio_fmts)+2}. Best quality → convert to M4A")

        raw_choice = input(Fore.WHITE + "\nChoose quality (number): ").strip()
        convert_to = None

        try:
            idx = int(raw_choice) - 1
            if idx == len(audio_fmts):
                sel = audio_fmts[0]
                convert_to = 'mp3'
            elif idx == len(audio_fmts) + 1:
                sel = audio_fmts[0]
                convert_to = 'm4a'
            elif 0 <= idx < len(audio_fmts):
                sel = audio_fmts[idx]
            else:
                print(Fore.RED + "Invalid choice, using best quality.")
                sel = audio_fmts[0]
        except (ValueError, IndexError):
            print(Fore.RED + "Invalid choice, using best quality.")
            sel = audio_fmts[0]

        start_t, end_t = _ask_clip_range()
        section = _sections_filter(start_t, end_t)

        naming = cfg.get('output_naming', '%(title)s')

        pps = _build_postprocessors(cfg)
        if convert_to == 'mp3':
            pps.insert(0, {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            })
            out_ext = 'mp3'
        elif convert_to == 'm4a':
            pps.insert(0, {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'm4a',
            })
            out_ext = 'm4a'
        else:
            out_ext = sel['ext']

        dl_opts: dict = {
            'format':            sel['format_id'],
            'outtmpl':           os.path.join(save_path, f"{naming}_%(id)s.%(ext)s"),
            'restrictfilenames': True,
            'cookiefile':        cookie_file,
            'progress_hooks':    [hook],
            'postprocessors':    pps,
        }

        if section:
            dl_opts['download_ranges']         = section
            dl_opts['force_keyframes_at_cuts'] = True
        if use_aria2c:
            dl_opts['external_downloader'] = 'aria2c'
        _apply_config(dl_opts, cfg)

        clear_screen()
        label = f"→ {convert_to.upper()}" if convert_to else f"({sel['bitrate']:.0f} kbps)"
        print(Fore.CYAN + f" Downloading Audio {label}... ".center(54, "="))
        t0 = perf_counter()
        with YT.YoutubeDL(dl_opts) as ydl:
            ydl.download([url])
        duration = get_dur() or (perf_counter() - t0)

        logged = log_download(url, save_path, 'Audio', duration, cfg.get('auto_log', False))
        print(Fore.GREEN + "\n✓ Audio downloaded!")
        print(Fore.LIGHTMAGENTA_EX + "Saved to: " + Fore.LIGHTYELLOW_EX + save_path)
        if logged:
            print(Fore.LIGHTBLUE_EX + "Logged in download_history.txt")
        if cfg.get('notify_on_complete'):
            notify("Stream Scoop", f"Audio done: {info.get('title','')[:40]}")
        input(Fore.LIGHTBLACK_EX + "\nPress ENTER to continue...")
    except Exception as e:
        handle_error(e)


def download_subtitles(url, save_path, cfg, cookie_file=None):
    try:
        hook, get_dur = create_progress_hook(None)
        print(Fore.LIGHTBLACK_EX + "\nFetching video info...")
        info = fetch_info(url, cookie_file)
        _print_video_info(info)
        title = info.get('title', 'video')
        naming = cfg.get('output_naming', '%(title)s')

        all_subs = []
        for lang, fmts in info.get('subtitles', {}).items():
            for fmt in fmts:
                all_subs.append({'lang': lang, 'ext': fmt.get('ext','vtt'), 'is_auto': False})
        for lang, fmts in info.get('automatic_captions', {}).items():
            for fmt in fmts:
                all_subs.append({'lang': lang, 'ext': fmt.get('ext','vtt'), 'is_auto': True})

        if not all_subs:
            raise ValueError("No subtitles available for this video.")

        while True:
            choice = input(Fore.LIGHTCYAN_EX + "\nEnglish only? (Y/n): ").strip().lower()
            if choice in ('', 'y', 'yes'):
                en = [s for s in all_subs if s['lang'].lower().startswith('en')]
                if en:
                    all_subs = en
                else:
                    print(Fore.RED + "No English subs — showing all.")
                break
            if choice in ('n', 'no'):
                break
            print(Fore.RED + "Enter Y or n.")

        PAGE = 20
        total_pages = max(1, (len(all_subs) + PAGE - 1) // PAGE)
        cur_page = 0
        selected = None
        while selected is None:
            clear_screen()
            start = cur_page * PAGE
            end   = min(start + PAGE, len(all_subs))
            print(Fore.CYAN + f" Subtitles — Page {cur_page+1}/{total_pages} ".center(54, "="))
            for i in range(start, end):
                s  = all_subs[i]
                tp = 'Auto' if s['is_auto'] else 'Manual'
                print(get_next_colour() + f"  {i+1:>3}. {s['lang'].upper():8} ({tp:6}) — {s['ext'].upper()}")
            print(Fore.CYAN + "=" * 54)
            raw = input(Fore.YELLOW + "  [A] Prev  [D] Next  [number] Select\n  > ").strip().lower()
            if raw == 'a':
                cur_page = (cur_page - 1) % total_pages
            elif raw == 'd':
                cur_page = (cur_page + 1) % total_pages
            else:
                try:
                    idx = int(raw) - 1
                    if 0 <= idx < len(all_subs):
                        selected = all_subs[idx]
                    else:
                        print(Fore.RED + f"  Enter 1–{len(all_subs)}.")
                except ValueError:
                    print(Fore.RED + "  Enter a number, A, or D.")

        dl_opts: dict = {
            'writesubtitles':    not selected['is_auto'],
            'writeautomaticsub': selected['is_auto'],
            'subtitleslangs':    [selected['lang']],
            'subtitlesformat':   selected['ext'],
            'skip_download':     True,
            'outtmpl':           os.path.join(save_path, f"{naming}_%(id)s"),
            'restrictfilenames': True,
            'cookiefile':        cookie_file,
            'progress_hooks':    [hook],
        }
        _apply_config(dl_opts, cfg)

        clear_screen()
        lang_up = selected['lang'].upper()
        ext_up  = selected['ext'].upper()
        print(Fore.CYAN + f" Downloading {lang_up} Subtitles ({ext_up})... ".center(54, "="))
        with YT.YoutubeDL(dl_opts) as ydl:
            ydl.download([url])

        duration = get_dur()
        logged = log_download(url, save_path, 'Subtitles', duration, cfg.get('auto_log', False))
        print(Fore.GREEN + "\n✓ Subtitles downloaded!")
        print(Fore.LIGHTMAGENTA_EX + "Saved to: " + Fore.LIGHTYELLOW_EX + save_path)
        if logged:
            print(Fore.LIGHTBLUE_EX + "Logged in download_history.txt")

        sub_base = os.path.join(save_path, f"{title}.{selected['lang']}")
        auto_srt = cfg.get('auto_convert_srt', False)
        if auto_srt:
            convert_subtitles_to_srt(sub_base, selected['ext'])
        elif selected['ext'] != 'srt':
            while True:
                ans = input(Fore.LIGHTRED_EX + f"\nConvert to .srt? ({Fore.WHITE}Y/n): ").strip().lower()
                if ans in ('', 'y', 'yes'):
                    convert_subtitles_to_srt(sub_base, selected['ext'])
                    break
                if ans in ('n', 'no'):
                    break
                print(Fore.RED + "Enter Y or n.")

        if cfg.get('notify_on_complete'):
            notify("Stream Scoop", f"Subtitles done: {lang_up}")
        input(Fore.LIGHTBLACK_EX + "\nPress ENTER to continue...")
    except Exception as e:
        handle_error(e)


def download_video_audio_subtitles(url, save_path, cfg, cookie_file=None, use_aria2c=False):
    try:
        print(Fore.LIGHTCYAN_EX + "\n Downloading Video... ".center(54, "="))
        download_video_audio(url, save_path, cfg, cookie_file, use_aria2c)
        print(Fore.LIGHTCYAN_EX + "\n Downloading Subtitles... ".center(54, "="))
        download_subtitles(url, save_path, cfg, cookie_file)
        print(Fore.GREEN + "\n✓ All downloads complete!")
        print(Fore.LIGHTMAGENTA_EX + "Saved to: " + Fore.LIGHTYELLOW_EX + save_path)
    except Exception as e:
        handle_error(e)


# ─────────────────────────────────────────────────────────────────
#  Playlist selection UI
# ─────────────────────────────────────────────────────────────────

def select_playlist_entries(entries: list) -> list:
    clear_screen()
    print(Fore.CYAN + f" Playlist — {len(entries)} videos ".center(54, "="))
    for i, e in enumerate(entries, 1):
        title = e.get('title') or e.get('url') or f"Video {i}"
        dur   = e.get('duration')
        dur_s = ''
        if dur:
            m, s = divmod(int(dur), 60)
            h, m = divmod(m, 60)
            dur_s = f" [{h}:{m:02}:{s:02}]" if h else f" [{m}:{s:02}]"
        print(get_next_colour() + f"  {i:>3}. {title[:55]}{dur_s}")
    print(Fore.CYAN + "=" * 54)
    print(Fore.LIGHTBLACK_EX + "  Enter numbers (e.g. 1,3,5-8), or 'all': ", end='')
    raw = input().strip().lower()

    if not raw or raw == 'all':
        return entries

    selected = []
    for part in raw.split(','):
        part = part.strip()
        if '-' in part:
            lo, _, hi = part.partition('-')
            try:
                for n in range(int(lo), int(hi) + 1):
                    if 1 <= n <= len(entries):
                        selected.append(entries[n - 1])
            except ValueError:
                pass
        else:
            try:
                n = int(part)
                if 1 <= n <= len(entries):
                    selected.append(entries[n - 1])
            except ValueError:
                pass

    if not selected:
        print(Fore.YELLOW + "No valid selection — downloading all.")
        return entries
    print(Fore.LIGHTGREEN_EX + f"Selected {len(selected)} video(s).")
    sleep(0.8)
    return selected
