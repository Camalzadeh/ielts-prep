"""Write knowledge/kb/vocabulary-for-writing.md from "Vocabulary for writing .pdf" (topic intros + example
tasks taken from the handout) and the parsed items in knowledge/data/vocabulary.json."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "knowledge" / "raw" / "IELTS_PREP_ARCHIVE" / "docs" / "Vocabulary for writing .pdf.md"


def flat(s):
    return re.sub(r"\s+", " ", s).strip()


def main():
    t = DOC.read_text(encoding="utf-8")
    t = re.sub(r"<!-- page \d+ -->", "\n", t)
    vocab = [v for v in json.load(open(ROOT / "knowledge" / "data" / "vocabulary.json", encoding="utf-8"))
             if v["topic"].startswith("Writing Topic")]
    starts = [m for m in re.finditer(r"(?m)^Topic (\d+):? ([A-Z][^\n]+)$", t) if "Task" not in m.group(2)]
    out = ["""---
title: Vocabulary for Writing (10 IELTS Topics)
category: vocabulary
tags: [vocabulary, writing-task2, topic-vocabulary, collocations, work, education, family, environment, culture, health, global-challenges, cities, countryside, government]
sources: ["IELTS_PREP_ARCHIVE/files/Vocabulary for writing .pdf"]
---

# Vocabulary for writing: 10 IELTS topics

The teacher shared **"Vocabulary for writing"** on 31 July together with the list of the ten Task 2
topics (*Topic 1: Work and careers … Topic 10: Government and the authorities*). For each topic the
handout gives a short description of what the examiners ask about, an example task, a band-9 model
essay with the key words in bold, and then the key words with definitions and an example sentence.
The handout's own advice:

> "Please don't try to learn or memorise all of these words immediately. Go through the whole book
> from Module 1 to 10, and try to practise using a small group of words from all of the Modules, then
> go back and expand on each group."

Every word below is also in the app's vocabulary trainer (topic *Writing Topic N*), with its example
sentence. A good routine: before writing an essay, open the matching topic and choose 4–5 phrases to
use.
"""]
    for i, m in enumerate(starts):
        n, name = m.group(1), m.group(2).strip()
        end = starts[i + 1].start() if i + 1 < len(starts) else len(t)
        sec = t[m.start():end]
        about = re.search(r"About Topic \d+\s*(.+?)(?:Topic \d+ [Ee]xample Task)", sec, re.S)
        task = re.search(r"[Ee]xample Task\s*(.+?)(?:Explanation of the Task)", sec, re.S)
        expl = re.search(r"Explanation of the Task\s*(.+?)(?:\n\s*\n|If you are not)", sec, re.S)
        out.append(f"\n## Topic {n}: {name}\n")
        if about:
            a = flat(about.group(1))
            a = re.split(r"(?<=\.) You are not expected", a)[0]
            out.append(f"**What it covers:** {a}\n")
        if task:
            out.append(f"**Example task:** *{flat(task.group(1))}*\n")
        if expl:
            out.append(f"**Essay type:** {flat(expl.group(1))}\n")
        items = [v for v in vocab if v["topic"].startswith(f"Writing Topic {n}:")]
        out.append("| Word / phrase | Meaning | Example |\n|---|---|---|")
        for v in items:
            ex = v.get("example", "").replace("|", "/")
            out.append(f"| **{v['term'].replace('|', '/')}** | {v['meaning'].replace('|', '/')} | {ex} |")
    (ROOT / "knowledge" / "kb" / "vocabulary-for-writing.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(len(starts), "topics", len(vocab), "items")


if __name__ == "__main__":
    main()
