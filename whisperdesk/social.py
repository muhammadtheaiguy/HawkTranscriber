"""Public social-media URL validation and local media retrieval."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
from urllib.parse import urlsplit
from typing import Any

from . import mediatools

logger = logging.getLogger(__name__)

# Keep link imports to known public media sites. This also prevents the local
# server from becoming a general-purpose URL fetcher.
PLATFORM_HOSTS: dict[str, set[str]] = {
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"},
    "instagram": {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am", "www.instagr.am"},
    "facebook": {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch", "www.fb.watch"},
    "tiktok": {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"},
    "x": {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"},
    "vimeo": {"vimeo.com", "www.vimeo.com", "player.vimeo.com"},
    "soundcloud": {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com"},
    "more": {
        "twitch.tv", "www.twitch.tv", "clips.twitch.tv", "dailymotion.com", "www.dailymotion.com", "dai.ly",
        "reddit.com", "www.reddit.com", "old.reddit.com", "redd.it", "v.redd.it", "rumble.com", "www.rumble.com",
        "bilibili.com", "www.bilibili.com", "streamable.com", "www.streamable.com",
        "mixcloud.com", "www.mixcloud.com", "odysee.com", "www.odysee.com",
    },
}

MAX_MEDIA_SECONDS = 4 * 60 * 60


def normalize_and_validate_url(value: str, platform: str) -> str:
    """Normalize a pasted link and restrict it to the selected public platform."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Paste a link to a public video or audio post.")
    if "://" not in value:
        value = "https://" + value
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except (ValueError, UnicodeError):
        raise ValueError("That link is not a valid web address.") from None
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Use a regular HTTPS post link without embedded login details.")
    if port not in (None, 443):
        raise ValueError("Links with custom ports are not supported.")
    hosts = PLATFORM_HOSTS.get(platform)
    if hosts is None:
        raise ValueError("Choose a supported platform first.")
    if host not in hosts:
        raise ValueError(f"That link is not from {platform_label(platform)}. Choose the matching platform tab.")
    if not parsed.path or parsed.path == "/":
        raise ValueError("Paste a direct link to a video, reel, clip, or audio post.")
    return value


def platform_label(platform: str) -> str:
    return {
        "youtube": "YouTube", "instagram": "Instagram", "facebook": "Facebook",
        "tiktok": "TikTok", "x": "X", "vimeo": "Vimeo", "soundcloud": "SoundCloud",
        "more": "one of the additional supported sites",
    }.get(platform, "the selected platform")


class _QuietLogger:
    """Avoid leaking pasted URL query tokens into the application log."""

    def debug(self, _message: str) -> None:
        pass

    def info(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass

    def error(self, message: str) -> None:
        logger.warning("Media extractor reported an error (details omitted to protect URL query tokens)")


def _duration_filter(info: dict[str, Any], *, incomplete: bool = False) -> str | None:
    duration = info.get("duration")
    if duration and float(duration) > MAX_MEDIA_SECONDS:
        return "Links longer than four hours are not supported."
    if info.get("_type") in {"playlist", "multi_video"}:
        return "Paste a direct link to one video or audio item, not a playlist or channel."
    return None


def _download_progress_hook(d):
    """yt-dlp progress hook that updates global state with download progress."""
    # Check for cancellation
    if hasattr(download_media, "current_job_id"):
        job_id = download_media.current_job_id
        if job_id in _download_cancel_events and _download_cancel_events[job_id].is_set():
            raise Exception("Download cancelled")

    if d["status"] == "downloading":
        pct = d.get("_percent_str", "0%").strip().rstrip("%")
        try:
            pct_float = float(pct)
            # Update global progress state for UI
            social_progress["pct"] = min(100, max(0, int(pct_float)))
            social_progress["determinate"] = True
        except (ValueError, TypeError):
            pass
    elif d["status"] == "finished":
        # yt-dlp already handles final file placement via outtmpl
        pass
    elif d["status"] == "error":
        # Mark as indeterminate on error
        social_progress["determinate"] = False


def _check_existing_media(url: str, directory: Path) -> Path | None:
    """Check if media already exists in the download directory.

    yt-dlp can extract the expected title from a URL. If a file with that
    title already exists, we can skip the download.
    """
    try:
        import yt_dlp
    except ImportError:
        return None

    # Extract info without downloading to get the expected filename
    try:
        with yt_dlp.YoutubeDL({
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "default_search": "none",
        }) as checker:
            info = checker.extract_info(url, download=False)
            if info and info.get("_type") in {"video", "audio", "mixed"}:
                expected_title = info.get("title", "source")
                expected_ext = info.get("ext", "unknown")
                expected_path = directory / f"{expected_title}.{expected_ext}"
                if expected_path.is_file():
                    return expected_path
    except Exception:
        pass
    return None


# Global state for tracking download cancellation
_download_cancel_events: dict[str, Any] = {}


def download_media(url: str, directory: Path, job_id: str | None = None, cancel_event: Any = None) -> tuple[Path, dict[str, Any]]:
    """Download one audio-bearing media item using yt-dlp's Python API."""
    global social_progress
    social_progress = {"pct": 0, "determinate": False}

    if job_id:
        download_media.current_job_id = job_id
    if cancel_event and job_id:
        _download_cancel_events[job_id] = cancel_event

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "Social links need yt-dlp. Run setup.bat or install the project requirements."
        ) from exc

    directory.mkdir(parents=True, exist_ok=True)

    # Check if media already exists - skip download if it does
    existing = _check_existing_media(url, directory)
    if existing:
        info = {"title": existing.stem, "ext": existing.suffix.lstrip("."), "id": "existing"}
        # Clean up any other files in the directory that aren't our file
        for path in list(directory.iterdir()):
            if path.is_file() and path != existing:
                if path.suffix.lower() in mediatools.SUPPORTED_EXTENSIONS:
                    if not path.name.endswith((".part", ".ytdl")):
                        path.unlink(missing_ok=True)
        media_path = existing
    else:
        # Use video title for filename if available, fallback to "source"
        options = {
            "format": "bestaudio",
            "noplaylist": True,
            # max_downloads removed - yt-dlp handles this internally per session.
            # Setting it too low (e.g. 1) causes MaxDownloadsReached error across multiple calls.
            "max_filesize": 4 * 1024**3,
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 5,
            "match_filter": _duration_filter,
            "quiet": True,
            "no_warnings": True,
            "ignoreconfig": True,
            "logger": _QuietLogger(),
            "overwrites": False,
            # Use the video title in the output filename
            "outtmpl": str(directory / "%(title)s.%(ext)s"),
            "progress_hooks": [_download_progress_hook],
        }
        js_runtimes = {}
        for runtime in ("deno", "node", "bun"):
            executable = shutil.which(runtime)
            if executable:
                js_runtimes[runtime] = {"path": executable}
        if js_runtimes:
            options["js_runtimes"] = js_runtimes
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
        except Exception as exc:
            logger.warning("Social media retrieval failed (%s)", type(exc).__name__)
            # Clean up progress state on failure
            social_progress = {"pct": 0, "determinate": False}
            _download_cancel_events.pop(job_id, None)
            if hasattr(download_media, "current_job_id"):
                delattr(download_media, "current_job_id")
            raise RuntimeError(
                "Could not retrieve that media. It may be private, unavailable, unsupported, or blocked by the platform. Public links only; sign-in-required posts are not supported."
            ) from None

        # Clean up any partial/extra files from the download directory
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in mediatools.SUPPORTED_EXTENSIONS:
                if not path.name.endswith((".part", ".ytdl")):
                    # Check if this file matches our download
                    continue
        media_path = max(directory.iterdir(), key=lambda path: path.stat().st_mtime)

    if media_path.stat().st_size > 4 * 1024**3:
        media_path.unlink(missing_ok=True)
        social_progress = {"pct": 0, "determinate": False}
        _download_cancel_events.pop(job_id, None)
        if hasattr(download_media, "current_job_id"):
            delattr(download_media, "current_job_id")
        raise RuntimeError("This media file is larger than the 4 GB limit.")

    social_progress = {"pct": 100, "determinate": True}
    _download_cancel_events.pop(job_id, None)
    if hasattr(download_media, "current_job_id"):
        delattr(download_media, "current_job_id")
    return media_path, info if isinstance(info, dict) else {}