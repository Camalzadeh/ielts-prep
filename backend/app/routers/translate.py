"""Instant translation for the study assistant - free services, no API key.

Primary: Google Translate's public web endpoint (best quality for Azerbaijani, plus word alternatives
by part of speech). Fallbacks when it is rate-limited: a second Google endpoint, then MyMemory. For single English words also an English dictionary entry
(definitions, phonetics, pronunciation audio) from dictionaryapi.dev. Results are cached in SQLite.
"""
from __future__ import annotations

import json
import re
import sqlite3

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db

router = APIRouter(prefix="/api", tags=["translate"])

LANGS = {"az": "Azərbaycan", "en": "English", "ru": "Русский", "tr": "Türkçe"}
TIMEOUT = httpx.Timeout(8.0, connect=4.0)
WORD = re.compile(r"^[A-Za-z][A-Za-z'\-]*$")


async def _google(client: httpx.AsyncClient, text: str, to: str) -> dict:
    r = await client.get("https://translate.googleapis.com/translate_a/single",
                         params=[("client", "gtx"), ("sl", "auto"), ("tl", to), ("dt", "t"), ("dt", "bd"), ("q", text)])
    r.raise_for_status()
    data = r.json()
    translation = "".join(seg[0] for seg in (data[0] or []) if seg and seg[0])
    words = []
    for entry in data[1] or []:  # [pos, [terms...], [[term, [back-translations], ...]], ...]
        if isinstance(entry, list) and len(entry) > 1 and entry[1]:
            words.append({"pos": entry[0], "terms": entry[1][:6]})
    return {"translation": translation, "source_lang": data[2] if len(data) > 2 else None,
            "words": words, "provider": "google"}


async def _google_alt(client: httpx.AsyncClient, text: str, to: str) -> dict:
    """Second Google endpoint (the Chrome dictionary extension's); used when the first is rate-limited."""
    r = await client.get("https://clients5.google.com/translate_a/t",
                         params={"client": "dict-chrome-ex", "sl": "auto", "tl": to, "q": text})
    r.raise_for_status()
    data = r.json()  # [["translation", "src_lang"]] (or ["translation"] for some languages)
    first = data[0] if data else ""
    translation, source = (first[0], first[1] if len(first) > 1 else None) if isinstance(first, list) else (first, None)
    return {"translation": translation, "source_lang": source, "words": [], "provider": "google"}


async def _mymemory(client: httpx.AsyncClient, text: str, to: str, source: str) -> dict:
    r = await client.get("https://api.mymemory.translated.net/get",
                         params={"q": text[:500], "langpair": f"{source}|{to}"})
    r.raise_for_status()
    data = r.json()
    return {"translation": data["responseData"]["translatedText"], "source_lang": source, "words": [],
            "provider": "mymemory"}


async def _dictionary(client: httpx.AsyncClient, word: str) -> dict | None:
    try:
        r = await client.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.lower()}")
        if r.status_code != 200:
            return None
        entry = r.json()[0]
    except Exception:
        return None
    phon = next((p for p in entry.get("phonetics", []) if p.get("audio")), {})
    meanings = [{"pos": m.get("partOfSpeech"),
                 "definitions": [{"definition": d.get("definition"), "example": d.get("example")}
                                 for d in m.get("definitions", [])[:3]]}
                for m in entry.get("meanings", [])[:4]]
    return {"phonetic": entry.get("phonetic") or phon.get("text"), "audio": phon.get("audio") or None,
            "meanings": meanings}


@router.get("/translate")
async def translate(q: str = Query(..., min_length=1, max_length=5000), to: str = "az",
                    conn: sqlite3.Connection = Depends(db.get_db)) -> dict:
    text = re.sub(r"\s+", " ", q).strip()
    if to not in LANGS:
        raise HTTPException(422, f"to must be one of {list(LANGS)}")
    key = f"{to}:{text}"
    row = conn.execute("SELECT json FROM translations WHERE key = ?", (key,)).fetchone()
    if row:
        return {**json.loads(row[0]), "cached": True}

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"}) as client:
        result = None
        source = "az" if to == "en" else "en"
        for attempt in (lambda: _google(client, text, to), lambda: _google_alt(client, text, to),
                        lambda: _mymemory(client, text, to, source)):
            try:
                result = await attempt()
                if result["translation"]:
                    break
            except Exception:
                continue
        if not result or not result["translation"]:
            raise HTTPException(503, "Translation service unreachable - check your internet connection.")
        dictionary = await _dictionary(client, text) if WORD.match(text) else None

    out = {"text": text, "to": to, **result, "dictionary": dictionary}
    # a single word answered by a fallback (no alternatives / no dictionary) is retried next time, not cached
    complete = not WORD.match(text) or (result["words"] and dictionary)
    if complete:
        conn.execute("INSERT OR REPLACE INTO translations(key, json, created_at) VALUES (?,?,?)",
                     (key, json.dumps(out, ensure_ascii=False), db.now_iso()))
    return {**out, "cached": False}


@router.get("/translate/languages")
def languages() -> dict:
    return LANGS
