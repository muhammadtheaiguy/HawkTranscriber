# Development Guide

Technical documentation for contributors and maintainers of HawkTranscriber.

## Project structure

```
WhisperTranscriber/
├─ app.py                  Entry point (starts the local server)
├─ run.bat / setup.bat     Windows launch & setup scripts
├─ requirements.txt        Python dependencies
├─ README.md               User-facing documentation
├─ docs/
│  ├─ DEVELOPMENT.md       This file
│  └─ TROUBLESHOOTING.md    Diagnostic guide
├─ whisperdesk/
│  ├─ __init__.py           Package metadata (app name, version)
│  ├─ config.py             Settings persistence & validation
│  ├─ hardware.py           Device / dependency detection
│  ├─ mediatools.py         FFmpeg & FFprobe wrappers, validation
│  ├─ models.py             Whisper model catalog & recommendations
│  ├─ worker.py             Background transcription process
│  ├─ social.py             Public URL validation and yt-dlp media retrieval
│  ├─ jobs.py               Job queue, progress & cancellation
│  ├─ store.py              SQLite history store
│  ├─ exporters.py          TXT/SRT/VTT/JSON/CSV/DOCX builders
│  ├─ server.py             HTTP API (Starlette)
│  └─ static/               Interface (HTML/CSS/JS)
└─ tests/                  Unit tests
```

## Architecture

HawkTranscriber is built on a simple three-layer model:

1. **Frontend** (`whisperdesk/static/`) — A vanilla-JS, no-build-step HTML/CSS/JS single
   page app. It communicates with the backend via a small JSON API over HTTP (Starlette).

2. **HTTP API** (`whisperdesk/server.py`) — A Starlette application serving both the static
   UI and a REST-like JSON API for job management, settings, exports, and social-media
   URL imports.

3. **Worker process** (`whisperdesk/worker.py`) — A separate `multiprocessing.Process`
   that runs Whisper transcription jobs. Communication with the main process happens via
   command and event queues managed by `whisperdesk/jobs.py` (the `JobManager`).

### Key design decisions

- **Privacy by default.** The server binds to `127.0.0.1` unless `WHISPERDESK_HOST=0.0.0.0`
  is set. No data is sent to any remote service.
- **SQLite history store** (`whisperdesk/store.py`) persists all jobs, transcripts,
  segments, and metadata. On startup the app recovers any interrupted jobs.
- **Local media caching.** Imported media files are copied to `data/media/` with a stable
  filename so they can be used for playback and re-transcription without re-downloading.
- **Model management.** Whisper models are downloaded from OpenAI's public host on first
  use and cached in the standard Whisper cache directory.

## Running the test suite

The test suite uses only the Python standard library — no pytest required:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `WHISPERDESK_PORT` | Preferred port | `8501` (falls through to next free) |
| `WHISPERDESK_HOST` | Bind address | `127.0.0.1` |
| `WHISPERDESK_DATA` | Data directory override | `data\` next to project |
| `WHISPERDESK_NO_BROWSER` | Set to `1` to skip browser auto-open | not set |

## Entry point

The application is launched via:

```powershell
.venv\Scripts\python.exe app.py
```

or by double-clicking `run.bat` on Windows.

## Dependency management

Dependencies are pinned in `requirements.txt` and installed into a `.venv` virtual
environment by `setup.bat` (Windows) or manually:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Code style notes

- Python 3.11+ is the target. Type hints are used throughout.
- The frontend is vanilla JavaScript (no framework, no build step).
- CSS uses a lightweight custom system with CSS variables for theming.
