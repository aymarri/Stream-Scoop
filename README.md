# 🎬 Stream Scoop v2.0

A feature-rich terminal video downloader built on **yt-dlp** — supporting YouTube, SoundCloud, Twitch, and [1000+ other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

---

## 🚀 Quick Start

### Windows
Double-click **`run.bat`** — it auto-creates a virtualenv and installs everything.

### macOS / Linux
```bash
chmod +x run.sh
./run.sh
```

### Manual (any platform)
```bash
pip install yt-dlp colorama
python main.py
```

---

## ✅ Requirements

| Tool | Required | Notes |
|------|----------|-------|
| Python 3.9+ | ✅ Yes  |
| FFmpeg | ✅ Yes | For merging video+audio |
| aria2c | Optional | Faster multi-part downloads |
| ffprobe | Optional | From the ffmpeg suite |

**Install FFmpeg:**
- Windows: `winget install ffmpeg` or `choco install ffmpeg`
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`

---

## 🐛 Bug Fixed: `concurrent.py` → `concurrent_dl.py`

The original `concurrent.py` **shadowed Python's standard library** `concurrent` module,
causing this crash on startup:

```
ImportError: cannot import name 'ThreadPoolExecutor' from 'concurrent'
```

**Fix:** renamed to `concurrent_dl.py` and updated the import in `main.py`.

---

## ✨ Features

### Core Downloads
| # | Feature |
|---|---------|
| 1 | **Download Video** — pick quality, optional clip range |
| 2 | **Download Audio Only** — raw format or convert to MP3/M4A |
| 3 | **Download Subtitles** — manual or auto-generated, paginated list |
| 4 | **Download Video + Subtitles** |
| 5 | **★ Concurrent Download** — configure many jobs then download all at once with a live dashboard |

### New Features (v2.0)
| # | Feature |
|---|---------|
| 6 | **Search & Download** — search YouTube/SoundCloud/YT Music directly |
| 7 | **Format Inspector** — see every stream (codec, resolution, bitrate, filesize) before downloading |
| 8 | **Thumbnail Downloader** — save thumbnails in any image format |
| 9 | **Batch Manager** — import a `.txt` or `.json` file of URLs, save/resume queues |
| 10 | **Local File Converter** — convert, trim, extract audio, merge, change speed, denoise using FFmpeg |
| 11 | **Archive Manager** — skip already-downloaded videos, browse and manage your archive |
| 12 | **Download Statistics** — bar charts, timeline, domain stats, export to CSV |
| 13 | **Download History** — paginated, colour-coded, clearable |
| 14 | **Settings** — 27 configurable options |

---

## ⚙️ Settings

Key settings you can tune (menu option 14):

| Setting | Default | Description |
|---------|---------|-------------|
| `default_path` | `~/Downloads/StreamScoop` | Where files are saved |
| `preferred_quality` | `None` | Auto-pick quality (e.g. `1080`) |
| `merge_format` | `mp4` | Output container |
| `rate_limit` | `None` | Throttle speed (e.g. `2M`) |
| `concurrent_fragments` | `4` | Threads per video |
| `max_concurrent_downloads` | `3` | Videos at once (concurrent mode) |
| `proxy` | `None` | SOCKS5/HTTP proxy URL |
| `sponsorblock_remove` | `False` | Cut sponsor segments |
| `embed_thumbnail` | `False` | Embed cover art |
| `embed_chapters` | `True` | Write chapter markers |
| `archive_mode` | `False` | Skip already-downloaded |
| `sleep_interval` | `0` | Seconds between downloads |
| `auto_convert_srt` | `False` | Auto-convert subtitles to SRT |

---

## 📁 Batch File Format

Create a `urls.txt` with one URL per line:
```
# Comments are ignored
https://www.youtube.com/watch?v=...
https://soundcloud.com/...
```

Or a richer `urls.json`:
```json
[
  {"url": "https://youtube.com/watch?v=XXX", "mode": "video", "quality": 1080},
  {"url": "https://youtube.com/watch?v=YYY", "mode": "audio"},
  {"url": "https://youtube.com/playlist?list=ZZZ", "mode": "video"}
]
```

---

## 📂 File Structure

```
StreamScoop/
├── main.py              ← Entry point (launch this)
├── run.bat              ← Windows one-click launcher
├── run.sh               ← macOS/Linux one-click launcher
├── requirements.txt
├── setup.py             ← Optional: pip install -e .
│
├── config.py            ← Settings management
├── colours.py           ← Terminal colour cycling
├── utilities.py         ← Shared helpers, progress store
│
├── download_logic.py    ← Core download functions
├── concurrent_dl.py     ← Concurrent download dashboard (RENAMED from concurrent.py)
│
├── format_inspector.py  ← Format table viewer
├── thumbnail_dl.py      ← Thumbnail downloader
├── batch_manager.py     ← Batch import / queue manager
├── file_converter.py    ← Local FFmpeg converter
├── archive_manager.py   ← yt-dlp archive management
├── stats_manager.py     ← Download statistics & charts
└── search_dl.py         ← Search & download
```

---

## 🔧 Install as a command (optional)

```bash
pip install -e .
streamscoop    # launch from anywhere
```

---

## 📝 License

MIT — use freely, modify freely.
