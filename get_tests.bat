@echo off
rem Download (or finish downloading) the practice tests. Safe to run again any time - it resumes.
rem   get_tests.bat              everything incl. listening audio (~1.2 GB)
rem   get_tests.bat --no-audio   tests only; audio streams from the internet while you practise
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe tools\fetch_content.py %*
pause
