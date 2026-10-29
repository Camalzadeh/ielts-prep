"""Harvest the handout model-essay questions (**Task:** / **Question:** lines) and practice tasks
from knowledge/kb/writing-*.md into tools/kb_prompts_course_material.json (merged by kb_build_essays.py).

The writing pages quote the teacher's handouts verbatim, so these are course_material prompts.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge" / "kb"
TYPE = {"line-graph": "line", "bar-chart": "bar", "pie-chart": "pie", "table": "table", "multiple-graphs": "mixed",
        "map": "map", "process-diagram": "process", "opinion-agree-disagree": "opinion",
        "positive-negative-development": "positive_negative", "discussion": "discussion",
        "advantages-disadvantages": "adv_disadv", "outweigh": "outweigh", "problem-solution": "problem_solution",
        "cause-effect": "cause_effect", "cause-solution": "cause_solution", "direct-question": "direct_question"}


def main():
    out = []
    for p in sorted(KB.glob("writing-task*.md")):
        m = re.match(r"writing-task(\d)-(.+)\.md", p.name)
        task, slug = int(m.group(1)), m.group(2)
        if slug not in TYPE:
            continue
        text = p.read_text(encoding="utf-8")
        srcs = re.search(r"^sources:\s*\[(.*)\]", text, re.M)
        sources = re.findall(r'"([^"]+)"', srcs.group(1)) if srcs else []
        lines = text.splitlines()
        for i, line in enumerate(lines):
            q = re.match(r"^\*\*(Task|Question|Practice task|Practice)[^*]*:\*\*\s*\*?(.+?)\*?\s*$", line)
            if not q and line.startswith("*") and not line.startswith("**") and i >= 2 \
                    and lines[i - 2].startswith("## Practice task"):
                q = re.match(r"^()\*(.+?)\*\s*$", line)
                if q:
                    q = re.match(r"^(Practice)(.*)$", "Practice" + q.group(2))
            if not q:
                continue
            prompt = q.group(2).strip().strip("*").strip()
            if len(prompt) < 40:
                continue
            out.append({"task": task, "essay_type": TYPE[slug], "prompt": prompt, "source": "course_material",
                        "source_date": None, "image": None, "image_description": None,
                        "note": ("practice task" if q.group(1).startswith("Practice") else "model essay question") + f" in {p.name}",
                        "ref": sources[0] if sources else None})
    dest = Path(__file__).with_name("kb_prompts_course_material.json")
    json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(out), "prompts ->", dest)


if __name__ == "__main__":
    main()
