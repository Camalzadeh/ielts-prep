"""Writing prompts and submissions."""
from __future__ import annotations

import random
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..context import latest_ai_band
from ..importer import word_count

router = APIRouter(prefix="/api/writing", tags=["writing"])

PROMPT_COLS = ("p.id, p.task, p.module, p.essay_type, p.prompt, p.image_path, p.image_description, p.source, "
               "p.source_date, p.tags, (SELECT COUNT(*) FROM writing_submissions s WHERE s.prompt_id=p.id) AS submissions")


def prompt_dict(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["image_url"] = db.media_url(d.get("image_path"))
    return d


@router.get("/prompts")
def list_prompts(task: Optional[int] = None, essay_type: Optional[str] = None, q: Optional[str] = None,
                 module: Optional[str] = None, limit: int = 500,
                 conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    sql = f"SELECT {PROMPT_COLS} FROM writing_prompts p WHERE 1=1"
    args: list[Any] = []
    if task:
        sql += " AND p.task = ?"
        args.append(task)
    if essay_type:
        sql += " AND p.essay_type = ?"
        args.append(essay_type)
    if module:
        sql += " AND p.module = ?"
        args.append(module)
    if q:
        sql += " AND (p.prompt LIKE ? OR p.tags LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY p.source_date IS NULL, p.source_date DESC, p.id DESC LIMIT ?"
    args.append(max(1, min(limit, 5000)))
    return [prompt_dict(r) for r in conn.execute(sql, args)]


def pick_random_prompt(conn: sqlite3.Connection, task: int | None, module: str | None = None) -> dict | None:
    sql = f"SELECT {PROMPT_COLS} FROM writing_prompts p WHERE 1=1"
    args: list[Any] = []
    if task:
        sql += " AND p.task = ?"
        args.append(task)
    if module:
        sql += " AND (p.module = ? OR p.module IS NULL)"
        args.append(module)
    rows = conn.execute(sql, args).fetchall()
    if not rows:
        return None
    fresh = [r for r in rows if not r["submissions"]]
    return prompt_dict(random.choice(fresh or rows))


@router.get("/prompts/random")
def random_prompt(task: Optional[int] = None, module: Optional[str] = None,
                  conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    p = pick_random_prompt(conn, task, module)
    if not p:
        raise HTTPException(404, "no writing prompts available")
    return p


@router.get("/prompts/{prompt_id}")
def get_prompt(prompt_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    row = conn.execute(f"SELECT {PROMPT_COLS} FROM writing_prompts p WHERE p.id=?", (prompt_id,)).fetchone()
    if not row:
        raise HTTPException(404, "prompt not found")
    return prompt_dict(row)


class PromptCreate(BaseModel):
    task: int
    prompt: str
    essay_type: Optional[str] = None
    module: Optional[str] = "academic"
    image_path: Optional[str] = None
    image_description: Optional[str] = None
    tags: Optional[str] = None
    source: Optional[str] = "user"


@router.post("/prompts")
def create_prompt(body: PromptCreate, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    text = body.prompt.strip()
    if body.task not in (1, 2) or not text:
        raise HTTPException(422, "task must be 1 or 2 and prompt non-empty")
    existing = conn.execute("SELECT id FROM writing_prompts WHERE prompt=?", (text,)).fetchone()
    if existing:
        return {"id": existing[0], "existing": True}
    cur = conn.execute(
        "INSERT INTO writing_prompts(task, module, essay_type, prompt, image_path, image_description, source, "
        "source_date, tags) VALUES (?,?,?,?,?,?,?,?,?)",
        (body.task, body.module, body.essay_type, text, body.image_path, body.image_description, body.source,
         db.now_iso()[:10], body.tags))
    return {"id": cur.lastrowid, "existing": False}


class SubmissionCreate(BaseModel):
    prompt_id: int
    text: str
    time_spent_sec: Optional[int] = None
    mock_id: Optional[int] = None


@router.post("/submissions")
def create_submission(body: SubmissionCreate, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    if not conn.execute("SELECT 1 FROM writing_prompts WHERE id=?", (body.prompt_id,)).fetchone():
        raise HTTPException(404, "prompt not found")
    if body.mock_id is not None and not conn.execute("SELECT 1 FROM mock_exams WHERE id=?", (body.mock_id,)).fetchone():
        raise HTTPException(404, "mock not found")
    wc = word_count(body.text)
    cur = conn.execute(
        "INSERT INTO writing_submissions(prompt_id, mock_id, text, word_count, time_spent_sec, created_at, origin) "
        "VALUES (?,?,?,?,?,?, 'app')",
        (body.prompt_id, body.mock_id, body.text, wc, body.time_spent_sec, db.now_iso()))
    return {"id": cur.lastrowid, "word_count": wc}


@router.delete("/submissions/{submission_id}")
def delete_submission(submission_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    """Delete an essay written in the app, with its AI analyses."""
    s = conn.execute("SELECT origin, mock_id FROM writing_submissions WHERE id=?", (submission_id,)).fetchone()
    if not s:
        raise HTTPException(404, "submission not found")
    if s["origin"] == "telegram_import":
        raise HTTPException(409, "this essay was imported from the course chat and would come back on the next import")
    db.forget_result(conn, "writing", submission_id, s["mock_id"], "writing")
    conn.execute("DELETE FROM writing_submissions WHERE id=?", (submission_id,))
    return {"ok": True, "id": submission_id}


@router.get("/submissions")
def list_submissions(task: Optional[int] = None, origin: Optional[str] = None, limit: int = 200,
                     conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    sql = ("SELECT s.id, s.prompt_id, s.mock_id, s.word_count, s.time_spent_sec, s.created_at, s.origin, "
           "s.teacher_band, "
           "p.task, p.essay_type, substr(p.prompt, 1, 200) AS prompt_excerpt FROM writing_submissions s "
           "LEFT JOIN writing_prompts p ON p.id = s.prompt_id WHERE 1=1")
    args: list[Any] = []
    if task:
        sql += " AND p.task = ?"
        args.append(task)
    if origin:
        sql += " AND s.origin = ?"
        args.append(origin)
    sql += " ORDER BY s.created_at DESC, s.id DESC LIMIT ?"
    args.append(max(1, min(limit, 5000)))
    out = []
    for r in conn.execute(sql, args).fetchall():
        d = dict(r)
        d["band"] = latest_ai_band(conn, "writing", d["id"])
        out.append(d)
    return out


@router.get("/submissions/{submission_id}")
def get_submission(submission_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    s = conn.execute("SELECT * FROM writing_submissions WHERE id=?", (submission_id,)).fetchone()
    if not s:
        raise HTTPException(404, "submission not found")
    d = dict(s)
    p = conn.execute(f"SELECT {PROMPT_COLS} FROM writing_prompts p WHERE p.id=?", (s["prompt_id"],)).fetchone()
    d["prompt"] = prompt_dict(p)
    d["band"] = latest_ai_band(conn, "writing", submission_id)
    d["analyses"] = [dict(r) for r in conn.execute(
        "SELECT id, provider, status, created_at, finished_at FROM ai_analyses WHERE target_type='writing' "
        "AND target_id=? ORDER BY id DESC", (submission_id,))]
    return d
