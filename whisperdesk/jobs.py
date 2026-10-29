"""Background job management: owns the worker process and job lifecycle."""

from __future__ import annotations

import multiprocessing as mp
import logging
import queue as queue_mod
import threading
import time
from typing import Any

from . import config, paths, worker
from .store import Store, TERMINAL_STATUSES, utc_now

logger = logging.getLogger(__name__)


class JobManager:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._lock = threading.RLock()
        self._ctx = mp.get_context("spawn")
        self._cmd_queue: Any = None
        self._event_queue: Any = None
        self._cancel_event: Any = None
        self._process: mp.process.BaseProcess | None = None
        self._pending: list[str] = []
        self._current: str | None = None
        self._live: dict[str, dict[str, Any]] = {}
        self._reader: threading.Thread | None = None
        self._stopped = False

    # -- worker lifecycle --------------------------------------------------
    def _ensure_worker(self) -> None:
        with self._lock:
            if self._process and self._process.is_alive():
                return
            self._cmd_queue = self._ctx.Queue()
            self._event_queue = self._ctx.Queue()
            self._cancel_event = self._ctx.Event()
            settings = config.load()
            self._process = self._ctx.Process(
                target=worker.run_worker,
                args=(
                    self._cmd_queue,
                    self._event_queue,
                    self._cancel_event,
                    str(paths.default_whisper_cache()),
                    int(settings.get("max_loaded_models", 1)),
                ),
                name="whisperdesk-worker",
                daemon=True,
            )
            self._process.start()
            self._reader = threading.Thread(
                target=self._read_events, name="whisperdesk-events", daemon=True
            )
            self._reader.start()

    def _read_events(self) -> None:
        while not self._stopped:
            try:
                event = self._event_queue.get(timeout=1.0)
            except queue_mod.Empty:
                self._check_worker_health()
                continue
            except (EOFError, OSError):
                break
            self._handle_event(event)

    def _check_worker_health(self) -> None:
        with self._lock:
            if self._process is None:
                return
            if not self._process.is_alive() and self._current:
                job_id = self._current
                message = "The transcription process stopped unexpectedly."
                logger.error("Worker process exited unexpectedly while job %s was active", job_id)
                self._finalize(job_id, status="failed", error=message)
                self._current = None
                self._pump()

    # -- public API --------------------------------------------------------
    def submit(self, job_id: str) -> None:
        logger.info("Job queued: %s", job_id)
        self._ensure_worker()
        with self._lock:
            if job_id not in self._pending:
                self._pending.append(job_id)
            self._live[job_id] = {
                "progress": 0.0,
                "phase": "queued",
                "message": "Waiting in queue",
                "downloadProgress": None,
            }
        self._pump()

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._pending:
                self._pending.remove(job_id)
                self._finalize(job_id, status="cancelled", error=None)
                return True
            if job_id == self._current and self._cancel_event is not None:
                self._cancel_event.set()
                self._live.setdefault(job_id, {})["message"] = "Cancelling…"
                return True
        job = self.store.get(job_id)
        if job and job["status"] in TERMINAL_STATUSES:
            return False
        return False

    def live_state(self, job_id: str) -> dict[str, Any] | None:
        return self._live.get(job_id)

    def is_active(self, job_id: str) -> bool:
        with self._lock:
            return job_id == self._current or job_id in self._pending

    def active_count(self) -> int:
        with self._lock:
            return len(self._pending) + (1 if self._current else 0)

    def shutdown(self) -> None:
        self._stopped = True
        with self._lock:
            process = self._process
        if process and process.is_alive():
            try:
                if self._cancel_event is not None:
                    self._cancel_event.set()
                if self._cmd_queue is not None:
                    self._cmd_queue.put(None)
            except Exception:
                pass
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=3)

    # -- internals ---------------------------------------------------------
    def _pump(self) -> None:
        with self._lock:
            if self._current or not self._pending:
                return
            if self._process is None or not self._process.is_alive():
                self._ensure_worker()
            job_id = self._pending.pop(0)
            job = self.store.get(job_id)
            if job is None:
                self._pump()
                return
            self._current = job_id
            self._live[job_id] = {
                "progress": 0.0,
                "phase": "starting",
                "message": "Starting…",
                "downloadProgress": None,
            }
            self.store.update(job_id, status="queued")
            command = self._build_command(job)
            self._cmd_queue.put(command)

    def _build_command(self, job: dict[str, Any]) -> dict[str, Any]:
        settings = config.load()
        language = job.get("language")
        if not language or language == "auto":
            language = None
        return {
            "kind": "transcribe",
            "job_id": job["id"],
            "path": job["media_path"],
            "model": job["model"],
            "language": language,
            "task": job.get("task") or "transcribe",
            "word_timestamps": bool(job.get("word_timestamps")),
            "condition_on_previous_text": bool(
                settings.get("condition_on_previous_text", True)
            ),
            "duration": job.get("duration"),
        }

    def _handle_event(self, event: dict[str, Any]) -> None:
        job_id = event.get("jobId")
        if not job_id:
            return
        etype = event.get("type")

        with self._lock:
            live = self._live.setdefault(job_id, {})
            if etype == "download":
                live["downloadProgress"] = event.get("progress")
                live["message"] = "Downloading model"
                live["phase"] = "loading"
                self.store.update(job_id, status="loading")
            elif etype == "progress":
                live["progress"] = event.get("progress", 0.0)
                live["phase"] = "running"
                live["message"] = "Transcribing audio"
                self.store.update(job_id, status="running", progress=event.get("progress"))
            elif etype == "status":
                live["phase"] = event.get("status", "running")
                live["message"] = event.get("message", "")
                self.store.update(job_id, status=event.get("status", "running"))
            elif etype == "result":
                logger.info("Job completed: %s", job_id)
                live["progress"] = 1.0
                self._finalize(
                    job_id,
                    status="completed",
                    text=event.get("text", ""),
                    segments=event.get("segments", []),
                    language=event.get("language"),
                )
                self._current = None
                self._pump()
            elif etype == "error":
                logger.error("Job failed: %s: %s", job_id, event.get("error", "Unknown error"))
                self._finalize(
                    job_id,
                    status="failed",
                    error=event.get("error", "Unknown error"),
                )
                self._current = None
                self._pump()
            elif etype == "cancelled":
                logger.info("Job cancelled: %s", job_id)
                self._finalize(job_id, status="cancelled")
                self._current = None
                self._pump()

    def _finalize(self, job_id: str, status: str, **fields: Any) -> None:
        updates: dict[str, Any] = {"status": status, "finished_at": utc_now()}
        if status == "completed":
            updates["progress"] = 1.0
        updates.update(fields)
        # Preserve a detected language if Whisper reported one.
        if fields.get("language"):
            updates["language"] = fields["language"]
        try:
            self.store.update(job_id, **updates)
        except Exception:
            pass
        self._live.pop(job_id, None)
