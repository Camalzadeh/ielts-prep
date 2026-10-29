"""Merge photo transcriptions (knowledge/raw/photo_batches/*.out.jsonl) into curated data banks.

Writes:
  knowledge/data/speaking_questions.photos.json
  knowledge/data/writing_prompts.photos.json   (+ copies Task-1 chart images to content/media/writing/)
  knowledge/data/photo_essays.json             (essays in photos, with author; yours flagged via --me)
  knowledge/data/test_results.json             (band/score screenshots)
  knowledge/raw/photo_materials.md             (teaching/reading/listening material, for the KB)
"""
import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATCHES = ROOT / "knowledge" / "raw" / "photo_batches"
DATA = ROOT / "knowledge" / "data"
MEDIA = ROOT / "content" / "media" / "writing"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def load():
    records = []
    for out in sorted(BATCHES.glob("batch_*.out.jsonl")):
        inputs = {i["path"]: i for i in json.loads((BATCHES / out.name.replace(".out.jsonl", ".json")).read_text(encoding="utf-8"))}
        for line in out.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            meta = inputs.get(r["path"], {})
            r["author"] = meta.get("author")
            r["archive"] = meta.get("archive") or r["path"].split("/")[0]
            r.setdefault("structured", {})
            records.append(r)
    return records


def date_iso(d: str):
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", d or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else (d or None)


def speaking(records):
    out, index = [], {}

    def add(q):
        key = (q["part"], norm(q["topic"]), norm(q["question"]))
        if key in index:
            old = out[index[key]]
            # keep the newest season label, union cue points
            if q.get("season"):
                old["season"] = q["season"]
            for c in q.get("cue_points") or []:
                if c not in old.setdefault("cue_points", []):
                    old["cue_points"].append(c)
            return
        index[key] = len(out)
        out.append(q)

    prev_p2 = None
    for r in records:
        s, cat = r["structured"], r["category"]
        src = f"telegram:{r['archive']}"
        if cat == "speaking_part1" or cat == "speaking_part3":
            part = 1 if cat == "speaking_part1" else 3
            topic = (s.get("topic") or r.get("title") or "General").strip()
            for q in s.get("questions") or []:
                q = re.sub(r"\s*\((added|frequently)[^)]*\)\s*$", "", q, flags=re.I).strip()
                if q:
                    add({"part": part, "topic": topic, "question": q, "season": s.get("season"), "source": src})
        elif cat == "speaking_part2":
            cues = [c for c in (s.get("cue_points") or []) if c]
            if s.get("final_point"):
                cues.append(s["final_point"])
            if r.get("continues_previous") and prev_p2 is not None and not s.get("question"):
                for c in cues:
                    if c not in prev_p2["cue_points"]:
                        prev_p2["cue_points"].append(c)
                continue
            question = (s.get("question") or "").strip()
            topic = (s.get("topic") or r.get("title") or question).strip()
            if not question:
                continue
            q = {"part": 2, "topic": topic, "question": question, "cue_points": cues,
                 "season": s.get("season"), "source": src}
            add(q)
            prev_p2 = out[index[(2, norm(topic), norm(question))]]
            for p3 in s.get("part3_questions") or []:  # combined "P2&3" cards
                add({"part": 3, "topic": topic, "question": p3.strip(), "season": s.get("season"), "source": src})
    return out


def writing(records):
    MEDIA.mkdir(parents=True, exist_ok=True)
    prompts, seen = [], {}
    for r in records:
        s, cat = r["structured"], r["category"]
        if cat not in ("writing_task1", "writing_task2_prompt"):
            continue
        task = 1 if cat == "writing_task1" else 2
        prompt = (s.get("prompt") or "").strip()
        if not prompt:
            prompt = r.get("title") or ""
        key = (task, norm(prompt)[:160])
        item = {"task": task, "prompt": prompt, "source_date": date_iso(r.get("date")),
                "source": "real_exam" if re.search(r"real|exam|imtahan|sınaq|sinaq|trial|PBI", (r.get("caption") or "") + (r.get("context") or ""), re.I) else "teacher",
                "image": None, "image_description": None, "origin_photo": r["path"]}
        if task == 1:
            src = ROOT / r["path"]
            dest = MEDIA / f"{r['archive'].split('_')[0].lower()}_{src.name}"
            if src.exists():
                shutil.copy2(src, dest)
                item["image"] = f"media/writing/{dest.name}"
            item["essay_type"] = s.get("chart_type") or "mixed"
            item["image_description"] = s.get("data_description")
        else:
            item["essay_type"] = s.get("essay_type")
        if key in seen:
            # a later photo of the same task may carry a better description
            old = prompts[seen[key]]
            if task == 1 and len(item.get("image_description") or "") > len(old.get("image_description") or ""):
                old.update(image=item["image"], image_description=item["image_description"])
            continue
        seen[key] = len(prompts)
        prompts.append(item)
    return prompts


def is_mine(r, me: str) -> bool:
    """Essay photos are often re-posted by the teacher; the sender label ("<name> 2026") sits at the top."""
    if not me:
        return False
    name = re.escape(me.lower())
    text = re.sub(r"\(top:[^)]*\)", "", r.get("text") or "")
    text = re.sub(rf"{name} pinned[^\n]*", "", text, flags=re.I).strip()
    head = " ".join([r.get("title") or "", text[:40], str(r["structured"].get("author") or "")])
    if (r.get("author") or "").lower().startswith(me.lower()):
        return True
    return bool(re.search(rf"\b{name}\b", head, re.I)) and not re.search(rf"not {name}|{name} not", head, re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", default="", help="your name as shown in the chat, to flag your own essays")
    me = ap.parse_args().me
    records = load()
    # carry the triggering message caption/context onto the record for source detection
    for out in sorted(BATCHES.glob("batch_*.json")):
        for i in json.loads(out.read_text(encoding="utf-8")):
            for r in records:
                if r["path"] == i["path"]:
                    r["caption"], r["context"] = i.get("caption"), i.get("context")
    DATA.mkdir(parents=True, exist_ok=True)

    sq = speaking(records)
    wp = writing(records)
    essays = [{"task": r["structured"].get("task"), "prompt": r["structured"].get("prompt_if_visible"),
               "text": r["structured"].get("essay_text") or r.get("text"),
               "teacher_comments": r["structured"].get("teacher_comments"), "band": r["structured"].get("band"),
               "author": r.get("author"),
               # corrected essays are re-posted by the teacher, so also look for the name in the photo itself
               "is_mine": is_mine(r, me),
               "date": date_iso(r.get("date")), "photo": r["path"]}
              for r in records if r["category"] == "essay"]
    # join essay pages split over several photos
    joined = []
    for e, r in zip(essays, [r for r in records if r["category"] == "essay"]):
        if r.get("continues_previous") and joined:
            prev = joined[-1]
            prev["text"] = (prev["text"] or "") + "\n" + (e["text"] or "")
            prev["teacher_comments"] = "\n".join(x for x in (prev["teacher_comments"], e["teacher_comments"]) if x)
            prev["band"] = prev["band"] or e["band"]
            prev["is_mine"] = prev["is_mine"] or e["is_mine"]
            prev.setdefault("more_photos", []).append(e["photo"])
        else:
            joined.append(e)
    essays = joined
    results = [{**r["structured"], "date": date_iso(r.get("date")), "photo": r["path"], "posted_by": r.get("author")}
               for r in records if r["category"] == "test_result"]

    def dump(name, obj):
        (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

    dump("speaking_questions.photos.json", sq)
    dump("writing_prompts.photos.json", wp)
    dump("photo_essays.json", essays)
    dump("test_results.json", results)

    mats = [r for r in records if r["category"] in ("teaching_material", "reading_material", "listening_material")]
    md = ["# Teaching material found in chat photos\n"]
    for r in mats:
        md.append(f"## {r.get('title')}  \n*{r['category']} — {r.get('date')} — `{r['path']}`*\n\n{r.get('text', '').strip()}\n")
    (ROOT / "knowledge" / "raw" / "photo_materials.md").write_text("\n".join(md), encoding="utf-8")

    from collections import Counter
    print("records:", len(records), dict(Counter(r["category"] for r in records)))
    print("speaking questions:", dict(Counter(q["part"] for q in sq)))
    print("writing prompts:", dict(Counter(p["task"] for p in wp)), "essays:", len(essays),
          "mine:", sum(e["is_mine"] for e in essays), "results:", len(results), "materials:", len(mats))


if __name__ == "__main__":
    main()
