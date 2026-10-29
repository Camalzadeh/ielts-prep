"""Extract the Telegram HTML exports into machine-friendly files under knowledge/.

Outputs (per archive, in knowledge/raw/<ARCHIVE>/):
  messages.json   - every message: id, date, author, text, attachments, reply_to
  messages.md     - readable chronological transcript (photo albums collapsed)
  docs/<name>.md  - extracted text for each PDF / DOCX / TXT / ODT file
  manifest.json   - list of every attachment with type, size, and text-extraction status
"""
import json
import re
import sys
import zipfile
from pathlib import Path

import fitz  # pymupdf
from docx import Document
from lxml import html as lhtml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "knowledge" / "raw"
ARCHIVES = ["IELTS_PREP_ARCHIVE", "LATEST_EXAMS_ARCHIVE"]


def clean(s: str) -> str:
    return re.sub(r"[ \t]+\n", "\n", re.sub(r"\n{3,}", "\n\n", s or "")).strip()


def node_text(el) -> str:
    if el is None:
        return ""
    for br in el.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    return clean(el.text_content())


def parse_messages(archive: Path):
    tree = lhtml.parse(str(archive / "messages.html"))
    msgs, last_author, last_date = [], None, None
    for m in tree.xpath('//div[contains(@class,"message")]'):
        cls = m.get("class", "")
        mid = m.get("id", "")
        if "service" in cls:
            t = node_text(m.find('.//div[@class="body details"]'))
            if re.match(r"^\d{1,2} \w+ \d{4}$", t):
                last_date = t
            msgs.append({"id": mid, "service": True, "text": t, "day": last_date})
            continue
        if "default" not in cls:
            continue
        body = m.find('./div[@class="body"]')
        if body is None:
            continue
        date_el = body.find('./div[@class="pull_right date details"]')
        author_el = body.find('./div[@class="from_name"]')
        if author_el is not None:
            last_author = clean(author_el.text_content())
        text_el = body.find('./div[@class="text"]')
        reply = body.find('./div[@class="reply_to details"]')
        fwd = body.find('./div[@class="forwarded body"]')
        if fwd is not None and text_el is None:
            text_el = fwd.find('.//div[@class="text"]')
        atts = []
        for a in body.xpath('.//div[contains(@class,"media_wrap")]//a[@href]'):
            href = a.get("href")
            if not href or href.startswith("#") or href.startswith("http"):
                continue
            kind = "photo" if "photo_wrap" in a.get("class", "") else (
                "audio" if "audio" in a.get("class", "") or "voice" in a.get("class", "") else "file")
            title = a.find('.//div[@class="title bold"]')
            atts.append({"kind": kind, "path": href,
                         "title": clean(title.text_content()) if title is not None else Path(href).name})
        links = [a.get("href") for a in body.xpath('.//div[@class="text"]//a[@href]')
                 if a.get("href", "").startswith("http")]
        msgs.append({
            "id": mid,
            "day": last_date,
            "date": date_el.get("title") if date_el is not None else None,
            "author": last_author,
            "forwarded": fwd is not None,
            "reply_to": reply.xpath('.//a/@href')[0].replace("#go_to_", "") if reply is not None and reply.xpath('.//a/@href') else None,
            "text": node_text(text_el),
            "links": links,
            "attachments": atts,
        })
    return msgs


def pdf_text(p: Path):
    doc = fitz.open(p)
    pages = [pg.get_text() for pg in doc]
    return "\n\n".join(f"<!-- page {i+1} -->\n{t.strip()}" for i, t in enumerate(pages)), len(pages)


def docx_text(p: Path):
    d = Document(p)
    parts = [para.text for para in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts), None


def odt_text(p: Path):
    with zipfile.ZipFile(p) as z:
        xml = z.read("content.xml")
    tree = lhtml.fromstring(xml)
    return clean(tree.text_content()), None


def extract_doc(p: Path):
    ext = p.suffix.lower()
    if ext == ".pdf":
        return pdf_text(p)
    if ext == ".docx":
        return docx_text(p)
    if ext == ".odt":
        return odt_text(p)
    if ext == ".txt":
        return p.read_text(encoding="utf-8", errors="replace"), None
    return None, None


def write_transcript(msgs, out: Path, archive_name: str):
    lines = [f"# {archive_name} — chat transcript\n"]
    for m in msgs:
        if m.get("service"):
            lines.append(f"\n## {m['text']}\n")
            continue
        photos = [a for a in m["attachments"] if a["kind"] == "photo"]
        others = [a for a in m["attachments"] if a["kind"] != "photo"]
        head = f"**{m['author']}** [{(m['date'] or '')[:16]}] ({m['id']})"
        if m["reply_to"]:
            head += f" ↩ {m['reply_to']}"
        if m["forwarded"]:
            head += " [fwd]"
        body = []
        if m["text"]:
            body.append(m["text"])
        for a in photos:
            body.append(f"[photo: {a['path']}]")
        for a in others:
            body.append(f"[{a['kind']}: {a['path']}]")
        for l in m["links"]:
            body.append(f"<{l}>")
        lines.append(head + "\n" + "\n".join(body) + "\n")
    out.write_text("\n".join(lines), encoding="utf-8")


def main():
    for name in ARCHIVES:
        archive = ROOT / name
        if not archive.exists():
            continue
        dest = OUT / name
        (dest / "docs").mkdir(parents=True, exist_ok=True)
        msgs = parse_messages(archive)
        (dest / "messages.json").write_text(json.dumps(msgs, ensure_ascii=False, indent=1), encoding="utf-8")
        write_transcript(msgs, dest / "messages.md", name)

        manifest = []
        for m in msgs:
            for a in m.get("attachments", []):
                p = archive / a["path"]
                entry = {"message": m["id"], "date": m.get("date"), "author": m.get("author"),
                         "caption": m.get("text"), **a, "exists": p.exists(),
                         "size": p.stat().st_size if p.exists() else None}
                if p.exists() and a["kind"] == "file":
                    try:
                        text, pages = extract_doc(p)
                    except Exception as e:  # corrupt files shouldn't stop the run
                        text, pages = None, None
                        entry["error"] = str(e)
                    if text is not None:
                        doc_out = dest / "docs" / (p.name + ".md")
                        doc_out.write_text(f"# {p.name}\n\n{text}", encoding="utf-8")
                        entry["text_file"] = str(doc_out.relative_to(ROOT)).replace("\\", "/")
                        entry["text_chars"] = len(text.strip())
                        entry["pages"] = pages
                manifest.append(entry)
        (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        n_photo = sum(1 for e in manifest if e["kind"] == "photo")
        low_text = [e["title"] for e in manifest if e.get("text_file") and e.get("text_chars", 0) < 200]
        print(f"{name}: {len(msgs)} messages, {len(manifest)} attachments, {n_photo} photos")
        print(f"  docs with little/no text (likely scanned): {low_text}")


if __name__ == "__main__":
    sys.exit(main())
