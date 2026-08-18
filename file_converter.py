"""
file_converter.py — Convert local video/audio files using FFmpeg.

Features:
  - Convert video between MP4, MKV, WEBM, AVI, MOV
  - Convert audio between MP3, AAC, FLAC, OGG, WAV, OPUS, M4A
  - Extract audio from video
  - Re-encode with custom bitrate / CRF
  - Batch convert entire folders
  - Trim/clip local files by time range
  - Strip audio from video (mute)
  - Merge separate video + audio files
  - Change playback speed
  - Simple noise reduction (via ffmpeg's afftdn filter)##
  - Progress display
"""

import os
import subprocess as sp
import threading
from time import sleep, perf_counter

import colorama
from colorama import Fore

from utilities import (
    clear_screen, handle_error, ensure_writable_dir, resolve_path,
    _fmt_duration, notify,
)
from colours import get_next_colour

colorama.init(autoreset=True)


# ─────────────────────────────────────────────────────────────────
#  FFmpeg helpers
# ─────────────────────────────────────────────────────────────────

VIDEO_FORMATS = ['mp4', 'mkv', 'webm', 'avi', 'mov', 'flv', 'ts']
AUDIO_FORMATS = ['mp3', 'aac', 'm4a', 'flac', 'ogg', 'opus', 'wav']

VIDEO_CODECS = {
    'mp4':  'libx264',
    'mkv':  'libx264',
    'webm': 'libvpx-vp9',
    'avi':  'mpeg4',
    'mov':  'libx264',
    'flv':  'flv',
    'ts':   'mpeg2video',
}

AUDIO_CODECS = {
    'mp3':  'libmp3lame',
    'aac':  'aac',
    'm4a':  'aac',
    'flac': 'flac',
    'ogg':  'libvorbis',
    'opus': 'libopus',
    'wav':  'pcm_s16le',
}


def _run_ffmpeg(args: list, title: str = "Converting") -> bool:
    """Run ffmpeg, showing a spinner. Returns True on success."""
    stop  = threading.Event()
    spinner = ['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏']

    def spin():
        i = 0
        while not stop.is_set():
            print(Fore.YELLOW + f"\r  {spinner[i % len(spinner)]} {title}…", end='', flush=True)
            i += 1
            sleep(0.1)

    t = threading.Thread(target=spin, daemon=True)
    t.start()

    try:
        result = sp.run(args, stdout=sp.PIPE, stderr=sp.PIPE, text=True)
        stop.set()
        t.join()
        if result.returncode == 0:
            print(Fore.GREEN + f"\r  ✓ {title} complete!           ")
            return True
        else:
            print(Fore.RED + f"\r  ✗ FFmpeg error:              ")
            # Show last few lines of stderr
            err_lines = result.stderr.strip().split('\n')
            for line in err_lines[-5:]:
                print(Fore.RED + f"    {line}")
            return False
    except FileNotFoundError:
        stop.set()
        t.join()
        print(Fore.RED + "\r  ✗ FFmpeg not found. Install ffmpeg and add it to PATH.")
        return False
    except Exception as e:
        stop.set()
        t.join()
        print(Fore.RED + f"\r  ✗ Error: {e}")
        return False


def _probe_file(path: str) -> dict:
    """Get file info using ffprobe."""
    try:
        import json
        result = sp.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_streams', '-show_format', path],
            stdout=sp.PIPE, stderr=sp.PIPE, text=True
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return {}


def _has_video(path: str) -> bool:
    info = _probe_file(path)
    return any(s.get('codec_type') == 'video' for s in info.get('streams', []))


def _has_audio(path: str) -> bool:
    info = _probe_file(path)
    return any(s.get('codec_type') == 'audio' for s in info.get('streams', []))


def _get_duration(path: str) -> float:
    info = _probe_file(path)
    try:
        return float(info.get('format', {}).get('duration', 0))
    except (ValueError, TypeError):
        return 0.0


def _out_path(src: str, ext: str, suffix: str = '') -> str:
    """Build output path next to input file."""
    base = os.path.splitext(src)[0]
    return f"{base}{suffix}.{ext}"


def _confirm_overwrite(path: str) -> bool:
    if os.path.exists(path):
        ans = input(Fore.YELLOW + f"  '{os.path.basename(path)}' exists. Overwrite? (Y/n): ").strip().lower()
        return ans in ('', 'y', 'yes')
    return True


# ─────────────────────────────────────────────────────────────────
#  Conversion operations
# ─────────────────────────────────────────────────────────────────

def convert_format(src: str, target_ext: str,
                   crf: int = 23, audio_bitrate: str = '192k',
                   video_bitrate: str = '') -> bool:
    """Transcode a file to a different container/codec."""
    ext     = target_ext.lower().strip('.')
    out     = _out_path(src, ext, f'_converted')
    if not _confirm_overwrite(out):
        return False

    args = ['ffmpeg', '-y', '-i', src]

    if ext in AUDIO_FORMATS:
        acodec = AUDIO_CODECS.get(ext, 'copy')
        args += ['-vn', '-c:a', acodec]
        if ext in ('mp3', 'aac', 'm4a', 'ogg', 'opus') and audio_bitrate:
            args += ['-b:a', audio_bitrate]
    else:
        vcodec = VIDEO_CODECS.get(ext, 'libx264')
        args += ['-c:v', vcodec]
        if video_bitrate:
            args += ['-b:v', video_bitrate]
        elif ext in ('mp4', 'mkv', 'mov') and vcodec == 'libx264':
            args += ['-crf', str(crf), '-preset', 'medium']
        args += ['-c:a', 'aac', '-b:a', audio_bitrate]

    args.append(out)
    ok = _run_ffmpeg(args, f"Converting to {ext.upper()}")
    if ok:
        print(Fore.LIGHTMAGENTA_EX + f"  Output: {out}")
    return ok


def extract_audio(src: str, out_fmt: str = 'mp3', bitrate: str = '320k') -> bool:
    """Strip audio from a video file."""
    ext     = out_fmt.lower().strip('.')
    out     = _out_path(src, ext, '_audio')
    if not _confirm_overwrite(out):
        return False

    acodec = AUDIO_CODECS.get(ext, 'libmp3lame')
    args = ['ffmpeg', '-y', '-i', src, '-vn', '-c:a', acodec]
    if ext in ('mp3', 'aac', 'm4a'):
        args += ['-b:a', bitrate]
    args.append(out)

    ok = _run_ffmpeg(args, f"Extracting audio → {ext.upper()}")
    if ok:
        print(Fore.LIGHTMAGENTA_EX + f"  Output: {out}")
    return ok


def trim_file(src: str, start: str, end: str) -> bool:
    """Trim a file to the specified time range."""
    base = os.path.splitext(src)
    out  = f"{base[0]}_trimmed{base[1]}"
    if not _confirm_overwrite(out):
        return False

    args = ['ffmpeg', '-y', '-i', src]
    if start:
        args += ['-ss', start]
    if end:
        args += ['-to', end]
    args += ['-c', 'copy', out]

    ok = _run_ffmpeg(args, "Trimming")
    if ok:
        print(Fore.LIGHTMAGENTA_EX + f"  Output: {out}")
    return ok


def mute_video(src: str) -> bool:
    """Remove audio track from a video."""
    base = os.path.splitext(src)
    out  = f"{base[0]}_muted{base[1]}"
    if not _confirm_overwrite(out):
        return False

    args = ['ffmpeg', '-y', '-i', src, '-an', '-c:v', 'copy', out]
    ok = _run_ffmpeg(args, "Removing audio")
    if ok:
        print(Fore.LIGHTMAGENTA_EX + f"  Output: {out}")
    return ok


def merge_video_audio(video_src: str, audio_src: str) -> bool:
    """Merge separate video and audio files."""
    base = os.path.splitext(video_src)
    out  = f"{base[0]}_merged{base[1]}"
    if not _confirm_overwrite(out):
        return False

    args = [
        'ffmpeg', '-y',
        '-i', video_src,
        '-i', audio_src,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-shortest',
        out,
    ]
    ok = _run_ffmpeg(args, "Merging video + audio")
    if ok:
        print(Fore.LIGHTMAGENTA_EX + f"  Output: {out}")
    return ok


def change_speed(src: str, speed: float) -> bool:
    """Change playback speed (0.25 – 4.0)."""
    if not (0.25 <= speed <= 4.0):
        print(Fore.RED + "  Speed must be between 0.25 and 4.0")
        return False

    base = os.path.splitext(src)
    out  = f"{base[0]}_speed{speed:.2f}x{base[1]}"
    if not _confirm_overwrite(out):
        return False

    # Video filter: setpts
    # Audio filter: atempo (limited to 0.5–2.0, chain for extremes)
    vf = f"setpts={1/speed:.4f}*PTS"
    atempo = speed
    af_parts = []
    while atempo > 2.0:
        af_parts.append("atempo=2.0")
        atempo /= 2.0
    while atempo < 0.5:
        af_parts.append("atempo=0.5")
        atempo *= 2.0
    af_parts.append(f"atempo={atempo:.4f}")
    af = ','.join(af_parts)

    args = [
        'ffmpeg', '-y', '-i', src,
        '-filter:v', vf,
        '-filter:a', af,
        out,
    ]
    ok = _run_ffmpeg(args, f"Changing speed to {speed}x")
    if ok:
        print(Fore.LIGHTMAGENTA_EX + f"  Output: {out}")
    return ok


def reduce_noise(src: str) -> bool:
    """Apply basic noise reduction to audio."""
    base = os.path.splitext(src)
    out  = f"{base[0]}_denoised{base[1]}"
    if not _confirm_overwrite(out):
        return False

    # afftdn = adaptive FFT-based noise reduction
    if _has_video(src):
        args = ['ffmpeg', '-y', '-i', src,
                '-c:v', 'copy',
                '-af', 'afftdn=nf=-25',
                out]
    else:
        args = ['ffmpeg', '-y', '-i', src,
                '-af', 'afftdn=nf=-25',
                out]

    ok = _run_ffmpeg(args, "Noise reduction")
    if ok:
        print(Fore.LIGHTMAGENTA_EX + f"  Output: {out}")
    return ok


# ─────────────────────────────────────────────────────────────────
#  Batch conversion
# ─────────────────────────────────────────────────────────────────

def batch_convert_folder(folder: str, src_ext: str, target_ext: str,
                         crf: int = 23, audio_bitrate: str = '192k') -> None:
    """Convert all files of src_ext in a folder to target_ext."""
    src_ext    = src_ext.lower().strip('.')
    target_ext = target_ext.lower().strip('.')

    files = [
        f for f in os.listdir(folder)
        if f.lower().endswith(f'.{src_ext}')
    ]

    if not files:
        print(Fore.YELLOW + f"  No .{src_ext} files found in '{folder}'")
        return

    print(Fore.LIGHTBLUE_EX + f"\n  Found {len(files)} .{src_ext} file(s) → converting to .{target_ext}\n")
    success = 0
    for i, fname in enumerate(files, 1):
        src = os.path.join(folder, fname)
        print(Fore.CYAN + f"  [{i}/{len(files)}] {fname}")
        if convert_format(src, target_ext, crf=crf, audio_bitrate=audio_bitrate):
            success += 1

    print(Fore.CYAN + "\n  " + "─" * 50)
    print(Fore.GREEN + f"  ✓ {success}/{len(files)} converted.")


# ─────────────────────────────────────────────────────────────────
#  Interactive UI
# ─────────────────────────────────────────────────────────────────

def _ask_file(prompt: str = "File path") -> str:
    while True:
        print(Fore.WHITE + f"  {prompt}: ", end='')
        raw = input().strip().strip('"\'')
        if not raw:
            return ''
        path = resolve_path(raw)
        if os.path.isfile(path):
            return path
        print(Fore.RED + f"  File not found: '{path}'")


def run_file_converter(cfg: dict) -> None:
    """Main entry point for the local file converter."""
    while True:
        clear_screen()
        print(Fore.CYAN + " Local File Converter ".center(60, "="))
        print(Fore.LIGHTBLACK_EX + "  Convert, trim, and transform already-downloaded files.\n")

        ops = [
            ("1",  "Convert to another format (video or audio)"),
            ("2",  "Extract audio from video"),
            ("3",  "Trim / clip a file by time range"),
            ("4",  "Remove audio from video (mute)"),
            ("5",  "Merge separate video + audio files"),
            ("6",  "Change playback speed"),
            ("7",  "Apply noise reduction to audio"),
            ("8",  "Batch convert entire folder"),
            ("b",  "Back to main menu"),
        ]
        for key, label in ops:
            print(get_next_colour() + f"  [{key}] {label}")

        print()
        choice = input(Fore.WHITE + "Choice: ").strip().lower()

        if choice == 'b' or not choice:
            return

        if choice == '1':
            src = _ask_file("Source file path")
            if not src:
                continue
            print(Fore.WHITE + "  Target format (e.g. mp4, mp3, mkv, flac): ", end='')
            fmt = input().strip().lower().strip('.')
            if not fmt:
                continue
            print(Fore.WHITE + "  CRF quality 0-51 (23 = default, lower = better): ", end='')
            try:
                crf = int(input().strip() or '23')
            except ValueError:
                crf = 23
            print(Fore.WHITE + "  Audio bitrate (e.g. 192k, blank = 192k): ", end='')
            abr = input().strip() or '192k'
            convert_format(src, fmt, crf=crf, audio_bitrate=abr)

        elif choice == '2':
            src = _ask_file("Video file path")
            if not src:
                continue
            print(Fore.WHITE + "  Output audio format [mp3/aac/flac/wav/opus] (mp3): ", end='')
            fmt = input().strip().lower() or 'mp3'
            print(Fore.WHITE + "  Bitrate (e.g. 320k): ", end='')
            abr = input().strip() or '320k'
            extract_audio(src, fmt, abr)

        elif choice == '3':
            src = _ask_file("File to trim")
            if not src:
                continue
            dur = _get_duration(src)
            if dur:
                m, s = divmod(int(dur), 60)
                h, m = divmod(m, 60)
                print(Fore.LIGHTBLACK_EX
                      + f"  Duration: {h}:{m:02}:{s:02}" if h else f"  Duration: {m}:{s:02}")
            print(Fore.LIGHTBLACK_EX + "  Format: HH:MM:SS or MM:SS or seconds")
            start = input(Fore.WHITE + "  Start time (blank = beginning): ").strip() or None
            end   = input(Fore.WHITE + "  End time   (blank = full end):  ").strip() or None
            if start is None and end is None:
                print(Fore.YELLOW + "  No range specified, skipping.")
            else:
                trim_file(src, start, end)

        elif choice == '4':
            src = _ask_file("Video file to mute")
            if not src:
                continue
            mute_video(src)

        elif choice == '5':
            video = _ask_file("Video file path")
            if not video:
                continue
            audio = _ask_file("Audio file path")
            if not audio:
                continue
            merge_video_audio(video, audio)

        elif choice == '6':
            src = _ask_file("File path")
            if not src:
                continue
            print(Fore.WHITE + "  Speed multiplier (0.25–4.0, e.g. 1.5 for 50% faster): ", end='')
            try:
                speed = float(input().strip())
            except ValueError:
                print(Fore.RED + "  Invalid speed.")
                continue
            change_speed(src, speed)

        elif choice == '7':
            src = _ask_file("File path")
            if not src:
                continue
            reduce_noise(src)

        elif choice == '8':
            print(Fore.WHITE + "  Folder path: ", end='')
            raw_folder = input().strip().strip('"\'')
            folder = resolve_path(raw_folder)
            if not os.path.isdir(folder):
                print(Fore.RED + f"  Not a directory: '{folder}'")
                sleep(1)
                continue
            print(Fore.WHITE + "  Source extension (e.g. webm): ", end='')
            src_ext = input().strip().lower().strip('.')
            print(Fore.WHITE + "  Target extension (e.g. mp4):  ", end='')
            tgt_ext = input().strip().lower().strip('.')
            if not src_ext or not tgt_ext:
                continue
            print(Fore.WHITE + "  CRF (23): ", end='')
            try:
                crf = int(input().strip() or '23')
            except ValueError:
                crf = 23
            batch_convert_folder(folder, src_ext, tgt_ext, crf=crf)

        else:
            print(Fore.RED + "  Invalid choice.")
            sleep(0.8)
            continue

        sleep(0.5)
        input(Fore.LIGHTBLACK_EX + "\n  Press ENTER to continue…")
