"""Idempotent importer: content/tests + knowledge/data + knowledge/kb -> SQLite.

Copes with missing directories and partially-written / invalid files (they are skipped and
reported in the status). Runs at startup in a background thread and via POST /api/admin/reimport.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import traceback
from pathlib import Path
from typing import Any

from . import db
from .grading import count_questions
from .my_results import import_my_results

log = logging.getLogger("ielts.importer")

_lock = threading.Lock()
_status: dict[str, Any] = {"running": False, "last_started": None, "last_finished": None,
                           "last_result": None, "errors": []}


def status() -> dict[str, Any]:
    return dict(_status)


def start_background() -> bool:
    """Start an import in a daemon thread. Returns False if one is already running."""
    if _status["running"]:
        return False
    t = threading.Thread(target=run_import, name="ielts-importer", daemon=True)
    t.start()
    return True


def run_import() -> dict[str, Any]:
    if not _lock.acquire(blocking=False):
        return {"skipped": "import already running"}
    _status.update(running=True, last_started=db.now_iso(), errors=[])
    errors: list[str] = []
    result: dict[str, Any] = {}
    try:
        conn = db.connect()
        try:
            for name, fn in (("tests", import_tests), ("writing_prompts", import_writing_prompts),
                             ("speaking_questions", import_speaking_questions),
                             ("vocab", import_vocab), ("my_essays", import_my_essays),
                             ("photo_essays", import_photo_essays), ("test_results", import_test_results),
                             ("kb", import_kb),
                             ("my_results", import_my_results)):  # last: the learner's own records win
                try:
                    result[name] = fn(conn, errors)
                    conn.commit()
                except Exception as exc:  # keep going with the other sources
                    conn.rollback()
                    errors.append(f"{name}: {exc!r}")
                    log.error("import %s failed\n%s", name, traceback.format_exc())
        finally:
            conn.close()
    finally:
        _status.update(running=False, last_finished=db.now_iso(), last_result=result,
                       errors=errors[-200:])
        _lock.release()
    return {"result": result, "errors": errors}


# --------------------------------------------------------------------------- helpers
def _read_json(path: Path, errors: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        errors.append(f"{_rel(path)}: {exc}")
        return None


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(db.ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _items(data: Any) -> list[dict]:
    """Accept a list, or a dict wrapping a list (e.g. {"items": [...]})."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return [x for x in v if isinstance(x, dict)]
    return []


_NULLS = {"", "none", "null", "nan", "n/a"}


def _str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v) or None
    s = str(v).strip()
    return None if s.lower() in _NULLS else s


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    try:
        f = float(v)
        return f if f == f else None  # NaN -> None
    except (TypeError, ValueError):
        return None


def _bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "y")
    return bool(v)


def _norm_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def word_count(text: str | None) -> int:
    return len(re.findall(r"[A-Za-z0-9À-ɏ]+(?:['’-][A-Za-z0-9]+)*", text or ""))


def _data_files(pattern: str) -> list[Path]:
    d = db.KNOWLEDGE_DIR / "data"
    return sorted(d.glob(pattern)) if d.is_dir() else []


# --------------------------------------------------------------------------- tests
def import_tests(conn: sqlite3.Connection, errors: list[str]) -> int:
    base = db.CONTENT_DIR / "tests"
    if not base.is_dir():
        return 0
    n = 0
    for path in sorted(base.rglob("*.json")):
        data = _read_json(path, errors)
        if not isinstance(data, dict) or not data.get("id") or not isinstance(data.get("parts"), list):
            if data is not None:
                errors.append(f"{_rel(path)}: not a test document")
            continue
        ttype = data.get("type") or path.parent.name
        conn.execute(
            """INSERT INTO tests(id, type, module, title, series, book, test_no, source, source_url,
                                 question_count, file_path, data_json, imported_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET type=excluded.type, module=excluded.module,
                 title=excluded.title, series=excluded.series, book=excluded.book,
                 test_no=excluded.test_no, source=excluded.source, source_url=excluded.source_url,
                 question_count=excluded.question_count, file_path=excluded.file_path,
                 data_json=excluded.data_json, imported_at=excluded.imported_at""",
            (data["id"], ttype, data.get("module") or "academic", data.get("title") or data["id"],
             data.get("series"), _int(data.get("book")), _int(data.get("test_no")),
             data.get("source"), data.get("source_url"), count_questions(data), _rel(path),
             json.dumps(data, ensure_ascii=False), db.now_iso()))
        n += 1
    # Drop tests whose JSON was deleted (e.g. failed validation on a rescrape), unless already attempted.
    for test_id, rel in conn.execute("SELECT id, file_path FROM tests").fetchall():
        if rel and not (db.ROOT / rel).exists():
            if conn.execute("SELECT 1 FROM attempts WHERE test_id = ?", (test_id,)).fetchone():
                errors.append(f"{rel}: file missing but kept (has attempts)")
            else:
                conn.execute("DELETE FROM tests WHERE id = ?", (test_id,))
    return n


# --------------------------------------------------------------------------- writing prompts
def _upsert_prompt(conn: sqlite3.Connection, item: dict) -> int | None:
    prompt = _str(item.get("prompt"))
    if not prompt:
        return None
    task = _int(item.get("task"))
    conn.execute(
        """INSERT INTO writing_prompts(task, module, essay_type, prompt, image_path, image_description,
                                       source, source_date, tags)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(prompt) DO UPDATE SET
             task=COALESCE(excluded.task, task), module=COALESCE(excluded.module, module),
             essay_type=COALESCE(excluded.essay_type, essay_type),
             image_path=COALESCE(excluded.image_path, image_path),
             image_description=COALESCE(excluded.image_description, image_description),
             source=COALESCE(excluded.source, source), source_date=COALESCE(excluded.source_date, source_date),
             tags=COALESCE(excluded.tags, tags)""",
        (task, _str(item.get("module")) or "academic", _str(item.get("essay_type")), prompt,
         _str(item.get("image") or item.get("image_path")), _str(item.get("image_description")),
         _str(item.get("source")), _str(item.get("source_date") or item.get("date")),
         _str(item.get("tags"))))
    row = conn.execute("SELECT id FROM writing_prompts WHERE prompt = ?", (prompt,)).fetchone()
    return row[0] if row else None


def import_writing_prompts(conn: sqlite3.Connection, errors: list[str]) -> int:
    n = 0
    for path in _data_files("writing_prompts*.json"):
        for item in _items(_read_json(path, errors)):
            if _upsert_prompt(conn, item):
                n += 1
    return n


# --------------------------------------------------------------------------- speaking
def import_speaking_questions(conn: sqlite3.Connection, errors: list[str]) -> int:
    n = 0
    for path in _data_files("speaking_questions*.json"):
        for item in _items(_read_json(path, errors)):
            part, question = _int(item.get("part")), _str(item.get("question"))
            if part not in (1, 2, 3) or not question:
                continue
            cue = item.get("cue_points")
            fu = item.get("follow_up") or item.get("follow_ups")
            conn.execute(
                """INSERT INTO speaking_questions(part, topic, question, cue_points_json, follow_up_json,
                                                  season, source, model_answer)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(part, topic, question) DO UPDATE SET
                     cue_points_json=COALESCE(excluded.cue_points_json, cue_points_json),
                     follow_up_json=COALESCE(excluded.follow_up_json, follow_up_json),
                     season=COALESCE(excluded.season, season), source=COALESCE(excluded.source, source),
                     model_answer=COALESCE(excluded.model_answer, model_answer)""",
                (part, _str(item.get("topic")) or "", question,
                 db.dumps(cue) if cue else None, db.dumps(fu) if fu else None,
                 _str(item.get("season")), _str(item.get("source")), _str(item.get("model_answer"))))
            n += 1
    return n


# --------------------------------------------------------------------------- vocab
def import_vocab(conn: sqlite3.Connection, errors: list[str]) -> int:
    n = 0
    for path in _data_files("vocabulary*.json"):
        for item in _items(_read_json(path, errors)):
            term = _str(item.get("term") or item.get("word"))
            if not term:
                continue
            conn.execute(
                """INSERT INTO vocab(term, meaning, example, topic, source) VALUES (?,?,?,?,?)
                   ON CONFLICT(term, topic) DO UPDATE SET
                     meaning=COALESCE(excluded.meaning, meaning), example=COALESCE(excluded.example, example),
                     source=COALESCE(excluded.source, source)""",
                (term, _str(item.get("meaning") or item.get("definition")), _str(item.get("example")),
                 _str(item.get("topic")) or "", _str(item.get("source"))))
            n += 1
    return n


# --------------------------------------------------------------------------- my essays
def _match_prompt(conn: sqlite3.Connection, task: int | None, prompt: str) -> int | None:
    target = _norm_text(prompt)
    if not target:
        return None
    rows = conn.execute("SELECT id, task, prompt FROM writing_prompts").fetchall()
    prefix = target[:100]
    for r in rows:
        if _norm_text(r["prompt"]) == target:
            return r["id"]
    for r in rows:
        p = _norm_text(r["prompt"])
        if (task is None or r["task"] in (None, task)) and len(prefix) >= 40 and \
                (p.startswith(prefix) or target.startswith(p[:100])):
            return r["id"]
    return None


def import_my_essays(conn: sqlite3.Connection, errors: list[str]) -> dict[str, int]:
    stats = {"essays": 0, "inserted": 0, "prompts_matched": 0, "prompts_created": 0}
    path = db.KNOWLEDGE_DIR / "data" / "my_essays.json"
    if not path.is_file():
        return stats
    for item in _items(_read_json(path, errors)):
        text = _str(item.get("text"))
        prompt = _str(item.get("prompt"))
        if not text or not prompt:
            continue
        stats["essays"] += 1
        task = _int(item.get("task"))
        pid = _match_prompt(conn, task, prompt)
        if pid:
            stats["prompts_matched"] += 1
        else:
            pid = _upsert_prompt(conn, {"task": task, "prompt": prompt, "essay_type": item.get("essay_type"),
                                        "source": item.get("source") or "my_essays",
                                        "source_date": item.get("date"), "image": item.get("image"),
                                        "image_description": item.get("image_description")})
            stats["prompts_created"] += 1
        if _upsert_imported_essay(conn, pid, task, item):
            stats["inserted"] += 1
    return stats


def _similar(a: str, b: str) -> bool:
    """Same essay transcribed twice (typed in chat vs teacher-marked photo, often posted days apart)?
    On the real data duplicates score >= 0.85 word-set Jaccard and distinct essays (even on the same
    prompt) <= 0.35, so 0.8 is a safe cut-off."""
    na, nb = _norm_text(a), _norm_text(b)
    if na == nb:
        return True
    ta, tb = set(re.findall(r"[a-z]+", na)), set(re.findall(r"[a-z]+", nb))
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.8


def _upsert_imported_essay(conn: sqlite3.Connection, pid: int | None, task: int | None, item: dict) -> bool:
    """Insert a telegram_import submission unless the same essay exists; teacher feedback is merged.
    Returns True when a new row was inserted."""
    text = _str(item.get("text")) or ""
    band = _float(item.get("band") if item.get("band") is not None else item.get("teacher_band"))
    comments = _str(item.get("teacher_comments"))
    photo = _str(item.get("photo"))
    date = _str(item.get("date"))
    existing = None
    for r in conn.execute("SELECT s.id, s.text, s.created_at FROM writing_submissions s "
                          "LEFT JOIN writing_prompts p ON p.id = s.prompt_id "
                          "WHERE s.origin = 'telegram_import' AND (p.task = ? OR ? IS NULL OR p.task IS NULL)",
                          (task, task)).fetchall():
        if _similar(r["text"] or "", text):
            existing = r
            break
    if existing:
        conn.execute("UPDATE writing_submissions SET teacher_band = COALESCE(?, teacher_band), "
                     "teacher_comments = COALESCE(?, teacher_comments), source_photo = COALESCE(?, source_photo) "
                     "WHERE id = ?", (band, comments, photo, existing["id"]))
        return False
    conn.execute(
        """INSERT INTO writing_submissions(prompt_id, text, word_count, time_spent_sec, created_at, origin,
                                           teacher_band, teacher_comments, source_photo)
           VALUES (?,?,?,?,?, 'telegram_import', ?,?,?)""",
        (pid, text, word_count(text), _int(item.get("time_spent_sec")), date or db.now_iso(),
         band, comments, photo))
    return True


def import_photo_essays(conn: sqlite3.Connection, errors: list[str]) -> dict[str, int]:
    """photo_essays.json: essays read from chat photos. Only the user's own (is_mine) are imported."""
    stats = {"essays": 0, "mine": 0, "inserted": 0, "merged": 0}
    path = db.KNOWLEDGE_DIR / "data" / "photo_essays.json"
    if not path.is_file():
        return stats
    for item in _items(_read_json(path, errors)):
        stats["essays"] += 1
        if not _bool(item.get("is_mine")):
            continue
        text, prompt = _str(item.get("text")), _str(item.get("prompt"))
        if not text:
            continue
        stats["mine"] += 1
        task = _int(item.get("task"))
        pid = _match_prompt(conn, task, prompt) if prompt else None
        if pid is None and prompt:
            pid = _upsert_prompt(conn, {"task": task, "prompt": prompt, "source": "photo_essays",
                                        "source_date": item.get("date")})
        if _upsert_imported_essay(conn, pid, task, item):
            stats["inserted"] += 1
        else:
            stats["merged"] += 1
    return stats


# --------------------------------------------------------------------------- external results
def _my_names(conn: sqlite3.Connection) -> tuple[str, ...]:
    """The learner's name(s) from the `user_name` setting (comma-separated), lower-cased."""
    value = db.get_setting(conn, "user_name") or ""
    return tuple(n.strip().lower() for n in value.split(",") if n.strip())


def _is_me(name: str | None, my_names: tuple[str, ...]) -> bool:
    return any(n in (name or "").lower() for n in my_names)


def import_test_results(conn: sqlite3.Connection, errors: list[str]) -> int:
    path = db.KNOWLEDGE_DIR / "data" / "test_results.json"
    if not path.is_file():
        return 0
    n = 0
    keymap = {"L": "listening", "R": "reading", "W": "writing", "S": "speaking", "O": "overall"}
    my_names = _my_names(conn)
    for item in _items(_read_json(path, errors)):
        rows: list[tuple[str, dict]] = []
        results = item.get("results")
        if isinstance(results, dict) and results:   # group table: one row per person
            for person, sc in results.items():
                if isinstance(sc, dict):
                    rows.append((str(person), {keymap.get(k, k): v for k, v in sc.items()}))
        else:
            rows.append((_str(item.get("person")) or "unknown", item))
        for person, sc in rows:
            conn.execute(
                """INSERT INTO external_results(date, person, is_mine, listening, reading, writing, speaking, overall,
                                                notes, photo, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?, 'test_results.json')
                   ON CONFLICT(date, person, photo) DO UPDATE SET is_mine=excluded.is_mine,
                     listening=excluded.listening, reading=excluded.reading, writing=excluded.writing,
                     speaking=excluded.speaking, overall=excluded.overall, notes=excluded.notes""",
                (_str(item.get("date")) or "", person, int(_is_me(person, my_names)),
                 _float(sc.get("listening")), _float(sc.get("reading")), _float(sc.get("writing")),
                 _float(sc.get("speaking")), _float(sc.get("overall")), _str(item.get("notes")),
                 _str(item.get("photo")) or ""))
            n += 1
    return n


# --------------------------------------------------------------------------- knowledge base
def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Minimal YAML-ish front-matter: `key: value`, `key: [a, b]`, and `- item` lists."""
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return {}, text
    meta: dict[str, Any] = {}
    key = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if m and not line.startswith((" ", "\t", "-")):
            key, val = m.group(1).lower(), m.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                meta[key] = [_unquote(x) for x in val[1:-1].split(",") if x.strip()]
            elif val:
                meta[key] = _unquote(val)
            else:
                meta[key] = []
        elif key and line.strip().startswith("- "):
            if not isinstance(meta.get(key), list):
                meta[key] = []
            meta[key].append(_unquote(line.strip()[2:]))
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return meta, body


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    return s


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "doc"


def import_kb(conn: sqlite3.Connection, errors: list[str]) -> int:
    base = db.KNOWLEDGE_DIR / "kb"
    seen_paths: set[str] = set()
    used_slugs: set[str] = set()
    n = 0
    if base.is_dir():
        for path in sorted(base.rglob("*.md")):
            rel = path.relative_to(base)
            if rel.parts and rel.parts[0] == "assets":
                continue
            try:
                raw = path.read_text(encoding="utf-8-sig")
            except Exception as exc:
                errors.append(f"{_rel(path)}: {exc}")
                continue
            meta, body = parse_front_matter(raw)
            slug = _slugify(str(meta.get("slug") or path.stem))
            if slug in used_slugs:
                slug = _slugify("-".join(rel.with_suffix("").parts))
            used_slugs.add(slug)
            title = meta.get("title")
            if not title:
                m = re.search(r"^#\s+(.+)$", body, re.M)
                title = m.group(1).strip() if m else path.stem.replace("-", " ").replace("_", " ").title()
            category = meta.get("category") or (rel.parts[0] if len(rel.parts) > 1 else "general")
            tags = meta.get("tags")
            tags = ", ".join(tags) if isinstance(tags, list) else (tags or None)
            rel_posix = rel.as_posix()
            seen_paths.add(rel_posix)
            # the path is the stable identity; free the slug if another path held it
            conn.execute("DELETE FROM kb_docs WHERE slug = ? AND path <> ?", (slug, rel_posix))
            existing = conn.execute("SELECT id FROM kb_docs WHERE path = ?", (rel_posix,)).fetchone()
            if existing:
                conn.execute("UPDATE kb_docs SET slug=?, title=?, category=?, tags=?, content_md=? WHERE id=?",
                             (slug, str(title), str(category), tags, body, existing[0]))
            else:
                conn.execute("INSERT INTO kb_docs(slug, title, category, tags, path, content_md) VALUES (?,?,?,?,?,?)",
                             (slug, str(title), str(category), tags, rel_posix, body))
            n += 1
    for r in conn.execute("SELECT id, path FROM kb_docs").fetchall():
        if r["path"] not in seen_paths:
            conn.execute("DELETE FROM kb_docs WHERE id = ?", (r["id"],))
    conn.execute("INSERT INTO kb_fts(kb_fts) VALUES('rebuild')")
    return n


# --------------------------------------------------------------------------- counts
COUNT_TABLES = ("tests", "attempts", "writing_prompts", "writing_submissions", "speaking_questions",
                "speaking_sessions", "speaking_responses", "vocab", "kb_docs", "ai_analyses", "mock_exams",
                "external_results")


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    out = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in COUNT_TABLES}
    for r in conn.execute("SELECT type, COUNT(*) FROM tests GROUP BY type"):
        out[f"tests_{r[0]}"] = r[1]
    return out
