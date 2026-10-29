"""Validate the phrase-bank, tactics and cheat-sheet data files.

Checks every knowledge/data/phrases.*.json and knowledge/data/tactics.*.json against
knowledge/data/FORMAT-phrases-tactics.md (required keys, types, non-empty items/steps,
allowed skill/type/level/source values), checks knowledge/data/cheatsheets.json (word tables:
required keys, unique ids, allowed skills/colors/tones/applies_to, row width == column count)
and scans each file for the personal names listed in data/private_names.txt (if present).

Usage:
    .venv\\Scripts\\python.exe tools\\validate_phrases.py [file ...]

With no arguments, all matching files in knowledge/data are checked.
Exit code 0 = no errors (warnings allowed), 1 = errors found.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "knowledge" / "data"

# Personal names (students, teacher) that must never appear in the shared files. The list itself is private,
# so it is read from data/private_names.txt (one name per line, # comments; data/ is never committed).
NAMES_FILE = ROOT / "data" / "private_names.txt"


def _private_names() -> list[str]:
    if not NAMES_FILE.is_file():
        return []
    lines = NAMES_FILE.read_text(encoding="utf-8").splitlines()
    return [x.strip() for x in lines if x.strip() and not x.lstrip().startswith("#")]


PHRASE_SKILLS = {"writing1", "writing2", "speaking"}
TACTIC_SKILLS = {"reading", "listening", "speaking", "writing"}
LEVELS = {"core", "advanced"}
PHRASE_SOURCES = {"teacher", "standard"}
TACTIC_SOURCES = {"teacher", "standard", "mixed"}

# Question type ids used in content/tests (ARCHITECTURE.md section 1).
QUESTION_TYPES = {
    "note_completion", "form_completion", "table_completion", "flowchart_completion",
    "summary_completion", "sentence_completion", "short_answer", "diagram_labelling",
    "map_labelling", "plan_labelling", "mcq", "multi_select", "matching", "matching_headings",
    "matching_information", "matching_features", "matching_sentence_endings", "tfng", "ynng",
}
TASK1_TYPES = ["line", "bar", "pie", "table", "map", "process", "mixed"]
TASK2_TYPES = ["opinion", "discussion", "adv_disadv", "problem_solution", "cause_effect",
               "direct_question", "outweigh", "positive_negative"]
TACTIC_TYPES = {
    "reading": QUESTION_TYPES,
    "listening": QUESTION_TYPES,
    "speaking": {"part1", "part2", "part3"},
    "writing": {f"task1_{t}" for t in TASK1_TYPES} | {f"task2_{t}" for t in TASK2_TYPES},
}
# Skill-wide overview entry used by some tactics files (warning only).
GENERAL_TYPE = "general"
# Values allowed in a phrase category's optional "applies_to" list, per skill.
APPLIES_TO = {
    "writing1": set(TASK1_TYPES),
    "writing2": set(TASK2_TYPES),
    "speaking": {"part1", "part2", "part3"},
}

PHRASE_KEYS = {"skill", "category", "when", "applies_to", "items", "source"}
ITEM_KEYS = {"phrase", "pattern", "example", "note", "level"}
TACTIC_KEYS = {"skill", "type", "title", "summary", "rule", "quick", "steps", "traps", "tips",
               "example", "language", "source"}
# Optional quick view of a tactic card: "rule" (one line) + "quick" {do, avoid, remember}.
QUICK_KEYS = {"do", "avoid", "remember"}
RULE_MAX = 90         # soft limit (chars) for "rule" - warning only
QUICK_ITEM_MAX = 60   # soft limit (chars) for each quick.* item - warning only
QUICK_COUNTS = {"do": (3, 4), "avoid": (2, 3), "remember": (0, 2)}  # soft item-count ranges

# cheatsheets.json: compact word tables for the study-assistant drawer.
SHEET_FILE = "cheatsheets.json"
SHEET_SKILLS = {"writing1", "writing2", "speaking", "listening", "reading"}
SHEET_COLORS = {"green", "red", "blue", "amber", "purple", "teal", "pink", "gray"}
SHEET_TONES = {"up", "down", "flat", "wave", "peak", "good", "bad", "neutral"}
SHEET_SOURCES = {"teacher", "standard", "mixed"}
SHEET_APPLIES_TO = {**APPLIES_TO, "listening": QUESTION_TYPES, "reading": QUESTION_TYPES}
SHEET_KEYS = {"skill", "id", "title", "color", "applies_to", "note", "columns", "rows",
              "example", "source"}
SHEET_REQUIRED = ("skill", "id", "title", "color", "applies_to", "columns", "rows", "source")
ROW_KEYS = {"tone", "cells"}
SHEET_ID_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
SHEET_MAX_ROWS = 10
SHEET_NOTE_MAX = 140


class Report:
    def __init__(self, name: str):
        self.name = name
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _str_list(rep: Report, where: str, key: str, v, required: bool) -> None:
    if v is None:
        if required:
            rep.err(where, f"missing '{key}'")
        return
    if not isinstance(v, list) or (required and not v):
        rep.err(where, f"'{key}' must be a non-empty list of strings")
        return
    for i, s in enumerate(v):
        if not _nonempty_str(s):
            rep.err(where, f"'{key}'[{i}] must be a non-empty string")


def check_phrases(rep: Report, data, file_skill: str | None) -> None:
    if not isinstance(data, list) or not data:
        rep.err("file", "top level must be a non-empty JSON array of categories")
        return
    seen = set()
    for ci, cat in enumerate(data):
        where = f"category[{ci}]"
        if not isinstance(cat, dict):
            rep.err(where, "must be an object")
            continue
        if _nonempty_str(cat.get("category")):
            where = f"category[{ci}] '{cat['category']}'"
        for k in ("skill", "category", "when", "items", "source"):
            if k not in cat:
                rep.err(where, f"missing required key '{k}'")
        for k in set(cat) - PHRASE_KEYS:
            rep.warn(where, f"unknown key '{k}'")
        skill = cat.get("skill")
        if skill not in PHRASE_SKILLS:
            rep.err(where, f"skill {skill!r} not in {sorted(PHRASE_SKILLS)}")
        elif file_skill and skill != file_skill:
            rep.err(where, f"skill {skill!r} does not match file name ({file_skill!r})")
        for k in ("category", "when"):
            if k in cat and not _nonempty_str(cat[k]):
                rep.err(where, f"'{k}' must be a non-empty string")
        name = cat.get("category")
        if isinstance(name, str):
            if name in seen:
                rep.warn(where, "duplicate category name")
            seen.add(name)
        src = cat.get("source")
        if "source" in cat and src not in PHRASE_SOURCES:
            if src == "mixed":
                # Not in the format spec for phrases, but harmless (used for categories that
                # mix teacher and standard items). Reported, not fatal.
                rep.warn(where, "source 'mixed' is not in the phrases format (teacher|standard)")
            else:
                rep.err(where, f"source {src!r} not in {sorted(PHRASE_SOURCES)}")
        if "applies_to" in cat:
            _str_list(rep, where, "applies_to", cat["applies_to"], required=True)
            allowed = APPLIES_TO.get(skill)
            if allowed and isinstance(cat["applies_to"], list):
                for v in cat["applies_to"]:
                    if isinstance(v, str) and v not in allowed:
                        rep.warn(where, f"applies_to value {v!r} not in {sorted(allowed)}")
        items = cat.get("items")
        if not isinstance(items, list) or not items:
            rep.err(where, "'items' must be a non-empty list")
            continue
        for ii, it in enumerate(items):
            iw = f"{where} item[{ii}]"
            if not isinstance(it, dict):
                rep.err(iw, "must be an object")
                continue
            if not _nonempty_str(it.get("phrase")):
                rep.err(iw, "missing or empty 'phrase'")
            else:
                iw = f"{where} item '{it['phrase'][:40]}'"
            if "example" not in it:
                rep.warn(iw, "no 'example'")
            for k in ("pattern", "example", "note"):
                if k in it and not _nonempty_str(it[k]):
                    rep.err(iw, f"'{k}' must be a non-empty string when present")
            if "level" in it and it["level"] not in LEVELS:
                rep.err(iw, f"level {it['level']!r} not in {sorted(LEVELS)}")
            for k in set(it) - ITEM_KEYS:
                rep.warn(iw, f"unknown key '{k}'")


def check_quick(rep: Report, where: str, q) -> None:
    """Optional quick view: {"do": [...], "avoid": [...], "remember": [...]}."""
    if not isinstance(q, dict):
        rep.err(where, "'quick' must be an object with 'do', 'avoid', 'remember'")
        return
    for k in set(q) - QUICK_KEYS:
        rep.warn(where, f"unknown key 'quick.{k}'")
    for k in ("do", "avoid"):
        _str_list(rep, where, f"quick.{k}", q.get(k), required=True)
    # "remember" may be an empty list.
    _str_list(rep, where, "quick.remember", q.get("remember", []), required=False)
    for k, (lo, hi) in QUICK_COUNTS.items():
        items = q.get(k)
        if not isinstance(items, list):
            continue
        if not lo <= len(items) <= hi:
            rep.warn(where, f"'quick.{k}' has {len(items)} items (aim {lo}-{hi})")
        for i, s in enumerate(items):
            if isinstance(s, str) and len(s) > QUICK_ITEM_MAX:
                rep.warn(where, f"'quick.{k}'[{i}] is {len(s)} chars (aim <= {QUICK_ITEM_MAX})")


def check_tactics(rep: Report, data, file_skill: str | None) -> None:
    if not isinstance(data, list) or not data:
        rep.err("file", "top level must be a non-empty JSON array of tactics")
        return
    seen = set()
    for ti, t in enumerate(data):
        where = f"tactic[{ti}]"
        if not isinstance(t, dict):
            rep.err(where, "must be an object")
            continue
        if _nonempty_str(t.get("type")):
            where = f"tactic[{ti}] '{t['type']}'"
        for k in ("skill", "type", "title", "summary", "steps", "traps", "tips", "source"):
            if k not in t:
                rep.err(where, f"missing required key '{k}'")
        for k in set(t) - TACTIC_KEYS:
            rep.warn(where, f"unknown key '{k}'")
        skill = t.get("skill")
        if skill not in TACTIC_SKILLS:
            rep.err(where, f"skill {skill!r} not in {sorted(TACTIC_SKILLS)}")
        elif file_skill and skill != file_skill:
            rep.err(where, f"skill {skill!r} does not match file name ({file_skill!r})")
        typ = t.get("type")
        allowed = TACTIC_TYPES.get(skill)
        if allowed is not None and typ not in allowed:
            if typ == GENERAL_TYPE:
                # A skill-wide overview entry; not listed in the format, so flag it softly.
                rep.warn(where, f"type 'general' is not a listed {skill} type (overview entry)")
            else:
                rep.err(where, f"type {typ!r} not allowed for skill {skill!r}")
        if (skill, typ) in seen:
            rep.warn(where, "duplicate type")
        seen.add((skill, typ))
        for k in ("title", "summary"):
            if k in t and not _nonempty_str(t[k]):
                rep.err(where, f"'{k}' must be a non-empty string")
        _str_list(rep, where, "steps", t.get("steps"), required=True)
        _str_list(rep, where, "traps", t.get("traps"), required=True)
        _str_list(rep, where, "tips", t.get("tips"), required=True)
        if "rule" in t:
            if not _nonempty_str(t["rule"]):
                rep.err(where, "'rule' must be a non-empty string when present")
            elif len(t["rule"]) > RULE_MAX:
                rep.warn(where, f"'rule' is {len(t['rule'])} chars (aim <= {RULE_MAX})")
        if "quick" in t:
            check_quick(rep, where, t["quick"])
        if "language" in t:
            _str_list(rep, where, "language", t["language"], required=False)
        if "example" in t and not _nonempty_str(t["example"]):
            rep.err(where, "'example' must be a non-empty string when present")
        if "source" in t and t["source"] not in TACTIC_SOURCES:
            rep.err(where, f"source {t['source']!r} not in {sorted(TACTIC_SOURCES)}")


def check_cheatsheets(rep: Report, data) -> None:
    if not isinstance(data, list) or not data:
        rep.err("file", "top level must be a non-empty JSON array of tables")
        return
    seen: set[str] = set()
    for ti, tb in enumerate(data):
        where = f"table[{ti}]"
        if not isinstance(tb, dict):
            rep.err(where, "must be an object")
            continue
        if _nonempty_str(tb.get("id")):
            where = f"table[{ti}] '{tb['id']}'"
        for k in SHEET_REQUIRED:
            if k not in tb:
                rep.err(where, f"missing required key '{k}'")
        for k in set(tb) - SHEET_KEYS:
            rep.warn(where, f"unknown key '{k}'")
        tid = tb.get("id")
        if "id" in tb:
            if not isinstance(tid, str) or not SHEET_ID_RE.fullmatch(tid):
                rep.err(where, f"id {tid!r} must be kebab-case (a-z, 0-9, '-')")
            elif tid in seen:
                rep.err(where, "duplicate id")
            else:
                seen.add(tid)
        skill = tb.get("skill")
        if skill not in SHEET_SKILLS:
            rep.err(where, f"skill {skill!r} not in {sorted(SHEET_SKILLS)}")
        if "color" in tb and tb["color"] not in SHEET_COLORS:
            rep.err(where, f"color {tb['color']!r} not in {sorted(SHEET_COLORS)}")
        if "source" in tb and tb["source"] not in SHEET_SOURCES:
            rep.err(where, f"source {tb['source']!r} not in {sorted(SHEET_SOURCES)}")
        if "title" in tb and not _nonempty_str(tb["title"]):
            rep.err(where, "'title' must be a non-empty string")
        for k in ("note", "example"):
            if k in tb and not _nonempty_str(tb[k]):
                rep.err(where, f"'{k}' must be a non-empty string when present")
        if _nonempty_str(tb.get("note")) and len(tb["note"]) > SHEET_NOTE_MAX:
            rep.warn(where, f"note is {len(tb['note'])} chars (keep it under ~{SHEET_NOTE_MAX})")
        at = tb.get("applies_to")
        if "applies_to" in tb:
            if not isinstance(at, list) or not all(_nonempty_str(v) for v in at):
                rep.err(where, "'applies_to' must be a list of strings ([] = everywhere)")
            elif skill in SHEET_APPLIES_TO:
                for v in at:
                    if v not in SHEET_APPLIES_TO[skill]:
                        rep.err(where, f"applies_to value {v!r} not valid for skill {skill!r}")
        cols = tb.get("columns")
        ncols = None
        if "columns" in tb:
            if not isinstance(cols, list) or not all(isinstance(c, str) for c in cols):
                rep.err(where, "'columns' must be a list of strings")
            elif not 2 <= len(cols) <= 4:
                rep.err(where, f"'columns' has {len(cols)} entries (allowed 2-4)")
            else:
                ncols = len(cols)
        rows = tb.get("rows")
        if "rows" not in tb:
            continue
        if not isinstance(rows, list) or not rows:
            rep.err(where, "'rows' must be a non-empty list")
            continue
        if len(rows) > SHEET_MAX_ROWS:
            rep.warn(where, f"{len(rows)} rows (keep tables to ~{SHEET_MAX_ROWS}; split big ones)")
        for ri, row in enumerate(rows):
            rw = f"{where} row[{ri}]"
            if not isinstance(row, dict):
                rep.err(rw, "must be an object")
                continue
            for k in set(row) - ROW_KEYS:
                rep.warn(rw, f"unknown key '{k}'")
            if "tone" in row and row["tone"] not in SHEET_TONES:
                rep.err(rw, f"tone {row['tone']!r} not in {sorted(SHEET_TONES)}")
            cells = row.get("cells")
            if not isinstance(cells, list) or not all(isinstance(c, str) for c in cells):
                rep.err(rw, "'cells' must be a list of strings")
                continue
            if not any(c.strip() for c in cells):
                rep.err(rw, "all cells are empty")
            if ncols is not None and len(cells) != ncols:
                rep.err(rw, f"{len(cells)} cells but {ncols} columns")
            for c in cells:
                if "*" in c or "](" in c:
                    rep.err(rw, f"markdown in cell {c[:40]!r}")
                if re.search(r"\S·|·\S", c):
                    rep.warn(rw, f"use ' · ' (spaces around the dot) in {c[:40]!r}")


_NAMES = _private_names()
NAME_RE = (re.compile(r"(?<!\w)(" + "|".join(re.escape(n) for n in _NAMES) + r")(?!\w)", re.IGNORECASE)
           if _NAMES else None)


def scan_names(rep: Report, text: str) -> None:
    if NAME_RE is None:
        return
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in NAME_RE.finditer(line):
            rep.err(f"line {lineno}", f"personal name {m.group(0)!r} found")


def validate(path: Path) -> Report:
    rep = Report(path.name)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        rep.err("file", f"not valid UTF-8: {e}")
        return rep
    scan_names(rep, text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        rep.err("file", f"invalid JSON: {e}")
        return rep
    if path.name == SHEET_FILE:
        check_cheatsheets(rep, data)
        return rep
    m = re.fullmatch(r"(phrases|tactics)\.([a-z0-9_]+)\.json", path.name)
    if not m:
        rep.err("file", f"file name must be phrases.<skill>.json, tactics.<skill>.json or {SHEET_FILE}")
        return rep
    kind, file_skill = m.groups()
    if kind == "phrases":
        if file_skill not in PHRASE_SKILLS:
            rep.err("file", f"unknown phrase skill {file_skill!r}")
        check_phrases(rep, data, file_skill)
    else:
        if file_skill not in TACTIC_SKILLS:
            rep.err("file", f"unknown tactics skill {file_skill!r}")
        check_tactics(rep, data, file_skill)
    return rep


def summary(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if path.name.startswith("phrases.") and isinstance(data, list):
        n = sum(len(c.get("items", [])) for c in data if isinstance(c, dict))
        return f"{len(data)} categories, {n} items"
    if path.name == SHEET_FILE and isinstance(data, list):
        n = sum(len(t.get("rows", [])) for t in data if isinstance(t, dict))
        return f"{len(data)} tables, {n} rows"
    if isinstance(data, list):
        return f"{len(data)} entries"
    return ""


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    files = [Path(a) for a in argv] if argv else sorted(
        list(DATA.glob("phrases.*.json")) + list(DATA.glob("tactics.*.json"))
        + list(DATA.glob(SHEET_FILE)))
    if not files:
        print(f"No phrases.*.json / tactics.*.json / {SHEET_FILE} files found in {DATA}")
        return 0
    total_err = 0
    for f in files:
        rep = validate(f)
        status = "OK" if not rep.errors else "FAIL"
        print(f"[{status}] {f.name}  {summary(f)}  "
              f"({len(rep.errors)} errors, {len(rep.warnings)} warnings)")
        for e in rep.errors:
            print(f"    ERROR   {e}")
        for w in rep.warnings:
            print(f"    warning {w}")
        total_err += len(rep.errors)
    print(f"\n{len(files)} file(s) checked, {total_err} error(s).")
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
