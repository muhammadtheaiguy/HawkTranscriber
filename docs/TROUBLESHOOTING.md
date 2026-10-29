# Troubleshooting guide

This document covers the most common problems users encounter when running
HawkTranscriber, with diagnostics for each symptom.

## FFmpeg not found

**Symptoms:** The app starts but shows a warning in **Settings → Diagnostics**.
Jobs fail immediately with a media-related error.

**Diagnosis:** HawkTranscriber requires FFmpeg to decode audio and video. Whisper
does not bundle it.

**Fix:**

- **Windows:** `winget install Gyan.FFmpeg`
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg` (Debian/Ubuntu) or your distro's package manager.

Then **close and reopen your terminal** so `ffmpeg` is on your `PATH`, and verify:

```bash
ffmpeg -version
ffprobe -version
```

If the app still cannot find FFmpeg after installation, check that the terminal you
used to launch the app has the new `PATH` (or restart the app from a fresh terminal).

## Model is slow or the machine runs out of memory

**Symptoms:** Transcription hangs, the process uses excessive memory, or the system
becomes unresponsive.

**Diagnosis:** Large Whisper models (Large v3, ~3.1 GB) require substantial RAM and
run slowly on CPU-only machines.

**Fix:** Pick a smaller model on the **New transcription** screen:

| Model | Size | Best for |
| --- | --- | --- |
| Tiny / Base | ~75–145 MB | Fastest, clear speech |
| Small | ~466 MB | CPU balance (recommended default) |
| Medium | ~1.5 GB | Better accuracy |
| Large v3 Turbo | ~1.6 GB | High accuracy, needs more memory |
| Large v3 | ~3.1 GB | Highest accuracy, heavy |

## Job shows "interrupted"

**Symptoms:** A job in the Library has status "interrupted".

**Diagnosis:** The app was closed while the job was running. The transcription
process was terminated before it could save its result.

**Fix:** Open the job and use **Retry**. The original media is kept in
`data/media/` for this purpose, so you do not need to re-import or re-upload.

## Transcript looks wrong

**Symptoms:** The transcript is inaccurate, missing words, or contains gibberish.

**Diagnosis:** Whisper accuracy depends on the model, language setting, and audio
quality.

**Fix:** Try these in order:

1. Set the spoken language explicitly instead of "Detect automatically" — Whisper
   performs better when it knows the language.
2. Use a larger model (Small → Medium → Large).
3. Disable "Use previous text as context" in **Settings** if the transcript seems
   to drift or repeat.
4. Check the original audio for background noise or clipping.

## Social media link fails to import

**Symptoms:** The link import returns an error such as "Could not retrieve that media."

**Diagnosis:** Only public, direct-post URLs are supported. Private, age-restricted,
sign-in-required, or region-blocked posts are not. The selected platform must also
match the link's host.

**Fix:**

- Verify the link is a direct post URL (not a channel, playlist, or search page).
- Make sure the selected platform matches the site the link points to.
- Try the link in a browser to confirm it is publicly accessible without signing in.

## Port already in use

**Symptoms:** The app fails to start, or the browser opens a blank page.

**Diagnosis:** Port `8501` is already in use by another application.

**Fix:** Set a different port with the `WHISPERDESK_PORT` environment variable:

```powershell
$env:WHISPERDESK_PORT = "8502"
.venv\Scripts\python.exe app.py
```

The app falls through to the next free port automatically if the preferred one is taken.

## App crashes on startup

**Symptoms:** The terminal shows a Python traceback or the app exits immediately.

**Diagnosis:** A missing or incompatible dependency.

**Fix:** Reinstall the dependencies:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If the error mentions a specific package, check that its version is compatible with
your Python version (the project targets Python 3.11+).

## Data folder location

**Symptoms:** You cannot find where the app stores its data.

**Diagnosis:** Everything lives in the `data\` folder next to the project, unless
`WHISPERDESK_DATA` is set.

**Fix:** To move the data folder, set the environment variable before starting:

```powershell
$env:WHISPERDESK_DATA = "C:\path\to\custom-data"
.venv\Scripts\python.exe app.py
```

The exact paths are shown in **Settings → Diagnostics**.

## Clearing all data

**Symptoms:** You want to start fresh or free disk space.

**Fix:** Go to **Settings → Storage & history → Clear history**. This removes every
record and the stored media. Individual transcripts can also be deleted from the
Library or the workspace.