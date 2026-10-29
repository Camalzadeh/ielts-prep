#!/usr/bin/env bash
# Start IELTS Prep (server + app window). Same as the desktop shortcut.
cd "$(dirname "$(readlink -f "$0")")/.."
nohup .venv/bin/python launcher/launch.pyw >/dev/null 2>&1 &
