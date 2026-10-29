"""WhisperDesk entry point.

Starts the local web server on 127.0.0.1 and opens the browser. Everything runs
on your machine; no data leaves the computer.

Usage:
    python app.py
Environment variables:
    WHISPERDESK_PORT   Port to listen on (default: first free of 8501/8502/.../8510)
    WHISPERDESK_HOST   Bind address (default: 127.0.0.1). Use 0.0.0.0 to allow LAN access.
    WHISPERDESK_DATA   Override the data directory
    WHISPERDESK_NO_BROWSER  Set to 1 to skip opening the browser
"""

from __future__ import annotations

import multiprocessing
import os
import socket
import sys

APP_NAME = "WhisperDesk"


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _pick_port(preferred: int) -> int:
    for port in range(preferred, preferred + 10):
        if _port_available(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _check_dependencies() -> None:
    missing = []
    for module, package in (
        ("whisper", "openai-whisper"),
        ("torch", "torch"),
        ("starlette", "starlette"),
        ("uvicorn", "uvicorn"),
        ("yt_dlp", "yt-dlp"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        print(f"{APP_NAME} is missing required packages: {', '.join(missing)}")
        print("Install them with:  .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        print("or run setup.bat.")
        sys.exit(1)


def main() -> None:
    multiprocessing.freeze_support()
    _check_dependencies()

    from whisperdesk import paths
    from whisperdesk.server import create_app

    paths.ensure_directories()
    app = create_app()

    host = os.environ.get("WHISPERDESK_HOST", "127.0.0.1").strip() or "127.0.0.1"
    preferred = int(os.environ.get("WHISPERDESK_PORT", "8501") or "8501")
    port = preferred if _port_available(preferred) else _pick_port(preferred)

    display_host = "localhost" if host in {"127.0.0.1", "localhost"} else host
    url = f"http://{display_host}:{port}/"

    print()
    print(f"  {APP_NAME}  ·  local transcription")
    print(f"  ------------------------------------")
    print(f"  Open: {url}")
    print(f"  Data: {paths.DATA_DIR}")
    if host not in {"127.0.0.1", "localhost"}:
        print()
        print("  !!  Network access is ENABLED (binding to " + host + ").")
        print("      Anyone on your network who can reach this port may view")
        print("      transcripts. Only use this on a trusted network.")
    print()
    print("  Press Ctrl+C to stop.")
    print()

    if os.environ.get("WHISPERDESK_NO_BROWSER") != "1":
        import threading
        import webbrowser

        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
