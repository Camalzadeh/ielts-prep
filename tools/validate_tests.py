"""Validate scraped test JSON files against the schema in ARCHITECTURE.md section 1.

Usage:
  .venv\\Scripts\\python.exe tools\\validate_tests.py                 # all of content/tests/**
  .venv\\Scripts\\python.exe tools\\validate_tests.py listening        # only content/tests/listening
  .venv\\Scripts\\python.exe tools\\validate_tests.py path\\to\\x.json  # specific files
  options: --quiet (only errors summary), --warnings (also print warnings)

Checks (errors): required keys/types, 40 questions numbered 1..N without gaps or dupes
(listening & academic reading = 40), every {{N}} placeholder in a group's content_html belongs to
a question of that group (and every question of a gap-fill group appears once), group `range`
matches its questions, non-empty `answer` lists, letter answers exist in the options,
multi_select answer sets, referenced media files exist under content/ (incl. <img> in HTML fields,
as "media/..." or "/media/content/..."), passage heading-slot markers point at real questions.
Exit code 1 if any file has errors.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
TESTS = CONTENT / "tests"

GROUP_TYPES = {
    "note_completion", "form_completion", "table_completion", "flowchart_completion",
    "summary_completion", "sentence_completion", "short_answer", "diagram_labelling",
    "map_labelling", "plan_labelling", "mcq", "multi_select", "matching", "matching_headings",
    "matching_information", "matching_features", "matching_sentence_endings", "tfng", "ynng",
}
# types whose answers must be option keys (labelling types only when the group has options)
LETTER_TYPES = {"mcq", "multi_select", "matching", "matching_headings", "matching_information",
                "matching_features", "matching_sentence_endings"}
TOP_KEYS = {"id": str, "type": str, "module": str, "title": str, "series": str, "source": str,
            "source_url": str, "duration_minutes": (int, float), "parts": list}
PH_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")
EXPECTED_TOTAL = {"listening": 40, "reading": 40}


def check_media(rel, where, errors):
    if rel is None:
        return
    if not isinstance(rel, str) or not rel:
        errors.append(f"{where}: bad media path {rel!r}")
        return
    if rel.startswith(("http://", "https://", "/")):
        errors.append(f"{where}: media path must be relative to content/: {rel}")
        return
    if not (CONTENT / rel).exists():
        errors.append(f"{where}: missing media file content/{rel}")


def check_inline_img(src, where, errors):
    """<img src> inside HTML fields: either content-relative ("media/...") or the served
    URL form "/media/content/<x>" (-> content/media/<x>, see ARCHITECTURE.md)."""
    if src.startswith("/media/content/"):
        if not (CONTENT / "media" / src[len("/media/content/"):]).exists():
            errors.append(f"{where}: missing media file for {src}")
    else:
        check_media(src, where, errors)


IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"')
SLOT_RE = re.compile(r'class="heading-slot"[^>]*data-q="(\d+)"|data-q="(\d+)"[^>]*class="heading-slot"')


def validate(path: Path) -> tuple[list, list]:
    errors, warns = [], []
    try:
        t = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"invalid JSON: {e}"], []
    for k, typ in TOP_KEYS.items():
        if k not in t:
            errors.append(f"missing key '{k}'")
        elif not isinstance(t[k], typ):
            errors.append(f"key '{k}' has wrong type {type(t[k]).__name__}")
    for k in ("book", "test_no"):
        if k not in t:
            errors.append(f"missing key '{k}'")
        elif t[k] is not None and not isinstance(t[k], int):
            errors.append(f"'{k}' must be int or null")
    ttype = t.get("type")
    if ttype not in ("listening", "reading"):
        errors.append(f"type must be listening|reading, got {ttype!r}")
    if t.get("module") not in ("academic", "general"):
        errors.append(f"module must be academic|general, got {t.get('module')!r}")
    if t.get("id") and t["id"] != path.stem:
        errors.append(f"id {t['id']!r} != file name {path.stem!r}")
    if ttype and path.parent.name in ("listening", "reading") and path.parent.name != ttype:
        errors.append(f"type {ttype} but file is in {path.parent.name}/")

    numbers = []
    parts = t.get("parts") or []
    if ttype == "listening" and len(parts) != 4:
        errors.append(f"listening test has {len(parts)} parts (expected 4)")
    for pi, p in enumerate(parts):
        pw = f"part {p.get('number', pi + 1)}"
        if not isinstance(p.get("number"), int):
            errors.append(f"{pw}: missing number")
        if not isinstance(p.get("groups"), list) or not p["groups"]:
            errors.append(f"{pw}: no groups")
            continue
        if ttype == "listening":
            if not p.get("audio") and not p.get("audio_remote"):
                errors.append(f"{pw}: no audio and no audio_remote")
            check_media(p.get("audio"), pw, errors)
            if not p.get("transcript_html"):
                warns.append(f"{pw}: no transcript")
        if ttype == "reading" and not p.get("passage_html"):
            errors.append(f"{pw}: empty passage_html")
        for src in IMG_RE.findall((p.get("passage_html") or "") + (p.get("transcript_html") or "")):
            check_inline_img(src, pw + " passage <img>", errors)
        part_qnums = {q.get("number") for g in (p.get("groups") or []) for q in (g.get("questions") or [])}
        for a, b in SLOT_RE.findall(p.get("passage_html") or ""):
            if int(a or b) not in part_qnums:
                errors.append(f"{pw}: passage heading-slot for Q{a or b} has no question in this part")
        for gi, g in enumerate(p["groups"]):
            gw = f"{pw} group {gi + 1}"
            gtype = g.get("type")
            if gtype not in GROUP_TYPES:
                errors.append(f"{gw}: unknown type {gtype!r}")
            qs = g.get("questions")
            if not isinstance(qs, list) or not qs:
                errors.append(f"{gw}: no questions")
                continue
            qnums = []
            for q in qs:
                n = q.get("number")
                if not isinstance(n, int):
                    errors.append(f"{gw}: question without integer number")
                    continue
                qnums.append(n)
                ans = q.get("answer")
                if not isinstance(ans, list) or not ans or not all(isinstance(a, str) and a.strip() for a in ans):
                    errors.append(f"Q{n}: empty/invalid answer {ans!r}")
                    continue
                if "prompt_html" not in q:
                    errors.append(f"Q{n}: missing prompt_html")
                opts = q.get("options") or g.get("options")
                if gtype in LETTER_TYPES:
                    if not opts:
                        errors.append(f"Q{n}: {gtype} without options")
                    else:
                        keys = {o.get("key") for o in opts}
                        if not set(ans) <= keys:
                            errors.append(f"Q{n}: answer {ans} not among options {sorted(keys)}")
                elif opts and isinstance(opts, list):
                    keys = {o.get("key") for o in opts}
                    if not set(ans) <= keys:
                        errors.append(f"Q{n}: answer {ans} not among options {sorted(keys)}")
                for o in (q.get("options") or []):
                    if not isinstance(o, dict) or "key" not in o or "text" not in o:
                        errors.append(f"Q{n}: bad option {o!r}")
            for o in (g.get("options") or []):
                if not isinstance(o, dict) or "key" not in o or "text" not in o:
                    errors.append(f"{gw}: bad option {o!r}")
            numbers.extend(qnums)
            rng = g.get("range")
            if not (isinstance(rng, list) and len(rng) == 2):
                errors.append(f"{gw}: bad range {rng!r}")
            elif qnums and [min(qnums), max(qnums)] != rng:
                errors.append(f"{gw}: range {rng} != questions {min(qnums)}-{max(qnums)}")
            if not g.get("options") and gtype not in LETTER_TYPES and gtype not in ("tfng", "ynng") \
                    and all(re.fullmatch(r"[A-J]", a) for q in qs for a in (q.get("answer") or ["x"])) \
                    and not any(q.get("options") for q in qs):
                errors.append(f"{gw}: answers are all letters but the group has no options (missing option box?)")
            if gtype == "multi_select":
                sets = {tuple(sorted(q.get("answer") or [])) for q in qs}
                if len(sets) != 1:
                    errors.append(f"{gw}: multi_select questions have different answer sets {sets}")
                elif len(next(iter(sets))) < len(qs):
                    warns.append(f"{gw}: multi_select answer set smaller than question count")
            html = g.get("content_html") or ""
            ph = [int(x) for x in PH_RE.findall(html)]
            if ph:
                stray = sorted(set(ph) - set(qnums))
                if stray:
                    errors.append(f"{gw}: placeholders {stray} have no question in this group")
                dup = sorted({x for x in ph if ph.count(x) > 1})
                if dup:
                    errors.append(f"{gw}: duplicate placeholders {dup}")
                missing = sorted(set(qnums) - set(ph))
                if missing:
                    errors.append(f"{gw}: questions {missing} have no placeholder in content_html")
            elif gtype not in LETTER_TYPES and gtype not in ("tfng", "ynng") and not g.get("options") and not all(q.get("prompt_html") for q in qs):
                # labelling a picture: numbered boxes without prompt text are fine
                if not (g.get("image") or "<img" in html):
                    errors.append(f"{gw}: gap-fill group without placeholders and with empty prompts")
            check_media(g.get("image"), gw, errors)
            for src in IMG_RE.findall(html + (g.get("instructions_html") or "")):
                check_inline_img(src, gw + " <img>", errors)
    if numbers:
        dup = sorted({n for n in numbers if numbers.count(n) > 1})
        if dup:
            errors.append(f"duplicate question numbers {dup}")
        exp = EXPECTED_TOTAL.get(ttype)
        top = max(numbers)
        missing = sorted(set(range(1, top + 1)) - set(numbers))
        if missing:
            errors.append(f"missing question numbers {missing}")
        n = len(set(numbers))
        if exp and n != exp:
            # a few old Cambridge listening tests (books 1-3) really have 41-43 questions;
            # the scraper marks them with "question_count"
            if n > exp and t.get("question_count") == n:
                warns.append(f"{n} questions (non-standard, expected {exp})")
            else:
                errors.append(f"{n} questions (expected {exp})")
    else:
        errors.append("no questions")
    return errors, warns


def main(argv):
    quiet = "--quiet" in argv
    show_w = "--warnings" in argv
    args = [a for a in argv if not a.startswith("--")]
    files = []
    if not args:
        files = sorted(TESTS.glob("**/*.json"))
    for a in args:
        p = Path(a)
        if p.is_file():
            files.append(p)
        elif (TESTS / a).is_dir():
            files.extend(sorted((TESTS / a).glob("**/*.json")))
        elif p.is_dir():
            files.extend(sorted(p.glob("**/*.json")))
    bad = 0
    nwarn = 0
    for f in files:
        errs, warns = validate(f)
        nwarn += len(warns)
        if errs:
            bad += 1
        if (errs or (show_w and warns)) and not quiet:
            print(f"{f.relative_to(ROOT) if f.is_relative_to(ROOT) else f}:")
            for e in errs:
                print("  ERROR", e)
            if show_w:
                for w in warns:
                    print("  warn ", w)
    print(f"validated {len(files)} files: {len(files) - bad} ok, {bad} with errors, {nwarn} warnings")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
