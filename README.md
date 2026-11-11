# IELTS Prep — local study app

A local IELTS practice app that runs on your own computer: exam-style **Listening** and **Reading**
tests (Cambridge IELTS 1–21), a **Writing** prompt bank with a timed editor, **Speaking** practice with
recording and automatic transcription, random **Mock exams**, a **Learn** section built from our course
materials, and an **AI tutor** (Claude Code, Codex or Antigravity) that explains your mistakes.

Everything you do is stored locally in `data/ielts.db`. Nothing is uploaded anywhere.

## Install

### Windows
1. Install **Python 3.11+** from https://www.python.org/downloads/ (tick *Add python.exe to PATH*).
2. Recommended: `winget install Gyan.FFmpeg` (needed for speaking transcription).
3. Download this repo (green **Code** button → *Download ZIP*, or `git clone`), then double-click **`setup.bat`**.

### Ubuntu / Linux
```bash
sudo apt install python3 python3-venv ffmpeg git
git clone <this repo url> ielts && cd ielts
./setup.sh
```
Chrome or Chromium gives the best app window; otherwise your default browser opens.

Setup creates a Python environment, **downloads the practice tests** (about 1.2 GB with audio; takes a
while; you can stop it and re-run later — it resumes), creates an **IELTS Prep** shortcut on the desktop
and in the app menu, and opens the app.

## Getting the practice tests
The tests are **not** in this repo (copyrighted Cambridge material, ~1.2 GB of audio). Every user
downloads their own copy from engnovate.com for personal study. `setup` does this automatically. To run
it yourself (e.g. to finish an interrupted download), use:

| | Windows | Ubuntu |
|---|---|---|
| Everything (tests + audio, ~1.2 GB) | double-click `get_tests.bat` | `./get_tests.sh` |
| Tests only, audio streamed online | `get_tests.bat --no-audio` | `./get_tests.sh --no-audio` |
| A single test | `get_tests.bat --only cam18-listening-2` | `./get_tests.sh --only cam18-listening-2` |

- **Where from:** https://engnovate.com/ielts-reading-tests/ and https://engnovate.com/ielts-listening-tests/
  (free Cambridge IELTS 1–21 tests; premium tests are skipped). Answer keys come from engnovate's own
  checker, transcripts from the test pages.
- **Where to:** `content/tests/reading/*.json`, `content/tests/listening/*.json` (passages, questions, answers),
  `content/media/listening/<test>/part1-4.mp3` (audio), `content/_cache/` (raw pages, speeds up re-runs).
- **How long:** reading ~10 min, listening 20–60 min depending on your connection. You can stop it (Ctrl+C)
  any time; running it again skips finished tests and retries failed downloads.
- **Check:** the script validates every test at the end and prints how many tests and audio files you have.
  The app picks up new tests automatically (or Settings → *Reimport content*).
- **Problems:** "Cannot reach engnovate.com" means there's no internet connection, or the site is down; try
  later. If audio is missing, run the script again; meanwhile those parts stream from engnovate.

## Using the app
Afterwards just click the **IELTS Prep** shortcut. It starts the local server when needed and opens
http://127.0.0.1:8765. To stop the server: `launcher\stop.bat` / `launcher/stop.sh`.

First time: open **Settings → Your name**.

**Study assistant** — the **Help** button (or Alt+H) on every practice screen opens a side panel with:
tactics for the current question/task type, the course's word tables and phrase bank (click a word to
insert it into your essay), the course rules, vocabulary and a free translator (select any text →
*Translate*). It is off during mock exams unless you allow it in Settings.

## AI feedback (optional)
"Explain my mistakes" / "Analyse with AI" uses a coding-agent CLI installed and logged in on your
computer. The header offers the ones it finds; **Settings → AI provider** lists all of them with install steps.
- **Claude Code** — https://claude.com/claude-code (`claude` on PATH)
- **Codex** (OpenAI) — `npm install -g @openai/codex`, then `codex login` once (`codex` on PATH)
- **Antigravity** — the `agy` CLI (`~/.gemini/bin/agy`)

After installing one, press **Re-check** in Settings (or restart the app) and it appears in the header.

The app builds the context from your local database (your answers vs. the correct ones, the passage or
transcript, your essay, speaking transcript + fluency metrics) and runs the CLI with read-only access.
Analyses are saved; *Re-analyse* adds a new one and keeps the history.

## Add your own past results (optional)
Put a Word file **`My Results.docx`** in the project folder with one table:

| Link/Description | Type | Score |
|---|---|---|
| https://engnovate.com/ielts-reading-tests/cambridge-ielts-15-academic-reading-test-1/ | Reading | 7 |
| Part1 (Topic1-15) | Speaking | 6 |
| Part2 (first words of your essay…) | Writing | 6.5 |

They're imported on every start (Settings → *Reimport content* after editing), dated to when the teacher
posted the task if the course chat archive is present, and count in your dashboard.

## What's shared in this repo and what isn't
Shared: the app, the curated knowledge base (`knowledge/kb`), question banks (`knowledge/data`:
predicted speaking topics, real-exam writing prompts with Task-1 charts, vocabulary), scrapers.
**Not shared** (see `.gitignore`): anyone's personal data — databases, recordings, essays, scores, names,
the Telegram chat exports — and the downloaded test files (each user fetches them with
`tools/fetch_content.py`; the test material is for personal study only).

## History essays (branch `history-essays` only)
This branch adds IELTS writing practice on Azerbaijani history topics Q13–Q20:
- `knowledge/history/Q*.md` — the notes for each topic: short, medium and detailed answers in English and
  Azərbaycanca, with sources.
- `knowledge/data/writing_prompts.history.json` — 16 Task 2 prompts (2 per topic, real IELTS essay types) and
  5 Task 1 prompts whose charts use figures quoted from the notes. The charts are drawn by
  `tools/history_charts.py` into `content/media/writing/history/`.
- **Writing:** the prompts are a separate class, **Source → History (Azerbaijan)**. **Settings → History essays**
  shows or hides them. They are never used in mock exams or by Random Task 1/2.
- **Reading:** one IELTS-style passage with 13 questions per topic (`knowledge/history/reading/`), in the Reading
  library under "History (Azerbaijan)"; **Settings → History essays** has a switch for them too. Never in mocks.
- **Help → Notes:** shows your notes for the topic of the prompt on screen (Short / Medium / Detailed,
  English / Azərbaycanca). When an essay is analysed, the AI also gets the medium notes so it can check the
  facts.

## License
Proprietary - all rights reserved (see `LICENSE`). You may use this app only with the author's
written permission, for your own non-commercial study; copying, sharing, modifying or selling it
is not allowed. Bundled libraries and downloaded test material keep their own owners and licences.

## For developers
- Architecture & API contract: `ARCHITECTURE.md`. Backend `backend/app` (FastAPI, stdlib sqlite3),
  frontend `frontend/` (vanilla ES modules, no build step), AI rules `.claude/skills/ielts-analysis/SKILL.md`.
- Tests: `.venv/bin/python -m pytest backend/tests` (Windows: `.venv\Scripts\python -m pytest backend\tests`).
- AI parallelism: setting `ai_workers` (default 6).
