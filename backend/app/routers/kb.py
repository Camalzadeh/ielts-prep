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
