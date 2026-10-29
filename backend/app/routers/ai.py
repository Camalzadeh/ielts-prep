"""AI analysis endpoints + settings."""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from .. import ai_runner, db
from ..context import TARGET_TYPES, target_exists

router = APIRouter(prefix="/api", tags=["ai"])


def analysis_dict(row: sqlite3.Row, with_prompt: bool = False) -> dict:
    d = dict(row)
    d["result"] = db.loads(d.pop("result_json"))
    d["result_json"] = d["result"]
    if not with_prompt:
        d.pop("prompt", None)
    return d


@router.get("/ai/providers")
def providers(refresh: bool = False) -> list[dict]:
    return ai_runner.providers(force=refresh)


class AnalyzeBody(BaseModel):
    target_type: str
    target_id: Optional[int] = None
    provider: Optional[str] = None
    force: bool = False


@router.post("/ai/analyze")
def analyze(body: AnalyzeBody, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    if body.target_type not in TARGET_TYPES:
        raise HTTPException(422, f"target_type must be one of {TARGET_TYPES}")
    target_id = body.target_id if body.target_type != "progress" else (body.target_id or 0)
    if body.target_type != "progress" and not target_exists(conn, body.target_type, target_id):
        raise HTTPException(404, f"{body.target_type} {target_id} not found")
    if body.target_type == "attempt":
        st = conn.execute("SELECT status FROM attempts WHERE id=?", (target_id,)).fetchone()
        if st["status"] != "submitted":
            raise HTTPException(409, "attempt must be submitted before analysis")
    provider = body.provider or db.get_setting(conn, "ai_provider") or "claude"
    if provider not in ai_runner.PROVIDERS:
        raise HTTPException(422, f"provider must be one of {list(ai_runner.PROVIDERS)}")
    if not body.force:
        row = conn.execute(
            "SELECT * FROM ai_analyses WHERE target_type=? AND target_id=? AND status IN ('done','queued','running') "
            "ORDER BY CASE status WHEN 'done' THEN 0 ELSE 1 END, id DESC LIMIT 1",
            (body.target_type, target_id)).fetchone()
        if row:
            return {**analysis_dict(row), "existing": True}
    aid = ai_runner.enqueue(conn, body.target_type, target_id, provider)
    conn.commit()
    ai_runner.wake()
    return {"id": aid, "status": "queued", "existing": False}


@router.get("/ai/analyses")
def list_analyses(target_type: Optional[str] = None, target_id: Optional[int] = None, limit: int = 100,
                  conn: sqlite3.Connection = Depends(db.get_db)) -> list[dict]:
    sql = "SELECT * FROM ai_analyses WHERE 1=1"
    args: list[Any] = []
    if target_type:
        sql += " AND target_type=?"
        args.append(target_type)
    if target_id is not None:
        sql += " AND target_id=?"
        args.append(target_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(limit, 1000)))
    return [analysis_dict(r) for r in conn.execute(sql, args)]


@router.get("/ai/analyses/{analysis_id}")
def get_analysis(analysis_id: int, prompt: bool = False, conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    row = conn.execute("SELECT * FROM ai_analyses WHERE id=?", (analysis_id,)).fetchone()
    if not row:
        raise HTTPException(404, "analysis not found")
    return analysis_dict(row, with_prompt=prompt)


# --------------------------------------------------------------------------- settings
@router.get("/settings")
def get_settings(conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    out = dict(db.DEFAULT_SETTINGS)
    out.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
    return out


@router.put("/settings")
def put_settings(body: dict[str, Any] = Body(...), conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    for key, value in body.items():
        if not isinstance(key, str) or not key or len(key) > 100:
            raise HTTPException(422, "invalid setting key")
        if key == "ai_provider" and value not in ai_runner.PROVIDERS:
            raise HTTPException(422, f"ai_provider must be one of {list(ai_runner.PROVIDERS)}")
        if key.startswith("ai_cmd_"):
            args = db.loads(value) if isinstance(value, str) else value
            if value not in (None, "") and (not isinstance(args, list) or not all(isinstance(a, str) for a in args)):
                raise HTTPException(422, f"{key} must be a JSON list of strings")
            try:
                ai_runner.validate_command(args or [])
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            value = db.dumps(args) if args else None
        if value is None:
            conn.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            db.set_setting(conn, key, value if isinstance(value, str) else db.dumps(value))
    if any(k.startswith(("ai_cmd_", "ai_exe_")) for k in body):
        ai_runner.invalidate_provider_cache()
    return get_settings(conn)
