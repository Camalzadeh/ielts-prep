# Phrase bank & tactics — data format

Shown in the study assistant (Help drawer, Alt+H) next to the practice screens. Phrases are also imported
into the vocabulary flashcards. **No personal data** (no student names, no essays by students) — these files
are shared in the git repo.

## `phrases.<skill>.json` — useful language (skill = `writing1`, `writing2`, `speaking`)

```jsonc
[
  {
    "skill": "writing1",                      // writing1 | writing2 | speaking
    "category": "Trends: upward movement",    // shown as a heading; keep categories short and ordered logically
    "when": "Describing a rise in a line graph / bar chart over time",   // one line: when to use these
    "applies_to": ["line", "bar", "table", "mixed"],   // optional: chart types / essay types / speaking parts ("part1".."part3")
    "items": [
      {
        "phrase": "rise / increase / grow / climb",           // the phrase or alternatives separated by " / "
        "pattern": "X rose from A to B (between YEAR and YEAR)",   // optional: sentence frame with placeholders
        "example": "The number of visitors rose from 2 million in 2000 to 5 million in 2010.",
        "note": "noun form: a rise / an increase in X",     // optional: grammar/usage note, register, common mistake
        "level": "core"                                      // core (must know) | advanced (band 7+)
      }
    ],
    "source": "teacher"                      // teacher (from the course materials) | standard (general IELTS knowledge) | mixed
  }
]
```

## `tactics.<skill>.json` — how to approach each question/task type (skill = `reading`, `listening`, `speaking`, `writing`)

```jsonc
[
  {
    "skill": "reading",
    "type": "tfng",                 // reading/listening: the question type ids used in content/tests (see ARCHITECTURE.md §1);
                                    // speaking: part1 | part2 | part3; writing: task1_<line|bar|pie|table|map|process|mixed>,
                                    // task2_<opinion|discussion|adv_disadv|problem_solution|cause_effect|direct_question|outweigh|positive_negative>;
                                    // every skill may also have one "general" card (overall strategy)
    "title": "True / False / Not Given",
    "summary": "One-sentence description of what the task tests.",
    "rule": "FALSE = the passage says the opposite; NOT GIVEN = it says nothing about it.",
                                    // optional: the single golden rule, one line, ~90 chars max, plain B1–B2 English
    "quick": {                      // optional: quick view shown first ("Show more" opens steps/traps/tips)
      "do": ["3–4 short imperative steps in exam order (~60 chars each)"],
      "avoid": ["2–3 biggest traps (~60 chars each)"],
      "remember": ["0–2 key format/time facts (~60 chars each); may be []"]
    },
    "steps": ["Ordered, concrete steps to follow during the exam", "..."],
    "traps": ["Typical mistakes / distractors and how to avoid them", "..."],
    "tips": ["Extra tips, time management, answer-format rules", "..."],
    "example": "Optional short worked example (question -> how to find the answer -> why).",
    "language": ["Optional: signpost/paraphrase words to listen or look for"],
    "source": "teacher"             // teacher | standard | mixed
  }
]
```

`rule` and `quick` are optional. The app shows them as a quick view first; the full `steps` / `traps` / `tips`
stay behind "Show more". Derive them from the card's own steps/traps/tips (no new facts), plain text (no markdown),
symbols only where they shorten (→, =, ✓, ✗). `tools/validate_phrases.py` checks their types and soft-warns on
length (rule > 90 chars, quick items > 60 chars) and item counts (do 3–4, avoid 2–3, remember 0–2).
