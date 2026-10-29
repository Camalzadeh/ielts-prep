"""Build knowledge/data/speaking_questions.docs.json from the extracted course docs.

Sources (IELTS_PREP_ARCHIVE/docs):
  * SPEAKING PART 1 QUESTIONS (ALL).pdf.md         -> part 1 question list (+ season)
  * MODEL ANSWERS AND VOCABULARY (ALL).pdf.md      -> part 1 model answers + vocabulary
  * Topic 1..6 *.pdf.md                            -> part 2 cue cards, vocabulary, part 3 Q + model answers
Chat (text only, photos ignored):
  * LATEST_EXAMS_ARCHIVE message548 -> part 2 topic reported from a real exam (2026-09-18)

Run:  .venv\\Scripts\\python.exe tools\\kb_speaking_build.py
Writes knowledge/data/speaking_questions.docs.json and prints warnings for anything unmatched.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "knowledge", "raw", "IELTS_PREP_ARCHIVE", "docs")
LATEST = os.path.join(ROOT, "knowledge", "raw", "LATEST_EXAMS_ARCHIVE", "messages.json")
OUT = os.path.join(ROOT, "knowledge", "data", "speaking_questions.docs.json")

SEASON_RE = re.compile(r"\(\s*May\s*-\s*December\s*2026\s*\)?", re.I)
CITATION_RE = re.compile(r"\s*\[\d+(?:,\s*\d+)*\]")


def warn(msg: str) -> None:
    print("WARN:", msg, file=sys.stderr)


def norm(q: str) -> str:
    q = q.replace("(Do) ", "")
    q = q.lower().replace("’", "'").replace("colour", "color").replace("favourite", "favorite")
    q = re.sub(r"[^a-z0-9]+", " ", q).strip()
    return q.replace("the outer space", "outer space")


def clean_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def read_lines(path: str) -> list[str]:
    """Return content lines without page markers / title / bare page numbers; bullets merged."""
    raw = open(path, encoding="utf-8").read().splitlines()
    out: list[str] = []
    pending_bullet = False
    for ln in raw:
        s = ln.strip()
        if not s or s.startswith("<!--") or s.startswith("# "):
            continue
        if re.fullmatch(r"\d{1,2}", s):  # page numbers in the "(1)" duplicate
            continue
        if s == "•":
            pending_bullet = True
            continue
        if pending_bullet:
            out.append("• " + s)
            pending_bullet = False
        else:
            out.append(s)
    return out


def season_of(header: str) -> str | None:
    return "May-Dec 2026" if SEASON_RE.search(header) else None


def topic_name(header: str) -> str:
    h = re.sub(r"^TOPIC\s+\d+\s*:\s*", "", header, flags=re.I)
    h = SEASON_RE.sub("", h)
    return clean_ws(h)


# ---------------------------------------------------------------- Part 1 list
def parse_part1_list(fname: str):
    lines = read_lines(os.path.join(DOCS, fname))
    topics: list[dict] = []
    cur = None
    for s in lines:
        if s.startswith("• "):
            cur["questions"].append(s[2:].strip())
        elif s.startswith("TOPIC") or (cur and "?" not in s and SEASON_RE.search(s)):
            cur = {"topic": topic_name(s), "season": season_of(s), "questions": []}
            topics.append(cur)
        else:  # wrapped question line
            cur["questions"][-1] += " " + s
    for t in topics:
        t["questions"] = [clean_ws(q) for q in t["questions"]]
    return topics


# ---------------------------------------------------------------- Part 1 model answers
def parse_bullet(b: str) -> dict:
    b = CITATION_RE.sub("", clean_ws(b))
    m = re.match(r"^(.*?):\s*(\((?:Collocation|Idiom|Phrasal verb)[^)]*\))?\s*(.*)$", b)
    if not m:
        return {"term": b, "meaning": ""}
    d = {"term": m.group(1).strip(), "meaning": m.group(3).strip()}
    if m.group(2):
        d["type"] = m.group(2).strip("()").strip().lower()
    return d


def parse_part1_answers(fname: str, known_topics: list[str], known_q: set[str]):
    lines = read_lines(os.path.join(DOCS, fname))
    known_topics_n = {norm(t): t for t in known_topics}
    entries: list[dict] = []  # {topic, questions:[...], answer, vocab}
    topic = None
    state = "topic"  # topic | answer | vocab
    i = 0
    while i < len(lines):
        s = lines[i]
        if s.startswith("• "):
            if state == "answer" or state == "vocab":
                entries[-1]["vocab"].append(s[2:])
                state = "vocab"
            i += 1
            continue
        # topic header?
        if s.startswith("TOPIC") or (state in ("vocab", "topic") and norm(topic_name(s)) in known_topics_n):
            topic = known_topics_n.get(norm(topic_name(s)), topic_name(s))
            state = "topic"
            i += 1
            continue
        if state in ("topic", "vocab"):
            # question candidates: this line, or this line + next (wrapped)
            cand = None
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if s.rstrip().endswith("?") or norm(s) in known_q:
                cand = (s, 1)
            elif state == "vocab" and not nxt.startswith("• ") and any(norm(p) in known_q for p in split_multi(nxt)):
                entries[-1]["vocab"][-1] += " " + s  # bullet continuation before a question line
                i += 1
                continue
            elif i + 1 < len(lines) and lines[i + 1].rstrip().endswith("?") and not lines[i + 1].startswith("• "):
                joined = s + " " + lines[i + 1]
                if any(norm(p) in known_q for p in split_multi(joined)):
                    cand = (joined, 2)
                elif state == "vocab":
                    entries[-1]["vocab"][-1] += " " + s  # bullet continuation
                    i += 1
                    continue
                else:
                    cand = (joined, 2)
            if cand:
                qs = split_multi(cand[0])
                for q in qs:
                    if norm(q) not in known_q:
                        warn(f"part1 model-answer question not in list: [{topic}] {q}")
                entries.append({"topic": topic, "questions": qs, "answer": [], "vocab": []})
                state = "answer"
                i += cand[1]
                continue
            if state == "vocab":
                entries[-1]["vocab"][-1] += " " + s
                i += 1
                continue
            warn(f"unexpected line after topic header: {s}")
            i += 1
            continue
        # state == answer
        entries[-1]["answer"].append(s)
        i += 1
    for e in entries:
        e["answer"] = CITATION_RE.sub("", clean_ws(" ".join(e["answer"])))
        e["vocab"] = [parse_bullet(v) for v in e["vocab"]]
    return entries


def split_multi(q: str) -> list[str]:
    q = clean_ws(q)
    q = re.sub(r"^\d+\.\s*", "", q)
    parts = [clean_ws(p) for p in re.split(r"\?\s*/\s*", q)]
    parts = [p if p.endswith("?") else p + "?" for p in parts if p]
    return parts


# ---------------------------------------------------------------- Part 2/3 topic docs
SECTION_RE = re.compile(r"^(Idioms|Collocations|Essential Everyday Phrasal Verbs|High-Level Phrasal Verbs|"
                        r"High-Level Vocabulary|Advanced Words|Adjectives|High-Advanced Words)\b", re.I)


def parse_topic_doc(path: str):
    lines = read_lines(path)
    header = lines[0]
    m = re.match(r"TOPIC\s+(\d+)\s*:", header)
    num = int(m.group(1))
    p2_topic = topic_name(header).rstrip("(").strip()
    season = season_of(header) or ("May-Dec 2026" if "May - December 2026" in header else None)
    question = lines[1]
    idx = 2
    cue = []
    while idx < len(lines) and not SECTION_RE.match(lines[idx]):
        s = lines[idx]
        if s.lower().startswith("you should say"):
            idx += 1
            continue
        cue.append(s.lstrip("• ").strip())
        idx += 1
    # vocabulary sections
    sections: list[dict] = []
    p3_start = None
    while idx < len(lines):
        s = lines[idx]
        if re.search(r"PART 3 QUESTIONS", s):
            p3_start = idx
            break
        if SECTION_RE.match(s):
            sections.append({"name": clean_ws(s), "items": []})
        elif s.startswith("• "):
            sections[-1]["items"].append(s[2:])
        else:
            sections[-1]["items"][-1] += " " + s
        idx += 1
    for sec in sections:
        sec["items"] = [parse_bullet(CITATION_RE.sub("", x)) for x in sec["items"]]
    p3_topic_raw = re.sub(r"^TOPIC\s+\d+\s*:\s*", "", lines[p3_start]).replace("- PART 3 QUESTIONS", "")
    p3_topic = clean_ws(p3_topic_raw).capitalize()
    # part 3 questions
    p3 = []
    for s in lines[p3_start + 1:]:
        if s.rstrip().endswith("?") and (re.match(r"^\d+\.", s) or not p3 or p3[-1]["answer"]):
            p3.append({"question": re.sub(r"^\d+\.\s*", "", s).strip(), "answer": []})
            continue
        if s.startswith("• "):
            s = s[2:]
        s = re.sub(r"^Answer:\s*", "", s)
        p3[-1]["answer"].append(s)
    for q in p3:
        q["answer"] = CITATION_RE.sub("", clean_ws(" ".join(q["answer"])))
    return {"num": num, "topic": p2_topic, "season": season, "question": clean_ws(question), "cue_points": cue,
            "sections": sections, "p3_topic": p3_topic, "p3": p3, "file": os.path.basename(path)}


def src_name(md_name: str) -> str:
    return md_name[:-3] if md_name.endswith(".md") else md_name


def main() -> None:
    items: list[dict] = []
    p1_file = "SPEAKING PART 1 QUESTIONS (ALL).pdf.md"
    ma_file = "MODEL ANSWERS AND VOCABULARY (ALL).pdf.md"
    p1 = parse_part1_list(p1_file)
    known_q = {norm(q) for t in p1 for q in t["questions"]}
    answers = parse_part1_answers(ma_file, [t["topic"] for t in p1], known_q)
    ans_by_q = {}
    for e in answers:
        for q in e["questions"]:
            ans_by_q[norm(q)] = e
    for t in p1:
        for q in t["questions"]:
            it = {"part": 1, "topic": t["topic"], "question": q}
            if t["season"]:
                it["season"] = t["season"]
            e = ans_by_q.get(norm(q))
            if e:
                it["source"] = "course_material:" + src_name(ma_file)
                it["model_answer"] = e["answer"]
                if e["vocab"]:
                    it["vocabulary"] = e["vocab"]
            else:
                it["source"] = "course_material:" + src_name(p1_file)
                warn(f"no model answer for part1 [{t['topic']}] {q}")
            items.append(it)

    topic_docs = sorted(glob.glob(os.path.join(DOCS, "Topic [0-9] - *.md")))
    parsed_topics = [parse_topic_doc(p) for p in topic_docs]
    for t in parsed_topics:
        it = {"part": 2, "topic": t["topic"], "question": t["question"], "cue_points": t["cue_points"]}
        if t["season"]:
            it["season"] = t["season"]
        it["source"] = "course_material:" + src_name(t["file"])
        vocab = [dict(v, group=s["name"]) for s in t["sections"] for v in s["items"]]
        it["vocabulary"] = vocab
        items.append(it)
        for q in t["p3"]:
            p3 = {"part": 3, "topic": t["p3_topic"], "question": q["question"], "related_part2": t["topic"]}
            if t["season"]:
                p3["season"] = t["season"]
            p3["source"] = "course_material:" + src_name(t["file"])
            if q["answer"]:
                p3["model_answer"] = q["answer"]
            items.append(p3)

    # chat: text-only speaking questions (the full lists in the chat are photos -> not processed here)
    msgs = json.load(open(LATEST, encoding="utf-8"))
    for x in msgs:
        t = x.get("text") or ""
        m = re.search(r"SPEAKING PART 2 TOPIC:\s*\n?(.+)", t)
        if m:
            d = re.match(r"(\d\d)\.(\d\d)\.(\d{4})", x.get("date", ""))
            items.append({"part": 2, "topic": clean_ws(m.group(1)), "question": clean_ws(m.group(1)),
                          "cue_points": [], "source": "telegram:LATEST_EXAMS_ARCHIVE",
                          "source_date": f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None})

    # dedupe on part + normalised question, prefer the one with a model answer
    seen: dict[tuple, int] = {}
    final: list[dict] = []
    for it in items:
        k = (it["part"], norm(it["question"]))
        if k in seen:
            j = seen[k]
            if "model_answer" in it and "model_answer" not in final[j]:
                final[j] = it
            continue
        seen[k] = len(final)
        final.append(it)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    from collections import Counter
    c = Counter(i["part"] for i in final)
    ma = Counter(i["part"] for i in final if "model_answer" in i)
    print(f"wrote {len(final)} items -> {OUT}; by part {dict(c)}; with model answers {dict(ma)}")


if __name__ == "__main__":
    main()
