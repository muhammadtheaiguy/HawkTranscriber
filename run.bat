@echo off
setlocal
cd /d "%~dp0"

echo.
echo   WhisperDesk - local transcription
echo   ================================
echo.

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -c "import whisper, torch, starlette, uvicorn" 2>nul
if errorlevel 1 (
    echo   Required packages are missing.
    echo   Run setup.bat first to install them, then launch this file again.
    echo.
    pause
    exit /b 1
)

"%PY%" app.py
if errorlevel 1 (
    echo.
    echo   WhisperDesk stopped with an error. Review the messages above.
    pause
)
