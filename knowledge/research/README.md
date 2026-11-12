# AI Research lessons

Each lesson teaches one idea from AI and gives IELTS practice on it. It is built from a research paper, forum thread,
course, article or video. In the app each lesson is spread over the normal sections: its reading is a test in
**Reading** (series "AI Research"), its writing tasks are in **Writing** (source "AI Research"), and its notes and key
terms are a guide in **Learn → Knowledge base → AI Research** (terms also as flashcards). **Settings → AI Research**
switches them on or off. They are never used in mock exams or random picks.

```
knowledge/research/
  inbox/            your raw materials (PDFs, links, pasted forum posts...) — NOT committed (see .gitignore)
  lessons/<id>.json one lesson per source (or per group of sources on one idea) — committed
  charts/<name>.json chart specs for Task 1 images (tools/research_chart.py) — committed
content/media/writing/research/<name>.svg   the rendered Task 1 charts
```

Workflow: put material in `inbox/`, ask Claude to "make research lessons from the inbox" (it follows
`.claude/skills/research-lessons/SKILL.md`), check them with `.venv/Scripts/python.exe tools/check_research.py`,
then **Settings → Re-import** (or restart the app).

## Lesson file

```jsonc
{
  "id": "transformer-attention",          // = file name; lowercase, digits, hyphens
  "title": "Attention Is All You Need: the Transformer",
  "topic": "Model architectures",         // groups lessons in the list
  "level": "beginner|intermediate|advanced",   // how hard the AI content is
  "added": "2026-11-12",
  "sources": [{"kind": "paper|forum|course|article|blog|video|book", "title": "...", "authors": "...",
               "year": 2017, "url": "https://..."}],
  "summary_md": "Markdown: the AI idea in plain English (shown as 'The idea'; also given to the AI marker).",
  "key_terms": [{"term": "...", "meaning": "...", "example": "..."}],   // also become flashcards, topic "AI Research"
  "discussion": ["Speaking Part 3 style questions on the topic"],          // optional
  "reading": {                             // optional; same as a test JSON (ARCHITECTURE.md §1) minus the header
    "duration_minutes": 20,
    "parts": [{"number": 1, "title": "...", "passage_html": "<p><strong>A</strong> ...</p>...",
               "groups": [ /* question groups: range, type, instructions_html, content_html, options, questions */ ]}]
  },
  "writing": [                             // optional
    {"task": 2, "essay_type": "opinion", "prompt": "..."},
    {"task": 1, "essay_type": "bar", "prompt": "The chart below shows ...",
     "image": "media/writing/research/<name>.svg", "image_description": "the data in words, for the AI marker"}
  ]
}
```

## Full tests (Cambridge format)

`tests.json` groups three lessons into one full reading test, as in the real exam: Passages 1-3, 40 questions,
60 minutes. Write each lesson's questions numbered from 1 (13 questions; the **third** lesson of a test has 14, usually
ending with a "best title" multiple-choice question). The importer renumbers them 1-13, 14-26 and 27-40 and rewrites
the "You should spend about 20 minutes on Questions ..." line.

```json
[{"test_no": 1, "lessons": ["transformer-attention", "ask-or-assume", "swe-clar"]}]
```

A lesson that is not in any test yet appears on its own as a one-passage, 20-minute test until three are grouped.
Test ids are `research-test-<n>`; never reuse or reorder a test_no that has attempts.
Writing prompts get source "research" and tags "research,<id>".
