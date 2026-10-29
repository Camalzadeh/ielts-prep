# IELTS Prep app

Local IELTS practice app (FastAPI + SQLite + vanilla-JS frontend). Contract and layout: `ARCHITECTURE.md`.

- Run: desktop shortcut, or `launcher\start.bat` (Windows) / `launcher/start.sh` (Linux) → http://127.0.0.1:8765
- Python: always the project venv — `.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` (Linux).
- When asked to analyse the learner's work (attempts, essays, speaking, mocks, progress), follow
  `.claude/skills/ielts-analysis/SKILL.md`. Read-only DB access: `<venv python> tools/ielts_db.py`.
- Knowledge base from the course: `knowledge/kb/` (curated pages) and `knowledge/data/` (question banks).
- Never commit personal data (see `.gitignore`): `data/`, `My Results.docx`, chat archives, `knowledge/raw/`.
