"""Analyse every past item that has no AI analysis yet, then date each analysis to its item.

Items: submitted attempts (incl. band-only imported ones), chat-imported essays, imported speaking
results; finally one overall progress analysis. Analyses are queued through the running server
(sequential worker) with the provider chosen in Settings unless --provider is given. When all are done,
each analysis is dated to its item's date (= when the teacher posted the task).

Usage: .venv\\Scripts\\python.exe tools\\backfill_analyses.py [--provider claude|codex|antigravity]
"""
import argparse
import sqlite3
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "ielts.db"
API = "http://127.0.0.1:8765/api"

ITEMS = {  # target_type -> SQL returning (id, date) of items to analyse
    "attempt": "SELECT id, finished_at FROM attempts WHERE status = 'submitted' AND finished_at < '2026-10-01'",
    "writing": "SELECT id, created_at FROM writing_submissions WHERE origin = 'telegram_import'",
    "speaking_session": "SELECT id, created_at FROM speaking_sessions WHERE mode = 'imported'",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider")
    args = ap.parse_args()
    http = httpx.Client(timeout=60)
    provider = args.provider or http.get(f"{API}/settings").json().get("ai_provider") or "claude"
    conn = sqlite3.connect(DB)
    started = time.strftime("%Y-%m-%d")
    # resumable: anything done, queued or running already counts as handled
    handled = {(t, i) for t, i in conn.execute(
        "SELECT target_type, target_id FROM ai_analyses WHERE status IN ('done', 'queued', 'running')")}
    queued = 0
    for ttype, sql in ITEMS.items():
        for item_id, _ in conn.execute(sql).fetchall():
            if (ttype, item_id) not in handled:
                http.post(f"{API}/ai/analyze", json={"target_type": ttype, "target_id": item_id, "provider": provider})
                queued += 1
    print(f"queued {queued} new analyses with {provider}", flush=True)

    while True:
        left = conn.execute("SELECT COUNT(*) FROM ai_analyses WHERE status IN ('queued', 'running')").fetchone()[0]
        print(f"{left} analyses still queued/running", flush=True)
        if not left:
            break
        time.sleep(20)

    # date each analysis made by this backfill to its item (= when the teacher posted the task)
    for ttype, sql in ITEMS.items():
        for item_id, date in conn.execute(sql).fetchall():
            conn.execute("UPDATE ai_analyses SET created_at = ?, started_at = ?, finished_at = ? WHERE target_type = ? "
                         "AND target_id = ? AND status = 'done' AND created_at >= ?",
                         (date, date, date, ttype, item_id, started))
    conn.commit()
    errors = conn.execute("SELECT id, target_type, target_id, error FROM ai_analyses WHERE status = 'error' "
                          "AND created_at >= ?", (started,)).fetchall()
    print("errors:", errors)

    # one overall progress analysis over the whole history, last
    r = http.post(f"{API}/ai/analyze", json={"target_type": "progress", "target_id": 0, "provider": provider,
                                             "force": True}).json()
    while http.get(f"{API}/ai/analyses/{r['id']}").json()["status"] not in ("done", "error"):
        time.sleep(10)
    print("progress analysis:", http.get(f"{API}/ai/analyses/{r['id']}").json()["status"])


if __name__ == "__main__":
    main()
