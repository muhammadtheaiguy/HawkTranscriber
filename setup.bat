@echo off
setlocal
cd /d "%~dp0"

echo.
echo   WhisperDesk setup
echo   =================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo   Python was not found on your PATH.
    echo   Install Python 3.11 or newer from https://www.python.org/downloads/
    echo   and make sure "Add python.exe to PATH" is checked.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo   Creating a virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo   Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo   Upgrading pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip

echo   Installing dependencies from requirements.txt ...
echo   (This can take several minutes and downloads PyTorch - about 200 MB.)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   Dependency installation failed. Review the messages above.
    pause
    exit /b 1
)

echo.
echo   Checking for FFmpeg ...
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo   FFmpeg was NOT found on your PATH.
    echo   WhisperDesk needs FFmpeg to read audio and video files.
    echo   Recommended:  winget install Gyan.FFmpeg
    echo   Then close and reopen this window so PATH updates.
) else (
    echo   FFmpeg found.
)

echo.
echo   Setup complete. Launch WhisperDesk with run.bat
echo.
pause
