"""Write knowledge/kb/course-timeline-and-resources.md (hand-written prose + generated link tables).

All links below were assigned by the teacher in the IELTS_PREP_ARCHIVE / LATEST_EXAMS_ARCHIVE chats.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def L(b, t):
    return f"[C{b} T{t}](https://engnovate.com/ielts-listening-tests/cambridge-ielts-{b:02d}-academic-listening-test-{t}/)"


def R(b, t):
    return f"[C{b} T{t}](https://engnovate.com/ielts-reading-tests/cambridge-ielts-{b:02d}-academic-reading-test-{t}/)"


HOMEWORK = [  # date, tests
    ("24 Jul", [(11, 1), (11, 2)]), ("27 Jul", [(12, 1), (12, 2), (12, 3)]), ("29 Jul", [(12, 4), (13, 1)]),
    ("31 Jul", [(13, 2), (13, 3)]), ("3 Aug", [(13, 4), (14, 1)]), ("5 Aug", [(14, 2), (14, 3), (14, 4)]),
    ("7 Aug", [(15, 1), (15, 2)]), ("10 Aug", [(15, 3), (15, 4)]), ("12 Aug", [(16, 1), (16, 2), (16, 3), (16, 4)]),
    ("19 Aug", [(17, 1), (17, 2)]), ("21 Aug", [(17, 3), (17, 4)]), ("24 Aug", [(18, 1), (18, 2), (18, 3)]),
    ("24 Aug (2nd post)", [(18, 4), (19, 1)]), ("28 Aug", [(19, 2), (19, 3), (19, 4)]),
]

IP = "https://ieltsprogress.com/cambridge-10-listening-test-{}-transcript/"
ITO = "https://ieltstrainingonline.com/audio-script-cambridge-ielts-{}-listening-test-0{}/"

PAGE = """---
title: Course Timeline & Resources (Jul–Sep 2026)
category: course
tags: [course, timeline, homework, engnovate, ieltsdeal, ieltstrainingonline, links, trial-exam]
sources: ["IELTS_PREP_ARCHIVE/messages.json", "LATEST_EXAMS_ARCHIVE/messages.json"]
---

# Course timeline & resources

The course ran in the Telegram group **"July - 1.3.5 - 17.00"** (lessons on Mondays, Wednesdays and
Fridays at 17:00) from **20 July to 13 September 2026**, taught by **Elvira Malikova**. This page lists,
lesson by lesson, every handout she shared and every practice link she assigned, so you can redo the
course in order. Handouts are summarised in the other Learn pages (links in the last column).

> Pattern of the course: each lesson = one *Unit* (Cambridge listening/reading pages + answers + a
> vocabulary list) → two or three engnovate listening + reading tests for homework → one Task 1 and one
> Task 2 essay posted in the chat. Three trial exams (14 Aug, 30 Aug, 11 Sep) and two speaking tests
> (26 Aug, 9 Sep).

## 1. Lesson-by-lesson

| Date | Unit / topic | Handouts shared | Writing homework | Learn pages |
|---|---|---|---|---|
| Mon 20 Jul | Unit 1 | Unit 1.pdf (Cambridge 10 listening pages + reading), Unit 1 - Answers, **Vocabulary Unit 1**, audio *page 1–7.mp3* | – | [Listening](listening-strategies.md) |
| Tue 21 Jul | – | Numbers & letters practice videos (see §3) | – | [Listening](listening-strategies.md) |
| Wed 22 Jul | Unit 2 | Unit 2.pdf, Unit 2 - Answers, **Vocabulary Unit 2** | – | |
| Fri 24 Jul | Unit 3 | Unit 3.pdf (Task 1 introductions & paraphrasing), Unit 3 - Answers, **Types of graphs.pdf**; board notes *MIN 150 WORDS / Introduction / Overview / Detail*; **Terms used in map questions** | Line graph: money spent on books (Germany, France, Italy, Austria 1995–2005) | [Task 1 overview](writing-task1-overview.md), [Line graph](writing-task1-line-graph.md) |
| Mon 27 Jul | Unit 4 | Unit 4.pdf (scanned reading pages), Unit 4 - Answers, **Vocabulary Unit 4**, Speaking Part 1 Questions (PART 1), Model Answers and Vocabulary for PART 1 | – | [Speaking P1](speaking-part1-model-answers-1.md) |
| Wed 29 Jul | Bar charts | **Writing + Bar graph.pdf**, **Bar Graph - Model Essays.pdf**; board notes *number / amount / quantity / percentage, the figure for, tenses with by/until* | Bar charts: transport used by young people in 4 countries; UK businesses on social media 2012–2016 | [Bar chart](writing-task1-bar-chart.md), [Task 1 language](writing-task1-language.md) |
| Fri 31 Jul | Cause/solution | **Cause/Solution Essay Structure**, **Linking Words**, **Vocabulary for writing** (10 topics), **General examples**, **statistical examples**, SPEAKING PART 1 QUESTIONS (ALL), MODEL ANSWERS AND VOCABULARY (ALL) | Task 2: *Each year, the crime rate increases…* | [Cause/solution](writing-task2-cause-solution.md), [Linking words](linking-words.md), [Vocabulary for writing](vocabulary-for-writing.md) |
| Mon 3 Aug | Multiple graphs, problem/solution | **Multiple Graphs.pdf**, **Problem/Solution Essay - Structure**; board notes for two graphs | Electricity demand (line + pie); children & computer games (problem/solution) | [Multiple graphs](writing-task1-multiple-graphs.md), [Problem/solution](writing-task2-problem-solution.md) |
| Wed 5 Aug | Speaking test 1 (Part 1) | **Vocabulary Unit 8**; "Get ready for the Speaking Part 1 questions on pages 6–8" | – | [Speaking overview](speaking-overview-and-strategies.md) |
| Fri 7 Aug | Pie charts, cause/effect | **Pie Chart Example Essays**, **Cause/Effect Essay - Structure**, **Vocabulary Unit 9**, **Topic 1 – Travel** and **Topic 2 – Tall building** (Part 2/3 vocabulary) | Pie charts: TV devices in Canada; household spending Japan/Malaysia; Task 2: students not choosing science | [Pie chart](writing-task1-pie-chart.md), [Cause/effect](writing-task2-cause-effect.md), [Part 2 cue cards](speaking-part2-cue-cards.md) |
| Mon 10 Aug | – | **Vocabulary Unit 10**; to-do: all L/R tests, Speaking Topics 3 & 4, Part 3 for Topics 1 & 2 | – | |
| Wed 12 Aug | In-class writing exam | **Vocabulary Unit 11** | Fast-food line graph + students' concentration (cause/solution), written in class | |
| **Fri 14 Aug** | **First Trial Exam** (17:00–20:00, L + R + W) | Listening [C21 T1](https://engnovate.com/ielts-listening-tests/cambridge-ielts-21-academic-listening-test-1/), Reading [C21 T1](https://engnovate.com/ielts-reading-tests/cambridge-ielts-21-academic-reading-test-1/) | Line graph: students studying abroad (UK/USA/Australia 2002–2008); homelessness (cause/solution) | [Exam format](exam-format-and-scoring.md) |
| 17–18 Aug | Results | "Unit 11 – the results of the Writing Exam"; results of the first trial exam with minimum speaking bands | – | |
| Wed 19 Aug | Tables, adv/disadv | **Vocabulary Unit 13**, **Table Example Essays**, **Advantage/Disadvantage essay examples**, **Topic 3 – Getting up early**, **Topic 4 – Planting**, **Topic 5 – Friend**, **Topic 6 – Plan** | Tables: tourist arrivals 2009–2010; consumer spending 2002; Task 2: machines replacing human jobs | [Table](writing-task1-table.md), [Adv/disadv](writing-task2-advantages-disadvantages.md) |
| Fri 21 Aug | Speaking Parts 2–3 | **Vocabulary Unit 14**; Part 2 topics and Part 3 questions (photos) | – | [Part 3](speaking-part3-discussion.md) |
| Mon 24 Aug | Opinion, outweigh, predictions, processes | **Outweigh essay structure**, **Prediction Structures in IELTS Writing Task 1**, **Vocabulary Unit 15**, **Vocabulary unit 16**, **Opinion Essay - Agree/Disagree**, **Opinion Essay - Positive/Negative Development**, **Process Diagram Structure** | Pie charts: global production 2040/2060; bamboo fabric process; Task 2: overpopulation (outweigh), money transfers (pos/neg), local customs (opinion) | [Outweigh](writing-task2-outweigh.md), [Opinion](writing-task2-opinion-agree-disagree.md), [Pos/neg](writing-task2-positive-negative-development.md), [Process](writing-task1-process-diagram.md) |
| Wed 26 Aug | Speaking test 2 (Parts 2–3) + reading | Reading [C20 T3](https://engnovate.com/ielts-reading-tests/cambridge-ielts-20-academic-reading-test-3/) | – | |
| Fri 28 Aug | Discussion, direct question | **Discussion Essay - Structure**, **Direct Question Essay Structure**, **Vocabulary Unit 17** | Task 2: children & smartphones (direct question); university subjects (discussion) | [Discussion](writing-task2-discussion.md), [Direct question](writing-task2-direct-question.md) |
| **Sun 30 Aug** | **Second Trial Exam** (12:30, ~3 h) | Listening [C21 T3](https://engnovate.com/ielts-listening-tests/cambridge-ielts-21-academic-listening-test-3/), Reading [C21 T2](https://engnovate.com/ielts-reading-tests/cambridge-ielts-21-academic-reading-test-2/) | Bar chart: UK people eating 5+ portions of vegetables 2011–2017; teachers: academic achievement vs motivation (opinion) | |
| Mon 31 Aug | Maps | **Map Essay Structure**, **Vocabulary Unit 19**; extra practice site <https://ieltsonlinetests.com/> | Map: village of Stokeford 1930 / 2010 | [Map](writing-task1-map.md) |
| Wed 2 Sep | – | **Unit 20 Vocabulary** | – | |
| Wed 9 Sep | Speaking test 3 (Parts 1–3) + class writing | – | Oil resources vs consumption (bar charts); lack of respect for older people (causes/problems) | |
| **Fri 11 Sep** | **Final Trial Exam** (17:00, L + R + W) | Listening [C21 T3](https://engnovate.com/ielts-listening-tests/cambridge-ielts-21-academic-listening-test-3/), Reading [C21 T3](https://engnovate.com/ielts-reading-tests/cambridge-ielts-21-academic-reading-test-3/) | Urbanisation in four Asian countries 1970–2040 (line graph with predictions); environmental damage (cause/solution) | |
| 13 Sep | End | "The programme is complete." | | |

Every Task 1/Task 2 question above is in the writing-prompt bank, and the course's student essays
(including your own) are in the essays bank.

## 2. Homework tests (engnovate) — IELTS_PREP chat

Listening and reading tests were always assigned in pairs from the same Cambridge book.

| Posted | Listening | Reading |
|---|---|---|
{HOMEWORK_ROWS}

Extra links posted in the group: Reading [C20 T2](https://engnovate.com/ielts-reading-tests/cambridge-ielts-20-academic-reading-test-2/) (5 Aug) and the three trial-exam tests listed above.

## 3. Unit audioscripts and reading explanations

The Unit PDFs are scans of Cambridge IELTS pages; these were the links given to check answers.

**Unit 1 — audioscripts (Cambridge 10)**
- Pages 1–2: [Cambridge 10 Test 1 (ieltstrainingonline)]({ITO_10_1})
- Pages 3–4: [Cambridge 10 Test 2 (ieltsprogress)]({IP_2})
- Pages 5–6: [Cambridge 10 Test 3 (ieltsprogress)]({IP_3})
- Page 7: [Cambridge 10 Test 4 (ieltsprogress)]({IP_4})

**Unit 1 — reading explanations (ieltsdeal)**
- Page 8: [Cambridge 11 Test 1, Passage 1](https://ieltsdeal.com/cambridge-11-test-1-reading-passage-1-answers-solutions-with-explanations/)
- Page 11: [Cambridge 11 Test 3, Passage 1 – The Story of Silk](https://ieltsdeal.com/ielts-academic-reading-cambridge-11-reading-test-3-passage-1-the-story-of-silk-with-best-solutions-and-detailed-explanations/)
- Page 15: [Cambridge 10 Test 4, Passage 1 – The Megafires of California](https://ieltsdeal.com/ielts-academic-reading-cambridge-10-test-4-reading-passage-1-the-megafires-of-california-with-best-solutions-and-explanations/)

**Unit 2 — audioscripts (Cambridge 10)**
- Pages 1–2: [Cambridge 10 Test 1 (ieltsprogress)]({IP_1})
- Pages 3, 5: [Cambridge 10 Test 2 (ieltstrainingonline)]({ITO_10_2})
- Pages 7, 9: [Cambridge 10 Test 3 (ieltstrainingonline)]({ITO_10_3})
- Pages 11, 13, 15: [Cambridge 10 Test 4 (ieltstrainingonline)]({ITO_10_4})

**Unit 2 — reading explanations (ieltsdeal)**
- Page 17: [Cambridge 10 Test 1, Passage 2 – European Transport System 1990–2010](https://ieltsdeal.com/ielts-academic-reading-cambridge-10-test-1-reading-passage-2-european-transport-system-1990-2010-with-best-solutions-and-explanations/)
- Page 21: [Cambridge 10 Test 2, Passage 1 – Tea and the Industrial Revolution](https://ieltsdeal.com/ielts-academic-reading-cambridge-10-test-2-reading-passage-1-tea-and-the-industrial-revolution-with-best-solutions-detailed-explanations/)
- Page 25: [Cambridge 10 Test 3, Passage 1 – The Context, Meaning and Scope of Tourism](https://ieltsdeal.com/ielts-academic-reading-cambridge-10-test-3-reading-passage-1-the-context-meaning-and-scope-of-tourism-with-best-solutions-and-explanations/)
- Page 29: [Cambridge 10 Test 1, Passage 1 – Stepwells](https://ieltsdeal.com/ielts-academic-reading-cambridge-10-test-1-reading-passage-1-stepwells-with-best-solutions-and-explanations/)

**Unit 3**
- Audioscript, page 1: [Cambridge 11 Test 1 (ieltstrainingonline)]({ITO_11_1})
- Reading, page 3: [Cambridge 10 Test 1, Passage 3 – The Psychology of Innovation](https://ieltsdeal.com/ielts-academic-reading-cambridge-10-test-1-reading-passage-3-the-psychology-of-innovation-with-best-solutions-and-explanations/?amp=1)

**Numbers & letters practice (listening, 21 Jul)**
- <https://www.youtube.com/watch?v=JiagO6-PWhM&t=15s>
- <https://www.youtube.com/watch?v=iNQ8vtM2Vu4&t=0s>
- <https://www.youtube.com/watch?v=n9E-1kURLEk>

## 4. LATEST_EXAMS channel (Jun–Oct 2026)

A separate channel where the teacher posts predicted speaking questions and questions from real
and trial exams (see [Real exam questions 2026](real-exam-questions-2026.md)).

- **28 Jun — "Listening Test to do this week"**: all of Cambridge 5–8:
  {LATEST_L}
- **28 Jun — "Reading Tests to do this week"**: all of Cambridge 5–8:
  {LATEST_R}
- **28 Jun**: for a computer-delivered exam, register for a **trial exam at Barattson** (contact by WhatsApp; number in the chat) and send the teacher the date and result so she can help you choose the exam day.
- **27 Sep / 29 Sep**: the two big handbooks **Writing Task 2 Essays – STRUCTURE.pdf** and **Writing Task 1 – Structure.pdf** (they combine all the course handouts; see the writing pages).
- Speaking lists (photos): All Part 1 (28 Jun, 17 Sep, 22 Oct), Part 2 May–Dec and Jan–Aug (9 Jul), Part 2 (17 Sep, 22 Oct), Part 3 (9 Jul, 17 Sep, 6 Oct, 22 Oct).
"""


def main():
    rows = "\n".join(
        f"| {d} | " + ", ".join(L(b, t) for b, t in ts) + " | " + ", ".join(R(b, t) for b, t in ts) + " |"
        for d, ts in HOMEWORK)
    latest_l = ", ".join(L(b, t) for b in range(5, 9) for t in range(1, 5))
    latest_r = ", ".join(R(b, t) for b in range(5, 9) for t in range(1, 5))
    text = PAGE.replace("{HOMEWORK_ROWS}", rows).replace("{LATEST_L}", latest_l).replace("{LATEST_R}", latest_r)
    for k, v in {"{ITO_10_1}": ITO.format(10, 1), "{ITO_10_2}": ITO.format(10, 2), "{ITO_10_3}": ITO.format(10, 3),
                 "{ITO_10_4}": ITO.format(10, 4), "{ITO_11_1}": ITO.format(11, 1),
                 "{IP_1}": IP.format(1), "{IP_2}": IP.format(2), "{IP_3}": IP.format(3), "{IP_4}": IP.format(4)}.items():
        text = text.replace(k, v)
    (ROOT / "knowledge" / "kb" / "course-timeline-and-resources.md").write_text(text, encoding="utf-8")
    print("ok")


if __name__ == "__main__":
    main()
