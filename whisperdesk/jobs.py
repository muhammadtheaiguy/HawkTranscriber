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


class _Slot:
    """One worker process; runs one job at a time."""

    def __init__(self, process, cmd_queue, cancel_event) -> None:
        self.process = process
        self.cmd_queue = cmd_queue
        self.cancel_event = cancel_event
        self.job_id: str | None = None
        self.suspended = False


def _procs(pid: int):
    import psutil

    root = psutil.Process(pid)
    return [root, *root.children(recursive=True)]


class JobManager:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._lock = threading.RLock()
        self._ctx = mp.get_context("spawn")
        self._event_queue: Any = self._ctx.Queue()
        self._slots: list[_Slot] = []
        self._pending: list[str] = []
        self._held: set[str] = set()  # queued jobs the user paused
        self._live: dict[str, dict[str, Any]] = {}
        self._reader: threading.Thread | None = None
        self._stopped = False

    # -- worker lifecycle --------------------------------------------------
    def _max_parallel(self) -> int:
        return max(1, min(3, int(config.load().get("max_parallel_jobs", 2))))

    def _spawn_slot(self) -> _Slot:
        cmd_queue = self._ctx.Queue()
        cancel_event = self._ctx.Event()
        process = self._ctx.Process(
            target=worker.run_worker,
            args=(
                cmd_queue,
                self._event_queue,
                cancel_event,
                str(paths.default_whisper_cache()),
                int(config.load().get("max_loaded_models", 1)),
            ),
            name="whisperdesk-worker",
            daemon=True,
        )
        process.start()
        if self._reader is None:
            self._reader = threading.Thread(
                target=self._read_events, name="whisperdesk-events", daemon=True
            )
            self._reader.start()
        slot = _Slot(process, cmd_queue, cancel_event)
        self._slots.append(slot)
        return slot

    def _slot_for(self, job_id: str) -> _Slot | None:
        return next((s for s in self._slots if s.job_id == job_id), None)

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
            for slot in list(self._slots):
                if slot.process.is_alive():
                    continue
                self._slots.remove(slot)
                if slot.job_id:
                    logger.error("Worker exited unexpectedly during job %s", slot.job_id)
                    self._finalize(
                        slot.job_id,
                        status="failed",
                        error="The transcription process stopped unexpectedly.",
                    )
            self._pump()

    # -- public API --------------------------------------------------------
    def submit(self, job_id: str) -> None:
        logger.info("Job queued: %s", job_id)
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
                self._held.discard(job_id)
                self._finalize(job_id, status="cancelled", error=None)
                return True
            slot = self._slot_for(job_id)
            if slot:
                self._resume_slot(slot)  # a frozen process could never see the flag
                slot.cancel_event.set()
                self._live.setdefault(job_id, {})["message"] = "Cancelling…"
                return True
        return False

    def pause(self, job_id: str) -> bool:
        """Hold a queued job, or freeze a running one (it keeps its memory)."""
        with self._lock:
            if job_id in self._pending:
                self._held.add(job_id)
                self._set_paused(job_id, "Paused (will not start until resumed)")
                return True
            slot = self._slot_for(job_id)
            if slot and not slot.suspended:
                try:
                    for proc in _procs(slot.process.pid):
                        proc.suspend()
                except Exception:
                    logger.exception("Could not pause job %s", job_id)
                    return False
                slot.suspended = True
                self._set_paused(job_id, "Paused")
                return True
        return False

    def resume(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._held:
                self._held.discard(job_id)
                self._live.setdefault(job_id, {}).update(phase="queued", message="Waiting in queue")
                self.store.update(job_id, status="queued")
                self._pump()
                return True
            slot = self._slot_for(job_id)
            if slot and slot.suspended:
                self._resume_slot(slot)
                self._live.setdefault(job_id, {}).update(phase="running", message="Transcribing audio")
                self.store.update(job_id, status="running")
                return True
        return False

    def prioritize(self, job_id: str) -> bool:
        """Move a queued job to the front (and un-pause it)."""
        with self._lock:
            if job_id not in self._pending:
                return False
            self._pending.remove(job_id)
            self._pending.insert(0, job_id)
            if job_id in self._held:
                self.resume(job_id)
            self._pump()
            return True

    def live_state(self, job_id: str) -> dict[str, Any] | None:
        return self._live.get(job_id)

    def is_active(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._pending or self._slot_for(job_id) is not None

    def active_count(self) -> int:
        with self._lock:
            return len(self._pending) + sum(1 for s in self._slots if s.job_id)

    def shutdown(self) -> None:
        self._stopped = True
        with self._lock:
            slots = list(self._slots)
        for slot in slots:
            try:
                self._resume_slot(slot)
                slot.cancel_event.set()
                slot.cmd_queue.put(None)
            except Exception:
                pass
        for slot in slots:
            slot.process.join(timeout=5)
            if slot.process.is_alive():
                slot.process.terminate()
                slot.process.join(timeout=3)

    # -- internals ---------------------------------------------------------
    def _resume_slot(self, slot: _Slot) -> None:
        if not slot.suspended:
            return
        try:
            for proc in _procs(slot.process.pid):
                proc.resume()
        except Exception:
            logger.exception("Could not resume process")
        slot.suspended = False

    def _set_paused(self, job_id: str, message: str) -> None:
        self._live.setdefault(job_id, {}).update(phase="paused", message=message)
        self.store.update(job_id, status="paused")

    def _release(self, job_id: str) -> None:
        slot = self._slot_for(job_id)
        if slot:
            slot.job_id = None
            slot.suspended = False

    def _pump(self) -> None:
        with self._lock:
            while True:
                job_id = next((j for j in self._pending if j not in self._held), None)
                if job_id is None:
                    return
                self._slots = [s for s in self._slots if s.process.is_alive() or s.job_id]
                slot = next((s for s in self._slots if s.job_id is None), None)
                if slot is None:
                    if len(self._slots) >= self._max_parallel():
                        return
                    slot = self._spawn_slot()
                self._pending.remove(job_id)
                job = self.store.get(job_id)
                if job is None:
                    continue
                slot.job_id = job_id
                slot.cancel_event.clear()
                self._live[job_id] = {
                    "progress": 0.0,
                    "phase": "starting",
                    "message": "Starting…",
                    "downloadProgress": None,
                }
                self.store.update(job_id, status="queued")
                slot.cmd_queue.put(self._build_command(job))

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
            slot = self._slot_for(job_id)
            if slot and slot.suspended and etype in {"download", "progress", "status"}:
                return  # a late event from a job the user just paused
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
                self._release(job_id)
                self._pump()
            elif etype == "error":
                logger.error("Job failed: %s: %s", job_id, event.get("error", "Unknown error"))
                self._finalize(
                    job_id,
                    status="failed",
                    error=event.get("error", "Unknown error"),
                )
                self._release(job_id)
                self._pump()
            elif etype == "cancelled":
                logger.info("Job cancelled: %s", job_id)
                self._finalize(job_id, status="cancelled")
                self._release(job_id)
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
