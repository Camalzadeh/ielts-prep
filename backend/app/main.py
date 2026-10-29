"""FastAPI application: API routers, media routes and the static frontend.

Run from the project root:
    .venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai_runner, db, importer, transcribe
from .routers import admin, ai, kb, mock, speaking, stats, tests, writing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ielts")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    stale = ai_runner.mark_stale_running()
    if stale:
        log.info("marked %d interrupted AI analyses as error", stale)
    importer.start_background()
    transcribe.start_worker()
    transcribe.requeue_pending()
    ai_runner.start_worker()
    ai_runner.wake()
    yield


app = FastAPI(title="IELTS Prep", version="1.0", lifespan=lifespan)

for r in (admin, tests, writing, speaking, mock, ai, kb, stats):
    app.include_router(r.router)


@app.exception_handler(ValueError)
async def value_error_handler(request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# --------------------------------------------------------------------------- media
def _safe_file(base: Path, rel: str) -> Path:
    base = base.resolve()
    try:
        p = (base / rel).resolve()
    except (OSError, ValueError):
        raise HTTPException(404)
    if not p.is_relative_to(base) or not p.is_file():
        raise HTTPException(404)
    return p


@app.get("/media/content/{path:path}", include_in_schema=False)
def media_content(path: str):
    # "/media/content/listening/x.mp3" -> content/media/listening/x.mp3; tolerate a "media/" prefix too
    for base, rel in ((db.CONTENT_DIR / "media", path), (db.CONTENT_DIR, path)):
        try:
            return FileResponse(_safe_file(base, rel))
        except HTTPException:
            continue
    raise HTTPException(404)


@app.get("/media/uploads/{path:path}", include_in_schema=False)
def media_uploads(path: str):
    return FileResponse(_safe_file(db.UPLOADS_DIR, path))


@app.get("/media/archive/{archive}/{path:path}", include_in_schema=False)
def media_archive(archive: str, path: str):
    if archive not in db.ARCHIVES:
        raise HTTPException(404)
    return FileResponse(_safe_file(db.ROOT / archive, path))


@app.get("/media/kb/{path:path}", include_in_schema=False)
def media_kb(path: str):
    return FileResponse(_safe_file(db.KNOWLEDGE_DIR / "kb" / "assets", path))


# --------------------------------------------------------------------------- frontend (must be last)
class _Frontend(StaticFiles):
    """Static SPA with no-cache headers so edits show up without hard reloads."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


if db.FRONTEND_DIR.is_dir():
    app.mount("/", _Frontend(directory=str(db.FRONTEND_DIR), html=True, check_dir=False), name="frontend")
else:
    @app.get("/", include_in_schema=False)
    def no_frontend():
        return JSONResponse({"detail": "frontend/ not found; API is at /api"})
