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

router = APIRouter(prefix="/api/mock", tags=["mock"])

SECTIONS = ("listening", "reading", "writing", "speaking")


class MockCreate(BaseModel):
    sections: list[str] = list(SECTIONS)
    random: bool = True
    module: str = "academic"
    listening: Optional[str] = None
    reading: Optional[str] = None


# ---------------------------------------------------------------------------- what a mock is made of
# Listening / Reading: Cambridge books after 10 only; the newest books (after 17) weigh 4, the others 1.
# Writing: by where the prompt comes from (sources not listed, e.g. course material, are never used).
# Anything already attempted (submitted or still in progress) weighs half.
MOCK_MIN_BOOK = 11
RECENT_BOOK = 18
WRITING_SOURCE_WEIGHTS = {"teacher": 1, "trial_exam": 2, "mock_exam": 3, "real_exam": 4}


def test_weight(book: int | None, attempted: bool) -> float:
    base = 4 if (book or 0) >= RECENT_BOOK else 1
    return base / 2 if attempted else base


def mock_test_weights(conn: sqlite3.Connection, ttype: str, module: str | None) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT t.id, t.module, t.book, EXISTS (SELECT 1 FROM attempts a WHERE a.test_id=t.id) AS done FROM tests t "
        "WHERE t.type=? AND COALESCE(t.source, '') NOT IN ('external', 'history')",
        (ttype,)).fetchall()
    if ttype == "reading":
        # only the exam's own module: an Academic mock never gets a General Training passage
        rows = [r for r in rows if (r["module"] or "academic") == (module or "academic")]
    recent = [r for r in rows if (r["book"] or 0) >= MOCK_MIN_BOOK]
    return [(r["id"], test_weight(r["book"], bool(r["done"]))) for r in (recent or rows)]


def mock_prompt_weights(conn: sqlite3.Connection, task: int, module: str | None) -> list[tuple[dict, float]]:
    rows = conn.execute(
        "SELECT p.id, p.source, EXISTS (SELECT 1 FROM writing_submissions s WHERE s.prompt_id=p.id) AS done "
        "FROM writing_prompts p WHERE p.task=? AND (p.module=? OR p.module IS NULL)",
        (task, module or "academic")).fetchall()
    out = []
    for r in rows:
        w = WRITING_SOURCE_WEIGHTS.get(r["source"] or "", 0)
        if w:
            out.append(({"id": r["id"]}, w / 2 if r["done"] else w))
    return out


def _weighted(choices: list) -> object | None:
    return random.choices([c for c, _ in choices], weights=[w for _, w in choices])[0] if choices else None


def pick_test(conn: sqlite3.Connection, ttype: str, module: str | None) -> str | None:
    return _weighted(mock_test_weights(conn, ttype, module))


def pick_mock_prompt(conn: sqlite3.Connection, task: int, module: str | None) -> dict | None:
    return _weighted(mock_prompt_weights(conn, task, module))


@router.post("")
def create_mock(body: MockCreate, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    sections = [s for s in body.sections if s in SECTIONS] or list(SECTIONS)
    plan: dict[str, Any] = {"sections": sections, "module": body.module}
    if "listening" in sections:
        plan["listening"] = body.listening or pick_test(conn, "listening", None)
    if "reading" in sections:
        plan["reading"] = body.reading or pick_test(conn, "reading", body.module)
    if "writing" in sections:
        t1 = pick_mock_prompt(conn, 1, body.module)
        t2 = pick_mock_prompt(conn, 2, body.module)
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
        task = conn.execute("SELECT p.task, s.teacher_band FROM writing_submissions s JOIN writing_prompts p "
                            "ON p.id=s.prompt_id WHERE s.id=?", (sid,)).fetchone()
        # an examiner's band (e.g. an official external mock) counts before the AI estimate
        b = task[1] if task and task[1] is not None else latest_ai_band(conn, "writing", sid)
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
    # whether each linked test attempt / speaking session is finished, so the page can tell
    # "in progress" (resume it) from "done" (review it)
    d["progress"] = {
        "attempts": {str(r[0]): r[1] for r in conn.execute(
            "SELECT id, status FROM attempts WHERE mock_id=?", (row["id"],))},
        "speaking": {str(r[0]): ("finished" if r[1] else "in_progress") for r in conn.execute(
            "SELECT id, finished_at FROM speaking_sessions WHERE mock_id=?", (row["id"],))},
    }
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


@router.delete("/{mock_id}")
def delete_mock(mock_id: int, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    """Cancel (or delete) a mock exam. Sections already completed stay as ordinary results in History;
    unfinished attempts of the mock are discarded."""
    if not conn.execute("SELECT 1 FROM mock_exams WHERE id=?", (mock_id,)).fetchone():
        raise HTTPException(404, "mock not found")
    unfinished = [r[0] for r in conn.execute(
        "SELECT id FROM attempts WHERE mock_id=? AND status != 'submitted'", (mock_id,))]
    for aid in unfinished:
        db.forget_result(conn, "attempt", aid, None, "")
        conn.execute("DELETE FROM attempts WHERE id=?", (aid,))
    kept = sum(conn.execute(f"UPDATE {t} SET mock_id=NULL WHERE mock_id=?", (mock_id,)).rowcount
               for t in ("attempts", "writing_submissions", "speaking_sessions"))
    conn.execute("DELETE FROM ai_analyses WHERE target_type='mock' AND target_id=?", (mock_id,))
    conn.execute("DELETE FROM mock_exams WHERE id=?", (mock_id,))
    return {"ok": True, "id": mock_id, "kept_results": kept, "discarded_attempts": unfinished}


class SectionsBody(BaseModel):
    sections: list[str]


@router.put("/{mock_id}/sections")
def set_sections(mock_id: int, body: SectionsBody, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    """Change which sections an unfinished mock includes (e.g. skip Speaking, or add it back).
    A section that already has results cannot be dropped; a section added back gets its materials."""
    row = conn.execute("SELECT * FROM mock_exams WHERE id=?", (mock_id,)).fetchone()
    if not row:
        raise HTTPException(404, "mock not found")
    if row["status"] == "finished":
        raise HTTPException(409, "a finished mock cannot change its sections")
    want = [s for s in SECTIONS if s in body.sections]
    if not want:
        raise HTTPException(422, f"choose at least one of {list(SECTIONS)}")
    plan = db.loads(row["plan_json"], {}) or {}
    links = mock_links(conn, mock_id)
    kept = [s for s in (plan.get("sections") or SECTIONS) if s not in want and links.get(s)]
    if kept:
        raise HTTPException(409, f"{', '.join(kept)} already has results in this mock")
    module = plan.get("module") or "academic"
    for s in want:
        if plan.get(s):
            continue
        if s in ("listening", "reading"):
            plan[s] = pick_test(conn, s, module if s == "reading" else None)
        elif s == "writing":
            t1, t2 = pick_mock_prompt(conn, 1, module), pick_mock_prompt(conn, 2, module)
            plan[s] = {"task1": t1["id"] if t1 else None, "task2": t2["id"] if t2 else None}
        else:
            plan[s] = build_random_set(conn, "full")
    plan["sections"] = want
    conn.execute("UPDATE mock_exams SET plan_json=? WHERE id=?", (db.dumps(plan), mock_id))
    return {"ok": True, "plan": plan}


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
