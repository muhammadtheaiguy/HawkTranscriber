# HawkTranscriber

**A private, local-first transcription studio for Windows (and macOS/Linux).**

HawkTranscriber turns local audio/video files and supported public media links into
clean, editable transcripts using [OpenAI Whisper](https://github.com/openai/whisper)
on your own computer. No transcript is ever uploaded to a cloud service. When you paste a
social link, the app fetches that media to this device — nothing more.

![Local only](https://img.shields.io/badge/runs-100%25%20locally-6f42c1)

---

## What it does

- **Transcribe locally.** Whisper runs entirely on your machine. Your media and transcripts
  never leave the computer.
- **Import public media links.** Fetch supported public posts from YouTube, Instagram,
  Facebook, TikTok, X, Vimeo, SoundCloud and more, then transcribe them directly.
- **Edit transcripts.** A built-in editor with search, segment-by-segment editing, copy, and
  timestamp-synced playback. Word timestamps display inline when Whisper provides them.
- **Export anywhere.** Generate TXT, SRT, VTT, JSON, CSV, or DOCX files — all locally.
- **Resume & retry.** The original media is kept in a local library so you can re-transcribe
  with a different model at any time.
- **Background jobs.** Transcription runs in a separate process. The interface stays
  responsive, shows real progress, and supports cancellation.

---

## Who is this for

- **Podcasters & journalists** who need accurate transcripts of local recordings
- **Students** transcribing lectures or interviews
- **Content creators** turning audio/video into captions or articles
- **Anyone** who wants accurate transcription without sending data to the cloud

---

## Screenshots

> Screenshots will be added once captured from the running application.

---

## Requirements

| Requirement | Notes |
| --- | --- |
| Windows 10/11 (recommended) | Also runs on macOS and Linux with the same commands |
| Python 3.11+ | Built and tested on Python 3.14 |
| FFmpeg | **Required** to decode audio/video. Whisper does not bundle it. |
| ~2 GB free disk | For the app, plus Whisper models (Tiny ≈ 75 MB, Large ≈ 3.1 GB) |

### Installing FFmpeg (Windows)

The easiest way on Windows is via [winget](https://learn.microsoft.com/windows/package-manager/):

```powershell
winget install Gyan.FFmpeg
```

Then **close and reopen your terminal** so `ffmpeg` is on your `PATH`, and verify:

```powershell
ffmpeg -version
ffprobe -version
```

HawkTranscriber checks for FFmpeg on startup and shows a clear warning in
**Settings → Diagnostics** if it cannot find it.

---

## Installation

### Option A: One-click setup (Windows)

1. Install Python 3.11 or newer (check *"Add python.exe to PATH"* during setup).
2. Install FFmpeg (see above).
3. Double-click **`setup.bat`**. It creates a `.venv` virtual environment and installs the
   dependencies from `requirements.txt`. This downloads PyTorch, so expect a few hundred
   megabytes.

### Option B: Manual setup

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## Running

Double-click **`run.bat`**, or run:

```powershell
.venv\Scripts\python.exe app.py
```

The app starts a local server and opens your browser at
**http://localhost:8501** (or the next free port). Press **Ctrl+C** in the
terminal to stop it.

### Useful options

| Environment variable | Purpose |
| --- | --- |
| `WHISPERDESK_PORT` | Preferred port (default `8501`) |
| `WHISPERDESK_HOST` | Bind address. Default `127.0.0.1` (this PC only). |
| `WHISPERDESK_DATA` | Move the data folder somewhere else |
| `WHISPERDESK_NO_BROWSER` | Set to `1` to stop the browser from opening |

> **Network access:** setting `WHISPERDESK_HOST=0.0.0.0` exposes the app to your
> network. Only do this on a trusted network — anyone who can reach the port
> could view your transcripts. The app prints a warning when this is enabled.

---

## A quick walkthrough

1. **New transcription** — upload a local file (WAV, MP3, M4A, AAC, FLAC, OGG, WMA, MP4,
   MOV, MKV, WEBM and more), or switch to **Social media link** and choose the site. Public
   direct-post URLs are fetched to the local media folder; private or sign-in-required items
   are not supported.
2. **Configure** — pick a Whisper model, language, and task (transcribe or translate to
   English). Enable *word timestamps* when precise word timing is useful.
3. **Start** — watch real-time progress. You can cancel at any time; the job stays in the
   sidebar and can be retried (the original media is kept).
4. **Edit** — play the media, click a segment to seek, search, edit text, and copy.
5. **Export** — TXT, SRT, VTT, JSON, CSV, or DOCX.
6. **Library** — find every transcript again in the Library view.

---

## Models

HawkTranscriber offers Whisper's model family and detects which ones are already downloaded:

| Model | Size | Notes |
| --- | --- | --- |
| Tiny / Base | ~75–145 MB | Fastest, good for clear speech |
| Small | ~466 MB | Great balance on CPU (recommended default) |
| Medium | ~1.5 GB | More accurate, slower on CPU |
| Large v3 Turbo | ~1.6 GB | High accuracy, needs more memory |
| Large v3 | ~3.1 GB | Highest accuracy, heavy |

- The **first time** you use a model it is downloaded once, then cached offline.
  Downloads show progress in the job view and can be retried if interrupted.
- Models are chosen based on your hardware in the **New transcription** screen.
- On CPU-only machines, *Small* or *Base* usually give the best speed/accuracy trade-off.
  GPU (CUDA) hardware is detected and used automatically when available.

---

## Where your data lives

Everything is kept inside the `data\` folder next to the project:

| Path | Contents |
| --- | --- |
| `data\history.db` | Transcripts, segments, and job metadata (SQLite) |
| `data\media\` | A copy of each uploaded or link-imported file, kept for playback & retry |
| `data\settings.json` | Your preferences |
| `data\outputs\` | Reserved for direct-to-disk exports |
| `data\logs\whisperdesk.log` | Rotating application diagnostics (1 MB, three backups) |

Whisper model weights are stored in the standard cache folder
(`%USERPROFILE%\.cache\whisper`) so they can be shared with other Whisper tools.
The exact path is shown in **Settings → Diagnostics**.

Use **Settings → Storage & history → Clear history** to remove every record
(and the stored media) at once. Individual transcripts can be deleted from the
Library or the workspace.

---

## Testing

The test suite uses only the Python standard library:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

It covers timestamp formatting, all export formats, the history store,
settings persistence, media validation, and the worker's progress/cancel hooks.

---

## Troubleshooting

**"FFmpeg could not be found"** — install FFmpeg and reopen your terminal
(`winget install Gyan.FFmpeg`).

**A model is slow or the machine runs out of memory** — pick a smaller model on
the New transcription screen. Large models need a lot of RAM and are slow on CPU.

**A job shows "interrupted"** — the app was closed while it was running. Open
the job and use **Retry** (the original media is kept for this purpose).

**A transcript looks wrong** — try a larger model, set the spoken language
explicitly instead of "Detect automatically", or disable
"Use previous text as context" in Settings.

**A social media link fails to import** — only public, direct-post URLs are supported.
Private, age-restricted, sign-in-required, or region-blocked posts are not. Make sure
the correct platform is selected for the link.

See [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) for more detailed diagnostics.

---

## Privacy & data handling

- Local-file transcription and all Whisper processing happen on this device.
- Social-link imports connect to the selected platform and download its public media here;
  transcripts are never sent to a remote service.
- Whisper model weights are downloaded from their public model host when first needed.
- The web server binds to `127.0.0.1` by default. Setting `WHISPERDESK_HOST=0.0.0.0`
  exposes it to your local network — avoid this on untrusted networks.

---

## Development

Interested in contributing or running from source? See
[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) for architecture, project structure, and
developer workflows. Contribution guidelines are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

> **Important (needs a decision):** This project does **not** currently include a license
> file. By default, all rights are reserved to the author. Before publishing to GitHub,
> you should add a license file (e.g. `LICENSE`). Recommended options:
>
> - **MIT** — permissive, allows reuse with minimal restrictions
> - **Apache 2.0** — permissive, adds an explicit patent grant
> - **GPL v3** — copyleft, requires derivative works to stay open source
>
> HawkTranscriber is a front-end and workspace built around
> [OpenAI Whisper](https://github.com/openai/whisper) (MIT licensed). Whisper model
> weights are downloaded from OpenAI's public model host.

---

## Support

- [Open an issue](https://github.com/anthropics/claude-code/issues/new) if you find a bug.

