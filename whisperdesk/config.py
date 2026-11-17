"""Application settings: defaults, validation and JSON persistence."""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "theme": "system",  # "system" | "light" | "dark"
    "default_model": "small",
    "default_language": "auto",
    "default_task": "transcribe",  # "transcribe" | "translate"
    "word_timestamps": False,
    "condition_on_previous_text": True,
    "keep_media": True,
    "autosave_edits": True,
    "max_loaded_models": 1,
    "max_parallel_jobs": 2,  # 1-3 transcriptions at once (each loads its own model)
}

_THEMES = {"system", "light", "dark"}
_TASKS = {"transcribe", "translate"}

_lock = threading.RLock()
_cache: dict[str, Any] | None = None


def _coerce(key: str, value: Any) -> Any:
    if key == "theme":
        return value if value in _THEMES else DEFAULTS["theme"]
    if key == "default_task":
        return value if value in _TASKS else DEFAULTS["default_task"]
    if key == "default_language":
        value = str(value) if value else "auto"
        return value
    if key == "default_model":
        return str(value) if value else DEFAULTS["default_model"]
    if key in {"word_timestamps", "condition_on_previous_text", "keep_media", "autosave_edits"}:
        return bool(value)
    if key in {"max_loaded_models", "max_parallel_jobs"}:
        try:
            return max(1, min(4 if key == "max_loaded_models" else 3, int(value)))
        except (TypeError, ValueError):
            return DEFAULTS[key]
    return value


def load() -> dict[str, Any]:
    """Return the current settings, reading from disk on first access."""
    global _cache
    with _lock:
        if _cache is not None:
            return deepcopy(_cache)

        settings = deepcopy(DEFAULTS)
        if paths.SETTINGS_FILE.exists():
            try:
                raw = json.loads(paths.SETTINGS_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for key, value in raw.items():
                        if key in DEFAULTS:
                            settings[key] = _coerce(key, value)
            except (OSError, json.JSONDecodeError):
                # Corrupt settings should never block startup; fall back to defaults.
                settings = deepcopy(DEFAULTS)
        _cache = settings
        return deepcopy(_cache)


def save(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge ``updates`` into the settings and persist them."""
    global _cache
    with _lock:
        current = load()
        for key, value in updates.items():
            if key in DEFAULTS:
                current[key] = _coerce(key, value)
        paths.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = paths.SETTINGS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        tmp.replace(paths.SETTINGS_FILE)
        _cache = current
        return deepcopy(current)


def reset() -> dict[str, Any]:
    """Restore defaults and persist them."""
    global _cache
    with _lock:
        _cache = deepcopy(DEFAULTS)
        paths.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        paths.SETTINGS_FILE.write_text(
            json.dumps(_cache, indent=2), encoding="utf-8"
        )
        return deepcopy(_cache)


def write_default_if_missing() -> None:
    if not paths.SETTINGS_FILE.exists():
        save({})
