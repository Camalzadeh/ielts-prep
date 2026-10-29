#!/usr/bin/env bash
# Download (or finish downloading) the practice tests. Safe to run again any time - it resumes.
#   ./get_tests.sh              everything incl. listening audio (~1.2 GB)
#   ./get_tests.sh --no-audio   tests only; audio streams from the internet while you practise
cd "$(dirname "$(readlink -f "$0")")"
[ -x .venv/bin/python ] || { echo "Run ./setup.sh first."; exit 1; }
.venv/bin/python tools/fetch_content.py "$@"
