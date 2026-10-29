"""Generate the data-heavy speaking KB pages from knowledge/data/speaking_questions.docs.json.

Run after tools/kb_speaking_build.py:
    .venv\\Scripts\\python.exe tools\\kb_speaking_pages.py
Writes knowledge/kb/speaking-part1-model-answers-1.md, -2.md, speaking-part2-cue-cards.md,
speaking-part3-discussion.md. (speaking-overview-and-strategies.md is hand-written.)
"""
from __future__ import annotations

import json
import os
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "knowledge", "data", "speaking_questions.docs.json")
KB = os.path.join(ROOT, "knowledge", "kb")

P1_LIST = "IELTS_PREP_ARCHIVE/files/SPEAKING PART 1 QUESTIONS (ALL).pdf"
P1_MA = "IELTS_PREP_ARCHIVE/files/MODEL ANSWERS AND VOCABULARY (ALL).pdf"
P1_MA_SHORT = "IELTS_PREP_ARCHIVE/files/Model Answers and Vocabulary for PART 1 QUESTIONS.pdf"
TOPIC_FILES = [
    "IELTS_PREP_ARCHIVE/files/Topic 1 - Travel - P2_3 vocabulary.pdf",
    "IELTS_PREP_ARCHIVE/files/Topic 2 - Tall building - P2_3 vocabulary.pdf",
    "IELTS_PREP_ARCHIVE/files/Topic 3 - Getting up early Vocabulary.pdf",
    "IELTS_PREP_ARCHIVE/files/Topic 4 - Planting Vocabulary.pdf",
    "IELTS_PREP_ARCHIVE/files/Topic 5 - Friend Vocabulary.pdf",
    "IELTS_PREP_ARCHIVE/files/Topic 6 - Plan Vocabulary.pdf",
]


def fm(title: str, tags: list[str], sources: list[str]) -> str:
    return ("---\n"
            f"title: {title}\n"
            "category: speaking\n"
            f"tags: [{', '.join(tags)}]\n"
            f"sources: [{', '.join(json.dumps(s, ensure_ascii=False) for s in sources)}]\n"
            "---\n\n")


def vocab_line(v: dict) -> str:
    t = f" *({v['type']})*" if v.get("type") else ""
    return f"- **{v['term']}**{t} — {v['meaning']}"


def group_by_topic(items):
    g: "OrderedDict[str, list]" = OrderedDict()
    for it in items:
        g.setdefault(it["topic"], []).append(it)
    return g


def render_part1(topics: "OrderedDict[str, list]", numbering: dict) -> str:
    out = []
    for topic, qs in topics.items():
        season = qs[0].get("season")
        out.append(f"## {numbering[topic]}. {topic}" + (f" ({season})" if season else "") + "\n")
        i = 0
        while i < len(qs):
            # questions that share one model answer are shown together
            group = [qs[i]]
            while i + len(group) < len(qs) and qs[i + len(group)].get("model_answer") == qs[i].get("model_answer"):
                group.append(qs[i + len(group)])
            out.append("### " + " / ".join(q["question"] for q in group) + "\n")
            if qs[i].get("model_answer"):
                out.append(qs[i]["model_answer"] + "\n")
            if qs[i].get("vocabulary"):
                out.append("\n".join(vocab_line(v) for v in qs[i]["vocabulary"]) + "\n")
            i += len(group)
    return "\n".join(out)


def main() -> None:
    data = json.load(open(DATA, encoding="utf-8"))
    os.makedirs(KB, exist_ok=True)
    p1 = [d for d in data if d["part"] == 1]
    topics = group_by_topic(p1)
    names = list(topics)
    numbering = {t: i + 1 for i, t in enumerate(names)}
    split = names.index("Websites")
    halves = [OrderedDict((t, topics[t]) for t in names[:split]), OrderedDict((t, topics[t]) for t in names[split:])]

    intro = (
        "These are the teacher's Part 1 model answers (from *MODEL ANSWERS AND VOCABULARY (ALL)*), reproduced "
        "verbatim, with the key vocabulary she attached to each answer. Questions come from *SPEAKING PART 1 "
        "QUESTIONS (ALL)*; topics marked **(May-Dec 2026)** are the ones predicted for the current exam season.\n\n"
        "**How the model answers are built** — almost every answer is three sentences:\n"
        "1. a direct answer to the question (often with a softener such as *To be completely honest*, *Generally speaking*, *Without a doubt*);\n"
        "2. a reason or a concrete detail;\n"
        "3. an extra point, example or contrast (*Also*, *Plus*, *However*, *On top of that*).\n\n"
        "Practise by answering aloud in your own words (20–30 seconds each) and try to reuse two or three of the listed "
        "collocations — do not memorise the answers word for word; examiners notice rehearsed speech.\n\n"
    )
    other = ["speaking-part1-model-answers-2.md", "speaking-part1-model-answers-1.md"]
    titles = ["Speaking Part 1 Model Answers (1): Work, Home, People and Habits",
              "Speaking Part 1 Model Answers (2): Everyday Things, Leisure and Culture"]
    for n, half in enumerate(halves):
        toc = "Topics on this page: " + ", ".join(f"{numbering[t]}. {t}" for t in half) + \
              f". Continued in [{other[n]}]({other[n]}).\n\n"
        tags = ["speaking", "part-1", "model-answers", "vocabulary"] + [t.lower().replace(" ", "-") for t in half][:8]
        body = fm(titles[n], tags, [P1_MA, P1_LIST, P1_MA_SHORT]) + f"# {titles[n]}\n\n" + intro + toc + render_part1(half, numbering)
        open(os.path.join(KB, f"speaking-part1-model-answers-{n + 1}.md"), "w", encoding="utf-8").write(body)

    # ---------------- Part 2
    p2 = [d for d in data if d["part"] == 2]
    out = [fm("Speaking Part 2 Cue Cards (May-Dec 2026)",
              ["speaking", "part-2", "cue-cards", "idioms", "collocations", "phrasal-verbs", "may-dec-2026"],
              TOPIC_FILES)]
    out.append("# Speaking Part 2 Cue Cards (May-Dec 2026)\n\n"
               "The six cue cards the teacher worked through in class (Topic 1–6 handouts, sent 7 and 19 August), each "
               "with the topic vocabulary she grouped into idioms, collocations, phrasal verbs and advanced words. "
               "The handouts give no Part 2 sample answer; their Part 3 follow-up questions with model answers are in "
               "[speaking-part3-discussion.md](speaking-part3-discussion.md).\n\n"
               "**Routine for every card** (1 minute to prepare, speak for up to 2 minutes): write one or two words "
               "per bullet point, pick 3–4 phrases from the lists below to use, then answer the bullets in order "
               "and finish with the *why / how you felt* point — that last point is where you can talk longest.\n")
    for d in p2:
        src = d["source"]
        out.append(f"\n## {d['question']}\n")
        meta = []
        if d.get("season"):
            meta.append(f"Season: **{d['season']}**")
        if src.startswith("telegram"):
            meta.append(f"Reported by the teacher from a real exam on {d['source_date']} (Telegram)")
        else:
            meta.append(f"Handout: *{src.split(':', 1)[1]}*")
        out.append(" · ".join(meta) + "\n")
        if d.get("cue_points"):
            out.append("You should say:\n" + "\n".join(f"- {c}" for c in d["cue_points"]) + "\n")
        groups: "OrderedDict[str, list]" = OrderedDict()
        for v in d.get("vocabulary", []):
            groups.setdefault(v["group"], []).append(v)
        for gname, vs in groups.items():
            out.append(f"**{gname}**\n\n" + "\n".join(vocab_line(v) for v in vs) + "\n")
        if src.startswith("telegram"):
            out.append("No cue points or vocabulary were given in the chat (the full Part 2 topic lists the teacher "
                       "posted were photos). Use the standard frame: *who the person is · what the compliment was · "
                       "when/where it happened · how you felt about it*.\n")
    open(os.path.join(KB, "speaking-part2-cue-cards.md"), "w", encoding="utf-8").write("\n".join(out))

    # ---------------- Part 3
    p3 = [d for d in data if d["part"] == 3]
    out = [fm("Speaking Part 3 Discussion Questions and Model Answers",
              ["speaking", "part-3", "discussion", "model-answers", "may-dec-2026"], TOPIC_FILES)]
    out.append("# Speaking Part 3 Discussion Questions and Model Answers\n\n"
               "Part 3 questions from the teacher's Topic 1–6 handouts, each linked to its Part 2 cue card "
               "(see [speaking-part2-cue-cards.md](speaking-part2-cue-cards.md)). Model answers are verbatim.\n\n"
               "**Pattern of the model answers** (6–7 sentences, about 45–60 seconds spoken):\n"
               "1. answer the question directly / give your overall view;\n"
               "2. first reason with an explanation;\n"
               "3. second reason or contrasting side (*On the other hand*, *However*, *In contrast*);\n"
               "4. an example or a specific situation (*For instance*, *For example*, *my grandparents...*);\n"
               "5. a closing sentence (*Ultimately*, *Therefore*, *Consequently*, *In short*).\n\n"
               "Notice that the answers recycle the Part 2 vocabulary (e.g. *get away from it all*, *a hard pill to "
               "swallow*, *the early bird catches the worm*, *call a rain check*) — Part 3 is where those phrases earn "
               "Lexical Resource points. Part 3 is about people and society in general, so speak about *people*, "
               "*young people*, *my country* rather than only about yourself.\n")
    for topic, qs in group_by_topic(p3).items():
        out.append(f"\n## {topic} (Part 2: *{qs[0]['related_part2']}*)\n")
        for q in qs:
            out.append(f"### {q['question']}\n\n{q.get('model_answer', '')}\n")
    open(os.path.join(KB, "speaking-part3-discussion.md"), "w", encoding="utf-8").write("\n".join(out))
    print("pages written")


if __name__ == "__main__":
    main()
