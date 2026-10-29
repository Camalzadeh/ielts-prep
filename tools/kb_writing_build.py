"""Expand verbatim model-essay placeholders in the writing KB pages.

Pages in knowledge/kb/ may contain placeholders such as

    <!--ESSAY src="LATEST:Writing Task 2 Essays - STRUCTURE.pdf.md" from="In today's world" to="happiness and health." paras="To begin with|In conclusion"-->

The script finds the passage in the extracted source markdown (knowledge/raw/<ARCHIVE>/docs/),
starting at the first occurrence of `from` (searched after the optional `after` marker) and
ending at the end of the first following occurrence of `to`. PDF line wraps are joined, and a
paragraph break is inserted before each `paras` phrase. The placeholder is replaced in place by
a block quote, so the essay text stays verbatim with the teacher's handout.

Usage: python tools/kb_writing_build.py [page.md ...]   (default: all writing pages)
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge" / "kb"
ARCHIVES = {
    "PREP": ROOT / "knowledge" / "raw" / "IELTS_PREP_ARCHIVE" / "docs",
    "LATEST": ROOT / "knowledge" / "raw" / "LATEST_EXAMS_ARCHIVE" / "docs",
}
PLACEHOLDER = re.compile(r"<!--ESSAY (.*?)-->", re.S)
ATTR = re.compile(r'(\w+)="(.*?)"', re.S)


def load_source(spec: str) -> str:
    arch, name = spec.split(":", 1)
    raw = (ARCHIVES[arch] / name).read_text(encoding="utf-8")
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("<!-- page") or s.startswith("# "):
            continue
        lines.append(s)
    out = ""
    for s in lines:
        if not out:
            out = s
        elif out.endswith("-") and not out.endswith(" -"):
            out += s  # re-join words hyphenated across a line break
        else:
            out += " " + s
    return re.sub(r"\s+", " ", out)


def extract(attrs: dict) -> str:
    text = load_source(attrs["src"])
    pos = 0
    if attrs.get("after"):
        pos = text.index(attrs["after"]) + len(attrs["after"])
    start = text.index(attrs["from"], pos)
    end = text.index(attrs["to"], start) + len(attrs["to"])
    passage = text[start:end].strip()
    for phrase in [p for p in attrs.get("paras", "").split("|") if p]:
        idx = passage.find(" " + phrase)
        if idx < 0:
            raise ValueError(f"paragraph marker not found: {phrase!r}")
        passage = passage[:idx] + "\n\n" + passage[idx + 1:]
    paras = [p.strip() for p in passage.split("\n\n")]
    return "\n>\n".join("> " + p for p in paras)


def expand(page: pathlib.Path) -> int:
    src = page.read_text(encoding="utf-8")
    count = 0

    def repl(m):
        nonlocal count
        count += 1
        return extract(dict(ATTR.findall(m.group(1))))

    new = PLACEHOLDER.sub(repl, src)
    if count:
        page.write_text(new, encoding="utf-8")
    return count


if __name__ == "__main__":
    targets = [pathlib.Path(p) for p in sys.argv[1:]] or sorted(
        list(KB.glob("writing-*.md")) + [KB / "linking-words.md"]
    )
    for t in targets:
        if t.exists():
            n = expand(t)
            if n:
                print(f"{t.name}: expanded {n} essay(s)")
