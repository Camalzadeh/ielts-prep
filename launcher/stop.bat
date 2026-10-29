@echo off
rem Stop the IELTS Prep server (the process listening on port 8765, plus its venv launcher parent).
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $p = Get-CimInstance Win32_Process -Filter \"ProcessId=$($_.OwningProcess)\"; Stop-Process -Id $_.OwningProcess -Force; if ($p) { Stop-Process -Id $p.ParentProcessId -Force -ErrorAction SilentlyContinue } }"
