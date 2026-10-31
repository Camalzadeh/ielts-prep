"""Full mock exams: random plan, linking section results, overall band."""
from __future__ import annotations

import random
import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..context import latest_ai_band, mock_links
from ..grading import ielts_round, overall_band
from .speaking import build_random_set
from .writing import pick_random_prompt

router = APIRouter(prefix="/api/mock", tags=["mock"])

SECTIONS = ("listening", "reading", "writing", "speaking")


class MockCreate(BaseModel):
    sections: list[str] = list(SECTIONS)
    random: bool = True
    module: str = "academic"
    listening: Optional[str] = None
    reading: Optional[str] = None


def pick_test(conn: sqlite3.Connection, ttype: str, module: str | None) -> str | None:
    rows = conn.execute(
        "SELECT t.id, t.module, (SELECT COUNT(*) FROM attempts a WHERE a.test_id=t.id) AS n FROM tests t WHERE t.type=?",
        (ttype,)).fetchall()
    if ttype == "reading":
        # only the exam's own module: an Academic mock never gets a General Training passage
        rows = [r for r in rows if (r["module"] or "academic") == (module or "academic")]
    if not rows:
        return None
    fresh = [r for r in rows if not r["n"]]
    return random.choice(fresh or rows)["id"]


@router.post("")
def create_mock(body: MockCreate, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    sections = [s for s in body.sections if s in SECTIONS] or list(SECTIONS)
    plan: dict[str, Any] = {"sections": sections, "module": body.module}
    if "listening" in sections:
        plan["listening"] = body.listening or pick_test(conn, "listening", None)
    if "reading" in sections:
        plan["reading"] = body.reading or pick_test(conn, "reading", body.module)
    if "writing" in sections:
        t1 = pick_random_prompt(conn, 1, body.module)
        t2 = pick_random_prompt(conn, 2, body.module)
        plan["writing"] = {"task1": t1["id"] if t1 else None, "task2": t2["id"] if t2 else None}
    if "speaking" in sections:
        plan["speaking"] = build_random_set(conn, "full")
    cur = conn.execute("INSERT INTO mock_exams(created_at, status, plan_json) VALUES (?, 'in_progress', ?)",
                       (db.now_iso(), db.dumps(plan)))
    return {"id": cur.lastrowid, "plan": plan}


def compute_bands(conn: sqlite3.Connection, mock_id: int) -> dict[str, Any]:
    links = mock_links(conn, mock_id)
    bands: dict[str, Any] = {}
    for sec in ("listening", "reading"):
        row = conn.execute("SELECT band FROM attempts WHERE mock_id=? AND type=? AND status='submitted' "
                           "ORDER BY finished_at DESC, id DESC LIMIT 1", (mock_id, sec)).fetchone()
        bands[sec] = row[0] if row else None
    # writing: Task 2 counts double (official weighting); single task -> its own band
    task_bands: dict[int, float] = {}
    for sid in links["writing"]:
        task = conn.execute("SELECT p.task FROM writing_submissions s JOIN writing_prompts p ON p.id=s.prompt_id "
                            "WHERE s.id=?", (sid,)).fetchone()
        b = latest_ai_band(conn, "writing", sid)
        if b is not None and task:
            task_bands[task[0]] = b
    if 1 in task_bands and 2 in task_bands:
        bands["writing"] = ielts_round((task_bands[1] + 2 * task_bands[2]) / 3)
    else:
        bands["writing"] = next(iter(task_bands.values()), None)
    sp = [b for b in (latest_ai_band(conn, "speaking_session", s) for s in links["speaking"]) if b is not None]
    bands["speaking"] = sp[-1] if sp else None
    bands["writing_tasks"] = task_bands
    return bands


def overall_if_complete(bands: dict[str, Any], sections: list[str]) -> float | None:
    """Overall band only once every planned section has a band (mean, IELTS rounding)."""
    if not sections or any(bands.get(s) is None for s in sections):
        return None
    return overall_band(bands[s] for s in sections)


def _mock_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = dict(row)
    d["plan"] = db.loads(d.pop("plan_json"), {})
    d["links"] = mock_links(conn, row["id"])
    return d


@router.get("")
def list_mocks(conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    return [_mock_dict(conn, r) for r in conn.execute("SELECT * FROM mock_exams ORDER BY id DESC")]


@router.get("/{mock_id}")
def get_mock(mock_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    row = conn.execute("SELECT * FROM mock_exams WHERE id=?", (mock_id,)).fetchone()
    if not row:
        raise HTTPException(404, "mock not found")
    d = _mock_dict(conn, row)
    live = compute_bands(conn, mock_id)
    sections = d["plan"].get("sections") or list(SECTIONS)
    d["live_bands"] = {**live, "overall": overall_if_complete(live, sections)}
    d["missing"] = [s for s in sections if live.get(s) is None]
    return d


class LinkBody(BaseModel):
    section: str
    ref_id: int


@router.post("/{mock_id}/link")
def link(mock_id: int, body: LinkBody, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    if not conn.execute("SELECT 1 FROM mock_exams WHERE id=?", (mock_id,)).fetchone():
        raise HTTPException(404, "mock not found")
    if body.section in ("listening", "reading"):
        cur = conn.execute("UPDATE attempts SET mock_id=?, mode='mock' WHERE id=? AND type=?",
                           (mock_id, body.ref_id, body.section))
    elif body.section == "writing":
        cur = conn.execute("UPDATE writing_submissions SET mock_id=? WHERE id=?", (mock_id, body.ref_id))
    elif body.section == "speaking":
        cur = conn.execute("UPDATE speaking_sessions SET mock_id=? WHERE id=?", (mock_id, body.ref_id))
    else:
        raise HTTPException(422, "section must be listening|reading|writing|speaking")
    if not cur.rowcount:
        raise HTTPException(404, f"{body.section} item {body.ref_id} not found")
    return {"ok": True, "links": mock_links(conn, mock_id)}


@router.post("/{mock_id}/finish")
def finish(mock_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    row = conn.execute("SELECT * FROM mock_exams WHERE id=?", (mock_id,)).fetchone()
    if not row:
        raise HTTPException(404, "mock not found")
    b = compute_bands(conn, mock_id)
    sections = (db.loads(row["plan_json"], {}) or {}).get("sections") or list(SECTIONS)
    overall = overall_if_complete(b, sections)
    conn.execute("UPDATE mock_exams SET status='finished', finished_at=COALESCE(finished_at, ?), listening_band=?, "
                 "reading_band=?, writing_band=?, speaking_band=?, overall_band=? WHERE id=?",
                 (db.now_iso(), b["listening"], b["reading"], b["writing"], b["speaking"], overall, mock_id))
    missing = [s for s in sections if b.get(s) is None]
    return {"id": mock_id, "bands": {**b, "overall": overall}, "missing": missing}
