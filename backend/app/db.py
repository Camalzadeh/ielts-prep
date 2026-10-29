"""SQLite access, project paths and small shared helpers.

Paths can be overridden with environment variables (used by the test-suite):
IELTS_ROOT, IELTS_DATA_DIR, IELTS_CONTENT_DIR, IELTS_KNOWLEDGE_DIR.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(os.environ.get("IELTS_ROOT") or Path(__file__).resolve().parents[2])
DATA_DIR = Path(os.environ.get("IELTS_DATA_DIR") or ROOT / "data")
CONTENT_DIR = Path(os.environ.get("IELTS_CONTENT_DIR") or ROOT / "content")
KNOWLEDGE_DIR = Path(os.environ.get("IELTS_KNOWLEDGE_DIR") or ROOT / "knowledge")
FRONTEND_DIR = ROOT / "frontend"
DB_PATH = DATA_DIR / "ielts.db"
UPLOADS_DIR = DATA_DIR / "uploads"
AI_RUNS_DIR = DATA_DIR / "ai_runs"
MODELS_DIR = DATA_DIR / "models"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
ARCHIVES = ("IELTS_PREP_ARCHIVE", "LATEST_EXAMS_ARCHIVE")

DEFAULT_SETTINGS: dict[str, str] = {
    "ai_provider": "claude",
    "user_name": "",          # the learner's name: dashboard greeting + which archive results are theirs
    "translate_to": "az",     # study assistant: target language of the translator
    "assist_in_mock": "0",    # "1" = study assistant also available during mock exams
}

_init_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect(readonly: bool = False, path: Path | None = None) -> sqlite3.Connection:
    """Open a connection. Read-only connections use a `mode=ro` URI."""
    path = Path(path or DB_PATH)
    if readonly:
        uri = "file:" + path.resolve().as_posix() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=10)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    if not readonly:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def session(readonly: bool = False) -> Iterator[sqlite3.Connection]:
    conn = connect(readonly=readonly)
    try:
        yield conn
        if not readonly:
            conn.commit()
    except Exception:
        if not readonly:
            conn.rollback()
        raise
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, committed on success."""
    with session() as conn:
        yield conn


# --------------------------------------------------------------------------- migrations
# Each entry: (version, list of SQL statements). Applied in order after schema.sql.
# Version 1 is the baseline created by schema.sql.
MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, []),
    # v2: teacher feedback on imported (photo) essays; external results table lives in schema.sql
    (2, ["ALTER TABLE writing_submissions ADD COLUMN teacher_band REAL",
         "ALTER TABLE writing_submissions ADD COLUMN teacher_comments TEXT",
         "ALTER TABLE writing_submissions ADD COLUMN source_photo TEXT"]),
    # v3: band-only speaking results from the learner's own records (tools/import_my_results.py)
    (3, ["ALTER TABLE speaking_sessions ADD COLUMN teacher_band REAL",
         "ALTER TABLE speaking_sessions ADD COLUMN notes TEXT"]),
    # v4: cache for the study-assistant translator
    (4, ["CREATE TABLE IF NOT EXISTS translations (key TEXT PRIMARY KEY, json TEXT NOT NULL, created_at TEXT)"]),
]


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def init_db() -> None:
    with _init_lock:
        for d in (DATA_DIR, UPLOADS_DIR, AI_RUNS_DIR, MODELS_DIR):
            d.mkdir(parents=True, exist_ok=True)
        conn = connect()
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            current = _current_version(conn)
            for version, statements in MIGRATIONS:
                if version <= current:
                    continue
                for stmt in statements:
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError as exc:
                        if "duplicate column" not in str(exc):
                            raise
                conn.execute("INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                             (version, now_iso()))
            for k, v in DEFAULT_SETTINGS.items():
                conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
            conn.commit()
        finally:
            conn.close()


# --------------------------------------------------------------------------- helpers
def row_to_dict(row: sqlite3.Row | None, json_fields: tuple[str, ...] = ()) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for f in json_fields:
        if f in d:
            d[f.removesuffix("_json") if f.endswith("_json") else f] = loads(d.pop(f))
    return d


def rows_to_dicts(rows, json_fields: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    return [row_to_dict(r, json_fields) for r in rows]


def loads(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    return row[0]


def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def media_url(rel_path: str | None) -> str | None:
    """Map a content-relative path ("media/listening/x/part1.mp3") to its URL."""
    if not rel_path:
        return None
    if rel_path.startswith(("http://", "https://", "/")):
        return rel_path
    p = rel_path.replace("\\", "/").lstrip("./")
    if p.startswith("media/"):
        p = p[len("media/"):]
    return "/media/content/" + p
