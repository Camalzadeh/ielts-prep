"""Health and admin endpoints."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from .. import db, importer, transcribe

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/health")
def health(conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    return {"ok": True, "time": db.now_iso(), "schema_version": version,
            "importing": importer.status()["running"]}


@router.post("/admin/reimport")
def reimport(wait: bool = False) -> dict:
    if wait:
        return {"started": True, **importer.run_import()}
    return {"started": importer.start_background()}


@router.get("/admin/status")
def admin_status(conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    return {"counts": importer.counts(conn), "import": importer.status(),
            "transcriber": transcribe.model_info(),
            "ai_queue": {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM ai_analyses GROUP BY status")},
            "db_path": str(db.DB_PATH)}
