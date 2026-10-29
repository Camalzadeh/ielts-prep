"""Start the IELTS backend (used by the launcher): python backend/run.py [--port 8765]."""
from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("IELTS_PORT", 8765)))
    args = parser.parse_args()
    # A second instance must not run startup hooks (stale-job cleanup, import) against the live server's DB.
    with socket.socket() as s:
        if s.connect_ex((args.host, args.port)) == 0:
            sys.exit(f"port {args.port} is already in use - is the server already running?")
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import uvicorn
    uvicorn.run("backend.app.main:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
