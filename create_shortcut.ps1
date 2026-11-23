# Creates a "HawkTranscriber" shortcut on the Desktop that starts the app with no console window.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { Write-Host "Run setup.bat first (.venv not found)."; exit 1 }
$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "HawkTranscriber.lnk"
$sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$sc.TargetPath = $py
$sc.Arguments = "app.py"
$sc.WorkingDirectory = $root
$sc.Description = "HawkTranscriber - local transcription"
$sc.Save()
Write-Host "Shortcut created: $lnk"
