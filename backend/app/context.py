"""Build concise, LLM-ready context text from the database.

Used by the AI runner (embedded in the prompt) and by tools/ielts_db.py (printed). All functions
only read from the connection, so they work on a `mode=ro` connection.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from . import db
from .grading import html_to_text, iter_questions, normalise

STOPWORDS = set("""a an the and or but of to in on at for with by from as is are was were be been being it its
this that these those there their they them he she his her we our you your i my me not no do does did
have has had can could will would should may might must which who whom what when where why how than then
so such into over under about after before between during also more most other some any each all""".split())


def _fmt_dur(sec: Any) -> str:
    try:
        sec = int(float(sec))
    except (TypeError, ValueError):
        return "?"
    return f"{sec // 60}m{sec % 60:02d}s"


def _clip(text: str | None, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 3].rstrip() + "..."


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOPWORDS and len(w) > 2}


def _load_test(conn: sqlite3.Connection, test_id: str) -> dict | None:
    row = conn.execute("SELECT data_json FROM tests WHERE id = ?", (test_id,)).fetchone()
    return db.loads(row[0]) if row else None


# --------------------------------------------------------------------------- previous analyses
def latest_ai_band(conn: sqlite3.Connection, target_type: str, target_id: int) -> float | None:
    for r in conn.execute(
            "SELECT result_json FROM ai_analyses WHERE target_type=? AND target_id=? AND status='done' "
            "AND result_json IS NOT NULL ORDER BY id DESC", (target_type, target_id)):
        data = db.loads(r[0], {})
        band = data.get("band") if isinstance(data, dict) else None
        try:
            return float(band) if band is not None else None
        except (TypeError, ValueError):
            continue
    return None


def _item_text(x: Any) -> str:
    if isinstance(x, dict):
        for k in ("summary", "text", "mistake", "tip", "issue", "description", "title", "type", "category"):
            if x.get(k):
                return str(x[k])
        return json.dumps(x, ensure_ascii=False)
    return str(x)


def summarize_analysis(row: sqlite3.Row) -> str:
    data = db.loads(row["result_json"], {}) or {}
    head = f"- #{row['id']} {row['target_type']} {row['target_id']} ({(row['finished_at'] or row['created_at'] or '')[:10]})"
    if isinstance(data, dict) and data.get("band") is not None:
        head += f" band {data['band']}"
    parts = [head]
    if isinstance(data, dict):
        crit = data.get("criteria")
        if isinstance(crit, dict) and crit:
            parts.append("  criteria: " + ", ".join(f"{k} {v if not isinstance(v, dict) else v.get('band', '')}"
                                                     for k, v in crit.items()))
        for key in ("mistakes", "tips"):
            items = data.get(key) or []
            if isinstance(items, list) and items:
                parts.append(f"  {key}: " + "; ".join(_clip(_item_text(x), 140) for x in items[:4]))
    if len(parts) == 1 and row["result_md"]:
        parts.append("  " + _clip(re.sub(r"\s+", " ", row["result_md"]), 300))
    return "\n".join(parts)


def previous_analyses_text(conn: sqlite3.Connection, target_types: tuple[str, ...],
                           target_id: int | None = None, limit: int = 3,
                           exclude_id: int | None = None) -> str:
    q = ("SELECT * FROM ai_analyses WHERE status='done' AND target_type IN (%s)"
         % ",".join("?" * len(target_types)))
    args: list[Any] = list(target_types)
    if target_id is not None:
        q += " AND target_id = ?"
        args.append(target_id)
    if exclude_id is not None:
        q += " AND id <> ?"
        args.append(exclude_id)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(q, args).fetchall()
    return "\n".join(summarize_analysis(r) for r in rows)


def type_accuracy(conn: sqlite3.Connection, test_type: str | None = None) -> list[dict]:
    q = """SELECT aa.question_type AS type, SUM(aa.is_correct) AS correct, COUNT(*) AS total
           FROM attempt_answers aa JOIN attempts a ON a.id = aa.attempt_id
           WHERE a.status = 'submitted'"""
    args: list[Any] = []
    if test_type:
        q += " AND a.type = ?"
        args.append(test_type)
    q += " GROUP BY aa.question_type ORDER BY CAST(SUM(aa.is_correct) AS REAL) / COUNT(*)"
    return [dict(r) for r in conn.execute(q, args)]


def weaknesses_text(conn: sqlite3.Connection, test_type: str | None = None, min_total: int = 3) -> str:
    lines = []
    for r in type_accuracy(conn, test_type):
        if r["total"] >= min_total and r["correct"] / r["total"] < 0.75:
            lines.append(f"- {r['type']}: {r['correct']}/{r['total']} correct "
                         f"({round(100 * r['correct'] / r['total'])}%)")
    return "\n".join(lines) or "- (no clear weak question types yet)"


# --------------------------------------------------------------------------- test text
def _paragraphs(passage_html: str | None) -> list[str]:
    return [p for p in html_to_text(passage_html).splitlines() if p.strip()]


def test_text(conn: sqlite3.Connection, test_id: str, part: int | None = None,
              with_answers: bool = True) -> str:
    test = _load_test(conn, test_id)
    if not test:
        return f"Test {test_id} not found."
    out = [f"# {test.get('title')} ({test.get('id')}) — {test.get('type')}, {test.get('module')}"]
    for p in test.get("parts") or []:
        if part is not None and p.get("number") != part:
            continue
        out.append(f"\n## Part {p.get('number')}: {p.get('title') or ''}")
        if p.get("passage_html"):
            out.append("### Passage\n" + "\n\n".join(_paragraphs(p["passage_html"])))
        if p.get("transcript_html"):
            out.append("### Transcript\n" + html_to_text(p["transcript_html"]))
        for g in p.get("groups") or []:
            rng = g.get("range") or []
            out.append(f"\n### Questions {'-'.join(str(x) for x in rng)} [{g.get('type')}]")
            instr = html_to_text(g.get("instructions_html"))
            if instr:
                out.append(instr)
            if g.get("content_html"):
                out.append(html_to_text(g["content_html"]))
            if g.get("options"):
                out.append("Options: " + " | ".join(f"{o.get('key')}) {html_to_text(str(o.get('text') or ''))}"
                                                    for o in g["options"]))
            for q in g.get("questions") or []:
                line = f"Q{q.get('number')}: {html_to_text(q.get('prompt_html')).replace(chr(10), ' ')}"
                if q.get("options"):
                    line += "  [" + " | ".join(f"{o.get('key')}) {html_to_text(str(o.get('text') or ''))}"
                                              for o in q["options"]) + "]"
                if with_answers:
                    line += f"  => answer: {' / '.join(str(a) for a in q.get('answer') or [])}"
                out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------- attempt
def _relevant_paragraphs(paragraphs: list[str], query: str, answers: list[str], top: int = 1) -> list[int]:
    qt = _tokens(query) | _tokens(" ".join(answers))
    scored = []
    for i, para in enumerate(paragraphs):
        low = para.lower()
        score = len(qt & _tokens(para))
        for a in answers:
            a = normalise(a)
            if len(a) > 2 and a.lower() in low:
                score += 5
        scored.append((score, i))
    scored.sort(reverse=True)
    return [i for s, i in scored[:top] if s > 0]


def _transcript_windows(text: str, answers: list[str], query: str, width: int = 260) -> list[tuple[int, int]]:
    low = text.lower()
    wins = []
    for a in answers:
        a = normalise(a)
        if len(a) < 2:
            continue
        i = low.find(a)
        if i >= 0:
            wins.append((max(0, i - width), min(len(text), i + len(a) + width)))
            break
    if not wins:
        lines = text.splitlines()
        best = _relevant_paragraphs(lines, query, answers, top=1)
        if best:
            start = sum(len(l) + 1 for l in lines[:best[0]])
            wins.append((max(0, start - 100), min(len(text), start + len(lines[best[0]]) + 150)))
    return wins


def _merge(wins: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for s, e in sorted(wins):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def attempt_context(conn: sqlite3.Connection, attempt_id: int, exclude_analysis: int | None = None) -> str:
    a = conn.execute("SELECT a.*, t.title, t.module FROM attempts a LEFT JOIN tests t ON t.id = a.test_id "
                     "WHERE a.id = ?", (attempt_id,)).fetchone()
    if not a:
        return f"Attempt {attempt_id} not found."
    test = _load_test(conn, a["test_id"]) or {}
    answers = conn.execute("SELECT * FROM attempt_answers WHERE attempt_id = ? ORDER BY question_number",
                           (attempt_id,)).fetchall()
    out = [f"# {a['type'].title() if a['type'] else 'Test'} attempt #{a['id']}: {a['title']} ({a['test_id']})",
           f"Module: {a['module']} | mode: {a['mode']} | status: {a['status']} | started: {a['started_at']} | "
           f"time used: {_fmt_dur(a['duration_sec'])}",
           f"Score: {a['raw_score']}/{a['total']} -> band {a['band']}"]
    if a["mode"] == "imported":
        out[-1] = f"Band {a['band']} (imported from the learner's own records — band only, no per-question answers)"
        out.append("No individual answers exist for this attempt: do not invent mistakes. Comment on the band in "
                   "the context of the learner's other results and suggest redoing the test in the app for a "
                   "question-level analysis.")
        return "\n".join(out)
    if a["status"] != "submitted":
        out.append("(Attempt not submitted yet — no graded answers.)")
        return "\n".join(out)

    by_type: dict[str, list[int]] = {}
    for r in answers:
        t = by_type.setdefault(r["question_type"] or "?", [0, 0])
        t[0] += r["is_correct"] or 0
        t[1] += 1
    out.append("\n## Score by question type")
    out += [f"- {k}: {v[0]}/{v[1]}" for k, v in sorted(by_type.items(), key=lambda kv: kv[1][0] / kv[1][1])]

    wrong = [r for r in answers if not r["is_correct"]]
    right = [str(r["question_number"]) for r in answers if r["is_correct"]]
    out.append(f"\n## Mistakes ({len(wrong)})")
    explanations = {q.get("number"): q.get("explanation_html") for _, _, q in iter_questions(test)}
    for r in wrong:
        ua = r["user_answer"] or "(blank)"
        ca = " / ".join(db.loads(r["correct_answers"], []) or [])
        out.append(f"\nQ{r['question_number']} (part {r['part']}, {r['question_type']})\n"
                   f"{r['question_text']}\n  your answer: {ua}\n  correct: {ca}")
        ex = explanations.get(r["question_number"])
        if ex:
            ex_text = html_to_text(ex).replace("\n", " ")
            ex_text = ex_text.split(" Excerpt/Transcript Explanation:")[0]  # keep the evidence quote only
            out.append("  evidence: " + _clip(ex_text, 350))
    out.append(f"\nCorrect: Q{', Q'.join(right)}" if right else "\nCorrect: none")

    # evidence from passages / transcripts for the parts with mistakes
    parts = {p.get("number"): p for p in test.get("parts") or []}
    wrong_by_part: dict[int, list[sqlite3.Row]] = {}
    for r in wrong:
        wrong_by_part.setdefault(r["part"], []).append(r)
    if wrong_by_part:
        out.append("\n## Evidence (passage / transcript excerpts for the mistakes)")
    for pno, rows in sorted(wrong_by_part.items(), key=lambda kv: kv[0] or 0):
        part = parts.get(pno) or {}
        if part.get("passage_html"):
            paras = _paragraphs(part["passage_html"])
            chosen: set[int] = set()
            for r in rows:
                chosen.update(_relevant_paragraphs(paras, r["question_text"] or "",
                                                   db.loads(r["correct_answers"], []) or [], top=1))
            out.append(f"\n### Passage {pno}: {part.get('title') or ''} (relevant paragraphs)")
            for i in sorted(chosen)[:6]:
                out.append(_clip(paras[i], 1500))
        elif part.get("transcript_html"):
            text = html_to_text(part["transcript_html"])
            wins: list[tuple[int, int]] = []
            for r in rows:
                wins += _transcript_windows(text, db.loads(r["correct_answers"], []) or [], r["question_text"] or "")
            out.append(f"\n### Listening part {pno} transcript excerpts")
            for s, e in _merge(wins)[:8]:
                out.append(("..." if s else "") + text[s:e].replace("\n", " ") + ("..." if e < len(text) else ""))
        elif a["type"] == "listening":
            out.append(f"\n### Listening part {pno}: no transcript available.")

    out.append(f"\n## Recurring weaknesses ({a['type']}, all submitted attempts)")
    out.append(weaknesses_text(conn, a["type"]))
    prev = previous_analyses_text(conn, ("attempt",), None, 3, exclude_analysis)
    if prev:
        out.append("\n## Previous AI analyses (latest attempts)\n" + prev)
    return "\n".join(out)


# --------------------------------------------------------------------------- writing
def writing_context(conn: sqlite3.Connection, submission_id: int, exclude_analysis: int | None = None) -> str:
    s = conn.execute(
        "SELECT s.*, p.task, p.module, p.essay_type, p.prompt, p.image_path, p.image_description, p.source "
        "FROM writing_submissions s LEFT JOIN writing_prompts p ON p.id = s.prompt_id WHERE s.id = ?",
        (submission_id,)).fetchone()
    if not s:
        return f"Writing submission {submission_id} not found."
    minimum = 150 if s["task"] == 1 else 250
    limit_min = 20 if s["task"] == 1 else 40
    out = [f"# Writing Task {s['task']} submission #{s['id']} ({s['module']}, {s['essay_type'] or 'type ?'})",
           f"Date: {s['created_at']} | origin: {s['origin']} | words: {s['word_count']} "
           f"(minimum {minimum}{' — UNDER LENGTH' if (s['word_count'] or 0) < minimum else ''}) | "
           f"time spent: {_fmt_dur(s['time_spent_sec']) if s['time_spent_sec'] else 'unknown'} "
           f"(recommended {limit_min} min)",
           "\n## Prompt", s["prompt"] or "(missing)"]
    if s["image_path"]:
        out.append(f"Image: content/{s['image_path']}")
    if s["image_description"]:
        out.append("Image description (data shown in the visual):\n" + s["image_description"])
    elif s["task"] == 1:
        out.append("(No image description available — judge data accuracy cautiously.)")
    out += ["\n## Candidate's essay", s["text"] or ""]
    keys = s.keys()
    if "teacher_band" in keys and (s["teacher_band"] is not None or s["teacher_comments"]):
        out.append(f"\n## Teacher feedback (from the class chat)\nband: {s['teacher_band']}\n"
                   f"{s['teacher_comments'] or ''}".rstrip())
    hist = conn.execute(
        "SELECT s.id, s.created_at, s.word_count FROM writing_submissions s JOIN writing_prompts p ON p.id=s.prompt_id "
        "WHERE p.task = ? AND s.id <> ? ORDER BY s.created_at DESC LIMIT 8", (s["task"], s["id"])).fetchall()
    if hist:
        out.append(f"\n## Previous Task {s['task']} submissions")
        for h in hist:
            band = latest_ai_band(conn, "writing", h["id"])
            out.append(f"- #{h['id']} {str(h['created_at'])[:10]}: {h['word_count']} words"
                       + (f", AI band {band}" if band is not None else ""))
    prev = previous_analyses_text(conn, ("writing",), None, 3, exclude_analysis)
    if prev:
        out.append("\n## Previous AI writing analyses\n" + prev)
    return "\n".join(out)


# --------------------------------------------------------------------------- speaking
def _metrics_line(m: dict | None) -> str:
    if not m:
        return "metrics: n/a"
    keys = ("duration", "words", "wpm", "pause_count", "long_pauses", "filler_count")
    line = "metrics: " + ", ".join(f"{k}={m.get(k)}" for k in keys if m.get(k) is not None)
    if m.get("fillers"):
        line += " | fillers: " + ", ".join(f"{k}x{v}" for k, v in m["fillers"].items())
    lc = m.get("low_confidence_words") or []
    if lc:
        line += " | unclear words: " + ", ".join(f"'{w.get('word')}'@{w.get('start')}s" for w in lc[:15])
    return line


def speaking_context(conn: sqlite3.Connection, session_id: int, exclude_analysis: int | None = None) -> str:
    s = conn.execute("SELECT * FROM speaking_sessions WHERE id = ?", (session_id,)).fetchone()
    if not s:
        return f"Speaking session {session_id} not found."
    rows = conn.execute("SELECT * FROM speaking_responses WHERE session_id = ? ORDER BY part, id",
                        (session_id,)).fetchall()
    out = [f"# Speaking session #{s['id']} (mode {s['mode']}), {s['created_at']}, {len(rows)} responses"]
    if s["teacher_band"] is not None:
        out.append(f"Teacher-assessed band {s['teacher_band']} for: {s['notes']} (from the learner's records; "
                   "no recordings or transcripts exist — do not invent answer-level feedback)")
    tot_words = tot_dur = tot_fill = tot_pause = 0.0
    for r in rows:
        m = db.loads(r["metrics_json"], {}) or {}
        src = "whisper" if r["transcribe_status"] == "done" else "browser speech recognition"
        out.append(f"\n## Response {r['id']} · Part {r['part']} — {r['question_text']}\n"
                   f"duration {r['duration_sec']}s | transcript source: {src} ({r['transcribe_status']})\n"
                   f"{_metrics_line(m)}\nTranscript: {r['transcript'] or r['browser_transcript'] or '(empty)'}")
        tot_words += m.get("words") or 0
        tot_dur += m.get("duration") or r["duration_sec"] or 0
        tot_fill += m.get("filler_count") or 0
        tot_pause += m.get("long_pauses") or 0
    if tot_dur:
        out.append(f"\n## Session totals\nwords {int(tot_words)}, speaking time {round(tot_dur)}s, "
                   f"avg wpm {round(tot_words / tot_dur * 60)}, fillers {int(tot_fill)}, long pauses {int(tot_pause)}")
    prev = previous_analyses_text(conn, ("speaking_session",), None, 3, exclude_analysis)
    if prev:
        out.append("\n## Previous AI speaking analyses\n" + prev)
    return "\n".join(out)


# --------------------------------------------------------------------------- mock
def mock_links(conn: sqlite3.Connection, mock_id: int) -> dict[str, list[int]]:
    return {
        "listening": [r[0] for r in conn.execute(
            "SELECT id FROM attempts WHERE mock_id=? AND type='listening' ORDER BY id", (mock_id,))],
        "reading": [r[0] for r in conn.execute(
            "SELECT id FROM attempts WHERE mock_id=? AND type='reading' ORDER BY id", (mock_id,))],
        "writing": [r[0] for r in conn.execute(
            "SELECT id FROM writing_submissions WHERE mock_id=? ORDER BY id", (mock_id,))],
        "speaking": [r[0] for r in conn.execute(
            "SELECT id FROM speaking_sessions WHERE mock_id=? ORDER BY id", (mock_id,))],
    }


def mock_context(conn: sqlite3.Connection, mock_id: int, exclude_analysis: int | None = None) -> str:
    m = conn.execute("SELECT * FROM mock_exams WHERE id = ?", (mock_id,)).fetchone()
    if not m:
        return f"Mock exam {mock_id} not found."
    links = mock_links(conn, mock_id)
    out = [f"# Mock exam #{m['id']} ({m['status']}) created {m['created_at']}, finished {m['finished_at'] or '-'}",
           f"Bands: listening {m['listening_band']}, reading {m['reading_band']}, writing {m['writing_band']}, "
           f"speaking {m['speaking_band']} -> overall {m['overall_band']}"]
    for sec in ("listening", "reading"):
        for aid in links[sec]:
            a = conn.execute("SELECT * FROM attempts WHERE id=?", (aid,)).fetchone()
            out.append(f"\n## {sec.title()} attempt #{aid} ({a['test_id']}): {a['raw_score']}/{a['total']} band {a['band']}")
            wrong = conn.execute("SELECT question_type, COUNT(*) n FROM attempt_answers WHERE attempt_id=? "
                                 "AND is_correct=0 GROUP BY question_type ORDER BY n DESC", (aid,)).fetchall()
            if wrong:
                out.append("wrong by type: " + ", ".join(f"{w[0]} {w[1]}" for w in wrong))
            prev = previous_analyses_text(conn, ("attempt",), aid, 1)
            if prev:
                out.append("AI analysis: " + prev)
    for wid in links["writing"]:
        out.append("\n" + writing_context(conn, wid).split("\n## Previous")[0])
        band = latest_ai_band(conn, "writing", wid)
        out.append(f"AI band: {band}")
    for sid in links["speaking"]:
        out.append("\n" + speaking_context(conn, sid).split("\n## Previous")[0])
        out.append(f"AI band: {latest_ai_band(conn, 'speaking_session', sid)}")
    prev = previous_analyses_text(conn, ("mock",), None, 2, exclude_analysis)
    if prev:
        out.append("\n## Previous mock analyses\n" + prev)
    return "\n".join(out)


# --------------------------------------------------------------------------- progress
def progress_context(conn: sqlite3.Connection, exclude_analysis: int | None = None) -> str:
    out = ["# Progress overview (all history)"]
    ext = conn.execute("SELECT * FROM external_results WHERE is_mine = 1 ORDER BY date").fetchall()
    if ext:
        out.append("\n## External results (trial exams / screenshots — baseline)")
        for e in ext:
            scores = ", ".join(f"{k[0].upper()} {e[k]}" for k in ("listening", "reading", "writing", "speaking", "overall")
                               if e[k] is not None)
            out.append(f"- {e['date']}: {scores} — {_clip(e['notes'], 160)}")
    for t in ("listening", "reading"):
        rows = conn.execute("SELECT finished_at, test_id, raw_score, total, band, mode FROM attempts "
                            "WHERE type=? AND status='submitted' ORDER BY finished_at DESC LIMIT 30", (t,)).fetchall()
        out.append(f"\n## {t.title()} — {len(rows)} recent attempts (newest first)")
        out += [f"- {str(r['finished_at'])[:10]} {r['test_id']} "
                + (f"{r['raw_score']}/{r['total']} " if r["raw_score"] is not None else "")
                + f"band {r['band']} ({r['mode']})" for r in rows]
        out.append("Accuracy by question type (weakest first):")
        out += [f"- {r['type']}: {r['correct']}/{r['total']} ({round(100 * r['correct'] / r['total'])}%)"
                for r in type_accuracy(conn, t)]
    rows = conn.execute("SELECT s.id, s.created_at, s.word_count, s.origin, s.teacher_band, p.task, p.essay_type "
                        "FROM writing_submissions s LEFT JOIN writing_prompts p ON p.id=s.prompt_id "
                        "ORDER BY s.created_at DESC LIMIT 15").fetchall()
    out.append(f"\n## Writing — {len(rows)} recent submissions")
    for r in rows:
        band = latest_ai_band(conn, "writing", r["id"])
        out.append(f"- #{r['id']} {str(r['created_at'])[:10]} T{r['task']} {r['essay_type'] or ''} {r['word_count']}w"
                   f" ({r['origin']})" + (f" AI band {band}" if band is not None else "")
                   + (f" teacher band {r['teacher_band']}" if r["teacher_band"] is not None else ""))
    teacher = conn.execute("SELECT created_at, teacher_band, notes FROM speaking_sessions "
                           "WHERE teacher_band IS NOT NULL ORDER BY created_at").fetchall()
    if teacher:
        out.append("\n## Speaking — bands from the learner's records (teacher-assessed, no recordings)")
        out += [f"- {str(r['created_at'])[:10]} {r['notes']}: band {r['teacher_band']}" for r in teacher]
    rows = conn.execute("SELECT session_id, metrics_json FROM speaking_responses WHERE metrics_json IS NOT NULL "
                        "ORDER BY id DESC LIMIT 60").fetchall()
    if rows:
        ms = [db.loads(r["metrics_json"], {}) or {} for r in rows]
        wpm = [m["wpm"] for m in ms if m.get("wpm")]
        fill = sum(m.get("filler_count") or 0 for m in ms)
        words = sum(m.get("words") or 0 for m in ms) or 1
        out.append(f"\n## Speaking — last {len(rows)} responses: avg wpm {round(sum(wpm) / len(wpm)) if wpm else '?'}, "
                   f"fillers per 100 words {round(100 * fill / words, 1)}, "
                   f"long pauses {sum(m.get('long_pauses') or 0 for m in ms)}")
        sess = conn.execute("SELECT id FROM speaking_sessions ORDER BY id DESC LIMIT 8").fetchall()
        bands = [(r[0], latest_ai_band(conn, "speaking_session", r[0])) for r in sess]
        bands = [f"#{i} {b}" for i, b in bands if b is not None]
        if bands:
            out.append("Speaking AI bands (newest first): " + ", ".join(bands))
    mocks = conn.execute("SELECT * FROM mock_exams WHERE status='finished' ORDER BY id DESC LIMIT 5").fetchall()
    if mocks:
        out.append("\n## Mock exams")
        out += [f"- #{m['id']} {str(m['finished_at'])[:10]}: L {m['listening_band']} R {m['reading_band']} "
                f"W {m['writing_band']} S {m['speaking_band']} -> {m['overall_band']}" for m in mocks]
    out.append("\n## Recurring mistakes / tips from recent AI analyses")
    prev = previous_analyses_text(conn, ("attempt", "writing", "speaking_session", "mock", "progress"),
                                  None, 8, exclude_analysis)
    out.append(prev or "- (no analyses yet)")
    return "\n".join(out)


# --------------------------------------------------------------------------- dispatch / misc
TARGET_TYPES = ("attempt", "writing", "speaking_session", "mock", "progress")


def build_context(conn: sqlite3.Connection, target_type: str, target_id: int | None,
                  exclude_analysis: int | None = None) -> str:
    if target_type == "attempt":
        return attempt_context(conn, int(target_id), exclude_analysis)
    if target_type == "writing":
        return writing_context(conn, int(target_id), exclude_analysis)
    if target_type == "speaking_session":
        return speaking_context(conn, int(target_id), exclude_analysis)
    if target_type == "mock":
        return mock_context(conn, int(target_id), exclude_analysis)
    if target_type == "progress":
        return progress_context(conn, exclude_analysis)
    raise ValueError(f"unknown target_type {target_type!r}")


def target_exists(conn: sqlite3.Connection, target_type: str, target_id: int | None) -> bool:
    table = {"attempt": "attempts", "writing": "writing_submissions", "speaking_session": "speaking_sessions",
             "mock": "mock_exams"}.get(target_type)
    if target_type == "progress":
        return True
    if not table:
        return False
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (target_id,)).fetchone() is not None


def schema_text(conn: sqlite3.Connection) -> str:
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type IN ('table','index') AND sql IS NOT NULL "
                        "AND name NOT LIKE 'kb_fts_%' ORDER BY type DESC, name").fetchall()
    return "\n\n".join(r["sql"] + ";" for r in rows)


def fts_query(q: str) -> str:
    terms = re.findall(r"\w+", q or "")
    return " ".join(f'"{t}"*' for t in terms)


def kb_search(conn: sqlite3.Connection, q: str, limit: int = 20) -> list[dict]:
    match = fts_query(q)
    if not match:
        return []
    rows = conn.execute(
        "SELECT d.slug, d.title, d.category, d.tags, snippet(kb_fts, 1, '[', ']', ' … ', 16) AS snippet "
        "FROM kb_fts JOIN kb_docs d ON d.id = kb_fts.rowid WHERE kb_fts MATCH ? ORDER BY rank LIMIT ?",
        (match, limit)).fetchall()
    return [dict(r) for r in rows]


def kb_doc(conn: sqlite3.Connection, slug: str) -> dict | None:
    row = conn.execute("SELECT * FROM kb_docs WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None
