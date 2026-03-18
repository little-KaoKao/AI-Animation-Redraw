# AI手书复刻 (AI Animation Redraw)

Upload an animation clip and a character reference image. The system automatically redraws every frame with your character while preserving the original animation's poses, timing, and audio.

并发
视频/角色复用
宫格数可选（感觉还是1帧1帧转比较稳）
单个重roll

## Features

- Automatic video analysis (resolution, FPS, frame hold pattern/拍数)
- Intelligent frame deduplication (removes held/duplicate frames)
- 3-view character reference sheet generation
- Batch grid-based redrawing via RunningHub API
- Concurrent API processing for speed
- Automatic video reassembly with original timing and audio
- Web UI with real-time progress tracking

## Prerequisites

- Python 3.12+
- [RunningHub](https://www.runninghub.cn) API key

## Quick Start

1. Clone and install:

   ```bash
   git clone <repo-url>
   cd ai-animation-redraw
   uv venv
   uv pip install -e .
   ```
2. Download [ffmpeg](https://www.gyan.dev/ffmpeg/builds/) (full build) and place `ffmpeg.exe` into the `bin/` directory.
3. Configure `.env` (copy from `.env.example`):

   ```bash
   cp .env.example .env
   # Edit .env with your API key
   ```
4. (Optional) Edit `config.yaml` to customize prompt templates and processing parameters.
5. Run:

   ```bash
   uv run python run.py
   ```
6. Open http://localhost:8000 in your browser.

## Configuration

### .env (secrets & paths)

| Variable               | Description             | Default            |
| ---------------------- | ----------------------- | ------------------ |
| `RUNNINGHUB_API_KEY` | Your RunningHub API key | (required)         |
| `FFMPEG_PATH`        | Path to ffmpeg binary   | `bin/ffmpeg.exe` |
| `HOST`               | Server bind address     | `127.0.0.1`      |
| `PORT`               | Server port             | `8000`           |
| `DATA_DIR`           | Project data directory  | `./data`         |

### config.yaml (prompts & processing)

- `prompts.threeview_generation`: Controls 3-view character sheet generation
- `prompts.grid_redraw`: Controls animation grid redraw style
- `processing.max_concurrent_redraws`: Parallel API call limit (default: 4)
- `output.default_resolution`: RunningHub output quality (`1k`/`2k`/`4k`)

## Pipeline Flow

```
Upload video + character image
  -> [1] Analyze video (resolution, fps, frame hold pattern)
  -> [2] Extract unique frames + compose into 4-panel grids
  -> [3] Generate 3-view character reference sheet
  -> [4] Redraw all grids with new character (concurrent)
  -> [5] Split redrawn grids back into individual frames
  -> [6] Assemble final video with original timing + audio
  -> Done!
```

## Project Structure

```
├── .env.example          # Config template
├── config.yaml           # Prompts & processing params
├── pyproject.toml        # Dependencies
├── run.py                # Entry point
├── bin/                  # ffmpeg binary (gitignored, download manually)
├── app/                  # Backend (FastAPI)
│   ├── config.py         # Settings loader
│   ├── main.py           # App factory
│   ├── models.py         # Data schemas
│   ├── routers/          # API endpoints
│   ├── services/         # Business logic
│   └── utils/            # Helpers
├── static/               # Frontend (HTML/JS/CSS)
└── data/                 # Runtime data (gitignored)
```

## License

MIT
