"""Thin wrappers around FFmpeg/FFprobe for validating and inspecting media."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import hardware

SUPPORTED_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".wma",
    ".mp4",
    ".m4v",
    ".mov",
    ".mkv",
    ".webm",
    ".mpg",
    ".mpeg",
    ".avi",
    ".aiff",
    ".amr",
}

AUDIO_ONLY_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".wma",
    ".aiff",
    ".amr",
}


class MediaError(Exception):
    """Raised when a file cannot be used as transcription input."""


@dataclass
class MediaInfo:
    path: str
    duration: float | None
    has_audio: bool
    has_video: bool
    container: str | None
    audio_codec: str | None
    channels: int | None
    sample_rate: int | None
    bitrate: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "duration": self.duration,
            "hasAudio": self.has_audio,
            "hasVideo": self.has_video,
            "container": self.container,
            "audioCodec": self.audio_codec,
            "channels": self.channels,
            "sampleRate": self.sample_rate,
            "bitrate": self.bitrate,
        }


def is_supported_extension(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS


def probe(path: str | Path) -> MediaInfo:
    """Inspect a media file with FFprobe.

    Raises :class:`MediaError` with an actionable message on failure.
    """
    path = Path(path)
    if not path.exists():
        raise MediaError("The file could not be found on disk.")
    if path.stat().st_size == 0:
        raise MediaError("The file is empty (0 bytes).")

    ffprobe = hardware.os_which("ffprobe")
    if not ffprobe:
        raise MediaError(
            "FFprobe is required but was not found. Install FFmpeg and ensure "
            "'ffprobe' is available on your PATH."
        )

    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=hardware._no_window(),
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError("FFprobe timed out while reading the file.") from exc
    except OSError as exc:
        raise MediaError(f"Could not run FFprobe: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        message = detail[-1] if detail else "FFprobe could not read this file."
        raise MediaError(f"The file could not be read by FFmpeg: {message}")

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError("FFprobe returned malformed metadata.") from exc

    streams = data.get("streams", [])
    fmt = data.get("format", {})

    audio_stream = next(
        (s for s in streams if s.get("codec_type") == "audio"), None
    )
    video_stream = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and s.get("disposition", {}).get("attached_pic", 0) != 1
        ),
        None,
    )

    if audio_stream is None:
        raise MediaError(
            "No audio track was found in this file. Choose a file that contains speech."
        )

    duration = _safe_float(fmt.get("duration")) or _safe_float(
        audio_stream.get("duration")
    )
    bitrate = _safe_int(fmt.get("bit_rate")) or _safe_int(
        audio_stream.get("bit_rate")
    )

    return MediaInfo(
        path=str(path),
        duration=duration,
        has_audio=True,
        has_video=video_stream is not None,
        container=fmt.get("format_name"),
        audio_codec=audio_stream.get("codec_name"),
        channels=_safe_int(audio_stream.get("channels")),
        sample_rate=_safe_int(audio_stream.get("sample_rate")),
        bitrate=bitrate,
    )


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return "--:--"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"
