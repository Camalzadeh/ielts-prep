"""History essay notes (this branch): the learner's answers to history exam questions, used as content for the
History writing prompts. One markdown file per question in knowledge/history/ (Q13_*.md ...), each with
'## 1. Short answer', '## 2. Medium answer ...', '## 3. Detailed answer' (each with '### English' and
'### Azərbaycanca') and '## Sources'."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .. import db

router = APIRouter(prefix="/api/history", tags=["history"])

LEVELS = {"1": "short", "2": "medium", "3": "detailed"}


def _dir() -> Path:
    return db.KNOWLEDGE_DIR / "history"


def _file(qid: str) -> Path | None:
    if not re.fullmatch(r"Q\d{1,3}", qid):
        return None
    return next(iter(sorted(_dir().glob(f"{qid}_*.md"))), None)


def parse_notes(text: str) -> dict:
    """Split one notes file into its title, question, levels (short/medium/detailed x en/az) and sources."""
    title = re.search(r"^#\s+(.+)$", text, re.M)
    question = re.search(r"^>\s*(.+?)\s*$", text, re.M)
    out: dict = {"title": title.group(1).strip() if title else "", "question": question.group(1) if question else "",
                 "levels": {}, "sources": ""}
    for block in re.split(r"(?m)^(?=## )", text):
        head = re.match(r"## (?:(\d)\.\s*)?(.+)", block)
        if not head:
            continue
        body = block[head.end():]
        if head.group(1) in LEVELS:
            langs = {}
            for part in re.split(r"(?m)^(?=### )", body):
                lh = re.match(r"### (.+)", part)
                if lh:
                    key = "en" if lh.group(1).strip().lower().startswith("english") else "az"
                    langs[key] = part[lh.end():].strip()
            out["levels"][LEVELS[head.group(1)]] = langs
        elif head.group(2).strip().lower().startswith("sources"):
            out["sources"] = body.strip()
    return out


@router.get("")
def list_notes() -> list[dict]:
    items = []
    for f in sorted(_dir().glob("Q*_*.md"), key=lambda p: int(re.match(r"Q(\d+)", p.name).group(1))):
        n = parse_notes(f.read_text(encoding="utf-8"))
        items.append({"id": f.name.split("_")[0], "title": n["title"], "question": n["question"]})
    return items


@router.get("/{qid}")
def get_notes(qid: str) -> dict:
    f = _file(qid)
    if not f:
        raise HTTPException(404, f"no history notes for {qid}")
    return {"id": qid, **parse_notes(f.read_text(encoding="utf-8"))}
