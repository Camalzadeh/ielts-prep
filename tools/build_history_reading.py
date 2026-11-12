"""Build the History reading tests in Cambridge format from the per-topic passages.

    .venv/Scripts/python.exe tools/build_history_reading.py

Source: knowledge/history/reading/passages/history-qNN.json — one passage per History topic (Q13-Q20), its
questions numbered from 1 (13 questions; the third passage of a test has 14, ending with a "best title" MCQ).
Output (imported with the Cambridge tests; do not edit by hand):
- knowledge/history/reading/history-test-<n>.json for each group in GROUPS: 3 passages, 40 questions, 60 minutes,
  questions renumbered 1-13 / 14-26 / 27-40, "You should spend about 20 minutes on Questions ..." lines rewritten;
- knowledge/history/reading/history-qNN-reading.json for a topic not in any group yet (one passage, 20 minutes).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READING = ROOT / "knowledge" / "history" / "reading"
PASSAGES = READING / "passages"
GROUPS = [(1, [13, 14, 15]), (2, [16, 17, 18])]   # (test_no, topics); Q19, Q20 wait for a third passage
INTRO = re.compile(r"^\s*<p><em>You should spend.*?</em></p>", re.S)


def shift(html: str | None, off: int) -> str | None:
    """Renumber {{n}} blanks and 'Questions a-b' references by `off`."""
    if not html or not off:
        return html
    html = re.sub(r"\{\{(\d+)\}\}", lambda m: "{{%d}}" % (int(m.group(1)) + off), html)
    return re.sub(r"(Questions?\s+)(\d+)(?:(\s*[-–]\s*)(\d+))?",
                  lambda m: f"{m.group(1)}{int(m.group(2)) + off}"
                  + (f"{m.group(3)}{int(m.group(4)) + off}" if m.group(4) else ""), html)


def as_part(src: dict, number: int, off: int) -> tuple[dict, int]:
    part = copy.deepcopy(src["parts"][0])
    last = off
    for g in part["groups"]:
        g["range"] = [g["range"][0] + off, g["range"][1] + off]
        last = max(last, g["range"][1])
        for k in ("instructions_html", "content_html"):
            g[k] = shift(g.get(k), off)
        for q in g["questions"]:
            q["number"] += off
            q["prompt_html"] = shift(q.get("prompt_html"), off)
    intro = (f"<p><em>You should spend about 20 minutes on Questions {off + 1}-{last}, which are based on "
             f"Reading Passage {number} below.</em></p>")
    body = part["passage_html"]
    part["passage_html"] = INTRO.sub(intro, body, count=1) if INTRO.match(body) else intro + body
    part["number"] = number
    return part, last


def count(src: dict) -> int:
    return sum(len(g["questions"]) for g in src["parts"][0]["groups"])


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", path.relative_to(ROOT))


def main() -> None:
    topics = {int(re.search(r"q(\d+)", p.stem).group(1)): json.loads(p.read_text(encoding="utf-8-sig"))
              for p in sorted(PASSAGES.glob("history-q*.json"))}
    expected = set()
    grouped = set()
    for test_no, qs in GROUPS:
        counts = [count(topics[q]) for q in qs]
        assert counts == [13, 13, 14], f"test {test_no}: {counts} questions, Cambridge format is [13, 13, 14]"
        parts, last = [], 0
        for n, q in enumerate(qs, 1):
            part, last = as_part(topics[q], n, last)
            parts.append(part)
        grouped.update(qs)
        name = f"history-test-{test_no}.json"
        expected.add(name)
        write(READING / name, {
            "id": f"history-test-{test_no}", "type": "reading", "module": "academic",
            "title": f"History Reading Test {test_no} (Q{qs[0]}–Q{qs[-1]})", "series": "History (Azerbaijan)",
            "book": None, "test_no": test_no, "source": "history", "source_url": "",
            "duration_minutes": 60, "parts": parts})
    for q, src in sorted(topics.items()):
        if q in grouped:
            continue
        single = copy.deepcopy(src)
        single.update(id=f"history-q{q}-reading", duration_minutes=20)
        name = f"history-q{q}-reading.json"
        expected.add(name)
        write(READING / name, single)
    for old in READING.glob("*.json"):   # outputs of earlier builds that no longer exist
        if old.name not in expected:
            old.unlink()
            print("removed", old.relative_to(ROOT))


if __name__ == "__main__":
    main()
