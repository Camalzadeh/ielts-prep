"""Dashboard statistics."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends

from .. import db
from ..context import type_accuracy

router = APIRouter(prefix="/api", tags=["stats"])


def _ai_bands(conn: sqlite3.Connection, target_type: str) -> list[dict]:
    """Latest done analysis band per target, dated by the analysed item."""
    date_sql = {"writing": "SELECT created_at FROM writing_submissions WHERE id = a.target_id",
                "speaking_session": "SELECT created_at FROM speaking_sessions WHERE id = a.target_id"}[target_type]
    rows = conn.execute(
        f"""SELECT a.target_id, a.result_json, ({date_sql}) AS item_date FROM ai_analyses a
            WHERE a.target_type=? AND a.status='done' AND a.result_json IS NOT NULL ORDER BY a.id""",
        (target_type,)).fetchall()
    latest: dict[int, dict] = {}
    for r in rows:
        data = db.loads(r["result_json"], {}) or {}
        band = data.get("band") if isinstance(data, dict) else None
        try:
            band = float(band)
        except (TypeError, ValueError):
            continue
        latest[r["target_id"]] = {"date": (r["item_date"] or "")[:10], "band": band, "id": r["target_id"]}
    return sorted(latest.values(), key=lambda x: x["date"])


def _activity_days(conn: sqlite3.Connection) -> set[str]:
    days: set[str] = set()
    for sql in ("SELECT DISTINCT substr(COALESCE(finished_at, started_at),1,10) FROM attempts",
                "SELECT DISTINCT substr(created_at,1,10) FROM writing_submissions WHERE origin='app'",
                "SELECT DISTINCT substr(created_at,1,10) FROM speaking_responses",
                "SELECT DISTINCT substr(created_at,1,10) FROM mock_exams"):
        days.update(r[0] for r in conn.execute(sql) if r[0])
    return days


def streak(days: set[str]) -> int:
    d = date.today()
    if d.isoformat() not in days:
        d -= timedelta(days=1)  # streak still alive if yesterday was active
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


@router.get("/stats")
def stats(conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    bands: dict[str, list] = {}
    for t in ("listening", "reading"):
        bands[t] = [{"date": (r["finished_at"] or "")[:10], "band": r["band"], "id": r["id"],
                     "test_id": r["test_id"], "mode": r["mode"]}
                    for r in conn.execute("SELECT id, test_id, finished_at, band, mode FROM attempts WHERE type=? "
                                          "AND status='submitted' AND band IS NOT NULL ORDER BY finished_at", (t,))]
    writing = {p["id"]: {**p, "source": "ai"} for p in _ai_bands(conn, "writing")}
    for r in conn.execute("SELECT id, created_at, teacher_band FROM writing_submissions WHERE teacher_band IS NOT NULL"):
        writing.setdefault(r["id"], {"date": (r["created_at"] or "")[:10], "band": r["teacher_band"],
                                     "id": r["id"], "source": "teacher"})
    bands["writing"] = sorted(writing.values(), key=lambda x: x["date"])
    speaking = {p["id"]: {**p, "source": "ai"} for p in _ai_bands(conn, "speaking_session")}
    for r in conn.execute("SELECT id, created_at, teacher_band FROM speaking_sessions WHERE teacher_band IS NOT NULL"):
        speaking.setdefault(r["id"], {"date": (r["created_at"] or "")[:10], "band": r["teacher_band"],
                                      "id": r["id"], "source": "teacher"})
    bands["speaking"] = sorted(speaking.values(), key=lambda x: x["date"])
    bands["overall"] = [{"date": (r["finished_at"] or "")[:10], "band": r["overall_band"], "id": r["id"]}
                        for r in conn.execute("SELECT id, finished_at, overall_band FROM mock_exams "
                                              "WHERE status='finished' AND overall_band IS NOT NULL ORDER BY finished_at")]

    by_type = []
    for t in ("listening", "reading"):
        by_type += [{"type": r["type"], "skill": t, "correct": r["correct"], "total": r["total"]}
                    for r in type_accuracy(conn, t)]

    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    counts = {
        "listening_attempts": one("SELECT COUNT(*) FROM attempts WHERE type='listening' AND status='submitted'"),
        "reading_attempts": one("SELECT COUNT(*) FROM attempts WHERE type='reading' AND status='submitted'"),
        "writing_submissions": one("SELECT COUNT(*) FROM writing_submissions"),
        "writing_submissions_app": one("SELECT COUNT(*) FROM writing_submissions WHERE origin='app'"),
        "speaking_sessions": one("SELECT COUNT(*) FROM speaking_sessions"),
        "speaking_responses": one("SELECT COUNT(*) FROM speaking_responses"),
        "mock_exams": one("SELECT COUNT(*) FROM mock_exams WHERE status='finished'"),
        "ai_analyses": one("SELECT COUNT(*) FROM ai_analyses WHERE status='done'"),
        "vocab_total": one("SELECT COUNT(*) FROM vocab"),
        "vocab_learned": one("SELECT COUNT(*) FROM vocab WHERE reps > 0"),
        "vocab_due": one("SELECT COUNT(*) FROM vocab WHERE due_at IS NULL OR due_at <= ?", db.now_iso()),
        "tests_listening": one("SELECT COUNT(*) FROM tests WHERE type='listening'"),
        "tests_reading": one("SELECT COUNT(*) FROM tests WHERE type='reading'"),
    }

    recent = []
    for r in conn.execute("SELECT a.id, a.type, a.finished_at AS at, a.band, a.raw_score, a.total, t.title FROM attempts a "
                          "LEFT JOIN tests t ON t.id=a.test_id WHERE a.status='submitted' ORDER BY a.finished_at DESC LIMIT 10"):
        score = f"{r['raw_score']}/{r['total']}" if r["raw_score"] is not None else "band only"
        recent.append({"kind": r["type"], "id": r["id"], "at": r["at"], "band": r["band"],
                       "title": f"{r['title']} — {score}"})
    for r in conn.execute("SELECT s.id, s.created_at AS at, p.task FROM writing_submissions s LEFT JOIN writing_prompts p "
                          "ON p.id=s.prompt_id WHERE s.origin='app' ORDER BY s.created_at DESC LIMIT 10"):
        recent.append({"kind": "writing", "id": r["id"], "at": r["at"], "band": None,
                       "title": f"Writing Task {r['task']}"})
    for r in conn.execute("SELECT id, created_at AS at, mode, teacher_band, notes FROM speaking_sessions "
                          "ORDER BY id DESC LIMIT 10"):
        recent.append({"kind": "speaking", "id": r["id"], "at": r["at"], "band": r["teacher_band"],
                       "title": f"Speaking — {r['notes']}" if r["notes"] else f"Speaking ({r['mode']})"})
    for r in conn.execute("SELECT id, COALESCE(finished_at, created_at) AS at, overall_band FROM mock_exams "
                          "ORDER BY id DESC LIMIT 5"):
        recent.append({"kind": "mock", "id": r["id"], "at": r["at"], "band": r["overall_band"], "title": "Mock exam"})
    recent.sort(key=lambda x: x["at"] or "", reverse=True)

    external = db.rows_to_dicts(conn.execute(
        "SELECT id, date, person, listening, reading, writing, speaking, overall, notes, photo FROM external_results "
        "WHERE is_mine = 1 ORDER BY date").fetchall())
    full = [e for e in external if e["overall"] is not None]
    baseline = full[0] if full else (external[0] if external else None)

    return {"bands_over_time": bands, "by_question_type": by_type, "counts": counts,
            "streak_days": streak(_activity_days(conn)), "recent": recent[:15],
            "external_results": external, "baseline": baseline}
