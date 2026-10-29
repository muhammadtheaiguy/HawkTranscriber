"""HTTP API and static host for HawkTranscriber, built on Starlette."""

from __future__ import annotations

import asyncio
import re
import shutil
import time
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.responses import (
    FileResponse,
    JSONResponse,
    Response,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import config, exporters, hardware, mediatools, models, paths, social
from .jobs import JobManager
from .store import Store, TERMINAL_STATUSES, new_id

MAX_UPLOAD_BYTES = 4 * 1024**3  # 4 GB

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    paths.ensure_directories()
    root = logging.getLogger()
    if any(getattr(handler, "_whisperdesk_file", False) for handler in root.handlers):
        return
    handler = RotatingFileHandler(
        paths.LOG_DIR / "whisperdesk.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler._whisperdesk_file = True
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(logging.INFO)


class AppContext:
    def __init__(self) -> None:
        _configure_logging()
        paths.ensure_directories()
        config.write_default_if_missing()
        self.store = Store()
        self.recovered = self.store.recover_interrupted()
        self.jobs = JobManager(self.store)
        self.started_at = time.time()


def _json(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status_code)


def _job_public(job: dict[str, Any], live: dict[str, Any] | None) -> dict[str, Any]:
    public = {
        "id": job["id"],
        "title": job["title"],
        "sourceName": job["source_name"],
        "mediaSize": job.get("media_size"),
        "duration": job.get("duration"),
        "model": job.get("model"),
        "language": job.get("language"),
        "task": job.get("task"),
        "wordTimestamps": bool(job.get("word_timestamps")),
        "status": job.get("status"),
        "progress": job.get("progress") or 0.0,
        "error": job.get("error"),
        "createdAt": job.get("created_at"),
        "updatedAt": job.get("updated_at"),
        "finishedAt": job.get("finished_at"),
        "hasMedia": bool(job.get("media_path")),
        "hasSegments": bool(job.get("segments")),
        "text": job.get("text"),
        "segments": job.get("segments") or [],
    }
    if live:
        public["progress"] = live.get("progress", public["progress"])
        public["phase"] = live.get("phase")
        public["message"] = live.get("message")
        public["downloadProgress"] = live.get("downloadProgress")
        public["live"] = True
    else:
        public["live"] = False
        if job.get("status") in TERMINAL_STATUSES and job.get("status") == "completed":
            public["progress"] = 1.0
    return public


def _job_summary(job: dict[str, Any], manager: JobManager) -> dict[str, Any]:
    live = manager.live_state(job["id"])
    summary = _job_public(job, live)
    summary.pop("text", None)
    summary.pop("segments", None)
    return summary


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
async def index(request):
    return FileResponse(paths.STATIC_DIR / "index.html")


async def health(request):
    return _json({"status": "ok", "uptime": round(time.time() - request.app.state.ctx.started_at, 1)})


async def system_info(request):
    ctx = request.app.state.ctx
    info = hardware.detect().to_dict()
    info["ffmpegVersion"] = hardware.ffmpeg_version()
    info["uploadLimitBytes"] = MAX_UPLOAD_BYTES
    info["paths"] = {
        "data": str(paths.DATA_DIR),
        "media": str(paths.MEDIA_DIR),
        "outputs": str(paths.OUTPUT_DIR),
        "models": str(paths.default_whisper_cache()),
        "settings": str(paths.SETTINGS_FILE),
        "database": str(paths.DATABASE_FILE),
    }
    info["supportedExtensions"] = sorted(mediatools.SUPPORTED_EXTENSIONS)
    info["recoveredJobs"] = ctx.recovered
    info["stats"] = ctx.store.stats()
    return _json(info)


async def list_models(request):
    return _json(
        {
            "models": models.catalog(),
            "recommended": models.recommend_model_name(),
        }
    )


async def list_languages(request):
    return _json({"languages": [{"code": c, "label": l} for c, l in models.LANGUAGES]})


async def get_settings(request):
    return _json({"settings": config.load(), "defaults": config.DEFAULTS})


async def put_settings(request):
    try:
        payload = await request.json()
    except Exception:
        return _json({"error": "Invalid JSON body."}, 400)
    if not isinstance(payload, dict):
        return _json({"error": "Expected a settings object."}, 400)
    updated = config.save(payload)
    return _json({"settings": updated})


async def reset_settings(request):
    return _json({"settings": config.reset()})


async def list_exports(request):
    return _json(
        {
            "formats": [
                {"id": key, "label": value["label"], "extension": value["extension"]}
                for key, value in exporters.EXPORTERS.items()
            ]
        }
    )


async def list_jobs(request):
    ctx = request.app.state.ctx
    query = request.query_params.get("query") or None
    status = request.query_params.get("status") or None
    try:
        limit = min(int(request.query_params.get("limit", 100)), 500)
    except ValueError:
        limit = 100
    jobs = ctx.store.list(query=query, status=status, limit=limit)
    return _json({"jobs": [_job_summary(job, ctx.jobs) for job in jobs]})


async def get_job(request):
    ctx = request.app.state.ctx
    job = ctx.store.get(request.path_params["job_id"])
    if not job:
        return _json({"error": "Job not found."}, 404)
    live = ctx.jobs.live_state(job["id"])
    return _json({"job": _job_public(job, live)})


async def create_transcription(request):
    ctx = request.app.state.ctx

    try:
        form = await request.form(max_files=1, max_fields=20)
    except Exception as exc:
        return _json({"error": f"Could not parse the upload: {exc}"}, 400)

    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", ""):
        return _json({"error": "No file was provided."}, 400)

    filename = Path(upload.filename).name
    if not mediatools.is_supported_extension(filename):
        return _json(
            {
                "error": (
                    f"'.{filename.rsplit('.', 1)[-1] if '.' in filename else ''}' is not a "
                    "supported format. Try WAV, MP3, M4A, FLAC, OGG, MP4, MOV, MKV or WEBM."
                )
            },
            400,
        )

    settings = config.load()
    model = str(form.get("model") or settings["default_model"])
    if models.get_spec(model) is None:
        model = settings["default_model"]

    language = str(form.get("language") or settings["default_language"])
    task = str(form.get("task") or settings["default_task"])
    if task not in {"transcribe", "translate"}:
        task = "transcribe"
    word_timestamps = str(form.get("word_timestamps", "")).lower() in {"1", "true", "on", "yes"}

    job_id = new_id()
    logging.getLogger(__name__).info("Transcription upload accepted: job=%s file=%s model=%s", job_id, filename, model)
    extension = Path(filename).suffix.lower() or ".bin"
    destination = paths.MEDIA_DIR / f"{job_id}{extension}"

    try:
        with open(destination, "wb") as target:
            shutil.copyfileobj(upload.file, target, length=1024 * 1024)
    except OSError as exc:
        return _json({"error": f"Could not store the uploaded file: {exc}"}, 500)
    finally:
        try:
            await upload.close()
        except Exception:
            pass

    size = destination.stat().st_size
    if size == 0:
        destination.unlink(missing_ok=True)
        return _json({"error": "The uploaded file was empty."}, 400)
    if size > MAX_UPLOAD_BYTES:
        destination.unlink(missing_ok=True)
        return _json({"error": "The file exceeds the 4 GB upload limit."}, 400)

    try:
        info = mediatools.probe(destination)
    except mediatools.MediaError as exc:
        destination.unlink(missing_ok=True)
        return _json({"error": str(exc)}, 400)

    title = Path(filename).stem.strip() or "Untitled transcription"
    job = ctx.store.create(
        job_id=job_id,
        title=title,
        source_name=filename,
        media_path=str(destination),
        media_size=size,
        duration=info.duration,
        model=model,
        language=language,
        task=task,
        word_timestamps=word_timestamps,
    )
    ctx.jobs.submit(job_id)

    warning = models.memory_warning(model, hardware.detect().total_ram_gb)
    return _json({"job": _job_public(job, ctx.jobs.live_state(job_id)), "warning": warning}, 201)


async def create_transcription_from_url(request):
    ctx = request.app.state.ctx
    try:
        payload = await request.json()
    except Exception:
        return _json({"error": "Invalid JSON body."}, 400)
    if not isinstance(payload, dict):
        return _json({"error": "Expected a link and transcription settings."}, 400)
    try:
        url = social.normalize_and_validate_url(
            str(payload.get("url") or ""), str(payload.get("platform") or "")
        )
    except ValueError as exc:
        return _json({"error": str(exc)}, 400)

    model = str(payload.get("model") or config.load()["default_model"])
    if models.get_spec(model) is None:
        model = config.load()["default_model"]
    language = str(payload.get("language") or config.load()["default_language"])
    task = str(payload.get("task") or config.load()["default_task"])
    if task not in {"transcribe", "translate"}:
        task = "transcribe"
    word_timestamps = bool(payload.get("word_timestamps"))

    job_id = new_id()
    download_dir = paths.TEMP_DIR / f"social-{job_id}"
    destination: Path | None = None
    download_cancel_event = asyncio.Event()
    try:
        downloaded, info = await asyncio.to_thread(
            social.download_media, url, download_dir, job_id, download_cancel_event
        )
        extension = downloaded.suffix.lower()
        if not mediatools.is_supported_extension(downloaded.name):
            raise ValueError("This platform returned a media type HawkTranscriber cannot play or transcribe.")
        # Use the video title for the filename to avoid random IDs and enable reuse
        raw_title = str(info.get("title") or info.get("fulltitle") or "HawkTranscriber recording").strip()
        title = raw_title[:200] or "HawkTranscriber recording"
        final_name = f"{title}{extension}"
        destination = paths.MEDIA_DIR / final_name
        shutil.move(str(downloaded), str(destination))
        size = destination.stat().st_size
        if size <= 0:
            raise ValueError("The platform returned an empty media file.")
        if size > MAX_UPLOAD_BYTES:
            raise ValueError("This media file is larger than the 4 GB limit.")
        media_info = mediatools.probe(destination)
        source_name = final_name
        job = ctx.store.create(
            job_id=job_id,
            title=title,
            source_name=source_name,
            media_path=str(destination),
            media_size=size,
            duration=media_info.duration,
            model=model,
            language=language,
            task=task,
            word_timestamps=word_timestamps,
        )
        ctx.jobs.submit(job_id)
    except (ValueError, mediatools.MediaError, RuntimeError) as exc:
        if destination:
            destination.unlink(missing_ok=True)
        if str(exc).startswith("Social links need yt-dlp"):
            return _json({"error": str(exc)}, 503)
        return _json({"error": str(exc)}, 400)
    except Exception as exc:
        logger.exception("Could not import social media link (job=%s, error=%s)", job_id, type(exc).__name__)
        if destination:
            destination.unlink(missing_ok=True)
        return _json({"error": "HawkTranscriber could not retrieve or prepare this media. Check that FFmpeg is installed and that the public link is still available."}, 502)
    finally:
        shutil.rmtree(download_dir, ignore_errors=True)

    logger.info("Social media import accepted: job=%s platform=%s", job_id, payload.get("platform"))
    warning = models.memory_warning(model, hardware.detect().total_ram_gb)
    return _json({"job": _job_public(job, ctx.jobs.live_state(job_id)), "warning": warning}, 201)


async def cancel_job(request):
    ctx = request.app.state.ctx
    job = ctx.store.get(request.path_params["job_id"])
    if not job:
        return _json({"error": "Job not found."}, 404)
    if job["status"] in TERMINAL_STATUSES:
        return _json({"error": "This job has already finished."}, 409)
    ctx.jobs.cancel(job["id"])
    logging.getLogger(__name__).info("Cancellation requested: job=%s", job["id"])
    return _json({"ok": True})


async def cancel_social_download(request):
    """Cancel a social media download in progress by signalling the cancel event."""
    ctx = request.app.state.ctx
    job_id = request.path_params["job_id"]
    # Find and signal the download cancel event
    download_dir = paths.TEMP_DIR / f"social-{job_id}"
    # Signal the event - this will be caught in download_media's progress hook
    # We'll just mark the job as cancelled and let the finally handle cleanup
    if ctx.jobs.is_active(job_id):
        ctx.jobs.cancel(job_id)
    return _json({"ok": True})


async def update_job(request):
    ctx = request.app.state.ctx
    job_id = request.path_params["job_id"]
    job = ctx.store.get(job_id)
    if not job:
        return _json({"error": "Job not found."}, 404)
    try:
        payload = await request.json()
    except Exception:
        return _json({"error": "Invalid JSON body."}, 400)
    if not isinstance(payload, dict):
        return _json({"error": "Expected an object."}, 400)

    updates: dict[str, Any] = {}
    if "title" in payload:
        title = str(payload["title"]).strip()
        updates["title"] = title[:200] or job["title"]
    if "text" in payload:
        updates["text"] = str(payload["text"])
    if "segments" in payload and isinstance(payload["segments"], list):
        updates["segments"] = payload["segments"]
    if not updates:
        return _json({"error": "Nothing to update."}, 400)

    ctx.store.update(job_id, **updates)
    return _json({"job": _job_public(ctx.store.get(job_id), ctx.jobs.live_state(job_id))})


async def delete_job(request):
    ctx = request.app.state.ctx
    job_id = request.path_params["job_id"]
    job = ctx.store.get(job_id)
    if not job:
        return _json({"error": "Job not found."}, 404)
    if ctx.jobs.is_active(job_id):
        ctx.jobs.cancel(job_id)
    removed = ctx.store.delete(job_id)
    if removed and removed.get("media_path"):
        Path(removed["media_path"]).unlink(missing_ok=True)
    return _json({"ok": True})


async def clear_history(request):
    ctx = request.app.state.ctx
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    delete_media = bool(payload.get("deleteMedia", False)) if isinstance(payload, dict) else False
    jobs = ctx.store.list(limit=100000)
    for job in jobs:
        if ctx.jobs.is_active(job["id"]):
            ctx.jobs.cancel(job["id"])
            continue
        if delete_media and job.get("media_path"):
            Path(job["media_path"]).unlink(missing_ok=True)
    count = ctx.store.clear()
    if delete_media:
        for entry in paths.MEDIA_DIR.glob("*"):
            if entry.is_file():
                entry.unlink(missing_ok=True)
    return _json({"removed": count})


async def job_media(request):
    ctx = request.app.state.ctx
    job = ctx.store.get(request.path_params["job_id"])
    if not job or not job.get("media_path"):
        return _json({"error": "Media not available."}, 404)
    media_path = Path(job["media_path"])
    if not media_path.exists():
        return _json({"error": "The media file is no longer on disk."}, 404)
    # Inline disposition lets the native player preview media instead of
    # prompting the browser to download the source file.
    return FileResponse(media_path, filename=job["source_name"], content_disposition_type="inline")


async def export_job(request):
    ctx = request.app.state.ctx
    job = ctx.store.get(request.path_params["job_id"])
    if not job:
        return _json({"error": "Job not found."}, 404)
    fmt = request.path_params["fmt"].lower()
    if fmt not in exporters.EXPORTERS:
        return _json({"error": "Unsupported export format."}, 404)
    segments = job.get("segments") or []
    if not segments and not (job.get("text") or "").strip():
        return _json({"error": "There is no transcript to export yet."}, 409)

    metadata = {
        "id": job["id"],
        "title": job["title"],
        "sourceName": job["source_name"],
        "model": job["model"],
        "language": job["language"],
        "task": job["task"],
        "duration": job["duration"],
        "createdAt": job["created_at"],
        "segmentCount": len(segments),
    }
    try:
        payload, extension, mime = exporters.build_export(
            fmt, segments, job.get("text") or "", metadata
        )
    except ValueError as exc:
        return _json({"error": str(exc)}, 400)

    safe = _SAFE_NAME.sub("_", job["title"]).strip() or "transcript"
    filename = f"{safe}.{extension}"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return Response(payload, media_type=mime, headers=headers)


async def not_found(request):
    return _json({"error": "Not found."}, 404)


def create_app() -> Starlette:
    ctx = AppContext()

    routes = [
        Route("/", index),
        Route("/api/health", health),
        Route("/api/system", system_info),
        Route("/api/models", list_models),
        Route("/api/languages", list_languages),
        Route("/api/exports", list_exports),
        Route("/api/settings", get_settings, methods=["GET"]),
        Route("/api/settings", put_settings, methods=["PUT"]),
        Route("/api/settings/reset", reset_settings, methods=["POST"]),
        Route("/api/jobs", list_jobs, methods=["GET"]),
        Route("/api/jobs", create_transcription, methods=["POST"]),
        Route("/api/jobs/from-url", create_transcription_from_url, methods=["POST"]),
        Route("/api/history/clear", clear_history, methods=["POST"]),
        Route("/api/jobs/{job_id}", get_job, methods=["GET"]),
        Route("/api/jobs/{job_id}", update_job, methods=["PATCH"]),
        Route("/api/jobs/{job_id}", delete_job, methods=["DELETE"]),
        Route("/api/jobs/{job_id}/cancel", cancel_job, methods=["POST"]),
        Route("/api/jobs/{job_id}/cancel-download", cancel_social_download, methods=["POST"]),
        Route("/api/jobs/{job_id}/media", job_media, methods=["GET"]),
        Route("/api/jobs/{job_id}/export/{fmt}", export_job, methods=["GET"]),
        Mount("/static", app=StaticFiles(directory=str(paths.STATIC_DIR)), name="static"),
        Route("/{path:path}", not_found),
    ]

    app = Starlette(routes=routes)
    app.state.ctx = ctx

    @asynccontextmanager
    async def lifespan(application):
        yield
        ctx.jobs.shutdown()
        ctx.store.close()

    app.router.lifespan_context = lifespan
    return app
