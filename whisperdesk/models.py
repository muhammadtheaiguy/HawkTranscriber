"""Whisper model catalog: metadata, availability and recommendations."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from . import hardware, paths

# Approximate on-disk / download sizes (bytes) for each official checkpoint.
_APPROX_BYTES = {
    "tiny": 75 * 1024**2,
    "tiny.en": 75 * 1024**2,
    "base": 142 * 1024**2,
    "base.en": 142 * 1024**2,
    "small": 466 * 1024**2,
    "small.en": 466 * 1024**2,
    "medium": 1530 * 1024**2,
    "medium.en": 1530 * 1024**2,
    "large-v1": 3100 * 1024**2,
    "large-v2": 3100 * 1024**2,
    "large-v3": 3100 * 1024**2,
    "large": 3100 * 1024**2,
    "large-v3-turbo": 1620 * 1024**2,
    "turbo": 1620 * 1024**2,
}


@dataclass(frozen=True)
class ModelSpec:
    name: str
    label: str
    params: str
    multilingual: bool
    speed: str
    approx_memory_gb: float
    relative_accuracy: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["approxBytes"] = _APPROX_BYTES.get(self.name, 0)
        return data


CATALOG: list[ModelSpec] = [
    ModelSpec("tiny", "Tiny", "39M", True, "Fastest", 1.0, "Basic"),
    ModelSpec("tiny.en", "Tiny (English)", "39M", False, "Fastest", 1.0, "Basic"),
    ModelSpec("base", "Base", "74M", True, "Very fast", 1.0, "Fair"),
    ModelSpec("base.en", "Base (English)", "74M", False, "Very fast", 1.0, "Fair"),
    ModelSpec("small", "Small", "244M", True, "Fast", 2.0, "Good"),
    ModelSpec("small.en", "Small (English)", "244M", False, "Fast", 2.0, "Good"),
    ModelSpec("medium", "Medium", "769M", True, "Moderate", 5.0, "Very good"),
    ModelSpec("medium.en", "Medium (English)", "769M", False, "Moderate", 5.0, "Very good"),
    ModelSpec("large-v3-turbo", "Large v3 Turbo", "809M", True, "Moderate", 6.0, "Excellent"),
    ModelSpec("large-v3", "Large v3", "1550M", True, "Slow", 10.0, "Best"),
]

_BY_NAME = {spec.name: spec for spec in CATALOG}

# Keep the option list tidy: hide duplicate aliases and the redundant ".en"
# variants when they are not in the curated catalog.
LANGUAGES = [
    ("auto", "Detect automatically"),
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("nl", "Dutch"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("pl", "Polish"),
    ("tr", "Turkish"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
    ("ur", "Urdu"),
    ("fa", "Persian"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("vi", "Vietnamese"),
    ("th", "Thai"),
    ("id", "Indonesian"),
    ("sv", "Swedish"),
    ("da", "Danish"),
    ("no", "Norwegian"),
    ("fi", "Finnish"),
    ("cs", "Czech"),
    ("el", "Greek"),
    ("he", "Hebrew"),
    ("ro", "Romanian"),
]


def get_spec(name: str) -> ModelSpec | None:
    return _BY_NAME.get(name)


def _search_roots() -> list[Any]:
    roots = [paths.default_whisper_cache()]
    if paths.MODELS_DIR.exists():
        roots.insert(0, paths.MODELS_DIR)
    return roots


def downloaded_path(name: str):
    """Return the path of a model checkpoint if it is already on disk."""
    for root in _search_roots():
        candidate = root / f"{name}.pt"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def is_downloaded(name: str) -> bool:
    return downloaded_path(name) is not None


def catalog() -> list[dict[str, Any]]:
    """Full model catalog annotated with availability information."""
    result: list[dict[str, Any]] = []
    for spec in CATALOG:
        entry = spec.to_dict()
        path = downloaded_path(spec.name)
        entry["downloaded"] = path is not None
        entry["sizeBytes"] = path.stat().st_size if path else entry["approxBytes"]
        entry["diskPath"] = str(path) if path else None
        result.append(entry)

    recommended = recommended_model()
    for entry in result:
        entry["recommended"] = entry["name"] == recommended
    return result


def recommend_model_name() -> str:
    return recommended_model()


def recommended_model() -> str:
    info = hardware.detect()
    ram = info.total_ram_gb or 8.0
    if info.cuda_available:
        candidates = ["large-v3-turbo", "small", "base"] if ram >= 12 else ["small", "base", "tiny"]
    elif ram >= 12:
        candidates = ["small", "base", "small.en", "base.en", "tiny"]
    elif ram >= 6:
        candidates = ["base", "base.en", "tiny"]
    else:
        candidates = ["tiny", "tiny.en"]

    # Prefer a model that is already downloaded to avoid a large surprise download.
    for name in candidates:
        if is_downloaded(name):
            return name
    return candidates[0]


def memory_warning(name: str, total_ram_gb: float) -> str | None:
    spec = get_spec(name)
    if not spec or not total_ram_gb:
        return None
    estimated = spec.approx_memory_gb
    if total_ram_gb < estimated * 1.3:
        return (
            f"The {spec.label} model may need more memory than this machine has "
            f"({total_ram_gb:.0f} GB total). Consider a smaller model."
        )
    return None


def verify_models_importable() -> list[str]:
    """Return the catalog intersected with models this Whisper build supports."""
    try:
        import whisper

        available = set(whisper.available_models())
    except Exception:
        return [spec.name for spec in CATALOG]
    return [spec.name for spec in CATALOG if spec.name in available]
