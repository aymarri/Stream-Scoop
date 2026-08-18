"""
config.py — Stream Scoop configuration manager.

New settings added:
  - proxy               HTTP/SOCKS proxy URL
  - sponsorblock        Skip sponsored segments (requires SponsorBlock)
  - embed_chapters      Write chapter markers into output file
  - embed_subs          Burn-in or mux subtitles into video
  - output_naming       Template for output filenames
  - keep_fragments      Keep fragment files after merging (debug)
  - geo_bypass          Enable yt-dlp geo-bypass workarounds
  - sleep_interval      Seconds to wait between downloads (avoid rate limits)
  - trim_silence        Trim leading/trailing silence from audio
  - write_thumbnail     Save thumbnail as separate image file
  - preferred_lang      Preferred audio language code (e.g. 'en')##
"""

import json
import os
from colorama import Fore
import colorama

colorama.init(autoreset=True)

CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.stream_scoop_config.json')

DEFAULT_CONFIG = {
    # Paths & naming
    'default_path':             os.path.join(os.path.expanduser('~'), 'Downloads', 'StreamScoop'),
    'output_naming':            '%(title)s',      # yt-dlp outtmpl base (timestamp appended)

    # Quality & format
    'preferred_quality':        None,             # e.g. 1080
    'merge_format':             'mp4',            # mp4 | mkv | webm
    'preferred_lang':           'en',             # preferred audio language

    # Download behaviour
    'rate_limit':               None,             # e.g. '2M', '500K'
    'retries':                  3,
    'concurrent_fragments':     4,                # fragment threads per video
    'max_concurrent_downloads': 3,                # videos downloading at once
    'sleep_interval':           0,                # seconds between downloads
    'geo_bypass':               False,
    'proxy':                    None,             # e.g. 'socks5://127.0.0.1:1080'

    # Metadata & post-processing
    'embed_thumbnail':          False,
    'embed_metadata':           True,
    'embed_chapters':           True,
    'embed_subs':               False,
    'write_thumbnail':          False,
    'auto_convert_srt':         False,
    'trim_silence':             False,
    'keep_fragments':           False,

    # SponsorBlock
    'sponsorblock_remove':      False,            # remove sponsor segments
    'sponsorblock_mark':        False,            # mark but keep segments
    'sponsorblock_categories':  ['sponsor', 'intro', 'outro', 'selfpromo', 'interaction'],

    # App behaviour
    'auto_log':                 False,
    'auto_check_updates':       True,
    'notify_on_complete':       True,
    'archive_mode':             False,            # skip already-downloaded videos
    'archive_file':             os.path.join(os.path.expanduser('~'), '.stream_scoop_archive.txt'),
}


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_PATH, 'r') as f:
            data = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged
    except (json.JSONDecodeError, IOError):
        print(Fore.YELLOW + "Warning: config file corrupted — using defaults.")
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
    except IOError as e:
        print(Fore.RED + f"Could not save config: {e}")


# ─────────────────────────────────────────────────────────────────
#  Settings menu
# ─────────────────────────────────────────────────────────────────

# (key, display label, type)
_SETTINGS_OPTIONS = [
    # Paths
    ('default_path',             'Default download path',                        str),
    ('output_naming',            'Output filename template (yt-dlp outtmpl)',    str),
    # Quality
    ('preferred_quality',        'Preferred quality height (e.g. 1080, None)',   str),
    ('merge_format',             'Merge format  (mp4 / mkv / webm)',             str),
    ('preferred_lang',           'Preferred audio language code (e.g. en)',      str),
    # Network
    ('rate_limit',               'Rate limit  (e.g. 2M, 500K, None)',            str),
    ('retries',                  'Retry attempts on failure',                    int),
    ('concurrent_fragments',     'Fragment threads per video  (1–16)',           int),
    ('max_concurrent_downloads', 'Max videos downloading simultaneously',       int),
    ('sleep_interval',           'Seconds to sleep between sequential downloads',int),
    ('geo_bypass',               'Enable geo-bypass workarounds (True/False)',   bool),
    ('proxy',                    'Proxy URL  (e.g. socks5://127.0.0.1:1080)',    str),
    # Metadata
    ('embed_thumbnail',          'Embed thumbnail in file (True/False)',         bool),
    ('embed_metadata',           'Embed metadata in file (True/False)',          bool),
    ('embed_chapters',           'Write chapter markers into file (True/False)', bool),
    ('embed_subs',               'Mux subtitles into video (True/False)',        bool),
    ('write_thumbnail',          'Save thumbnail as separate image (True/False)',bool),
    ('auto_convert_srt',         'Auto-convert subtitles to .srt (True/False)',  bool),
    ('trim_silence',             'Trim leading/trailing silence from audio',     bool),
    ('keep_fragments',           'Keep fragment files after merging (debug)',     bool),
    # SponsorBlock
    ('sponsorblock_remove',      'Remove SponsorBlock segments (True/False)',    bool),
    ('sponsorblock_mark',        'Mark (but keep) SponsorBlock segments',        bool),
    # App
    ('auto_log',                 'Always log downloads without asking',          bool),
    ('auto_check_updates',       'Check yt-dlp updates on startup',             bool),
    ('notify_on_complete',       'Desktop notification on completion',           bool),
    ('archive_mode',             'Archive mode — skip already-downloaded videos',bool),
    ('archive_file',             'Path to archive tracking file',               str),
]


def show_settings(cfg: dict) -> dict:
    while True:
        print(Fore.CYAN + "\n" + " Settings ".center(70, "="))
        for i, (key, label, _) in enumerate(_SETTINGS_OPTIONS, 1):
            val = cfg.get(key)
            # Truncate very long values
            val_str = str(val)
            if len(val_str) > 45:
                val_str = val_str[:42] + '...'
            print(Fore.YELLOW + f"  {i:>2}. " + Fore.WHITE + label)
            print(Fore.LIGHTBLACK_EX + f"       Current: {val_str}")

        print(Fore.CYAN + "=" * 70)
        print(Fore.LIGHTBLACK_EX + "  Option number to change, or ENTER to go back: ", end='')
        choice = input().strip()

        if not choice:
            return cfg

        try:
            idx = int(choice) - 1
            if not (0 <= idx < len(_SETTINGS_OPTIONS)):
                raise ValueError
        except ValueError:
            print(Fore.RED + "Invalid choice.")
            continue

        key, label, typ = _SETTINGS_OPTIONS[idx]
        current = cfg.get(key)
        print(Fore.LIGHTCYAN_EX + f"\nCurrent '{label}': {current}")

        # Special handling for sponsorblock_categories (list)
        if key == 'sponsorblock_categories':
            print(Fore.WHITE + "Available: sponsor, intro, outro, selfpromo, interaction, preview, filler")
            print(Fore.WHITE + "Enter comma-separated list (blank = keep): ", end='')
            raw = input().strip()
            if raw:
                cats = [c.strip() for c in raw.split(',') if c.strip()]
                cfg[key] = cats
                save_config(cfg)
                print(Fore.GREEN + f"✓ Saved: {key} = {cats}")
            continue

        print(Fore.WHITE + "New value (blank = keep): ", end='')
        raw = input().strip()

        if not raw:
            continue

        try:
            if raw.lower() == 'none':
                cfg[key] = None
            elif typ == bool:
                cfg[key] = raw.lower() in ('true', 'yes', '1', 'y')
            elif typ == int:
                cfg[key] = int(raw)
            else:
                cfg[key] = raw
            save_config(cfg)
            print(Fore.GREEN + f"✓ Saved: {key} = {cfg[key]}")
        except ValueError:
            print(Fore.RED + f"Invalid value for type {typ.__name__}")


def get_ydl_extra_opts(cfg: dict) -> dict:
    """
    Build extra yt-dlp options from config settings that apply globally.
    Caller merges these into their own opts dict.
    """
    extra = {}

    if cfg.get('proxy'):
        extra['proxy'] = cfg['proxy']

    if cfg.get('geo_bypass'):
        extra['geo_bypass'] = True

    if cfg.get('sleep_interval'):
        extra['sleep_interval'] = cfg['sleep_interval']

    if cfg.get('archive_mode') and cfg.get('archive_file'):
        extra['download_archive'] = cfg['archive_file']

    return extra
