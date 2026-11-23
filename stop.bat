@echo off
rem Stops the background HawkTranscriber server (and its transcription workers).
powershell -NoProfile -Command "Get-NetTCPConnection -State Listen -LocalPort 8501..8510 -ErrorAction SilentlyContinue | ForEach-Object { taskkill /F /T /PID $_.OwningProcess }"
echo HawkTranscriber stopped.
timeout /t 2 >nul
