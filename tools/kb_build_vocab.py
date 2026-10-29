"""Build knowledge/data/vocabulary.json from the course vocabulary handouts.

Sources (IELTS_PREP_ARCHIVE/docs, extracted text):
  * "Vocabulary Unit N.pdf" / "Unit 20 Vocabulary.pdf"  -> topic "Unit N"
      format A:  • Term (pos): meaning  ◦ Example: sentence
      format B:  Term (pos): meaning  • sentence
  * "Topic N - ... vocabulary.pdf" (Speaking Part 2/3)   -> topic "Speaking Topic N: <name>", grouped (Idioms, ...)
  * "Vocabulary for writing .pdf"                        -> topic "Writing Topic N: <name>"  (term = meaning, then example)
  * Speaking Part 1 model-answer vocabulary, taken from knowledge/data/speaking_questions.docs.json
      -> topic "Speaking Part 1: <topic>", example = the model-answer sentence that uses the term

Usage: .venv\\Scripts\\python.exe -I tools\\kb_build_vocab.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "knowledge" / "raw" / "IELTS_PREP_ARCHIVE" / "docs"
OUT = ROOT / "knowledge" / "data" / "vocabulary.json"
SRC = "IELTS_PREP_ARCHIVE/files/"


def read(name):
    t = (DOCS / name).read_text(encoding="utf-8")
    t = re.sub(r"^# .*\n", "", t)
    t = re.sub(r"<!-- page \d+ -->", "\n", t)
    t = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", t)  # page numbers
    return t


def flat(s):
    s = re.sub(r"\s+", " ", s).strip()
    return re.sub(r"\[\d+(, ?\d+)*\]", "", s).strip()


def strip_to(term):
    """'To assess' -> 'assess' is NOT done: keep the handout's form (verbs are listed with 'to')."""
    return flat(term).strip(" -•◦")


def parse_unit(name, topic):
    t = read(name)
    items = []
    if "◦" in t:  # format A
        for m in re.finditer(r"•\s*(?P<term>[^:•◦]{1,80}?)\s*\((?P<pos>[^)]{1,40})\)\s*:\s*(?P<mean>.+?)\s*◦\s*(Example:)?\s*(?P<ex>.+?)(?=\s*•|\Z)", t, re.S):
            items.append((m["term"], m["pos"], m["mean"], m["ex"]))
    else:  # format B
        head = r"(?m)^(?P<term>[A-Z][^:\n•]{0,70}?)\s*\((?P<pos>[a-z][a-z /,;-]{0,40})\)\s*:"
        heads = list(re.finditer(head, t))
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(t)
            body = t[m.end():end]
            mean, _, ex = body.partition("•")
            items.append((m["term"], m["pos"], mean, ex))
    out = []
    for term, pos, mean, ex in items:
        out.append({"term": strip_to(term), "meaning": flat(mean), "example": flat(ex), "topic": topic,
                    "source": SRC + name[:-3], "pos": flat(pos)})
    return out


def parse_topic(name, topic):
    t = read(name)
    out, group = [], None
    # group headings are short lines without ':' that precede a bullet
    parts = re.split(r"•", t)
    first = parts[0]
    for i, chunk in enumerate(parts[1:]):
        # heading may sit at the end of the previous chunk
        prev = parts[i]
        lines = [l.strip() for l in prev.strip().split("\n") if l.strip()]
        if lines and ":" not in lines[-1] and len(lines[-1]) < 60 and not lines[-1].endswith("."):
            group = lines[-1]
        m = re.match(r"\s*(?P<term>[^:\n]{2,90}?):\s*(?P<mean>.+)", chunk, re.S)
        if not m:
            continue
        mean = m["mean"]
        # cut a trailing group heading / next section off the meaning
        mlines = [l for l in mean.strip().split("\n")]
        keep = []
        for l in mlines:
            if keep and l.strip() and ":" not in l and len(l.strip()) < 60 and not l.strip().endswith(".") \
                    and keep[-1].strip().endswith("."):
                break
            keep.append(l)
        out.append({"term": strip_to(m["term"]), "meaning": flat(" ".join(keep)), "example": "", "topic": topic,
                    "source": SRC + name[:-3], "group": group})
    # example: the first sentence of the handout's Part 3 model answers that uses the term
    answers = " ".join(re.findall(r"Answer:\s*(.+?)(?=\n\s*\d+\.|\Z)", t, re.S))
    sents = re.split(r"(?<=[.!?])\s+", flat(answers))
    for it in out:
        words = [w for w in re.split(r"[\s/]+", it["term"].lower()) if w not in ("to", "one's", "a", "an", "the")]
        stem = " ".join(words)[:max(5, len(" ".join(words)) - 2)]
        it["example"] = next((s for s in sents if stem and stem in s.lower()), "")
    return out


def parse_writing(name):
    t = read(name)
    out = []
    topic = None
    lines = t.split("\n")
    i = 0
    while i < len(lines):
        l = lines[i].strip()
        tm = re.match(r"^Topic (\d+):? (?!example|Example)(.+)$", l)
        if tm and "Task" not in l:
            topic = f"Writing Topic {tm.group(1)}: {tm.group(2).strip()}"
        m = re.match(r"^(?P<term>[^=]{1,70}?)\s+=\s+(?P<mean>.+)$", l)
        if m and topic:
            mean = [m["mean"]]
            j = i + 1
            while j < len(lines) and lines[j].strip():
                mean.append(lines[j].strip()); j += 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            ex = []
            while j < len(lines) and lines[j].strip() and " = " not in lines[j] and not lines[j].strip().startswith("Topic") \
                    and not lines[j].strip().startswith("Summary"):
                ex.append(lines[j].strip()); j += 1
            if ex and ex[0].startswith("Example of using"):
                ex = []
                while j < len(lines) and not lines[j].strip():
                    j += 1
                while j < len(lines) and lines[j].strip():
                    ex.append(lines[j].strip()); j += 1
                ex = [" ".join(ex).strip("‘’'")]
            out.append({"term": strip_to(m["term"]), "meaning": flat(" ".join(mean)), "example": flat(" ".join(ex)),
                        "topic": topic, "source": SRC + name[:-3]})
            i = j
            continue
        i += 1
    return out


def from_speaking():
    p = ROOT / "knowledge" / "data" / "speaking_questions.docs.json"
    if not p.exists():
        return []
    out = []
    for q in json.load(open(p, encoding="utf-8")):
        if q.get("part") != 1:
            continue
        ans = q.get("model_answer") or ""
        sents = re.split(r"(?<=[.!?])\s+", ans)
        for v in q.get("vocabulary") or []:
            term = v.get("term", "").strip()
            if not term:
                continue
            key = term.lower().split("/")[0].strip()
            ex = next((s for s in sents if key[:max(6, len(key) - 2)] in s.lower()), "")
            out.append({"term": term, "meaning": flat(re.sub(r"^\((collocation|idiom|phrasal verb)\)\s*", "", v.get("meaning", ""), flags=re.I)),
                        "example": ex, "topic": f"Speaking Part 1: {q['topic']}",
                        "source": SRC + "MODEL ANSWERS AND VOCABULARY (ALL).pdf"})
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    items = []
    for f in sorted(DOCS.glob("*.md")):
        n = f.name
        m = re.match(r"Vocabulary [Uu]nit (\d+)\.pdf\.md$", n) or re.match(r"Unit (\d+) Vocabulary\.pdf\.md$", n)
        if m:
            items += parse_unit(n, f"Unit {int(m.group(1))}")
            continue
        m = re.match(r"Topic (\d+) - (.+?) (- P2_3 vocabulary|Vocabulary)\.pdf\.md$", n)
        if m:
            items += parse_topic(n, f"Speaking Topic {m.group(1)}: {m.group(2)}")
    items += parse_writing("Vocabulary for writing .pdf.md")
    items += from_speaking()
    seen, out = set(), []
    for it in items:
        it["term"] = it["term"].rstrip(".,;")
        if it["term"].lower() in ("answer", "example") or len(it["term"]) > 70:
            continue
        if not it["term"] or not it["meaning"]:
            print("SKIP (no meaning)", it)
            continue
        k = (it["term"].lower(), it["topic"])
        if k in seen:
            continue
        seen.add(k)
        out.append({k2: v for k2, v in it.items() if v not in (None, "") or k2 == "example"})
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    c = Counter(i["topic"].split(":")[0] if i["topic"].startswith(("Speaking Part 1", "Writing")) else i["topic"] for i in out)
    print(len(out), "items")
    for k, v in sorted(c.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
