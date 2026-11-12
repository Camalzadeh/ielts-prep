"""AI Research lessons (branch `research`).

One lesson per file: knowledge/research/lessons/<slug>.json, made from a research paper, forum thread, course
or article about AI. The importer spreads each lesson over the normal sections, all with source "research":
- the reading -> a passage of a full Cambridge-style test in the Reading library (series "AI Research"):
  knowledge/research/tests.json groups three lessons into `research-test-<n>` (Passages 1-3, 40 questions,
  60 minutes; the third lesson has 14 questions). A lesson not in any group is a one-passage test
  `research-<slug>` (20 minutes) until it is grouped,
- the writing tasks -> writing prompts in the Writing bank (tags "research,<slug>"),
- the notes (summary_md, key terms, sources, discussion) -> a knowledge-base guide `research-<slug>`
  (category "ai-research") with links to its reading and writing,
- the key terms -> flashcards (topic "AI Research").

Never in mock exams or random picks. Setting `show_research` ("1" by default) hides all of it.
Format: knowledge/research/README.md.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from . import db

SOURCE = "research"
SERIES = "AI Research"
VOCAB_TOPIC = "AI Research"
SETTING = "show_research"
KB_CATEGORY = "ai-research"
DEFAULT_MINUTES = 20

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_cache: dict[Path, tuple[float, dict | None]] = {}


def lessons_dir() -> Path:
    return db.KNOWLEDGE_DIR / "research" / "lessons"


def enabled(conn) -> bool:
    return db.get_setting(conn, SETTING) != "0"


def lesson_files() -> list[Path]:
    d = lessons_dir()
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _read(path: Path, errors: list[str] | None) -> dict | None:
    """Parse one lesson file (cached until it changes). The id defaults to the file name."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    lesson: dict | None = None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        data["id"] = str(data.get("id") or path.stem)
        if not _SLUG.match(data["id"]):
            raise ValueError(f"bad id {data['id']!r} (lowercase letters, digits and hyphens)")
        if not data.get("title"):
            raise ValueError("missing title")
        lesson = data
    except (OSError, ValueError) as exc:
        if errors is not None:
            errors.append(f"knowledge/research/lessons/{path.name}: {exc}")
    _cache[path] = (mtime, lesson)
    return lesson


def load_lessons(errors: list[str] | None = None) -> list[tuple[Path, dict]]:
    out, seen = [], set()
    for path in lesson_files():
        lesson = _read(path, errors)
        if not lesson:
            continue
        if lesson["id"] in seen:
            if errors is not None:
                errors.append(f"knowledge/research/lessons/{path.name}: duplicate id {lesson['id']!r}")
            continue
        seen.add(lesson["id"])
        out.append((path, lesson))
    return out


def get_lesson(lesson_id: str) -> dict | None:
    return next((l for _, l in load_lessons() if l["id"] == lesson_id), None)


def test_id(lesson: dict) -> str:
    return f"research-{lesson['id']}"


def lesson_test(lesson: dict) -> dict | None:
    """The lesson's reading as a normal test document (None if it has no reading yet)."""
    reading = lesson.get("reading")
    if not isinstance(reading, dict) or not isinstance(reading.get("parts"), list) or not reading["parts"]:
        return None
    sources = lesson.get("sources") or []
    first_url = next((s.get("url") for s in sources if isinstance(s, dict) and s.get("url")), None)
    return {**reading, "id": test_id(lesson), "type": "reading", "module": "academic",
            "title": reading.get("title") or f"AI Research — {lesson['title']}", "series": SERIES,
            "book": None, "test_no": None, "source": SOURCE, "source_url": first_url,
            "duration_minutes": reading.get("duration_minutes") or DEFAULT_MINUTES}


FULL_MINUTES = 60
_INTRO = re.compile(r"^\s*<p><em>You should spend.*?</em></p>", re.S)


def tests_file() -> Path:
    return db.KNOWLEDGE_DIR / "research" / "tests.json"


def _shift(html: str | None, off: int) -> str | None:
    """Renumber the {{n}} blanks and 'Questions a-b' references in question HTML by `off`."""
    if not html or not off:
        return html
    html = re.sub(r"\{\{(\d+)\}\}", lambda m: "{{%d}}" % (int(m.group(1)) + off), html)
    return re.sub(r"(Questions?\s+)(\d+)(?:(\s*[-–]\s*)(\d+))?",
                  lambda m: f"{m.group(1)}{int(m.group(2)) + off}"
                  + (f"{m.group(3)}{int(m.group(4)) + off}" if m.group(4) else ""), html)


def _renumbered_part(lesson: dict, number: int, off: int) -> tuple[dict, int]:
    """The lesson's passage as part `number` of a full test, questions shifted by `off`; returns (part, last Q)."""
    part = copy.deepcopy(lesson["reading"]["parts"][0])
    last = off
    for g in part.get("groups") or []:
        g["range"] = [g["range"][0] + off, g["range"][1] + off]
        last = max(last, g["range"][1])
        for k in ("instructions_html", "content_html"):
            g[k] = _shift(g.get(k), off)
        for q in g.get("questions") or []:
            q["number"] += off
            q["prompt_html"] = _shift(q.get("prompt_html"), off)
    intro = (f"<p><em>You should spend about 20 minutes on Questions {off + 1}-{last}, which are based on "
             f"Reading Passage {number} below.</em></p>")
    body = part.get("passage_html") or ""
    part["passage_html"] = _INTRO.sub(intro, body, count=1) if _INTRO.match(body) else intro + body
    part["number"] = number
    return part, last


def full_test_specs(errors: list[str] | None = None) -> list[dict]:
    """tests.json: [{"test_no": 1, "lessons": [id, id, id]}], only groups whose lessons all have a reading."""
    path = tests_file()
    if not path.is_file():
        return []
    try:
        specs = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        if errors is not None:
            errors.append(f"knowledge/research/tests.json: {exc}")
        return []
    have = {l["id"] for _, l in load_lessons() if lesson_test(l)}
    out = []
    for spec in specs if isinstance(specs, list) else []:
        ids = spec.get("lessons") if isinstance(spec, dict) else None
        if not ids or not isinstance(spec.get("test_no"), int) or any(i not in have for i in ids):
            if errors is not None:
                errors.append(f"knowledge/research/tests.json: bad or incomplete test {spec!r}")
            continue
        out.append(spec)
    return out


def reading_tests(errors: list[str] | None = None) -> list[tuple[dict, Path]]:
    """Every AI Research reading test to import, with the file it comes from."""
    lessons = {l["id"]: (path, l) for path, l in load_lessons(errors)}
    out, grouped = [], set()
    for spec in full_test_specs(errors):
        parts, last = [], 0
        for n, lid in enumerate(spec["lessons"], 1):
            part, last = _renumbered_part(lessons[lid][1], n, last)
            parts.append(part)
        grouped.update(spec["lessons"])
        out.append(({"id": f"research-test-{spec['test_no']}", "type": "reading", "module": "academic",
                     "title": f"AI Research Test {spec['test_no']}", "series": SERIES, "book": None,
                     "test_no": spec["test_no"], "source": SOURCE, "source_url": None,
                     "duration_minutes": FULL_MINUTES, "parts": parts}, tests_file()))
    for lid, (path, lesson) in lessons.items():
        test = lesson_test(lesson)
        if test and lid not in grouped:
            out.append((test, path))
    return out


def reading_location(lesson_id: str) -> tuple[str, int | None] | None:
    """(test id, passage number or None) where the lesson's reading is played."""
    for spec in full_test_specs():
        if lesson_id in spec["lessons"]:
            return f"research-test-{spec['test_no']}", spec["lessons"].index(lesson_id) + 1
    lesson = get_lesson(lesson_id)
    return (test_id(lesson), None) if lesson and lesson_test(lesson) else None


def lesson_prompts(lesson: dict) -> list[dict]:
    """The lesson's writing tasks as writing-prompt items for the importer."""
    out = []
    for w in lesson.get("writing") or []:
        if isinstance(w, dict) and w.get("prompt") and w.get("task") in (1, 2):
            out.append({**w, "module": "academic", "source": SOURCE, "source_date": lesson.get("added"),
                        "tags": f"{SOURCE},{lesson['id']}"})
    return out


def prompt_texts() -> set[str]:
    """Every research prompt a lesson file provides (so the stale-prompt pruning keeps them)."""
    return {str(p["prompt"]).strip() for _, l in load_lessons() for p in lesson_prompts(l)}


def lesson_id_from_tags(tags: str | None) -> str | None:
    parts = [t.strip() for t in (tags or "").split(",")]
    return parts[1] if len(parts) > 1 and parts[0] == SOURCE and parts[1] else None


KINDS = {"paper": "Paper", "forum": "Forum thread", "course": "Course", "article": "Article", "blog": "Blog post",
         "video": "Video", "book": "Book"}


def _cell(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def lesson_markdown(lesson: dict, prompt_ids: dict[str, int]) -> str:
    """The lesson's knowledge-base guide: the notes plus links to its reading test and writing prompts.
    prompt_ids maps prompt text -> writing_prompts.id (prompts are imported before the knowledge base)."""
    out = [f"# {lesson['title']}", ""]
    for s in lesson.get("sources") or []:
        if not isinstance(s, dict):
            continue
        meta = " · ".join(str(x) for x in (KINDS.get(s.get("kind"), s.get("kind")), s.get("authors"), s.get("year")) if x)
        title = f"[{s.get('title') or s.get('url')}]({s['url']})" if s.get("url") else (s.get("title") or "")
        out.append(f"> **Based on:** {title}" + (f" — {meta}" if meta else ""))
    out += ["", (lesson.get("summary_md") or "").strip(), ""]
    terms = [t for t in lesson.get("key_terms") or [] if isinstance(t, dict) and t.get("term")]
    if terms:
        out += ["## Key terms", "", "| Term | Meaning | Example |", "|---|---|---|"]
        out += [f"| **{_cell(t['term'])}** | {_cell(t.get('meaning'))} | {_cell(t.get('example'))} |" for t in terms]
        out += ["", "These are also in **Learn → Vocabulary flashcards**, topic *AI Research*.", ""]
    if lesson.get("discussion"):
        out += ["## Think and talk about it", "", "Speaking Part 3 practice: answer each aloud for 1–2 minutes.", ""]
        out += [f"- {q}" for q in lesson["discussion"]] + [""]
    practice = []
    where = reading_location(lesson["id"])
    if where and where[1]:
        practice.append(f"- **Reading:** [AI Research Test {where[0].rsplit('-', 1)[1]}](#/test/{where[0]}) — "
                        f"Reading Passage {where[1]} (full test: 3 passages, 40 questions, 60 minutes)")
    elif where:
        practice.append(f"- **Reading:** [{lesson['title']}](#/test/{where[0]}) — 1 passage, 20 minutes")
    for p in lesson_prompts(lesson):
        pid = prompt_ids.get(str(p["prompt"]).strip())
        first = str(p["prompt"]).strip().split("\n")[0]
        first = first if len(first) <= 140 else first[:137].rstrip() + "…"
        label = f"Writing Task {p['task']}"
        practice.append(f"- **{label}:** " + (f"[{first}](#/writing/write/{pid})" if pid else first))
    if practice:
        out += ["## Practise", ""] + practice + [""]
    return "\n".join(out).rstrip() + "\n"
