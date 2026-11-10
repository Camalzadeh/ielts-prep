"""Import an officially marked external mock exam (answer tables + marked essays) into the app's DB.

Usage (project venv):
    .venv\\Scripts\\python.exe tools\\import_external_mock.py data\\external_results\\<file>.json [--db PATH]

`--db` defaults to the app database (backend.app.db.DATA_DIR / "ielts.db"). The DB must already exist (the app
creates it on first start). Everything is written in one transaction and the import is idempotent: re-running it
updates the rows it created earlier instead of adding new ones.

Input JSON (personal data: keep it under the git-ignored data/ folder, e.g. data/external_results/):
{
  "mock": {"date": "YYYY-MM-DD", "provider": "...", "test_code": "...", "module": "academic",
           "sections": ["listening", "reading", "writing"], "note": "..."},
  "listening": {"answers": [{"number": 1, "accepted": ["a", "b"], "answer": "candidate", "correct": true}, ...]},
  "reading":   {"answers": [... same, numbers 1-40 ...]},
  "writing": {"overall": 5.5,
              "tasks": [{"task": 1, "prompt": "<exact prompt text>", "essay": "...", "review": "examiner review",
                         "criteria": {"TA": 6, "CC": 6, "LR": 6, "GRA": 6}, "band": 6.0},
                        {"task": 2, ..., "criteria": {"TR": 5, ...}, "band": 5.5}]}
}
Any of listening / reading / writing may be left out. The "correct" flags are the official marking and are stored
as given (answers are not re-graded).

What it creates (stable keys in brackets):
- tests        one per listening/reading section, source 'external', file_path NULL, a minimal answer-key document
               (listening: 4 parts of 10; reading: parts 1-13, 14-26, 27-40)  [id ext-<date>-<test code>-<type>]
- attempts     status 'submitted', mode 'mock', band from grading.raw_to_band, plus attempt_answers rows
               [test_id + mode 'mock']
- writing_submissions  origin 'external', teacher_band/teacher_comments from the official marking; the prompt is
               looked up by exact text (else taken from knowledge/data/writing_prompts*.json, else inserted bare)
               [prompt_id + origin 'external' + date]
- mock_exams   status 'finished', plan_json.external = {provider, test_code, date}, section bands and overall band
               (grading.overall_band of the sections present)  [plan_json.external.test_code]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import db, grading, importer  # noqa: E402

# Section timetable used for started_at/finished_at (minutes): the real exam order and lengths.
SCHEDULE = [("listening", 40), ("reading", 60), ("writing", 60)]
READING_PARTS = [(1, 13), (14, 26), (27, 40)]
CRITERIA_ORDER = ("TA", "TR", "CC", "LR", "GRA")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _fmt_band(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


def _parts_for(section: str, total: int) -> list[tuple[int, int]]:
    if section == "reading" and total == 40:
        return READING_PARTS
    size = 10 if section == "listening" else max(total, 1)
    return [(a, min(a + size - 1, total)) for a in range(1, total + 1, size)]


def _part_of(parts: list[tuple[int, int]], n: int) -> int:
    for i, (a, b) in enumerate(parts, 1):
        if a <= n <= b:
            return i
    return len(parts)


def _test_doc(test_id: str, section: str, title: str, rows: list[dict]) -> dict:
    by_n = {r["number"]: r for r in rows}
    parts = []
    for i, (a, b) in enumerate(_parts_for(section, len(rows)), 1):
        qs = [{"number": n, "prompt_html": "", "answer": list(by_n[n]["accepted"]), "explanation_html": None}
              for n in range(a, b + 1) if n in by_n]
        parts.append({"number": i, "title": f"Part {i}",
                      "groups": [{"range": [a, b], "type": "short_answer", "instructions_html": "",
                                  "content_html": "", "questions": qs}]})
    return {"id": test_id, "type": section, "title": title, "parts": parts}


def _upsert_test(conn, test_id: str, section: str, module: str, title: str, doc: dict, total: int) -> None:
    conn.execute(
        """INSERT INTO tests(id, type, module, title, source, question_count, file_path, data_json, imported_at)
           VALUES (?,?,?,?, 'external', ?, NULL, ?, ?)
           ON CONFLICT(id) DO UPDATE SET type=excluded.type, module=excluded.module, title=excluded.title,
             source='external', question_count=excluded.question_count, file_path=NULL,
             data_json=excluded.data_json, imported_at=excluded.imported_at""",
        (test_id, section, module, title, total, json.dumps(doc, ensure_ascii=False), db.now_iso()))


def _upsert_attempt(conn, test_id: str, section: str, module: str, mock_id: int, rows: list[dict],
                    start: datetime, minutes: int) -> dict:
    total = len(rows)
    raw = sum(1 for r in rows if r["correct"])
    band = grading.raw_to_band(raw, total, section, module)
    answers = {str(r["number"]): r["answer"] for r in rows}
    started, finished = start.isoformat(timespec="seconds"), (start + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    row = conn.execute("SELECT id FROM attempts WHERE test_id=? AND mode='mock' ORDER BY id LIMIT 1",
                       (test_id,)).fetchone()
    vals = (section, mock_id, started, finished, minutes * 60, raw, total, band,
            json.dumps(answers, ensure_ascii=False))
    if row:
        attempt_id = row[0]
        conn.execute("""UPDATE attempts SET type=?, mock_id=?, mode='mock', started_at=?, finished_at=?, duration_sec=?,
                          status='submitted', raw_score=?, total=?, band=?, answers_json=? WHERE id=?""",
                     vals + (attempt_id,))
        conn.execute("DELETE FROM attempt_answers WHERE attempt_id=?", (attempt_id,))
    else:
        attempt_id = conn.execute(
            """INSERT INTO attempts(test_id, type, mock_id, mode, started_at, finished_at, duration_sec, status,
                                    raw_score, total, band, answers_json)
               VALUES (?,?,?, 'mock', ?,?,?, 'submitted', ?,?,?,?)""", (test_id,) + vals).lastrowid
    parts = _parts_for(section, total)
    for r in rows:
        conn.execute(
            """INSERT INTO attempt_answers(attempt_id, part, question_number, question_type, user_answer,
                                           correct_answers, is_correct, question_text)
               VALUES (?,?,?, 'short_answer', ?,?,?,?)""",
            (attempt_id, _part_of(parts, r["number"]), r["number"], r["answer"],
             json.dumps(list(r["accepted"]), ensure_ascii=False), 1 if r["correct"] else 0, f"Question {r['number']}"))
    return {"attempt_id": attempt_id, "raw": raw, "total": total, "band": band}


def _prompt_id(conn, task: dict, date: str) -> int:
    text = task["prompt"]
    row = conn.execute("SELECT id FROM writing_prompts WHERE prompt=?", (text,)).fetchone()
    if row:
        return row[0]
    item = None
    for path in sorted((db.KNOWLEDGE_DIR / "data").glob("writing_prompts*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        item = next((x for x in data if isinstance(x, dict) and x.get("prompt") == text), None)
        if item:
            break
    item = item or {"task": task["task"], "prompt": text, "source": "mock_exam", "source_date": date}
    conn.execute(
        """INSERT INTO writing_prompts(task, module, essay_type, prompt, image_path, image_description, source,
                                       source_date)
           VALUES (?,?,?,?,?,?,?,?)""",
        (item.get("task"), item.get("module") or "academic", item.get("essay_type"), text,
         item.get("image") or item.get("image_path"), item.get("image_description"), item.get("source"),
         item.get("source_date")))
    return conn.execute("SELECT id FROM writing_prompts WHERE prompt=?", (text,)).fetchone()[0]


def _upsert_essay(conn, task: dict, prompt_id: int, mock_id: int, provider: str, created_at: str,
                  minutes: int) -> int:
    crit = task.get("criteria") or {}
    keys = [k for k in CRITERIA_ORDER if k in crit] + [k for k in crit if k not in CRITERIA_ORDER]
    marks = " · ".join(f"{k} {_fmt_band(crit[k])}" for k in keys)
    comments = f"Official marking ({provider}): {marks} → {_fmt_band(task['band'])}"
    if task.get("review"):
        comments += "\n\n" + task["review"]
    text = task["essay"]
    row = conn.execute("SELECT id FROM writing_submissions WHERE prompt_id=? AND origin='external' "
                       "AND substr(created_at,1,10)=? ORDER BY id LIMIT 1", (prompt_id, created_at[:10])).fetchone()
    vals = (mock_id, text, importer.word_count(text), minutes * 60, created_at, float(task["band"]), comments)
    if row:
        conn.execute("""UPDATE writing_submissions SET mock_id=?, text=?, word_count=?, time_spent_sec=?, created_at=?,
                          teacher_band=?, teacher_comments=? WHERE id=?""", vals + (row[0],))
        return row[0]
    return conn.execute(
        """INSERT INTO writing_submissions(prompt_id, mock_id, text, word_count, time_spent_sec, created_at, origin,
                                           teacher_band, teacher_comments)
           VALUES (?,?,?,?,?,?, 'external', ?,?)""", (prompt_id,) + vals).lastrowid


def run(data: dict, db_path: Path) -> dict:
    meta = data["mock"]
    date, code, provider = meta["date"], meta["test_code"], meta.get("provider") or "external"
    module = meta.get("module") or "academic"
    sections = [s for s, _ in SCHEDULE if data.get(s)]
    stamp = f"ext-{date}-{_slug(code)}"
    nice_date = datetime.strptime(date, "%Y-%m-%d").strftime("%-d %b %Y" if sys.platform != "win32" else "%#d %b %Y")
    clock = datetime.strptime(date + "T10:00:00", "%Y-%m-%dT%H:%M:%S")
    times: dict[str, tuple[datetime, int]] = {}
    for s, minutes in SCHEDULE:
        if s in sections:
            times[s] = (clock, minutes)
            clock += timedelta(minutes=minutes)
    start_iso = times[sections[0]][0].isoformat(timespec="seconds")
    end_iso = clock.isoformat(timespec="seconds")

    conn = db.connect(path=db_path)
    out: dict = {"db": str(db_path)}
    try:
        conn.execute("BEGIN")
        # prompts first: the mock plan refers to them
        tasks = (data.get("writing") or {}).get("tasks") or []
        prompt_ids = {t["task"]: _prompt_id(conn, t, date) for t in tasks}
        plan = {"sections": sections, "module": module,
                "external": {"provider": provider, "test_code": code, "date": date}}
        for s in ("listening", "reading"):
            if s in sections:
                plan[s] = f"{stamp}-{s}"
        if tasks:
            plan["writing"] = {f"task{k}": v for k, v in sorted(prompt_ids.items())}

        row = conn.execute("SELECT id FROM mock_exams WHERE json_extract(plan_json, '$.external.test_code')=? "
                           "ORDER BY id LIMIT 1", (code,)).fetchone()
        if row:
            mock_id = row[0]
        else:
            mock_id = conn.execute("INSERT INTO mock_exams(created_at, status) VALUES (?, 'finished')",
                                   (start_iso,)).lastrowid
        out["mock_id"] = mock_id

        bands: dict[str, float | None] = {}
        for s in ("listening", "reading"):
            if s not in sections:
                continue
            rows = sorted(data[s]["answers"], key=lambda r: r["number"])
            test_id = plan[s]
            title = f"Mock exam {nice_date} ({code}) — {s.capitalize()}"
            _upsert_test(conn, test_id, s, module, title, _test_doc(test_id, s, title, rows), len(rows))
            res = _upsert_attempt(conn, test_id, s, module, mock_id, rows, *times[s])
            out[s] = {"test_id": test_id, **res}
            bands[s] = res["band"]

        if tasks:
            w_start, w_minutes = times["writing"]
            essay_ids = {}
            for t in sorted(tasks, key=lambda t: t["task"]):
                minutes = 20 if t["task"] == 1 else 40
                created = (w_start + timedelta(minutes=20 if t["task"] == 1 else 60)).isoformat(timespec="seconds")
                essay_ids[t["task"]] = _upsert_essay(conn, t, prompt_ids[t["task"]], mock_id, provider, created, minutes)
            wband = data["writing"].get("overall")
            bands["writing"] = float(wband) if wband is not None else None
            out["writing"] = {"prompt_ids": prompt_ids, "submission_ids": essay_ids, "band": bands["writing"]}

        overall = grading.overall_band(bands.get(s) for s in sections) \
            if all(bands.get(s) is not None for s in sections) else None
        conn.execute(
            """UPDATE mock_exams SET created_at=?, finished_at=?, status='finished', plan_json=?, listening_band=?,
                 reading_band=?, writing_band=?, speaking_band=NULL, overall_band=? WHERE id=?""",
            (start_iso, end_iso, json.dumps(plan, ensure_ascii=False), bands.get("listening"), bands.get("reading"),
             bands.get("writing"), overall, mock_id))
        out["overall_band"] = overall
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file", type=Path, help="external mock JSON (see module docstring)")
    ap.add_argument("--db", type=Path, default=db.DATA_DIR / "ielts.db", help="database path (default: app DB)")
    args = ap.parse_args()
    if not args.db.is_file():
        sys.exit(f"database not found: {args.db} (start the app once to create it)")
    data = json.loads(args.file.read_text(encoding="utf-8"))
    out = run(data, args.db)
    print(f"DB: {out['db']}")
    print(f"mock_exams id {out['mock_id']}")
    for s in ("listening", "reading"):
        if s in out:
            r = out[s]
            print(f"{s:9s} test {r['test_id']}  attempt {r['attempt_id']}  {r['raw']}/{r['total']}  band {r['band']}")
    if "writing" in out:
        w = out["writing"]
        print(f"writing   prompts {w['prompt_ids']}  submissions {w['submission_ids']}  band {w['band']}")
    print(f"overall   {out['overall_band']}")


if __name__ == "__main__":
    main()
