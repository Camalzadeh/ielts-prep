"""Fill the topic-by-topic example lists in knowledge/kb/writing-task2-examples-and-support.md.

Reads the extracted "General examples.pdf" and "statistical examples.pdf" handouts, rebuilds the
sentences that were wrapped across PDF lines, groups them under the 30 topic headings, and
replaces the <!--GENERAL_EXAMPLES--> and <!--STAT_EXAMPLES--> placeholders with markdown.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "knowledge" / "raw" / "IELTS_PREP_ARCHIVE" / "docs"
PAGE = ROOT / "knowledge" / "kb" / "writing-task2-examples-and-support.md"

TOPICS = [
    "Education", "Technology", "Environment", "Health", "Crime and Punishment", "Globalization",
    "Culture and Tradition", "Government and Politics", "Economy and Money", "Work and Employment",
    "Media and Advertising", "Family and Relationships", "Transport and Infrastructure",
    "Public Services", "Urbanization and Housing", "Science and Innovation", "Immigration",
    "Gender Roles", "Social Issues", "Art and Music", "Food and Diet", "Tourism",
    "Sport and Leisure", "Law and Order", "Animal Rights", "Consumerism", "Climate Change",
    "Education vs Experience", "Freedom of Speech", "Censorship",
]


def parse(name: str, numbered: bool) -> dict:
    groups, current, buf = {}, None, ""
    for line in (DOCS / name).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("<!--") or s.startswith("# "):
            continue
        head = re.sub(r"^\d+\.", "", s) if numbered else s
        if head in TOPICS and not buf:
            current = head
            groups[current] = []
            continue
        buf = (buf + " " + s).strip() if not buf.endswith("-") else buf + s
        if s.endswith("."):
            groups[current].append(re.sub(r"\s+", " ", buf))
            buf = ""
    return groups


def render(groups: dict) -> str:
    out = []
    for topic in TOPICS:
        items = groups.get(topic, [])
        if not items:
            continue
        out.append(f"#### {topic}\n")
        out.extend(f"- {it}" for it in items)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":
    page = PAGE.read_text(encoding="utf-8")
    general = parse("General examples.pdf.md", numbered=False)
    stats = parse("statistical examples.pdf.md", numbered=True)
    page = page.replace("<!--GENERAL_EXAMPLES-->", render(general))
    page = page.replace("<!--STAT_EXAMPLES-->", render(stats))
    PAGE.write_text(page, encoding="utf-8")
    print("general:", sum(map(len, general.values())), "stats:", sum(map(len, stats.values())))
