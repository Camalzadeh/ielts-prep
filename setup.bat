@echo off
rem One-time setup on Windows: Python environment, practice tests, desktop shortcut.
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul || echo NOTE: ffmpeg not found - speaking transcription needs it: winget install Gyan.FFmpeg

if not exist .venv (
  echo Creating Python environment...
  %PY% -m venv .venv || goto :fail
)
.venv\Scripts\python.exe -m pip install --upgrade pip >nul
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :fail

echo.
echo Downloading the practice tests (about 1.2 GB with audio; this can take a while)...
.venv\Scripts\python.exe tools\fetch_content.py

powershell -NoProfile -ExecutionPolicy Bypass -File launcher\create_shortcut.ps1
echo.
echo Setup complete. Starting IELTS Prep...
start "" "launcher\start.bat"
exit /b 0

:fail
echo Setup failed - see the messages above.
pause
exit /b 1
