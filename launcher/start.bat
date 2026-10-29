@echo off
rem Start IELTS Prep (server + app window). Same as the desktop shortcut.
cd /d "%~dp0.."
start "" ".venv\Scripts\pythonw.exe" "launcher\launch.pyw"
