"""Knowledge base and vocabulary (SM-2 flashcards)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..context import kb_doc, kb_search

router = APIRouter(prefix="/api", tags=["kb"])


@router.get("/kb")
def list_kb(category: Optional[str] = None, conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    sql = "SELECT slug, title, category, tags, path FROM kb_docs"
    args: tuple = ()
    if category:
        sql += " WHERE category = ?"
        args = (category,)
    return db.rows_to_dicts(conn.execute(sql + " ORDER BY category, title", args).fetchall())


@router.get("/kb/search")
def search_kb(q: str = "", limit: int = 20, conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    try:
        return kb_search(conn, q, max(1, min(limit, 100)))
    except sqlite3.OperationalError as exc:
        raise HTTPException(422, f"bad search query: {exc}")


@router.get("/kb/{slug}")
def get_kb(slug: str, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    d = kb_doc(conn, slug)
    if not d:
        raise HTTPException(404, "document not found")
    return d


# --------------------------------------------------------------------------- vocab
@router.get("/vocab")
def list_vocab(topic: Optional[str] = None, due: int = 0, q: Optional[str] = None, limit: int = 1000,
               conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    sql = "SELECT * FROM vocab WHERE 1=1"
    args: list[Any] = []
    if topic:
        sql += " AND topic = ?"
        args.append(topic)
    if due:
        sql += " AND (due_at IS NULL OR due_at <= ?)"
        args.append(db.now_iso())
    if q:
        sql += " AND (term LIKE ? OR meaning LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY due_at IS NOT NULL, due_at, id LIMIT ?" if due else " ORDER BY topic, term LIMIT ?"
    args.append(max(1, min(limit, 20000)))
    return db.rows_to_dicts(conn.execute(sql, args).fetchall())


@router.get("/vocab/topics")
def vocab_topics(conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    return db.rows_to_dicts(conn.execute(
        "SELECT topic, COUNT(*) AS terms, SUM(CASE WHEN due_at IS NULL OR due_at <= ? THEN 1 ELSE 0 END) AS due "
        "FROM vocab GROUP BY topic ORDER BY topic", (db.now_iso(),)).fetchall())


class Review(BaseModel):
    grade: int = Field(ge=0, le=5)


def sm2(ease: float, interval: int, reps: int, grade: int) -> tuple[float, int, int]:
    if grade < 3:
        reps, interval = 0, 1
    else:
        reps += 1
        interval = 1 if reps == 1 else 6 if reps == 2 else max(1, round(interval * ease))
    ease = max(1.3, ease + 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    return round(ease, 3), interval, reps


@router.post("/vocab/{vocab_id}/review")
def review_vocab(vocab_id: int, body: Review, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    v = conn.execute("SELECT * FROM vocab WHERE id=?", (vocab_id,)).fetchone()
    if not v:
        raise HTTPException(404, "term not found")
    ease, interval, reps = sm2(v["ease"] or 2.5, v["interval_days"] or 0, v["reps"] or 0, body.grade)
    due = (datetime.now() + timedelta(days=interval)).isoformat(timespec="seconds")
    conn.execute("UPDATE vocab SET ease=?, interval_days=?, reps=?, due_at=? WHERE id=?",
                 (ease, interval, reps, due, vocab_id))
    return dict(conn.execute("SELECT * FROM vocab WHERE id=?", (vocab_id,)).fetchone())


class NewTerm(BaseModel):
    term: str = Field(..., min_length=1, max_length=200)
    meaning: str = Field("", max_length=2000)
    example: str = Field("", max_length=2000)
    topic: str = Field("My words", max_length=100)


@router.post("/vocab")
def add_vocab(body: NewTerm, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    """Add a word to the flashcards (e.g. from the translator); due immediately."""
    conn.execute("INSERT INTO vocab(term, meaning, example, topic, source) VALUES (?,?,?,?, 'translator') "
                 "ON CONFLICT(term, topic) DO UPDATE SET meaning=excluded.meaning, example=excluded.example",
                 (body.term.strip(), body.meaning.strip(), body.example.strip(), body.topic.strip() or "My words"))
    return dict(conn.execute("SELECT * FROM vocab WHERE term=? AND topic=?",
                             (body.term.strip(), body.topic.strip() or "My words")).fetchone())


# --------------------------------------------------------------------------- phrase bank & tactics
_json_cache: dict[str, tuple[float, Any]] = {}


def _data_file(name: str) -> Any:
    """Read knowledge/data/<name> (cached until the file changes); [] if missing."""
    path = db.KNOWLEDGE_DIR / "data" / name
    if not path.is_file():
        return []
    mtime = path.stat().st_mtime
    hit = _json_cache.get(name)
    if not hit or hit[0] != mtime:
        import json
        _json_cache[name] = (mtime, json.loads(path.read_text(encoding="utf-8-sig")))
    return _json_cache[name][1]


@router.get("/phrases")
def phrases(skill: str) -> list[dict]:
    """Useful language for writing1 | writing2 | speaking."""
    if skill not in ("writing1", "writing2", "speaking"):
        raise HTTPException(422, "skill must be writing1, writing2 or speaking")
    return _data_file(f"phrases.{skill}.json")


@router.get("/cheatsheets")
def cheatsheets(skill: str) -> list[dict]:
    """The teacher's word tables (verb/noun, adjective/adverb, linkers...) for one skill."""
    if skill not in ("writing1", "writing2", "speaking", "listening", "reading"):
        raise HTTPException(422, "skill must be writing1, writing2, speaking, listening or reading")
    return [t for t in _data_file("cheatsheets.json") if t.get("skill") == skill]


@router.get("/tactics")
def tactics(skill: str, type: Optional[str] = None) -> list[dict]:
    """How to approach each question/task type for reading | listening | speaking | writing."""
    if skill not in ("reading", "listening", "speaking", "writing"):
        raise HTTPException(422, "skill must be reading, listening, speaking or writing")
    cards = _data_file(f"tactics.{skill}.json")
    return [c for c in cards if c.get("type") == type] if type else cards


@router.get("/speaking/topic-vocab")
def topic_vocab(topic: str) -> dict:
    """Vocabulary for a speaking topic (matched on topic name or aliases, loosely)."""
    want = {w for w in topic.lower().replace("/", " ").replace(",", " ").split() if len(w) > 2}
    best, score = None, 0
    for entry in _data_file("speaking_topic_vocab.json"):
        names = [entry.get("topic", "")] + list(entry.get("aliases") or [])
        for name in names:
            words = {w for w in name.lower().replace("/", " ").replace(",", " ").split() if len(w) > 2}
            s = len(want & words) / (len(words) or 1) + (1 if name.lower() == topic.lower() else 0)
            if s > score:
                best, score = entry, s
    return best if best and score >= 0.5 else {"topic": topic, "words": []}
