"""Build knowledge/kb/speaking-predicted-topics.md from the photo-derived speaking bank."""
import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "knowledge" / "data" / "speaking_questions.photos.json"
OUT = ROOT / "knowledge" / "kb" / "speaking-predicted-topics.md"


def main():
    qs = json.loads(SRC.read_text(encoding="utf-8"))
    lines = ["---", "title: Predicted speaking topics (teacher's lists, 2026–2027)", "category: speaking",
             "tags: [speaking, predicted, part1, part2, part3, real-exam]",
             'sources: ["LATEST_EXAMS_ARCHIVE/photos", "IELTS_PREP_ARCHIVE/photos"]', "---", "",
             "# Predicted speaking topics",
             "",
             "Every topic the teacher posted as *predicted & reported* for the real exam, transcribed from the "
             "chat screenshots. Seasons follow the exam question-bank cycles (Jan–Aug, May–Dec, Sep–Apr). "
             "The teacher's instruction: practise **all** of them. Practise any of these with recording on the "
             "Speaking page.", ""]
    for part, name in ((1, "Part 1 — short questions"), (2, "Part 2 — cue cards"), (3, "Part 3 — discussion")):
        lines.append(f"## {name}\n")
        topics = OrderedDict()
        for q in qs:
            if q["part"] == part:
                topics.setdefault(q["topic"], []).append(q)
        for topic, items in topics.items():
            season = next((i["season"] for i in items if i.get("season")), "")
            lines.append(f"### {topic}" + (f"  \n*{season}*" if season else "") + "\n")
            for i in items:
                if part == 2:
                    lines.append(f"**{i['question']}**  \nYou should say:")
                    lines += [f"- {c}" for c in i.get("cue_points") or []]
                    lines.append("")
                else:
                    lines.append(f"- {i['question']}")
            lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT, sum(1 for _ in qs), "questions")


if __name__ == "__main__":
    main()
