---
name: research-lessons
description: Turn AI research papers, forum threads, courses or articles into AI Research lessons for this IELTS app (knowledge/research/lessons/*.json) - plain-English notes and key terms on the AI idea, an IELTS Academic reading passage with 13 questions (grouped three to a full 40-question Cambridge-style test), and Writing Task 1/2 prompts. Use when the user gives AI material (files in knowledge/research/inbox/, links, pasted text) and asks for reading/writing tasks or lessons from it.
---

# AI Research lessons

The learner prepares for IELTS Academic (aiming at band 7+) and wants to learn AI at the same time. Each lesson
does both: it explains one idea from AI and gives IELTS practice on it. The format is in `knowledge/research/README.md`.
`knowledge/research/lessons/transformer-attention.json` is a complete example; match its quality and structure.

## Steps

1. **Read the material** (`knowledge/research/inbox/`, or `papers/<NN-name>/` = one downloaded paper per folder with
   `meta.json`, `text/paper.md` or `text/page.md`, `figures/png/`, `pages/`; links; pasted text). Papers' own
   `README.md` files are the user's work notes: use them only to find your way, never copy their work/project
   remarks (company, proposals, "our" plans) into a lesson. Use one lesson per paper, thread or course module. If a
   source covers several separate ideas, split it into several lessons. If several short sources cover one idea,
   merge them into one lesson. Skip material with no real content (adverts, link dumps).
2. **Get the AI right first.** Write `summary_md` (350–600 words, markdown) for an intelligent non-specialist.
   Cover what problem the work addresses, the core idea with one concrete example or analogy, the key results with
   real numbers from the source, why it matters, and its limitations. Finish with an "IELTS angle" line: useful
   academic words from the passage, and how the topic could serve as an example in Task 2.
   - Use only facts that are in the source, or that you are sure of. Never invent numbers, dates, names or results.
   - Forum and opinion material: present claims as claims ("one forum user argued...").
3. **key_terms**: 8–14 terms. Mostly AI terms with one-line meanings and an example sentence, plus 2–3 academic
   words or phrases from the passage that are worth learning (they become flashcards).
4. **Reading passage** (`reading.parts[0]`): an original IELTS Academic-style text, 700–950 words, paragraphs
   lettered **A**, **B**, ... (`<p><strong>A</strong> ...</p>`), with a title in `<h3>`. Start passage_html with the
   standard line "You should spend about 20 minutes on Questions 1-13...". Write it in your own words, never copied
   from the source: academic register, paraphrase-rich, with some opinion and attribution so that TRUE/FALSE/NOT GIVEN works.
5. **13 questions in 3 groups**, numbered 1–13 in order (the importer renumbers them inside the full test). Vary the types across lessons (grading supports all of these):
   - `matching_information` / `matching_headings` / `matching_features` (options = letters/headings/people)
   - `tfng` (answers "TRUE"/"FALSE"/"NOT GIVEN") or `ynng` for the writer's claims
   - `summary_completion` / `sentence_completion` / `note_completion` with `{{n}}` blanks in `content_html` and a
     word limit in the instructions (NO MORE THAN TWO WORDS...), with answers copied exactly from the passage.
     Give accepted variants in the answer list (e.g. `["keys", "the keys"]`).
   - `mcq` (question `options` A–D, `answer: ["B"]`)
   Make the questions paraphrase the passage rather than repeat its words. NOT GIVEN items must really be absent.
   Every question has `explanation_html` with a short reason and a `<blockquote><p>` holding **an exact sentence copied
   from the passage** (the checker verifies this, and the review screen highlights it).
5b. **Full tests**: every three lessons form one Cambridge-style test in `knowledge/research/tests.json`
   (`{"test_no": n, "lessons": [p1, p2, p3]}`; group lessons on related topics, mix the question types across the
   three passages). The third lesson gets a 14th question so the test has 40 (13 + 13 + 14): add a group
   `{"range": [14, 14], "type": "mcq"}` asking for the most suitable title, with plausible distractors, and change
   its intro line to "Questions 1-14". Leftover lessons (fewer than three) stay ungrouped until more arrive.
6. **Writing**: one or two Task 2 prompts on the social side of the topic (education, jobs, ethics, regulation,
   privacy, society), worded like real IELTS prompts, with `essay_type` set. Add a Task 1 when the source has
   real numbers that make a fair chart. Write the data to `knowledge/research/charts/<name>.json` and render it with
   `.venv/Scripts/python.exe tools/research_chart.py <spec> content/media/writing/research/<name>.svg`. Then view the
   SVG, and put the data and main trends into `image_description`.
7. `discussion`: 3 Speaking Part 3 style questions.
8. Fill `sources` (kind, title, authors, year, url). Set `added` to today and `level` to how hard the AI content is.
9. **Check**: `.venv/Scripts/python.exe tools/check_research.py` must report OK for every lesson. Read each passage
   once more against its answer key. Then re-import (`POST /api/admin/reimport?wait=true`, or Settings → Re-import) and check
   Reading (series "AI Research"), Writing (source "AI Research") and Learn → Knowledge base → AI Research.

## Rules

- Never commit `knowledge/research/inbox/` or `papers/` (raw material may be copyrighted or contain people's names/posts).
  Lessons contain only your own rewritten text, plus the source titles and links.
- Keep lessons out of mocks: they always use `source: "research"` (set by the importer; do not change it).
- Generate the JSON with a short Python script in the scratchpad when that is easier (quoting the evidence
  sentences from the passage strings avoids mismatches). Don't commit the script.
