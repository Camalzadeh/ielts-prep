"""Speaking questions, sessions and recorded responses."""
from __future__ import annotations

import random
import re
import shutil
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import db, transcribe
from ..context import latest_ai_band, STOPWORDS

router = APIRouter(prefix="/api/speaking", tags=["speaking"])

FIRST_TOPICS = ("work", "study", "studies", "work or study", "hometown", "home", "accommodation",
                "your home", "where you live")
MIME_EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/x-wav": "wav",
            "audio/wave": "wav", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
            "audio/aac": "aac", "audio/flac": "flac", "video/webm": "webm"}


def question_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["cue_points"] = db.loads(d.pop("cue_points_json"), [])
    d["follow_up"] = db.loads(d.pop("follow_up_json"), [])
    return d


@router.get("/questions")
def list_questions(part: Optional[int] = None, topic: Optional[str] = None, q: Optional[str] = None,
                   season: Optional[str] = None, limit: int = 2000,
                   conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    sql = ("SELECT sq.*, (SELECT COUNT(*) FROM speaking_responses r WHERE r.question_id = sq.id) AS answered "
           "FROM speaking_questions sq WHERE 1=1")
    args: list[Any] = []
    if part:
        sql += " AND sq.part = ?"
        args.append(part)
    if topic:
        sql += " AND sq.topic = ?"
        args.append(topic)
    if season:
        sql += " AND sq.season = ?"
        args.append(season)
    if q:
        sql += " AND (sq.question LIKE ? OR sq.topic LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY sq.part, sq.topic, sq.id LIMIT ?"
    args.append(max(1, min(limit, 10000)))
    return [question_dict(r) for r in conn.execute(sql, args)]


@router.get("/topics")
def list_topics(part: Optional[int] = None, conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    sql = ("SELECT part, topic, COUNT(*) AS questions, MAX(season) AS season FROM speaking_questions "
           + ("WHERE part = ? " if part else "") + "GROUP BY part, topic ORDER BY part, topic")
    return db.rows_to_dicts(conn.execute(sql, (part,) if part else ()).fetchall())


# --------------------------------------------------------------------------- random set
def _stem(w: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


def _words(s: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]+", (s or "").lower())
            if w not in STOPWORDS and w not in ("describe", "people", "like") and len(w) > 2}


def _questions(conn: sqlite3.Connection, part: int) -> list[dict]:
    rows = conn.execute("SELECT sq.*, (SELECT COUNT(*) FROM speaking_responses r WHERE r.question_id=sq.id) AS answered "
                        "FROM speaking_questions sq WHERE part=?", (part,)).fetchall()
    return [question_dict(r) for r in rows]


def _prefer_fresh(items: list[dict]) -> list[dict]:
    fresh = [q for q in items if not q.get("answered")]
    return fresh or items


def build_random_set(conn: sqlite3.Connection, mode: str = "full") -> dict:
    out: dict[str, Any] = {"mode": mode, "part1": [], "part2": None, "part3": []}
    if mode in ("full", "part1", "mock"):
        qs = _questions(conn, 1)
        by_topic: dict[str, list[dict]] = {}
        for q in qs:
            by_topic.setdefault(q["topic"], []).append(q)
        topics = list(by_topic)
        random.shuffle(topics)
        topics.sort(key=lambda t: all(q.get("answered") for q in by_topic[t]))  # unanswered topics first
        first = [t for t in topics if t.lower() in FIRST_TOPICS]
        chosen = ([first[0]] if first else []) + [t for t in topics if not first or t != first[0]]
        for t in chosen[:3]:
            items = by_topic[t][:]
            random.shuffle(items)
            items.sort(key=lambda q: bool(q.get("answered")))
            out["part1"] += sorted(items[:random.choice((3, 4))], key=lambda q: q["id"])
    if mode in ("full", "part2", "part3", "mock"):
        p2 = _questions(conn, 2)
        if p2:
            out["part2"] = random.choice(_prefer_fresh(p2))
    if mode in ("full", "part3", "mock"):
        p3 = _questions(conn, 3)
        if p3:
            groups: dict[str, list[dict]] = {}
            for q in p3:
                groups.setdefault(q["topic"], []).append(q)
            best = None
            if out["part2"]:
                key = _words(out["part2"]["topic"] + " " + out["part2"]["question"])
                scored = sorted(((len(key & _words(t + " " + " ".join(q["question"] for q in g))), random.random(), t)
                                 for t, g in groups.items()), reverse=True)
                if scored and scored[0][0] > 0:
                    best = scored[0][2]
                exact = [t for t in groups if t.lower() == (out["part2"]["topic"] or "").lower()]
                if exact:
                    best = exact[0]
            if best is None:
                best = random.choice(list(groups))
            items = groups[best][:]
            random.shuffle(items)
            out["part3"] = items[:5]
        if mode == "part3":
            out["part2"] = out["part2"] if out["part3"] else None
    return out


@router.get("/random-set")
def random_set(mode: str = "full", conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    if mode not in ("full", "part1", "part2", "part3", "mock"):
        raise HTTPException(422, "mode must be full|part1|part2|part3")
    return build_random_set(conn, mode)


# --------------------------------------------------------------------------- sessions
class SessionCreate(BaseModel):
    mode: str = "full"
    plan: Optional[Any] = None
    mock_id: Optional[int] = None


@router.post("/sessions")
def create_session(body: SessionCreate, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    if body.mock_id is not None and not conn.execute("SELECT 1 FROM mock_exams WHERE id=?", (body.mock_id,)).fetchone():
        raise HTTPException(404, "mock not found")
    cur = conn.execute("INSERT INTO speaking_sessions(mock_id, created_at, plan_json, mode) VALUES (?,?,?,?)",
                       (body.mock_id, db.now_iso(), db.dumps(body.plan), "mock" if body.mock_id else body.mode))
    return {"id": cur.lastrowid}


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    cur = conn.execute("UPDATE speaking_sessions SET finished_at=COALESCE(finished_at, ?) WHERE id=?",
                       (db.now_iso(), session_id))
    if not cur.rowcount:
        raise HTTPException(404, "session not found")
    return {"ok": True}


@router.get("/sessions")
def list_sessions(limit: int = 100, conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    rows = conn.execute(
        "SELECT s.id, s.mock_id, s.created_at, s.finished_at, s.mode, s.teacher_band, s.notes, "
        "(SELECT COUNT(*) FROM speaking_responses r WHERE r.session_id=s.id) AS responses "
        "FROM speaking_sessions s ORDER BY s.id DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["band"] = latest_ai_band(conn, "speaking_session", d["id"])
        out.append(d)
    return out


def response_dict(row: sqlite3.Row, full: bool = False) -> dict:
    d = dict(row)
    d["audio_url"] = "/media/uploads/" + d["audio_path"] if d.get("audio_path") else None
    d["metrics"] = db.loads(d.pop("metrics_json"))
    whisper = db.loads(d.pop("whisper_json"))
    if full:
        d["whisper"] = whisper
    elif isinstance(whisper, dict) and whisper.get("error"):
        d["transcribe_error"] = whisper["error"]
    return d


@router.get("/sessions/{session_id}")
def get_session(session_id: int, full: bool = False, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    s = conn.execute("SELECT * FROM speaking_sessions WHERE id=?", (session_id,)).fetchone()
    if not s:
        raise HTTPException(404, "session not found")
    d = dict(s)
    d["plan"] = db.loads(d.pop("plan_json"))
    d["responses"] = [response_dict(r, full) for r in conn.execute(
        "SELECT * FROM speaking_responses WHERE session_id=? ORDER BY id", (session_id,))]
    d["band"] = latest_ai_band(conn, "speaking_session", session_id)
    return d


# --------------------------------------------------------------------------- responses
def _ext(upload: UploadFile | None) -> str:
    if upload is None:
        return "webm"
    name = upload.filename or ""
    m = re.search(r"\.([A-Za-z0-9]{2,5})$", name)
    if m:
        return m.group(1).lower()
    mime = (upload.content_type or "").split(";")[0].strip().lower()
    return MIME_EXT.get(mime, "webm")


@router.post("/responses")
def create_response(session_id: int = Form(...), part: int = Form(...), question_text: str = Form(""),
                    question_id: Optional[str] = Form(None), duration_sec: Optional[float] = Form(None),
                    browser_transcript: Optional[str] = Form(None), audio: Optional[UploadFile] = File(None),
                    conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    if not conn.execute("SELECT 1 FROM speaking_sessions WHERE id=?", (session_id,)).fetchone():
        raise HTTPException(404, "session not found")
    qid = int(question_id) if question_id not in (None, "", "null", "undefined") else None
    if qid is not None and not conn.execute("SELECT 1 FROM speaking_questions WHERE id=?", (qid,)).fetchone():
        qid = None
    mime = audio.content_type if audio else None
    cur = conn.execute(
        "INSERT INTO speaking_responses(session_id, question_id, part, question_text, duration_sec, mime, "
        "transcript, browser_transcript, transcribe_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (session_id, qid, part, question_text, duration_sec, mime, browser_transcript, browser_transcript,
         "pending" if audio else "unavailable", db.now_iso()))
    rid = cur.lastrowid
    status = "unavailable"
    if audio is not None:
        rel = f"speaking/{session_id}/{rid}.{_ext(audio)}"
        dest = db.UPLOADS_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            shutil.copyfileobj(audio.file, f)
        conn.execute("UPDATE speaking_responses SET audio_path=? WHERE id=?", (rel, rid))
        status = "pending"
    else:
        conn.execute("UPDATE speaking_responses SET metrics_json=? WHERE id=?",
                     (db.dumps(transcribe.text_metrics(browser_transcript, duration_sec)), rid))
    conn.commit()
    if status == "pending":
        transcribe.enqueue(rid)
    return {"id": rid, "transcribe_status": status}


@router.get("/responses/{response_id}")
def get_response(response_id: int, full: bool = False, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    r = conn.execute("SELECT * FROM speaking_responses WHERE id=?", (response_id,)).fetchone()
    if not r:
        raise HTTPException(404, "response not found")
    return response_dict(r, full)


@router.post("/responses/{response_id}/retranscribe")
def retranscribe(response_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    r = conn.execute("SELECT audio_path FROM speaking_responses WHERE id=?", (response_id,)).fetchone()
    if not r:
        raise HTTPException(404, "response not found")
    if not r["audio_path"]:
        raise HTTPException(409, "no audio stored for this response")
    conn.execute("UPDATE speaking_responses SET transcribe_status='pending' WHERE id=?", (response_id,))
    conn.commit()
    transcribe.enqueue(response_id)
    return {"id": response_id, "transcribe_status": "pending"}


@router.delete("/responses/{response_id}")
def delete_response(response_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    """Delete one recorded answer (a re-recorded or unwanted take) and its audio file."""
    r = conn.execute("SELECT audio_path FROM speaking_responses WHERE id=?", (response_id,)).fetchone()
    if not r:
        raise HTTPException(404, "response not found")
    conn.execute("DELETE FROM speaking_responses WHERE id=?", (response_id,))
    conn.commit()
    if r["audio_path"]:
        try:
            (db.UPLOADS_DIR / r["audio_path"]).unlink(missing_ok=True)
        except OSError:
            pass  # file still locked (e.g. being transcribed); the row is gone, which is what the app shows
    return {"ok": True, "id": response_id}
