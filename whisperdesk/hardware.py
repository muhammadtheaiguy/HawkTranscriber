"""Hardware and dependency detection used for model recommendations."""

from __future__ import annotations

import functools
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from . import paths


@dataclass
class HardwareInfo:
    device: str = "cpu"
    device_label: str = "CPU"
    cpu_count: int = 0
    total_ram_gb: float = 0.0
    available_ram_gb: float = 0.0
    torch_version: str = "unknown"
    whisper_version: str = "unknown"
    python_version: str = ""
    platform: str = ""
    cuda_available: bool = False
    cuda_device: str | None = None
    ffmpeg_path: str | None = None
    ffmpeg_available: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "deviceLabel": self.device_label,
            "cpuCount": self.cpu_count,
            "totalRamGb": round(self.total_ram_gb, 1),
            "availableRamGb": round(self.available_ram_gb, 1),
            "torchVersion": self.torch_version,
            "whisperVersion": self.whisper_version,
            "pythonVersion": self.python_version,
            "platform": self.platform,
            "cudaAvailable": self.cuda_available,
            "cudaDevice": self.cuda_device,
            "ffmpegPath": self.ffmpeg_path,
            "ffmpegAvailable": self.ffmpeg_available,
            "warnings": self.warnings,
        }


def _total_ram_gb() -> float:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullTotalPhys / (1024**3), stat.ullAvailPhys / (1024**3)
    except Exception:
        return 0.0, 0.0


@functools.lru_cache(maxsize=1)
def detect() -> HardwareInfo:
    info = HardwareInfo()
    info.cpu_count = os_cpu_count()
    info.python_version = platform.python_version()
    info.platform = f"{platform.system()} {platform.release()}"

    total, avail = _total_ram_gb()
    info.total_ram_gb = total
    info.available_ram_gb = avail

    try:
        import torch

        info.torch_version = torch.__version__
        info.cuda_available = bool(torch.cuda.is_available())
        if info.cuda_available:
            info.cuda_device = torch.cuda.get_device_name(0)
            info.device = "cuda"
            info.device_label = f"GPU · {info.cuda_device}"
        else:
            info.device_label = f"CPU · {info.cpu_count} cores"
    except Exception as exc:  # pragma: no cover - torch must be installed
        info.warnings.append(f"PyTorch could not be loaded: {exc}")

    try:
        import whisper

        info.whisper_version = getattr(whisper, "__version__", "unknown")
    except Exception as exc:  # pragma: no cover
        info.warnings.append(f"Whisper could not be loaded: {exc}")

    ffmpeg = os_which("ffmpeg")
    info.ffmpeg_path = ffmpeg
    info.ffmpeg_available = bool(ffmpeg)
    if not ffmpeg:
        info.warnings.append(
            "FFmpeg was not found on PATH. Audio and video decoding will fail. "
            "Install FFmpeg and make sure 'ffmpeg' runs from a terminal."
        )

    if info.total_ram_gb and info.total_ram_gb < 8:
        info.warnings.append(
            "Less than 8 GB of RAM detected. Larger models may run out of memory."
        )

    return info


def os_cpu_count() -> int:
    return __import__("os").cpu_count() or 1


@functools.lru_cache(maxsize=8)
def os_which(name: str) -> str | None:
    return shutil.which(name)


def ffmpeg_version() -> str | None:
    path = os_which("ffmpeg")
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_no_window(),
        )
        first = result.stdout.splitlines()[0] if result.stdout else ""
        return first.strip() or None
    except Exception:
        return None


def _no_window() -> int:
    import sys

    if sys.platform == "win32":
        return 0x08000000  # CREATE_NO_WINDOW
    return 0
