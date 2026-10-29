"""Write knowledge/kb/real-exam-questions-2026.md from the prompt banks (real + trial exam questions).

Reads knowledge/data/writing_prompts.docs.json (chat text) and, if present,
knowledge/data/writing_prompts.photos.json (questions transcribed from the teacher's photos).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "knowledge" / "data"
TYPE = {"opinion": "Opinion (agree/disagree)", "discussion": "Discussion", "adv_disadv": "Advantages/disadvantages",
        "outweigh": "Outweigh", "positive_negative": "Positive/negative", "problem_solution": "Problem/solution",
        "cause_effect": "Cause/effect", "cause_solution": "Cause/solution", "direct_question": "Direct (two-part) question",
        "line": "Line graph", "bar": "Bar chart", "pie": "Pie chart", "table": "Table", "map": "Map", "process": "Process",
        "mixed": "Multiple graphs"}
PAGE_LINK = {"opinion": "writing-task2-opinion-agree-disagree.md", "discussion": "writing-task2-discussion.md",
             "adv_disadv": "writing-task2-advantages-disadvantages.md", "outweigh": "writing-task2-outweigh.md",
             "positive_negative": "writing-task2-positive-negative-development.md",
             "problem_solution": "writing-task2-problem-solution.md", "cause_effect": "writing-task2-cause-effect.md",
             "cause_solution": "writing-task2-cause-solution.md", "direct_question": "writing-task2-direct-question.md",
             "line": "writing-task1-line-graph.md", "bar": "writing-task1-bar-chart.md", "pie": "writing-task1-pie-chart.md",
             "table": "writing-task1-table.md", "map": "writing-task1-map.md", "process": "writing-task1-process-diagram.md",
             "mixed": "writing-task1-multiple-graphs.md"}

HEAD = """---
title: Real & Trial Exam Questions Reported in 2026
category: exam-info
tags: [real-exam, trial-exam, writing-task2, writing-task1, speaking, 2026, predictions]
sources: ["LATEST_EXAMS_ARCHIVE/messages.json", "IELTS_PREP_ARCHIVE/messages.json"]
---

# Real & trial exam questions reported in 2026

The teacher's **LATEST_EXAMS** channel collects questions that her students got in the **real IELTS
exam** (computer-delivered, Baku) and in **trial exams** at the test centre, from June to October 2026.
Questions often come back within weeks, so practise every one of them. Each question is also in the
app's writing-prompt bank (filter by source *real_exam* / *trial_exam*) so you can write it under exam
conditions.

How to use this page:
1. Identify the essay type yourself before you look at the label.
2. Plan in 5 minutes using the structure page for that type (link in the table).
3. Write it in the app (40 min Task 2 / 20 min Task 1) and ask for AI feedback.

> Wording: questions typed by students from memory are kept close to the original; obvious typos are
> corrected and the original wording is kept in the prompt bank's note. Dates are the exam date when
> the teacher gave one, otherwise the date she posted the question.

"""


def norm(s):
    return re.sub(r"\W+", "", s.lower())[:80]


def main():
    rows = []
    seen = set()
    for f in ["writing_prompts.docs.json", "writing_prompts.photos.json"]:
        p = DATA / f
        if not p.exists():
            continue
        for r in json.load(open(p, encoding="utf-8")):
            if r.get("source") not in ("real_exam", "trial_exam"):
                continue
            if r.get("ref") == "telegram:IELTS_PREP_ARCHIVE":  # the course's own mock exams, not test-centre exams
                continue
            k = norm(r["prompt"])
            if k in seen:
                continue
            seen.add(k)
            rows.append((r.get("source_date") or "", r["task"], r.get("essay_type") or "", r["prompt"].strip(),
                         r["source"], "photo" if "photos" in f else "chat"))
    rows.sort(key=lambda x: x[0], reverse=True)
    out = [HEAD]
    for task in (2, 1):
        out.append(f"## Writing Task {task}\n")
        out.append("| Date | Exam | Type | Question |\n|---|---|---|---|")
        for d, t, et, prompt, src, origin in rows:
            if t != task:
                continue
            prompt = re.sub(r"\s+", " ", prompt).replace("|", "/")
            typ = f"[{TYPE.get(et, et)}]({PAGE_LINK[et]})" if et in PAGE_LINK else (et or "?")
            exam = "real" if src == "real_exam" else "trial"
            if origin == "photo":
                exam += " (photo)"
            out.append(f"| {d} | {exam} | {typ} | {prompt} |")
        out.append("")
    out.append("""## Speaking

- **Part 2 (real exam, 17 Sep 2026)**: *A good compliment made by a person you appreciate* (Describe a
  time when someone you appreciate gave you a good compliment). See
  [Part 2 cue cards](speaking-part2-cue-cards.md) for the prep routine.
- The teacher posted the full **predicted question lists** as photos: All Part 1 (28 Jun, 17 Sep, 22 Oct),
  Part 2 topics for **May–December** and **January–August** (9 Jul), Part 2 (17 Sep, 22 Oct), Part 3 (9 Jul,
  17 Sep, "new Part 3 questions" 6 Oct, 22 Oct) and "new speaking questions and topics" (13 Oct). The
  question bank contains the transcribed versions; her advice for a July exam was simply: *"Yes"*,
  learn all of them.

## Patterns worth noticing

- **Outweigh** and **direct (two-part)** questions came up repeatedly in Sep–Oct 2026 (private healthcare,
  fast-food outlets, personal data, cosmetic surgery, selfies at famous places, music).
- Several Task 2 questions are about **society and family** (living alone, family history, juvenile
  delinquency) and **public spending** (new buildings vs renovation, museums, healthcare).
- Task 1 in real exams used every type: maps and plans (museum, bookstore, university), processes
  (home smokery), mixed graphs, pie charts (household energy) and tables.
""")
    (ROOT / "knowledge" / "kb" / "real-exam-questions-2026.md").write_text("\n".join(out), encoding="utf-8")
    print(len(rows), "questions")


if __name__ == "__main__":
    main()
