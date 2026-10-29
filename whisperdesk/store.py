"""SQLite-backed history store for transcription jobs."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from . import paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    source_name     TEXT NOT NULL,
    media_path      TEXT,
    media_size      INTEGER,
    duration        REAL,
    model           TEXT,
    language        TEXT,
    task            TEXT,
    word_timestamps INTEGER DEFAULT 0,
    status          TEXT NOT NULL,
    progress        REAL DEFAULT 0,
    text            TEXT,
    segments        TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
ACTIVE_STATUSES = {"queued", "loading", "running", "saving"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Store:
    def __init__(self, path: str | None = None) -> None:
        self.path = str(path or paths.DATABASE_FILE)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.commit()

    # -- low level ---------------------------------------------------------
    def _row_to_job(self, row: sqlite3.Row) -> dict[str, Any]:
        job = dict(row)
        raw_segments = job.get("segments")
        try:
            job["segments"] = json.loads(raw_segments) if raw_segments else []
        except (json.JSONDecodeError, TypeError):
            job["segments"] = []
        job["word_timestamps"] = bool(job.get("word_timestamps"))
        return job

    # -- public API --------------------------------------------------------
    def create(
        self,
        *,
        title: str,
        source_name: str,
        media_path: str | None,
        media_size: int | None,
        duration: float | None,
        model: str,
        language: str,
        task: str,
        word_timestamps: bool,
        job_id: str | None = None,
        status: str = "queued",
    ) -> dict[str, Any]:
        job_id = job_id or new_id()
        now = utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (id, title, source_name, media_path, media_size,
                    duration, model, language, task, word_timestamps, status,
                    progress, segments, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '[]', ?, ?)
                """,
                (
                    job_id,
                    title,
                    source_name,
                    media_path,
                    media_size,
                    duration,
                    model,
                    language,
                    task,
                    1 if word_timestamps else 0,
                    status,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return self.get(job_id)  # type: ignore[return-value]

    def update(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "word_timestamps" in fields:
            fields["word_timestamps"] = 1 if fields["word_timestamps"] else 0
        if "segments" in fields and not isinstance(fields["segments"], str):
            fields["segments"] = json.dumps(fields["segments"], ensure_ascii=False)
        fields["updated_at"] = utc_now()
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [job_id]
        with self._lock:
            self._conn.execute(
                f"UPDATE jobs SET {columns} WHERE id = ?", values
            )
            self._conn.commit()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list(
        self,
        *,
        query: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            clauses.append(
                "(title LIKE ? OR source_name LIKE ? OR text LIKE ?)"
            )
            like = f"%{query}%"
            params.extend([like, like, like])
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, title, source_name, media_path, media_size, duration, "
            "model, language, task, word_timestamps, status, progress, error, "
            "created_at, updated_at, finished_at "
            f"FROM jobs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_job(row) for row in rows]

    def delete(self, job_id: str) -> dict[str, Any] | None:
        job = self.get(job_id)
        if not job:
            return None
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()
        return job

    def clear(self, *, keep_media: bool = False) -> int:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            self._conn.execute("DELETE FROM jobs")
            self._conn.commit()
        return int(count)

    def active_jobs(self) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders})",
                tuple(ACTIVE_STATUSES),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def recover_interrupted(self) -> int:
        """Mark jobs left running by a previous session as interrupted."""
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        now = utc_now()
        with self._lock:
            cursor = self._conn.execute(
                f"""
                UPDATE jobs
                SET status = 'interrupted',
                    error = 'The application closed before this job finished.',
                    updated_at = ?
                WHERE status IN ({placeholders})
                """,
                (now, *ACTIVE_STATUSES),
            )
            self._conn.commit()
        return cursor.rowcount or 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            completed = self._conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'completed'"
            ).fetchone()[0]
            total_seconds = self._conn.execute(
                "SELECT COALESCE(SUM(duration), 0) FROM jobs WHERE status = 'completed'"
            ).fetchone()[0]
        return {
            "total": int(total),
            "completed": int(completed),
            "totalMediaSeconds": float(total_seconds or 0),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()
