#!/usr/bin/env bash
# Stop the IELTS Prep server (the process listening on port 8765).
pid=$(lsof -t -iTCP:8765 -sTCP:LISTEN 2>/dev/null || fuser 8765/tcp 2>/dev/null)
[ -n "$pid" ] && kill $pid && echo "stopped" || echo "server not running"
