"""Listening / reading tests and attempts."""
from __future__ import annotations

import html
import re
import sqlite3
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..grading import grade_test, iter_questions, strip_answers

router = APIRouter(prefix="/api", tags=["tests"])


def _load_test(conn: sqlite3.Connection, test_id: str) -> tuple[sqlite3.Row, dict]:
    row = conn.execute("SELECT * FROM tests WHERE id = ?", (test_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"test {test_id} not found")
    return row, db.loads(row["data_json"], {})


def _add_media_urls(test: dict) -> dict:
    for part in test.get("parts") or []:
        audio_url = None
        if part.get("audio") and (db.CONTENT_DIR / part["audio"]).is_file():
            audio_url = db.media_url(part["audio"])
        if part.get("audio") or part.get("audio_remote"):
            part["audio_url"] = audio_url or part.get("audio_remote") or db.media_url(part.get("audio"))
        for g in part.get("groups") or []:
            if g.get("image"):
                g["image_url"] = db.media_url(g["image"])
    return test


def _has_submitted(conn: sqlite3.Connection, test_id: str) -> bool:
    return conn.execute("SELECT 1 FROM attempts WHERE test_id=? AND status='submitted' LIMIT 1",
                        (test_id,)).fetchone() is not None


@router.get("/tests")
def list_tests(type: Optional[str] = None, module: Optional[str] = None,
               conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    q = """SELECT t.id, t.type, t.module, t.title, t.series, t.book, t.test_no, t.question_count, t.source,
             (SELECT MAX(band) FROM attempts a WHERE a.test_id=t.id AND a.status='submitted') AS best_band,
             (SELECT band FROM attempts a WHERE a.test_id=t.id AND a.status='submitted'
                ORDER BY a.finished_at DESC, a.id DESC LIMIT 1) AS last_band,
             (SELECT COUNT(*) FROM attempts a WHERE a.test_id=t.id AND a.status='submitted') AS attempts,
             (SELECT id FROM attempts a WHERE a.test_id=t.id AND a.status='in_progress'
                ORDER BY a.id DESC LIMIT 1) AS in_progress_attempt
           FROM tests t WHERE 1=1"""
    args: list[Any] = []
    if type:
        q += " AND t.type = ?"
        args.append(type)
    if module:
        q += " AND t.module = ?"
        args.append(module)
    q += " ORDER BY t.series IS NULL, t.book DESC, t.series, t.test_no, t.title"
    return db.rows_to_dicts(conn.execute(q, args).fetchall())


@router.get("/tests/{test_id}")
def get_test(test_id: str, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    _, data = _load_test(conn, test_id)
    t = _add_media_urls(strip_answers(data))
    t["reviewable"] = _has_submitted(conn, test_id)
    return t


@router.get("/tests/{test_id}/review")
def review_test(test_id: str, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    _, data = _load_test(conn, test_id)
    if not _has_submitted(conn, test_id):
        raise HTTPException(403, "submit an attempt for this test before reviewing answers")
    t = _add_media_urls(data)
    t["reviewable"] = True
    return t


# --------------------------------------------------------------------------- attempts
class AttemptCreate(BaseModel):
    test_id: str
    mode: Literal["practice", "mock"] = "practice"
    mock_id: Optional[int] = None


class Autosave(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    highlights: Optional[Any] = None


class Submit(Autosave):
    duration_sec: Optional[int] = None


@router.post("/attempts")
def create_attempt(body: AttemptCreate, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    row, _ = _load_test(conn, body.test_id)
    if body.mock_id is not None and not conn.execute("SELECT 1 FROM mock_exams WHERE id=?", (body.mock_id,)).fetchone():
        raise HTTPException(404, f"mock {body.mock_id} not found")
    cur = conn.execute(
        "INSERT INTO attempts(test_id, type, mock_id, mode, started_at, status, answers_json) "
        "VALUES (?,?,?,?,?, 'in_progress', '{}')",
        (body.test_id, row["type"], body.mock_id, "mock" if body.mock_id else body.mode, db.now_iso()))
    return {"id": cur.lastrowid}


def _get_attempt(conn: sqlite3.Connection, attempt_id: int) -> sqlite3.Row:
    a = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not a:
        raise HTTPException(404, f"attempt {attempt_id} not found")
    return a


@router.put("/attempts/{attempt_id}/autosave")
def autosave(attempt_id: int, body: Autosave, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    a = _get_attempt(conn, attempt_id)
    if a["status"] != "in_progress":
        raise HTTPException(409, "attempt already submitted")
    conn.execute("UPDATE attempts SET answers_json=?, highlights_json=COALESCE(?, highlights_json) WHERE id=?",
                 (db.dumps(body.answers), db.dumps(body.highlights), attempt_id))
    return {"ok": True}


@router.post("/attempts/{attempt_id}/submit")
def submit(attempt_id: int, body: Submit, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    a = _get_attempt(conn, attempt_id)
    if a["status"] == "submitted":
        raise HTTPException(409, "attempt already submitted")
    _, test = _load_test(conn, a["test_id"])
    answers = body.answers or db.loads(a["answers_json"], {}) or {}
    result = grade_test(test, answers)
    conn.execute("DELETE FROM attempt_answers WHERE attempt_id = ?", (attempt_id,))
    conn.executemany(
        "INSERT INTO attempt_answers(attempt_id, part, question_number, question_type, user_answer, "
        "correct_answers, is_correct, question_text) VALUES (?,?,?,?,?,?,?,?)",
        [(attempt_id, d["part"], d["number"], d["type"], d["user_answer"], db.dumps(d["correct_answers"]),
          int(d["is_correct"]), d["question_text"]) for d in result["details"]])
    conn.execute(
        "UPDATE attempts SET status='submitted', finished_at=?, duration_sec=?, raw_score=?, total=?, band=?, "
        "answers_json=?, highlights_json=COALESCE(?, highlights_json) WHERE id=?",
        (db.now_iso(), body.duration_sec, result["raw_score"], result["total"], result["band"],
         db.dumps(answers), db.dumps(body.highlights), attempt_id))
    return {"id": attempt_id, **result}


@router.get("/attempts")
def list_attempts(type: Optional[str] = None, limit: int = 50, status: Optional[str] = None,
                  test_id: Optional[str] = None, conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    q = ("SELECT a.id, a.test_id, a.type, a.mock_id, a.mode, a.started_at, a.finished_at, a.duration_sec, "
         "a.status, a.raw_score, a.total, a.band, t.title, t.series, t.module FROM attempts a "
         "LEFT JOIN tests t ON t.id = a.test_id WHERE 1=1")
    args: list[Any] = []
    for col, val in (("a.type", type), ("a.status", status), ("a.test_id", test_id)):
        if val:
            q += f" AND {col} = ?"
            args.append(val)
    q += " ORDER BY COALESCE(a.finished_at, a.started_at) DESC, a.id DESC LIMIT ?"
    args.append(max(1, min(limit, 1000)))
    return db.rows_to_dicts(conn.execute(q, args).fetchall())


@router.delete("/attempts/{attempt_id}")
def delete_attempt(attempt_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    """Delete a result (or an unfinished attempt) with its answers and AI analyses."""
    a = _get_attempt(conn, attempt_id)
    if a["mode"] == "imported":
        raise HTTPException(409, "this result comes from My Results.docx; remove its row there instead")
    conn.execute("DELETE FROM ai_analyses WHERE target_type='attempt' AND target_id=?", (attempt_id,))
    conn.execute("DELETE FROM attempt_answers WHERE attempt_id=?", (attempt_id,))
    conn.execute("DELETE FROM attempts WHERE id=?", (attempt_id,))
    if a["mock_id"] and a["type"] in ("listening", "reading"):
        # the mock loses this section: its stored band (and so the overall band) no longer holds
        conn.execute(f"UPDATE mock_exams SET {a['type']}_band=NULL, overall_band=NULL WHERE id=?", (a["mock_id"],))
    return {"ok": True, "id": attempt_id}


_EXCERPT = re.compile(r"From the transcript:\s*</b>(.*?)</p>", re.IGNORECASE | re.DOTALL)


def transcript_excerpt(explanation_html: str | None) -> str | None:
    """The transcript line an explanation quotes as evidence ("From the transcript: '...'")."""
    m = _EXCERPT.search(explanation_html or "")
    if not m:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    return text.strip("\"'“”‘’ ").strip() or None


@router.get("/attempts/{attempt_id}/transcript")
def attempt_transcript(attempt_id: int, part: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    """Listening transcript of one part for the study assistant. Practice only: never in a mock exam."""
    a = _get_attempt(conn, attempt_id)
    if a["type"] != "listening":
        raise HTTPException(422, "transcripts exist for listening tests only")
    if a["mode"] == "mock" or a["mock_id"]:
        raise HTTPException(403, "the transcript is not available in exam mode")
    _, test = _load_test(conn, a["test_id"])
    p = next((p for p in test.get("parts") or [] if p.get("number") == part), None)
    if not p:
        raise HTTPException(404, f"part {part} not found")
    anchors = {q["number"]: transcript_excerpt(q.get("explanation_html"))
               for g in p.get("groups") or [] for q in g.get("questions") or [] if q.get("number") is not None}
    return {"part": part, "transcript_html": p.get("transcript_html") or "",
            "anchors": {n: t for n, t in anchors.items() if t}}


@router.get("/attempts/{attempt_id}")
def get_attempt(attempt_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    a = _get_attempt(conn, attempt_id)
    t = conn.execute("SELECT id, type, module, title, series, book, test_no, data_json FROM tests WHERE id=?",
                     (a["test_id"],)).fetchone()
    test = db.loads(t["data_json"], {}) if t else {}
    explanations = {q.get("number"): q.get("explanation_html") for _, _, q in iter_questions(test)}
    details = [{"number": r["question_number"], "part": r["part"], "type": r["question_type"],
                "user_answer": r["user_answer"], "correct_answers": db.loads(r["correct_answers"], []),
                "is_correct": bool(r["is_correct"]), "question_text": r["question_text"],
                "explanation_html": explanations.get(r["question_number"]),
                "excerpt": transcript_excerpt(explanations.get(r["question_number"]))}
               for r in conn.execute("SELECT * FROM attempt_answers WHERE attempt_id=? ORDER BY question_number",
                                     (attempt_id,))]
    out = dict(a)
    out["answers"] = db.loads(out.pop("answers_json"), {})
    out["highlights"] = db.loads(out.pop("highlights_json"))
    out["details"] = details
    out["test"] = {k: t[k] for k in ("id", "type", "module", "title", "series", "book", "test_no")} if t else None
    return out
