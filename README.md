# IELTS Prep — local study app

A local IELTS practice app that runs on your own computer: exam-style **Listening** and **Reading**
tests (Cambridge IELTS 1–21), a **Writing** prompt bank with a timed editor, **Speaking** practice with
recording and automatic transcription, random **Mock exams**, a **Learn** section built from our course
materials, and an **AI tutor** (Claude Code or Antigravity) that explains your mistakes.

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

Afterwards just click the **IELTS Prep** shortcut. It starts the local server when needed and opens
http://127.0.0.1:8765. To stop the server: `launcher\stop.bat` / `launcher/stop.sh`.

First time: open **Settings → Your name**.

## AI feedback (optional)
"Explain my mistakes" / "Analyse with AI" uses a coding-agent CLI installed and logged in on your
computer — pick one in the header:
- **Claude Code** — https://claude.com/claude-code (`claude` on PATH)
- **Antigravity** — the `agy` CLI (`~/.gemini/bin/agy`)

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

## For developers
- Architecture & API contract: `ARCHITECTURE.md`. Backend `backend/app` (FastAPI, stdlib sqlite3),
  frontend `frontend/` (vanilla ES modules, no build step), AI rules `.claude/skills/ielts-analysis/SKILL.md`.
- Tests: `.venv/bin/python -m pytest backend/tests` (Windows: `.venv\Scripts\python -m pytest backend\tests`).
- AI parallelism: setting `ai_workers` (default 6).
