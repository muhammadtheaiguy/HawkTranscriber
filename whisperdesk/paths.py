"""Filesystem paths and directory management for HawkTranscriber.

All application data (history, media copies, settings, logs) lives inside a
single ``data`` directory next to the project so it is easy to find, back up
or remove. Nothing is written outside this directory or the OS temp folder.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = Path(os.environ.get("WHISPERDESK_DATA", PROJECT_ROOT / "data"))

MEDIA_DIR = DATA_DIR / "media"
OUTPUT_DIR = DATA_DIR / "outputs"
MODELS_DIR = DATA_DIR / "models"
LOG_DIR = DATA_DIR / "logs"
TEMP_DIR = DATA_DIR / "tmp"

SETTINGS_FILE = DATA_DIR / "settings.json"
DATABASE_FILE = DATA_DIR / "history.db"

STATIC_DIR = PACKAGE_DIR / "static"


def ensure_directories() -> None:
    """Create every directory the application expects to exist."""
    for directory in (DATA_DIR, MEDIA_DIR, OUTPUT_DIR, MODELS_DIR, LOG_DIR, TEMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def default_whisper_cache() -> Path:
    """Return the location Whisper downloads its models to by default."""
    default = os.path.join(os.path.expanduser("~"), ".cache")
    root = os.getenv("XDG_CACHE_HOME", default)
    return Path(root) / "whisper"
