#!/usr/bin/env bash
# One-time setup on Linux (Ubuntu/Debian): Python environment, practice tests, app-menu + desktop shortcut.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  echo "Python 3.11+ is required (Ubuntu 24.04 has 3.12): sudo apt install python3 python3-venv"; exit 1
fi
if ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
  echo "Missing venv support: sudo apt install python3-venv"; exit 1
fi
command -v ffmpeg >/dev/null || echo "NOTE: ffmpeg not found - speaking transcription needs it: sudo apt install ffmpeg"
command -v google-chrome >/dev/null || command -v chromium >/dev/null || command -v chromium-browser >/dev/null \
  || echo "NOTE: Chrome/Chromium gives the best app window (falls back to your default browser)."

[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt

echo
echo "Downloading the practice tests (about 1.2 GB with audio; this can take a while)..."
.venv/bin/python tools/fetch_content.py

chmod +x launcher/*.sh
launcher/create_shortcut.sh
echo
echo "Setup complete. Starting IELTS Prep..."
launcher/start.sh
