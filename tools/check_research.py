"""Check AI Research lessons (knowledge/research/lessons/*.json) before importing them.

    .venv/Scripts/python.exe tools/check_research.py [lesson.json ...]     # default: every lesson

Checks the format in knowledge/research/README.md: required fields, question numbering, answer keys
(TRUE/FALSE/NOT GIVEN, option letters), {{n}} blanks, completion answers taken from the passage within the
word limit, evidence quotes that really are in the passage, writing tasks and their chart images.
Exit code 1 if anything is wrong.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LESSONS = ROOT / "knowledge" / "research" / "lessons"
TF = {"tfng": {"TRUE", "FALSE", "NOT GIVEN"}, "ynng": {"YES", "NO", "NOT GIVEN"}}
CHOICE = {"mcq", "multi_select", "matching", "matching_headings", "matching_information",
          "matching_features", "matching_sentence_endings"}
COMPLETION = {"summary_completion", "sentence_completion", "note_completion", "table_completion",
              "flowchart_completion", "short_answer"}
LIMIT_WORDS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4}
ESSAY_TYPES = {"opinion", "discussion", "adv_disadv", "problem_solution", "cause_effect", "direct_question",
               "outweigh", "positive_negative", "line", "bar", "pie", "table", "map", "process", "mixed"}


def text(s: str | None) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s).replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def check(path: Path) -> list[str]:
    errs: list[str] = []
    try:
        l = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return [f"cannot read: {exc}"]
    lid = l.get("id") or path.stem
    if lid != path.stem:
        errs.append(f"id {lid!r} should match the file name {path.stem!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", lid):
        errs.append("id: lowercase letters, digits and hyphens only")
    for f in ("title", "topic", "summary_md"):
        if not l.get(f):
            errs.append(f"missing {f}")
    if l.get("level") not in (None, "beginner", "intermediate", "advanced"):
        errs.append("level must be beginner, intermediate or advanced")
    if not l.get("sources"):
        errs.append("no sources")
    for t in l.get("key_terms") or []:
        if not t.get("term") or not t.get("meaning"):
            errs.append(f"key term without term/meaning: {t}")

    reading = l.get("reading")
    if reading:
        parts = reading.get("parts") or []
        if not parts:
            errs.append("reading has no parts")
        expect = 1
        for part in parts:
            passage = text(part.get("passage_html"))
            if len(passage.split()) < 500:
                errs.append(f"passage {part.get('number')}: only {len(passage.split())} words (aim for 700-950)")
            for g in part.get("groups") or []:
                gt, (a, b) = g.get("type"), g.get("range") or (0, -1)
                qs = g.get("questions") or []
                where = f"Q{a}-{b} ({gt})"
                if [q.get("number") for q in qs] != list(range(a, b + 1)):
                    errs.append(f"{where}: question numbers do not match the range")
                if a != expect:
                    errs.append(f"{where}: expected to start at Q{expect}")
                expect = b + 1
                keys = {o.get("key") for o in (g.get("options") or [])}
                limit = re.search(r"(ONE|TWO|THREE|FOUR) WORDS?", g.get("instructions_html") or "")
                for q in qs:
                    n, ans = q.get("number"), q.get("answer") or []
                    if not ans:
                        errs.append(f"Q{n}: no answer")
                        continue
                    if gt in TF:
                        if not set(ans) <= TF[gt]:
                            errs.append(f"Q{n}: answer {ans} is not one of {sorted(TF[gt])}")
                    elif gt in CHOICE or (gt in COMPLETION and keys - {None} and set(ans) <= keys):
                        # (a completion with a box of words: answers are the box's letters)
                        qkeys = keys | {o.get("key") for o in (q.get("options") or [])}
                        if not set(ans) <= qkeys:
                            errs.append(f"Q{n}: answer {ans} not among options {sorted(k for k in qkeys if k)}")
                    elif gt in COMPLETION:
                        if gt != "short_answer" and "{{%d}}" % n not in (g.get("content_html") or "") \
                                and "{{%d}}" % n not in (q.get("prompt_html") or ""):
                            errs.append(f"Q{n}: no {{{{{n}}}}} blank in content_html/prompt_html")
                        if text(ans[0]) not in passage:
                            errs.append(f"Q{n}: main answer {ans[0]!r} is not in the passage")
                        if limit and len(ans[0].split()) > LIMIT_WORDS[limit.group(1)]:
                            errs.append(f"Q{n}: {ans[0]!r} is longer than the word limit")
                    else:
                        errs.append(f"Q{n}: unknown question type {gt!r}")
                    ev = re.findall(r"<blockquote>(.*?)</blockquote>", q.get("explanation_html") or "", re.S)
                    if not ev:
                        errs.append(f"Q{n}: explanation has no <blockquote> evidence")
                    for e in ev:
                        if text(e) not in passage:
                            errs.append(f"Q{n}: evidence quote is not word-for-word in the passage")
        if expect - 1 not in (13, 14):
            errs.append(f"{expect - 1} questions (13, or 14 for a test's third passage)")

    for i, w in enumerate(l.get("writing") or [], 1):
        if w.get("task") not in (1, 2) or not w.get("prompt"):
            errs.append(f"writing {i}: needs task 1|2 and a prompt")
        if w.get("essay_type") and w["essay_type"] not in ESSAY_TYPES:
            errs.append(f"writing {i}: unknown essay_type {w['essay_type']!r}")
        if w.get("task") == 1:
            img = w.get("image")
            if not img or not (ROOT / "content" / img).is_file():
                errs.append(f"writing {i}: Task 1 image {img!r} not found under content/")
            if not w.get("image_description"):
                errs.append(f"writing {i}: Task 1 needs image_description (the data, for the AI marker)")
    if not reading and not l.get("writing"):
        errs.append("lesson has neither reading nor writing")
    return errs


def question_count(path: Path) -> int:
    try:
        l = json.loads(path.read_text(encoding="utf-8-sig"))
        return sum(len(g.get("questions") or []) for p in (l.get("reading") or {}).get("parts") or []
                   for g in p.get("groups") or [])
    except (OSError, ValueError):
        return 0


def check_tests() -> list[str]:
    """knowledge/research/tests.json: full tests of 3 lessons = 13 + 13 + 14 questions (Cambridge format)."""
    path = LESSONS.parent / "tests.json"
    if not path.is_file():
        return []
    try:
        specs = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        return [f"tests.json: {exc}"]
    errs, used, nos = [], set(), set()
    for spec in specs:
        no, ids = spec.get("test_no"), spec.get("lessons") or []
        if not isinstance(no, int) or no in nos:
            errs.append(f"test {no!r}: test_no must be a unique number")
        nos.add(no)
        if len(ids) != 3:
            errs.append(f"test {no}: needs exactly 3 lessons (Passages 1-3)")
        for i in ids:
            if i in used:
                errs.append(f"test {no}: lesson {i!r} is already in another test")
            used.add(i)
            if not (LESSONS / f"{i}.json").is_file():
                errs.append(f"test {no}: no lesson {i!r}")
        counts = [question_count(LESSONS / f"{i}.json") for i in ids]
        if len(ids) == 3 and counts != [13, 13, 14]:
            errs.append(f"test {no}: passages have {counts} questions; Cambridge format is [13, 13, 14] "
                        "(add a 14th question to the third lesson, e.g. a 'best title' MCQ)")
    return errs


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(LESSONS.glob("*.json"))
    bad = 0
    for p in paths:
        errs = check(p)
        print(f"{'OK  ' if not errs else 'FAIL'} {p.name}")
        for e in errs:
            print(f"     - {e}")
        bad += bool(errs)
    print(f"{len(paths) - bad}/{len(paths)} lessons OK")
    if not argv:
        terrs = check_tests()
        print(f"{'OK  ' if not terrs else 'FAIL'} tests.json (full 3-passage tests)")
        for e in terrs:
            print(f"     - {e}")
        bad += bool(terrs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
