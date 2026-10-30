# IELTS Prep — Architecture & Contracts

Local IELTS preparation web app. FastAPI + SQLite backend, no-build vanilla-JS frontend,
AI feedback produced by spawning the **Claude Code CLI** (`claude`), the **Codex CLI** (`codex`) or the
**Antigravity CLI** (`agy`) as a subprocess in this folder. Everything the user does is stored in SQLite.

Python: always use the project venv `.venv\Scripts\python.exe` (has fastapi, uvicorn,
python-multipart, httpx, lxml, bs4, pymupdf, python-docx, pillow, faster-whisper).

## Folder layout

```
ielts/
  ARCHITECTURE.md            <- this file (the contract)
  CLAUDE.md / AGENTS.md / GEMINI.md   <- tell AI CLIs to use the analysis skill
  .claude/skills/ielts-analysis/SKILL.md   <- how AI analyses attempts (DB access, rubrics)
  IELTS_PREP_ARCHIVE/  LATEST_EXAMS_ARCHIVE/   <- Telegram exports (read-only source)
  knowledge/
    raw/<ARCHIVE>/messages.json|messages.md|manifest.json|docs/*.md   <- extracted (tools/extract_archives.py)
    raw/<ARCHIVE>/photos/*.jsonl   <- vision transcriptions of photos
    kb/                        <- curated knowledge base (markdown, front-matter), shown in the "Learn" section
    data/                      <- curated structured banks (JSON) imported into DB:
       speaking_questions.json, writing_prompts.json, vocabulary.json, my_essays.json
  content/
    tests/listening/<id>.json  tests/reading/<id>.json   <- scraped tests (schema below)
    media/listening/<id>/partN.mp3   media/reading/<id>/*.png   media/writing/*.png
  data/
    ielts.db                   <- SQLite (created by backend on start)
    uploads/speaking/<session_id>/<response_id>.webm   <- user recordings
    ai_runs/<analysis_id>/     <- prompt + raw CLI output logs
  backend/
    app/main.py  db.py  schema.sql  grading.py  importer.py  ai_runner.py  transcribe.py  routers/*.py
  frontend/
    index.html  css/  js/ (ES modules, hash router)  vendor/ (chart.js etc., vendored — no CDN at runtime)
  tools/
    extract_archives.py  scrape_engnovate_*.py  ielts_db.py (CLI DB helper for AI)
  launcher/  start.bat  launch.pyw  ielts.ico  create_shortcut.ps1
```

Server: `http://127.0.0.1:8765`. Static frontend served at `/`, API at `/api/*`,
`/media/content/*` -> `content/media`, `/media/uploads/*` -> `data/uploads`,
`/media/archive/<ARCHIVE>/*` -> the Telegram archive folders (for PDFs/photos in the Learn section),
`/media/kb/*` -> `knowledge/kb/assets`.

---

## 1. Test JSON schema (listening & reading) — `content/tests/<type>/<id>.json`

```jsonc
{
  "id": "cam11-listening-1",              // "cam{book}-{type}-{test}" for Cambridge; slug otherwise
  "type": "listening",                    // "listening" | "reading"
  "module": "academic",                   // "academic" | "general"
  "title": "Cambridge IELTS 11 Academic Listening Test 1",
  "series": "Cambridge IELTS 11",          // grouping label for the library UI
  "book": 11, "test_no": 1,                // null if not Cambridge
  "source": "engnovate",
  "source_url": "https://engnovate.com/...",
  "duration_minutes": 30,                 // listening 30 (+ no transfer time in CD mode), reading 60
  "parts": [
    {
      "number": 1,                        // listening: 1-4 ("Part"), reading: 1-3 ("Passage")
      "title": "Part 1",                  // reading: passage title
      "audio": "media/listening/cam11-listening-1/part1.mp3",   // relative to content/, listening only
      "audio_remote": "https://...mp3",   // original URL (fallback when local file missing)
      "transcript_html": "<p>...</p>",    // listening transcript if available, else null
      "passage_html": "<p>...</p>",       // reading passage (paragraph letters kept: <p><b>A</b> ...)
      "groups": [
        {
          "range": [1, 10],               // first/last question number in this group
          "type": "note_completion",      // see question types below
          "instructions_html": "<p>Complete the notes below. Write <b>ONE WORD AND/OR A NUMBER</b>...</p>",
          "content_html": "<h4>Notes</h4><p>Name: {{1}}</p>...",  // optional; gaps as {{N}} placeholders
          "image": "media/reading/cam11-reading-1/map1.png",       // optional (maps, diagrams)
          "options": [{"key": "A", "text": "..."}],                // shared options (matching, headings, multi-select)
          "questions": [
            {
              "number": 1,
              "prompt_html": "...",       // question text (empty for inline gaps in content_html)
              "options": [{"key": "A", "text": "..."}],   // per-question options (MCQ)
              "answer": ["Jamieson"],     // ACCEPTED answers. Alternatives allowed: ["10", "ten"]
              "explanation_html": null    // optional explanation/evidence if scraped
            }
          ]
        }
      ]
    }
  ]
}
```

Question `type` values (group level):
`note_completion`, `form_completion`, `table_completion`, `flowchart_completion`,
`summary_completion`, `sentence_completion`, `short_answer`, `diagram_labelling`,
`map_labelling` (options letters on an image), `plan_labelling`,
`mcq` (single answer per question), `multi_select` (e.g. "Choose TWO letters" — the group's
questions share one `options` list; each question's `answer` contains the full accepted letter set
e.g. both Q21 and Q22 have `"answer": ["B","D"]`; grading: the user's distinct letters for the
group are matched against the set, each correct letter scores one mark),
`matching` (match items to options A–H), `matching_headings`, `matching_information`
(which paragraph contains...), `matching_features`, `matching_sentence_endings`,
`tfng` (TRUE/FALSE/NOT GIVEN), `ynng` (YES/NO/NOT GIVEN).

Rendering rules: if `content_html` has `{{N}}` placeholders the UI renders an input/select at that
spot (select if the group has `options`, text input otherwise). Otherwise it renders each
question's `prompt_html` with an input (text), radios (mcq/tfng/ynng) or a select (matching).

Grading (backend `grading.py`): normalise = lowercase, trim, collapse spaces, strip surrounding
punctuation, ignore leading articles "a/an/the" only when the accepted answer lacks them.
Answers containing "/" or "OR" in the scraped key are split into alternatives at scrape time.
Parenthesised optional words in keys like "(free) parking" -> accept "parking" and "free parking".
Numbers: "1,000" == "1000". Bands: standard IELTS raw-score -> band tables for Listening and
Academic Reading (General Training reading uses the GT table).

## 2. SQLite schema (owned by backend, `backend/app/schema.sql`)

```sql
tests(id TEXT PK, type TEXT, module TEXT, title TEXT, series TEXT, book INT, test_no INT,
      source TEXT, source_url TEXT, question_count INT, file_path TEXT, data_json TEXT, imported_at TEXT)

mock_exams(id INTEGER PK, created_at, finished_at, status TEXT /*in_progress|finished*/,
      plan_json TEXT /* {"listening": test_id, "reading": test_id, "writing": {"task1": prompt_id, "task2": prompt_id}, "speaking": session_plan} */,
      listening_band REAL, reading_band REAL, writing_band REAL, speaking_band REAL, overall_band REAL)

attempts(id INTEGER PK, test_id TEXT FK, type TEXT, mock_id INT NULL, mode TEXT /*practice|mock*/,
      started_at, finished_at, duration_sec INT, status TEXT /*in_progress|submitted*/,
      raw_score INT, total INT, band REAL, answers_json TEXT /* autosave {num: value} */,
      highlights_json TEXT /* reading highlights/notes */)

attempt_answers(id INTEGER PK, attempt_id FK, part INT, question_number INT, question_type TEXT,
      user_answer TEXT, correct_answers TEXT /* JSON list */, is_correct INT,
      question_text TEXT /* plain text snapshot so AI can read it without parsing test JSON */)

writing_prompts(id INTEGER PK, task INT /*1|2*/, module TEXT, essay_type TEXT /* opinion|discussion|
      adv_disadv|problem_solution|cause_effect|direct_question|outweigh|positive_negative|
      line|bar|pie|table|map|process|mixed */, prompt TEXT, image_path TEXT /* relative to /media/... */,
      image_description TEXT /* chart data in words so text-only AI can judge task-1 accuracy */,
      source TEXT /* real_exam|teacher|cambridge|... */, source_date TEXT, tags TEXT, UNIQUE(prompt))

writing_submissions(id INTEGER PK, prompt_id FK, mock_id INT NULL, text TEXT, word_count INT,
      time_spent_sec INT, created_at, origin TEXT /* app|telegram_import */,
      teacher_band REAL, teacher_comments TEXT, source_photo TEXT /* schema v2: teacher feedback on imported essays */)

external_results(id INTEGER PK, date TEXT, person TEXT, is_mine INT, listening REAL, reading REAL, writing REAL,
      speaking REAL, overall REAL, notes TEXT, photo TEXT, source TEXT, UNIQUE(date, person, photo))
      -- scores achieved outside the app (trial exams, screenshots); is_mine=1 rows are the user's baseline

schema_version(version INT, applied_at TEXT)   -- migrations in backend/app/db.py (MIGRATIONS)

speaking_questions(id INTEGER PK, part INT /*1|2|3*/, topic TEXT, question TEXT,
      cue_points_json TEXT /* part 2 bullet points */, follow_up_json TEXT, season TEXT /* e.g. "Jan-Aug 2026" */,
      source TEXT, model_answer TEXT, UNIQUE(part, topic, question))

speaking_sessions(id INTEGER PK, mock_id INT NULL, created_at, finished_at, plan_json TEXT,
      mode TEXT /* practice_part1|practice_part2|practice_part3|full|mock */)

speaking_responses(id INTEGER PK, session_id FK, question_id FK NULL, part INT, question_text TEXT,
      audio_path TEXT /* relative to data/uploads */, duration_sec REAL, mime TEXT,
      transcript TEXT /* best transcript (whisper > browser) */, browser_transcript TEXT,
      whisper_json TEXT /* segments + words with probability */, metrics_json TEXT
      /* {wpm, pause_count, long_pauses, filler_count, low_confidence_words:[...]} */,
      transcribe_status TEXT /* pending|done|error|unavailable */, created_at)

ai_analyses(id INTEGER PK, target_type TEXT /* attempt|writing|speaking_session|mock|progress */,
      target_id INT, provider TEXT /* claude|codex|antigravity */, status TEXT /* queued|running|done|error */,
      prompt TEXT, result_md TEXT, result_json TEXT /* {"band":..,"criteria":{..},"mistakes":[..],"tips":[..]} */,
      error TEXT, log_path TEXT, created_at, started_at, finished_at)

kb_docs(id INTEGER PK, slug TEXT UNIQUE, title TEXT, category TEXT, tags TEXT, path TEXT, content_md TEXT)
kb_fts  -- FTS5 virtual table over kb_docs(title, content_md)

vocab(id INTEGER PK, term TEXT, meaning TEXT, example TEXT, topic TEXT, source TEXT,
      ease REAL DEFAULT 2.5, interval_days INT DEFAULT 0, due_at TEXT, reps INT DEFAULT 0, UNIQUE(term, topic))

settings(key TEXT PK, value TEXT)   -- e.g. ai_provider default
```

Importer (`backend/app/importer.py`, runs on startup, idempotent, also `POST /api/admin/reimport`):
loads `content/tests/**.json` -> tests; `knowledge/data/*.json` -> writing_prompts,
speaking_questions, vocab, writing_submissions(origin=telegram_import); `knowledge/kb/**/*.md` -> kb_docs.
Globs: `writing_prompts*.json`, `speaking_questions*.json`, `vocabulary*.json` (all sources merged);
`my_essays.json` and `photo_essays.json` (only `is_mine` true) -> writing_submissions, the same essay found
twice (word-set Jaccard >= 0.8) is merged and its teacher band/comments stored; `test_results.json` ->
external_results (group tables in `results` are expanded per person). Invalid/partial files are skipped and
listed in `GET /api/admin/status`.

## 3. Curated data file formats (`knowledge/data/`)

```jsonc
// speaking_questions.json
[{"part":1,"topic":"Hometown","question":"Where is your hometown?","season":"Sep-Dec 2026","source":"telegram:LATEST_EXAMS_ARCHIVE"},
 {"part":2,"topic":"A film you watched and enjoyed","question":"Describe a film you watched and enjoyed",
  "cue_points":["what the film was about","when and where you watched it","why you liked it ..."],"season":"Jan-Aug 2026"},
 {"part":3,"topic":"Films","question":"Why do people like watching films at the cinema?"}]
// writing_prompts.json
[{"task":2,"essay_type":"opinion","prompt":"Some people believe ...","source":"real_exam","source_date":"2026-09-20",
  "image":null,"image_description":null},
 {"task":1,"essay_type":"line","prompt":"The graph below shows ...","image":"media/writing/xyz.jpg",
  "image_description":"Line graph, 1995-2005, millions USD: Germany 80->...","source":"teacher"}]
// vocabulary.json
[{"term":"inextricably linked","meaning":"...","example":"...","topic":"Unit 1","source":"Vocabulary Unit 1.pdf"}]
// my_essays.json  — the learner's own essays found in the chat, linked to prompts by text
[{"task":1,"prompt":"...","text":"...","date":"2026-07-28"}]
// photo_essays.json — essays read from chat photos (values may be strings: "True", "None", "6.5")
[{"task":1,"prompt":"...","text":"...","teacher_comments":"...","band":6.5,"author":"...","is_mine":true,
  "date":"2026-08-03","photo":"IELTS_PREP_ARCHIVE/photos/x.jpg"}]
// test_results.json — score screenshots / trial-exam tables
[{"person":"Student A","listening":null,"reading":8.0,"writing":null,"speaking":null,"overall":null,"notes":"...",
  "date":"2026-08-05","photo":"...","results":{"<user_name>":{"L":6.5,"R":6.5,"W":5.5,"S":6.0,"O":6.0}}}]
```
Image paths in these files are relative to `content/` (served at `/media/content/...`).

## 4. HTTP API (JSON)

Tests / practice
- `GET  /api/tests?type=listening|reading` -> `[{id,title,series,book,test_no,question_count,best_band,last_band,attempts}]`
- `GET  /api/tests/{id}` -> test JSON **with answers and explanations stripped**
- `POST /api/attempts` `{test_id, mode:"practice"|"mock", mock_id?}` -> `{id}`
- `PUT  /api/attempts/{id}/autosave` `{answers:{"1":"..."}, highlights?}` -> `{ok:true}`
- `POST /api/attempts/{id}/submit` `{answers:{"1":"..."}, duration_sec, highlights?}` ->
  `{id, raw_score, total, band, details:[{number, part, type, user_answer, correct_answers, is_correct, question_text, explanation_html}]}`
- `GET  /api/attempts?type=&limit=` ; `GET /api/attempts/{id}` (same shape as submit result + test meta;
  `details[].excerpt` = the transcript/passage line the explanation quotes, used to mark the evidence in the review)
- `DELETE /api/attempts/{id}` -> `{ok, id}`: removes the attempt, its answers and its AI analyses (a mock's
  stored section + overall band are cleared); 409 for imported results (they come from My Results.docx)
- `DELETE /api/writing/submissions/{id}` and `DELETE /api/speaking/sessions/{id}` (recordings and their files
  too): same rules: AI analyses go with them, a mock's section + overall band are cleared, and imported items
  are refused with 409 (course-chat essays, `My Results.docx` sessions; the next import would restore them)
- `GET  /api/attempts/{id}/transcript?part=N` -> `{part, transcript_html, anchors:{q: excerpt}}`: listening
  practice only (403 in mock / exam mode); feeds the study assistant's Transcript tab
- `GET  /api/tests/{id}/review` -> full test JSON **with** answers (only allowed if a submitted attempt exists)

Writing
- `GET  /api/writing/prompts?task=&essay_type=&q=` ; `GET /api/writing/prompts/random?task=1|2`
- `POST /api/writing/prompts` (user adds own prompt)
- `POST /api/writing/submissions` `{prompt_id, text, time_spent_sec, mock_id?}` -> `{id, word_count}`
- `GET  /api/writing/submissions` ; `GET /api/writing/submissions/{id}` (includes prompt)

Speaking
- `GET  /api/speaking/questions?part=&topic=&q=` ; `GET /api/speaking/topics?part=`
- `GET  /api/speaking/random-set?mode=full|part1|part2|part3` -> `{part1:[q..(3 topics x 3-4 q)], part2:{cue card}, part3:[q.. related]}`
- `POST /api/speaking/sessions` `{mode, plan, mock_id?}` -> `{id}` ; `POST /api/speaking/sessions/{id}/finish`
- `POST /api/speaking/responses` multipart: `session_id, question_id?, part, question_text, duration_sec, browser_transcript, audio(file)` -> `{id, transcribe_status}`
  (backend stores file, then transcribes in a background thread with faster-whisper `base.en`/`small.en` on CPU, int8; computes metrics with word timestamps)
- `GET  /api/speaking/sessions` ; `GET /api/speaking/sessions/{id}` (responses incl. audio URL `/media/uploads/...`, transcripts, metrics)
- `POST /api/speaking/responses/{id}/retranscribe`

Mock exam
- `POST /api/mock` `{sections:["listening","reading","writing","speaking"], random:true}` -> creates plan with random unseen tests/prompts -> `{id, plan}`
- `GET  /api/mock/{id}` -> plan + linked attempt/submission/session ids + bands
- `POST /api/mock/{id}/link` `{section, ref_id}` ; `POST /api/mock/{id}/finish` -> computes overall band
- `GET  /api/mock`

AI
- `GET  /api/ai/providers` -> `[{id:"claude", name:"Claude Code", available:true, version, path, install}, {id:"antigravity", ...}, {id:"codex", name:"Codex", available:bool, install}]`
  (`install` = how to add it; the header switch shows only the available providers plus the selected one)
- `POST /api/ai/analyze` `{target_type, target_id, provider, force:false}` -> if a `done` analysis exists for the
  target and `force` is false, return it; else enqueue -> `{id, status}`
- `GET  /api/ai/analyses/{id}` -> row (poll every 2s while queued/running)
- `GET  /api/ai/analyses?target_type=&target_id=` -> history (newest first)
- `GET  /api/settings` / `PUT /api/settings` `{ai_provider}`

Knowledge base / vocab / stats
- `GET /api/kb` -> `[{slug,title,category,tags}]` ; `GET /api/kb/{slug}` -> `{..., content_md}` ; `GET /api/kb/search?q=`
- `GET /api/vocab?topic=&due=1` ; `POST /api/vocab/{id}/review` `{grade:0..5}` (SM-2)
- `GET /api/stats` -> `{bands_over_time:{listening:[{date,band}],...}, by_question_type:[{type, correct, total}], counts, streak_days, recent:[...]}`
  plus `external_results:[...]` (the user's rows) and `baseline` (first with an overall band, e.g. First Trial exam).
  `bands_over_time.writing` points carry `source: "ai"|"teacher"` (AI band preferred, teacher band as fallback).

Backend additions (non-breaking, implemented)
- `GET /api/health` ; `POST /api/admin/reimport[?wait=1]` ; `GET /api/admin/status` (table counts, import errors, transcriber state, AI queue)
- `GET /api/tests` items also have `module, type, source, in_progress_attempt`; `GET /api/tests/{id}` adds `parts[].audio_url`
  (local `/media/content/...` if the file exists, else `audio_remote`), `groups[].image_url`, `reviewable`.
- `GET /api/writing/prompts/{id}` ; prompts include `image_url`, `submissions` ; submissions include `band` (latest AI) and `teacher_band`.
- `GET /api/speaking/responses/{id}[?full=1]` ; session/response payloads use parsed `metrics` (and `whisper` with `full=1`).
- `GET /api/vocab/topics` ; `/api/vocab` also takes `q`, `limit`.
- `GET /api/mock/{id}` adds `live_bands` (computed now) and `missing`. Overall band is `null` until every planned
  section has a band (mean, IELTS rounding). Writing band = (T1 + 2*T2)/3 when both tasks have AI bands.
- `/media/content/<path>` serves `content/media/<path>` and also tolerates a leading `media/` (i.e. `content/<path>`).
- Settings keys `ai_cmd_<provider>` (JSON arg list with `{exe}`, `{instruction}`, `{prompt_file}`, `{output_file}`)
  and `ai_exe_<provider>` for claude / codex / antigravity; permission-bypass flags are rejected (422).

## 5. AI analysis runner (`backend/app/ai_runner.py`)

One worker thread processes queued `ai_analyses` rows sequentially. **Least privilege:** the backend
itself assembles the full context (the same text `tools/ielts_db.py attempt|writing|speaking|mock|progress`
prints: questions, user vs correct answers, passage/transcript excerpts, essay, metrics, past analyses)
and embeds it in the prompt, so the AI never needs write or shell access. The prompt file is
written to `data/ai_runs/<id>/prompt.md` and passed on stdin (avoids Windows command-line length limits):

```
You are analysing an IELTS candidate's work. Follow the rules in .claude/skills/ielts-analysis/SKILL.md
(read it). Context from the local database follows. Respond ONLY with the report in the skill's format.
<context ...>
```
and runs, with `cwd` = project root, a timeout of 15 min, stdout/stderr captured to `data/ai_runs/<id>/`:
- Claude: `claude -p --output-format json --allowedTools "Read Grep Glob"` (default permission mode, so
  anything else is denied; it may read the skill, knowledge/kb and content files) -> parse JSON, take `result`.
- Codex: `codex exec --sandbox read-only --skip-git-repo-check --color never --output-last-message
  data/ai_runs/<id>/last_message.md -` (prompt on stdin; stdout only carries progress logs, so the answer is
  read from that file; a non-zero exit or an empty file is an error). `--full-auto`, `workspace-write`,
  `danger-full-access` and `-c sandbox_mode/approval_policy` overrides are rejected. Codex reads `AGENTS.md`.
- Antigravity: `%USERPROFILE%\.gemini\bin\agy.exe -p <prompt> --output-format json --sandbox` (no
  permission bypass; the context is already in the prompt) -> parse JSON (fallback: raw text).
  agy ignores stdin in print mode (tested, v1.4.10), so prompts up to 24k chars are passed inline as the `-p`
  argument; longer ones as "Read the file data/ai_runs/<id>/prompt.md ..." (agy can Read it under `--sandbox`).
  agy JSON output: `{"status":"SUCCESS","response":"...","conversation_id":..,"usage":{..}}`; Claude: `{"type":"result","result":"..."}`.
- Commands are configurable in `settings` but defaults must stay least-privilege (never bypass permissions).
The report is markdown ending with a fenced ```json block (band/criteria/mistakes/tips); the runner splits it
into `result_md` and `result_json`. Reanalyse = new row (`force:true`); old rows are kept as history.

`tools/ielts_db.py` (read-only, opens the DB with `mode=ro`; used by the backend to build context and
usable by the user / an interactive AI session) subcommands: `schema`, `query "<SELECT ...>"` (read-only),
`attempt <id>` (full mistakes view with question text, user vs correct answers, passage/transcript excerpt),
`writing <id>`, `speaking <session_id>`, `mock <id>`, `progress` (weak areas across history), `test <test_id> [--part N]`.

## 6. Frontend (no build step)

Vanilla ES modules + hash router, served statically. Pages: Dashboard, Listening, Reading, Writing,
Speaking, Mock Exam, Learn (knowledge base + vocab flashcards), History, Settings (AI provider).
Listening/Reading test player mimics the computer-delivered IELTS / engnovate UI: header with timer,
split-pane (passage left, questions right) for reading with text highlighting, bottom question palette
with answered/flagged states, part tabs, audio player for listening (plays once in mock mode, free in
practice), review mode after submit with correct/incorrect marking + "Explain my mistakes with AI".
```
