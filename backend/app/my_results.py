"""Import the learner's own band records from `My Results.docx` in the project root.

The document has one table: Link/Description | Type | Score. Each row is a task the teacher assigned
in the course chat; it is dated to when that task was posted there (looked up in the extracted chat
messages and photo transcriptions). Runs as the last import step, so these bands override others.

- Listening/Reading rows (engnovate links) -> attempts with mode='imported' (band only). If a full attempt
  of that test with the same band already exists (answers replayed from a screenshot), it is re-dated instead.
- Writing rows ("Part1 (<start of my essay>)") -> the matching telegram-imported essay gets the band and date.
- Speaking rows ("Part1 (Topic1-15)", "Part2 (Topic2)") -> band-only speaking sessions (mode='imported').
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from functools import lru_cache

from . import db

DOC = db.ROOT / "My Results.docx"
RAW = db.KNOWLEDGE_DIR / "raw"
# The teacher's name as it appears as message author in the course chat archive. Kept out of the repo:
# one line in data/teacher_name.txt (private). Without it, results are dated without the teacher's posts.
TEACHER_FILE = db.ROOT / "data" / "teacher_name.txt"


@lru_cache(maxsize=1)
def _teacher() -> str:
    try:
        return TEACHER_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return ""


def _is_teacher(author: str | None) -> bool:
    t = _teacher()
    return bool(t) and t in (author or "").lower()


def _iso(telegram_date: str | None) -> str | None:
    """'24.07.2026 21:56:51 UTC+04:00' -> '2026-07-24T21:56:51'."""
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}:\d{2}:\d{2})", telegram_date or "")
    return f"{m[3]}-{m[2]}-{m[1]}T{m[4]}" if m else None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower())} - {
        "the", "and", "graph", "chart", "bar", "line", "shows", "below", "represents", "which", "from", "with",
        "during", "information", "about", "give", "gives", "illustrates", "summarise", "main", "features"}


@lru_cache(maxsize=1)
def _messages() -> tuple[dict, ...]:
    out = []
    for path in sorted(RAW.glob("*/messages.json")):
        for m in json.loads(path.read_text(encoding="utf-8")):
            if not m.get("service"):
                out.append({**m, "archive": path.parent.name})
    return tuple(out)


@lru_cache(maxsize=1)
def _teacher_writing_posts() -> tuple[dict, ...]:
    """Writing tasks the teacher posted: text messages plus transcribed task photos."""
    posts = [{"date": _iso(m["date"]), "text": m["text"]} for m in _messages()
             if _is_teacher(m.get("author")) and m.get("text")]
    authors = {(m["archive"], m["id"]): m.get("author") or "" for m in _messages()}
    dates = {(m["archive"], m["id"]): m.get("date") for m in _messages()}
    for path in sorted((RAW / "photo_batches").glob("*.out.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line) if line.strip() else {}
            key = ((r.get("path") or "").split("/")[0], r.get("message"))
            if r.get("category") in ("writing_task1", "writing_task2_prompt") and _is_teacher(authors.get(key)):
                s = r.get("structured") or {}
                posts.append({"date": _iso(dates.get(key)),
                              "text": " ".join(str(x) for x in (r.get("title"), s.get("prompt"), s.get("data_description")) if x)})
    return tuple(p for p in posts if p["date"])


def _link_date(url: str) -> str | None:
    url = url.rstrip("/")
    hits = sorted(_iso(m["date"]) for m in _messages()
                  if url in m.get("text", "") or any(url in l for l in m.get("links", [])))
    return hits[0] if hits else None


def _speaking_date(part: int, description: str) -> str | None:
    """Part 1 -> when the full Part 1 question list was posted; Part 2 (TopicN) -> when topic N was posted."""
    topic = re.search(r"topic\s*(\d+)", description, re.I)
    for m in sorted(_messages(), key=lambda m: _iso(m["date"]) or ""):
        if not _is_teacher(m.get("author")):
            continue
        titles = " ".join(a.get("title") or a.get("path") or "" for a in m.get("attachments", []))
        if part == 1 and re.search(r"speaking part 1 questions \(all\)", titles, re.I):
            return _iso(m["date"])
        if part == 2 and topic and re.search(rf"\bTopic {topic[1]} -", titles):
            return _iso(m["date"])
    return None


def _rows() -> list[tuple[str, str, str]]:
    from docx import Document  # python-docx; only needed when the file exists

    rows = []
    for table in Document(str(DOC)).tables:
        for r in table.rows[1:]:
            cells = [c.text.strip() for c in r.cells]
            if len(cells) >= 3 and cells[0]:
                rows.append((cells[0], cells[1], cells[2]))
    return rows


def import_my_results(conn: sqlite3.Connection, errors: list[str]) -> dict:
    stats = {"tests": 0, "redated": 0, "writing": 0, "speaking": 0, "skipped": 0}
    if not DOC.exists():
        return stats
    # Rows are updated in place (not re-created) so AI analyses keep pointing at them.
    seen_attempts: set[int] = set()
    seen_sessions: set[int] = set()
    for desc, kind, score in _rows():
        try:
            band = float(score)
        except ValueError:
            stats["skipped"] += 1
            errors.append(f"My Results.docx: no score for {desc!r} - skipped")
            continue
        kind = kind.lower()
        if desc.startswith("http"):
            _import_test(conn, desc, band, stats, errors, seen_attempts)
        elif kind == "writing":
            _import_writing(conn, desc, band, stats, errors)
        elif kind == "speaking":
            part = int(m[1]) if (m := re.match(r"part\s*(\d)", desc, re.I)) else 1
            date = _speaking_date(part, desc) or db.now_iso()
            note = re.sub(r"\s*\(", " (", re.sub(r"(?i)part\s*(\d)", r"Part \1", desc))
            plan = json.dumps({"source": "My Results.docx", "part": part})
            row = conn.execute("SELECT id FROM speaking_sessions WHERE mode = 'imported' AND notes = ?", (note,)).fetchone()
            if row:
                conn.execute("UPDATE speaking_sessions SET created_at=?, finished_at=?, plan_json=?, teacher_band=? "
                             "WHERE id=?", (date, date, plan, band, row["id"]))
                seen_sessions.add(row["id"])
            else:
                cur = conn.execute("INSERT INTO speaking_sessions(created_at, finished_at, plan_json, mode, teacher_band, "
                                   "notes) VALUES (?,?,?, 'imported', ?,?)", (date, date, plan, band, note))
                seen_sessions.add(cur.lastrowid)
            stats["speaking"] += 1
        else:
            stats["skipped"] += 1
            errors.append(f"My Results.docx: unknown row {desc!r} ({kind})")
    # rows removed from the document disappear from the app (with their analyses)
    for table, ids, target in (("attempts", seen_attempts, "attempt"), ("speaking_sessions", seen_sessions, "speaking_session")):
        for (rid,) in conn.execute(f"SELECT id FROM {table} WHERE mode = 'imported'").fetchall():
            if rid not in ids:
                conn.execute("DELETE FROM ai_analyses WHERE target_type = ? AND target_id = ?", (target, rid))
                conn.execute(f"DELETE FROM {table} WHERE id = ?", (rid,))
    realign_essay_dates(conn)
    return stats


def realign_essay_dates(conn) -> None:
    """Date chat essays to when the teacher posted the task, when that post can be identified confidently
    (>= 75% of the prompt's key words, posted before the essay). Otherwise the essay keeps its own date."""
    posts = _teacher_writing_posts()
    for r in conn.execute("SELECT s.id, s.created_at, p.prompt FROM writing_submissions s JOIN writing_prompts p "
                          "ON p.id = s.prompt_id WHERE s.origin = 'telegram_import'").fetchall():
        words = _words(r["prompt"])
        if not words or not r["created_at"]:
            continue
        own_day = r["created_at"][:10]
        best = max(((len(words & _words(p["text"])) / len(words), p["date"]) for p in posts
                    if p["date"][:10] <= own_day), default=None, key=lambda x: (x[0], x[1]))
        if best and best[0] >= 0.75:
            conn.execute("UPDATE writing_submissions SET created_at = ? WHERE id = ?", (best[1], r["id"]))


def _import_test(conn, url, band, stats, errors, seen):
    m = re.search(r"cambridge-ielts-(\d+)-(academic|general-training)-(listening|reading)-test-(\d+)", url)
    if not m:
        errors.append(f"My Results.docx: unrecognised test link {url}")
        return
    book, module, ttype, no = int(m[1]), m[2], m[3], int(m[4])
    test_id = f"cam{book}-{ttype}-{no}" if module == "academic" or ttype == "listening" else f"cam{book}-gt-reading-{no}"
    if not conn.execute("SELECT 1 FROM tests WHERE id = ?", (test_id,)).fetchone():
        errors.append(f"My Results.docx: test {test_id} is not in the library - skipped")
        return
    date = _link_date(url) or db.now_iso()
    full = conn.execute("SELECT id FROM attempts WHERE test_id = ? AND band = ? AND status = 'submitted' "
                        "AND EXISTS (SELECT 1 FROM attempt_answers WHERE attempt_id = attempts.id)",
                        (test_id, band)).fetchone()
    if full:  # same result already replayed with its answers -> just move it to the assignment date
        conn.execute("UPDATE attempts SET started_at = ?, finished_at = ? WHERE id = ?", (date, date, full["id"]))
        stats["redated"] += 1
        return
    row = conn.execute("SELECT id FROM attempts WHERE mode = 'imported' AND test_id = ?", (test_id,)).fetchone()
    if row:
        conn.execute("UPDATE attempts SET started_at=?, finished_at=?, band=? WHERE id=?", (date, date, band, row["id"]))
        seen.add(row["id"])
    else:
        cur = conn.execute("INSERT INTO attempts(test_id, type, mode, started_at, finished_at, status, total, band) "
                           "VALUES (?,?, 'imported', ?,?, 'submitted', 40, ?)", (test_id, ttype, date, date, band))
        seen.add(cur.lastrowid)
    stats["tests"] += 1


def _import_writing(conn, desc, band, stats, errors):
    task = 2 if re.match(r"part\s*2", desc, re.I) else 1
    inner = re.sub(r"^part\s*\d\s*\(|\)\s*$", "", desc, flags=re.I)
    want = _words(inner)
    best, best_score = None, 0.0
    for r in conn.execute("SELECT s.id, s.text, p.prompt FROM writing_submissions s JOIN writing_prompts p "
                          "ON p.id = s.prompt_id WHERE s.origin = 'telegram_import' AND p.task = ?", (task,)):
        have = _words((r["text"] or "")[:300] + " " + (r["prompt"] or ""))
        score = len(want & have) / (len(want) or 1)
        if score > best_score:
            best, best_score = r, score
    if not best or best_score < 0.5:
        errors.append(f"My Results.docx: no essay found for {desc!r}")
        return
    # the teacher's post of this task = best keyword match among her writing posts, before the essay
    prompt_words = _words(best["prompt"])
    posts = sorted(_teacher_writing_posts(), key=lambda p: (-len(prompt_words & _words(p["text"])), p["date"]))
    date = posts[0]["date"] if posts and prompt_words & _words(posts[0]["text"]) else None
    conn.execute("UPDATE writing_submissions SET teacher_band = ?, created_at = COALESCE(?, created_at) WHERE id = ?",
                 (band, date, best["id"]))
    stats["writing"] += 1
