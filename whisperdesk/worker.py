"""Transcription worker that runs in a separate process.

Running the heavy model work in its own process keeps the web server responsive,
lets us show real progress, and allows cancellation: Whisper's own progress bar
is wrapped so that each update reports progress and checks a cancellation flag.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import traceback
from typing import Any

from . import hardware

logger = logging.getLogger(__name__)


class _Cancelled(Exception):
    """Internal signal used to abort a transcription run."""


def _jsonable(value: Any) -> Any:
    """Recursively convert numpy / torch scalars into plain Python types."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    return str(value)


class _ProgressBar:
    """Duck-typed replacement for tqdm used to observe Whisper's progress."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.total = kwargs.get("total") or 0
        self._n = 0
        self.disable = bool(kwargs.get("disable", False))
        self._emit = kwargs.pop("_emit", None)
        self._cancel_event = kwargs.pop("_cancel_event", None)

    def update(self, n: int = 1) -> None:
        self._n += n
        if self._emit and not self.disable and self.total:
            self._emit(min(self._n / float(self.total), 1.0))
        if self._cancel_event is not None and self._cancel_event.is_set():
            raise _Cancelled()

    def __enter__(self) -> "_ProgressBar":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def close(self) -> None:  # pragma: no cover - tqdm compatibility
        return None

    def refresh(self) -> None:  # pragma: no cover
        return None

    def set_postfix(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return None


def _install_progress_hooks(emit, cancel_event) -> tuple[Any, Any]:
    """Patch Whisper so model downloads and decoding report progress."""
    import whisper

    download_class = type(
        "ProgressBar",
        (_ProgressBar,),
        {
            "__init__": lambda self, *a, **k: _ProgressBar.__init__(
                self,
                *a,
                _emit=lambda frac: emit("download", frac),
                _cancel_event=cancel_event,
                **k,
            )
        },
    )
    whisper.tqdm = download_class  # used as `tqdm(...)` during downloads

    transcribe_module = sys.modules.get("whisper.transcribe") or importlib.import_module(
        "whisper.transcribe"
    )
    transcribe_class = type(
        "ProgressBar",
        (_ProgressBar,),
        {
            "__init__": lambda self, *a, **k: _ProgressBar.__init__(
                self,
                *a,
                _emit=lambda frac: emit("progress", frac),
                _cancel_event=cancel_event,
                **k,
            )
        },
    )
    shim = type("TqdmShim", (), {"tqdm": transcribe_class})()
    original = getattr(transcribe_module, "tqdm", None)
    transcribe_module.tqdm = shim
    return download_class, shim


def _select_device() -> tuple[str, bool]:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", True
    except Exception:
        pass
    return "cpu", False


def run_worker(cmd_queue, event_queue, cancel_event, models_dir, max_models: int = 1):
    """Entry point executed in the worker process."""
    loaded: dict[str, Any] = {}
    order: list[str] = []

    def emit(event: dict[str, Any]) -> None:
        event_queue.put(event)

    while True:
        command = cmd_queue.get()
        if command is None:
            break

        kind = command.get("kind")
        if kind == "shutdown":
            break
        if kind != "transcribe":
            continue

        job_id = command["job_id"]
        _handle_transcribe(
            command, emit, cancel_event, loaded, order, models_dir, max_models
        )

    for model in loaded.values():
        del model
    loaded.clear()


def _handle_transcribe(
    command, emit, cancel_event, loaded, order, models_dir, max_models
) -> None:
    job_id = command["job_id"]
    model_name = command["model"]

    def emit_for(kind: str, frac: float) -> None:
        emit({"type": kind, "jobId": job_id, "progress": round(float(frac), 4)})

    _install_progress_hooks(emit_for, cancel_event)
    cancel_event.clear()

    try:
        import whisper

        device, use_fp16 = _select_device()

        if model_name in loaded:
            model = loaded[model_name]
            order.remove(model_name)
            order.append(model_name)
        else:
            emit(
                {
                    "type": "status",
                    "jobId": job_id,
                    "status": "loading",
                    "message": f"Loading the {model_name} model",
                }
            )
            model = whisper.load_model(
                model_name, device=device, download_root=models_dir
            )
            loaded[model_name] = model
            order.append(model_name)
            while len(order) > max(1, max_models):
                stale = order.pop(0)
                loaded.pop(stale, None)

        if cancel_event.is_set():
            raise _Cancelled()

        emit(
            {
                "type": "status",
                "jobId": job_id,
                "status": "running",
                "message": "Transcribing audio",
            }
        )

        language = command.get("language") or None
        task = command.get("task") or "transcribe"
        options = {
            "language": language,
            "task": task,
            "fp16": use_fp16,
            "verbose": False,
            # Verbatim mode: disable every Whisper filter that drops or rewrites
            # speech (repeats, retakes, "silence"). Word timestamps follow the toggle.
            "word_timestamps": bool(command.get("word_timestamps")),
            "condition_on_previous_text": False,  # stops repeats being collapsed/skipped
            "compression_ratio_threshold": None,  # else repetitive segments are discarded
            "logprob_threshold": None,  # else stutters/mumbles are re-decoded or dropped
            "no_speech_threshold": None,  # else quiet speech is treated as silence
            "temperature": 0.0,  # deterministic, no fallback re-decoding
            "hallucination_silence_threshold": None,
        }
        options["beam_size"] = int(command.get("beam_size") or 5)
        initial_prompt = command.get("initial_prompt")
        if initial_prompt:
            options["initial_prompt"] = initial_prompt

        result = model.transcribe(command["path"], **options)

        segments = _jsonable(result.get("segments", []))
        text = str(result.get("text", "")).strip()

        emit(
            {
                "type": "result",
                "jobId": job_id,
                "segments": segments,
                "text": text,
                "language": result.get("language"),
                "duration": command.get("duration"),
            }
        )
    except _Cancelled:
        emit({"type": "cancelled", "jobId": job_id})
    except Exception as exc:  # noqa: BLE001 - report everything back to the UI
        logger.exception("Worker error for job %s", job_id)
        emit(
            {
                "type": "error",
                "jobId": job_id,
                "error": _humanize_error(exc),
                "traceback": traceback.format_exc(limit=8),
            }
        )


def _humanize_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    lowered = text.lower()
    if "no such file" in lowered or "cannot find the file" in lowered:
        return "The media file could not be opened. It may have been moved or deleted."
    if "memory" in lowered or "out of memory" in lowered:
        return (
            "The machine ran out of memory while transcribing. "
            "Try a smaller model or a shorter file."
        )
    if "ffmpeg" in lowered:
        return (
            "FFmpeg is required to decode this file but could not be run. "
            "Install FFmpeg and make sure it is on your PATH."
        )
    if "checksum" in lowered or "download" in lowered:
        return (
            "The model could not be downloaded or was corrupted. "
            "Check your connection and try again."
        )
    if "cuda" in lowered or "gpu" in lowered:
        return "The GPU could not be used for transcription. The app will fall back to CPU."
    return f"Transcription failed: {text}"


if __name__ == "__main__":  # pragma: no cover
    _ = hardware
    _ = os
