"""Answer normalisation, grading and IELTS band conversion (ARCHITECTURE.md §1)."""
from __future__ import annotations

import html
import itertools
import math
import re
from typing import Any, Iterable

# --------------------------------------------------------------------------- band tables
# (minimum raw score out of 40, band) — highest first.
LISTENING_TABLE = [
    (39, 9.0), (37, 8.5), (35, 8.0), (32, 7.5), (30, 7.0), (26, 6.5), (23, 6.0), (18, 5.5),
    (16, 5.0), (13, 4.5), (10, 4.0), (8, 3.5), (6, 3.0), (4, 2.5), (2, 2.0), (1, 1.0),
]
ACADEMIC_READING_TABLE = [
    (39, 9.0), (37, 8.5), (35, 8.0), (33, 7.5), (30, 7.0), (27, 6.5), (23, 6.0), (19, 5.5),
    (15, 5.0), (13, 4.5), (10, 4.0), (8, 3.5), (6, 3.0), (4, 2.5), (2, 2.0), (1, 1.0),
]
GT_READING_TABLE = [
    (40, 9.0), (39, 8.5), (37, 8.0), (36, 7.5), (34, 7.0), (32, 6.5), (30, 6.0), (27, 5.5),
    (23, 5.0), (19, 4.5), (15, 4.0), (12, 3.5), (9, 3.0), (6, 2.5), (4, 2.0), (1, 1.0),
]


def band_table(test_type: str, module: str | None) -> list[tuple[int, float]]:
    if test_type == "listening":
        return LISTENING_TABLE
    if (module or "academic").lower().startswith("gen"):
        return GT_READING_TABLE
    return ACADEMIC_READING_TABLE


def raw_to_band(raw: int, total: int, test_type: str, module: str | None = "academic") -> float | None:
    """Convert a raw score to a band. Non-40-question tests are scaled to 40 first."""
    if not total:
        return None
    scaled = raw if total == 40 else round(raw * 40 / total)
    for minimum, band in band_table(test_type, module):
        if scaled >= minimum:
            return band
    return 0.0


def ielts_round(value: float | None) -> float | None:
    """IELTS overall rounding: .25 -> .5, .75 -> next whole band."""
    if value is None:
        return None
    whole = math.floor(value + 1e-9)
    frac = value - whole
    if frac < 0.25 - 1e-9:
        return float(whole)
    if frac < 0.75 - 1e-9:
        return whole + 0.5
    return float(whole + 1)


def overall_band(bands: Iterable[float | None]) -> float | None:
    vals = [b for b in bands if b is not None]
    if not vals:
        return None
    return ielts_round(sum(vals) / len(vals))


# --------------------------------------------------------------------------- normalisation
CHOICE_TYPES = {
    "mcq", "multi_select", "matching", "matching_headings", "matching_information",
    "matching_features", "matching_sentence_endings", "tfng", "ynng",
}
TF_TYPES = {"tfng", "ynng"}
_ARTICLES = ("a ", "an ", "the ")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "–": "-", "—": "-", " ": " "})
_EDGE_PUNCT = " \t\r\n.,;:!?'\"()[]{}<>*_`"


def normalise(value: Any) -> str:
    """lowercase, trim, collapse spaces, strip surrounding punctuation, '1,000' -> '1000'."""
    if value is None:
        return ""
    s = str(value).translate(_QUOTES).lower()
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(_EDGE_PUNCT)
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)          # thousands separators
    s = re.sub(r"\s*-\s*", "-", s)                       # "full - time" -> "full-time"
    return s


def _strip_article(s: str) -> str:
    for art in _ARTICLES:
        if s.startswith(art):
            return s[len(art):]
    return s


def _optional_variants(answer: str) -> list[str]:
    """'(free) parking' -> ['free parking', 'parking']."""
    parts = re.split(r"(\([^()]*\))", answer)
    choices: list[list[str]] = []
    for p in parts:
        if p.startswith("(") and p.endswith(")"):
            choices.append([p[1:-1], ""])
        else:
            choices.append([p])
    variants = []
    for combo in itertools.islice(itertools.product(*choices), 64):
        variants.append("".join(combo))
    return variants


_ALT_SPLIT = re.compile(r"\s+/\s+|(?<=[A-Za-z])/(?=[A-Za-z])|\s+OR\s+")


def expand_accepted(accepted: Iterable[Any]) -> list[str]:
    """All normalised accepted forms (alternatives + optional words)."""
    out: list[str] = []
    for a in accepted or []:
        if a is None:
            continue
        for alt in _ALT_SPLIT.split(str(a)):
            for v in _optional_variants(alt):
                n = normalise(v)
                if n and n not in out:
                    out.append(n)
    return out


def _forms(n: str) -> set[str]:
    """Equivalent spellings of one normalised string (hyphen/space)."""
    return {n, n.replace("-", " "), n.replace("-", "")}


def text_match(user: Any, accepted: Iterable[Any]) -> bool:
    u = normalise(user)
    if not u:
        return False
    for acc in expand_accepted(accepted):
        cand = u
        if not acc.startswith(_ARTICLES):
            cand = _strip_article(u)
        if _forms(cand) & _forms(acc):
            return True
    return False


def _choice_norm(value: Any) -> str:
    s = normalise(value).upper()
    return re.sub(r"\s+", " ", s)


def choice_match(user: Any, accepted: Iterable[Any], options: list[dict] | None = None,
                 qtype: str | None = None) -> bool:
    u = _choice_norm(user)
    if not u:
        return False
    acc = {_choice_norm(a) for a in accepted or [] if a is not None}
    if qtype in TF_TYPES:
        return u in acc
    if u in acc:
        return True
    # user typed the option text instead of the key
    for opt in options or []:
        if _choice_norm(opt.get("key")) in acc and _choice_norm(opt.get("text")) == u:
            return True
    return False


def _looks_like_keys(accepted: list[Any], options: list[dict] | None) -> bool:
    if not options or not accepted:
        return False
    keys = {_choice_norm(o.get("key")) for o in options}
    return all(_choice_norm(a) in keys for a in accepted)


def is_choice_question(qtype: str, accepted: list[Any], options: list[dict] | None) -> bool:
    return qtype in CHOICE_TYPES or _looks_like_keys(accepted, options)


# --------------------------------------------------------------------------- text snapshots
_BLOCK_TAGS = r"p|div|li|ul|ol|tr|table|thead|tbody|h[1-6]|br|section|article|blockquote|dt|dd"


def html_to_text(fragment: str | None, keep_gaps: bool = True) -> str:
    """Rough HTML -> plain text, one block per line. {{N}} placeholders are kept."""
    if not fragment:
        return ""
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", fragment)
    s = re.sub(r"(?i)</?(td|th)\b[^>]*>", " | ", s)
    s = re.sub(rf"(?i)<(/?)({_BLOCK_TAGS})\b[^>]*>", "\n", s)
    s = re.sub(r"(?i)<input\b[^>]*>", " ____ ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    lines = []
    for line in s.splitlines():
        line = re.sub(r"[ \t ]+", " ", line).strip()
        line = re.sub(r"^(\|\s*)+|(\s*\|)+$", "", line).strip()
        line = re.sub(r"(\|\s*){2,}", "| ", line)
        if line:
            lines.append(line)
    text = "\n".join(lines)
    if not keep_gaps:
        text = re.sub(r"\{\{\s*\d+\s*\}\}", "____", text)
    return text


def _gap_context(text: str, number: int, max_len: int = 320) -> str | None:
    pat = re.compile(r"\{\{\s*" + str(number) + r"\s*\}\}")
    for line in text.splitlines():
        if pat.search(line):
            ctx = pat.sub("____", line)
            ctx = re.sub(r"\{\{\s*(\d+)\s*\}\}", r"[\1]", ctx)
            if len(ctx) > max_len:
                i = ctx.find("____")
                start = max(0, i - max_len // 2)
                ctx = ("..." if start else "") + ctx[start:start + max_len] + "..."
            return ctx
    return None


def _options_text(options: list[dict] | None) -> str:
    if not options:
        return ""
    if not any(str(o.get("text") or "").strip() for o in options):
        return ", ".join(str(o.get("key")) for o in options) + " (labels on the image)"
    return " ".join(f"{o.get('key')}) {html_to_text(str(o.get('text') or '')).replace(chr(10), ' ')}"
                    for o in options)


def question_text(group: dict, question: dict) -> str:
    """Plain-text snapshot of one question: prompt or gap sentence, plus options."""
    number = question.get("number")
    qtype = group.get("type") or ""
    prompt = html_to_text(question.get("prompt_html"))
    text = ""
    if prompt:
        text = _gap_context(prompt, number) or prompt.replace("\n", " ")
    if not text and group.get("content_html"):
        text = _gap_context(html_to_text(group.get("content_html")), number) or ""
    if not text:
        instr = html_to_text(group.get("instructions_html")).replace("\n", " ")
        text = instr[:300] if instr else f"Question {number}"
    text = re.sub(r"\{\{\s*(\d+)\s*\}\}", r"[\1]", text)
    opts = question.get("options") or group.get("options")
    if qtype == "tfng":
        text += "  (TRUE / FALSE / NOT GIVEN)"
    elif qtype == "ynng":
        text += "  (YES / NO / NOT GIVEN)"
    elif opts:
        text += "\nOptions: " + _options_text(opts)
    return text.strip()


# --------------------------------------------------------------------------- test traversal
def iter_questions(test: dict) -> Iterable[tuple[dict, dict, dict]]:
    """Yield (part, group, question) in document order."""
    for part in test.get("parts") or []:
        for group in part.get("groups") or []:
            for q in group.get("questions") or []:
                if q.get("number") is not None:
                    yield part, group, q


def count_questions(test: dict) -> int:
    return sum(1 for _ in iter_questions(test))


def _answer_for(answers: dict, number: int) -> str:
    v = answers.get(str(number), answers.get(number))
    if v is None:
        return ""
    if isinstance(v, list):
        return ",".join(str(x) for x in v)
    return str(v).strip()


def _letters(value: str) -> list[str]:
    return [t for t in re.split(r"[\s,;/&]+|\bAND\b", value.upper()) if t]


def grade_test(test: dict, answers: dict) -> dict:
    """Grade a whole test. Returns {raw_score, total, band, details:[...]}."""
    answers = answers or {}
    details: list[dict] = []
    for part in test.get("parts") or []:
        for group in part.get("groups") or []:
            qs = [q for q in group.get("questions") or [] if q.get("number") is not None]
            if not qs:
                continue
            qtype = group.get("type") or ""
            if qtype == "multi_select":
                details.extend(_grade_multi_select(part, group, qs, answers))
                continue
            for q in qs:
                accepted = [a for a in (q.get("answer") or []) if a is not None]
                if isinstance(q.get("answer"), str):
                    accepted = [q["answer"]]
                user = _answer_for(answers, q["number"])
                opts = q.get("options") or group.get("options")
                if is_choice_question(qtype, accepted, opts):
                    ok = choice_match(user, accepted, opts, qtype)
                else:
                    ok = text_match(user, accepted)
                details.append(_detail(part, group, q, user, accepted, ok))
    details.sort(key=lambda d: d["number"])
    raw = sum(1 for d in details if d["is_correct"])
    total = len(details)
    band = raw_to_band(raw, total, test.get("type") or "reading", test.get("module"))
    return {"raw_score": raw, "total": total, "band": band, "details": details}


def _grade_multi_select(part: dict, group: dict, qs: list[dict], answers: dict) -> list[dict]:
    correct: list[str] = []
    for q in qs:
        acc = q.get("answer") or []
        if isinstance(acc, str):
            acc = [acc]
        for a in acc:
            for letter in _letters(str(a)):
                if letter not in correct:
                    correct.append(letter)
    # user's distinct letters across the group, in question order
    letters: list[str] = []
    for q in qs:
        for letter in _letters(_answer_for(answers, q["number"])):
            if letter not in letters:
                letters.append(letter)
    out = []
    for i, q in enumerate(qs):
        user = letters[i] if i < len(letters) else ""
        ok = bool(user) and user in correct
        out.append(_detail(part, group, q, user, correct, ok))
    return out


def _detail(part: dict, group: dict, q: dict, user: str, accepted: list, ok: bool) -> dict:
    return {
        "number": q["number"],
        "part": part.get("number"),
        "type": group.get("type"),
        "user_answer": user,
        "correct_answers": [str(a) for a in accepted],
        "is_correct": bool(ok),
        "question_text": question_text(group, q),
        "explanation_html": q.get("explanation_html"),
    }


# --------------------------------------------------------------------------- stripping
def strip_answers(test: dict) -> dict:
    """Deep copy of a test without answers, explanations or transcripts."""
    import copy
    t = copy.deepcopy(test)
    for part in t.get("parts") or []:
        part.pop("transcript_html", None)
        for group in part.get("groups") or []:
            for q in group.get("questions") or []:
                q.pop("answer", None)
                q.pop("explanation_html", None)
    return t
