"""Scrape free IELTS *reading* tests from engnovate.com into content/tests/reading/<id>.json.

For personal offline study. Output follows ARCHITECTURE.md section 1.

How it works
  1. Enumerate https://engnovate.com/ielts-reading-tests/?category_type=<cat>&paged_full=<n>
     for every category linked from the index (only "Full Test" entries are kept).
  2. Fetch each test page. Tests whose submit button is `locked` are premium -> skipped.
  3. Answers + explanations: the page's own JS submits the form to admin-ajax.php
     (action=process_ielts_reading_test). Submitting an *empty* answer set returns, per
     question: correct_answer, type, section_id, `explanation` (evidence sentence(s) from the
     passage) and `detailed_explanation`. We store those in explanation_html.
  4. Parse passages + question groups from the page HTML, download images, write JSON.

Raw HTML / AJAX JSON is cached under content/_cache/engnovate/reading/ so re-runs are cheap.

Usage
  .venv\\Scripts\\python.exe tools\\scrape_engnovate_reading.py                  # everything
  .venv\\Scripts\\python.exe tools\\scrape_engnovate_reading.py --only cam20-reading-2
  .venv\\Scripts\\python.exe tools\\scrape_engnovate_reading.py --category cambridge-academic --force
Options: --force (rebuild existing JSON), --refresh (re-download cached HTML/answers),
         --refresh-index, --include-forecast, --delay 1.0, --limit N
"""
from __future__ import annotations

import argparse
import copy
import html as htmlmod
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag, Comment

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
OUT_DIR = CONTENT / "tests" / "reading"
MEDIA_DIR = CONTENT / "media" / "reading"
CACHE = CONTENT / "_cache" / "engnovate" / "reading"
BASE = "https://engnovate.com/ielts-reading-tests/"
AJAX = "https://engnovate.com/wp-admin/admin-ajax.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# Forecast tests are re-assembled from passages already in other categories (duplicates).
DERIVATIVE_CATEGORIES = {"forecast-academic", "forecast-general"}

TYPE_MAP = {
    "true_false_notgiven": "tfng",
    "yes_no_notgiven": "ynng",
    "one_choice": "mcq",
    "two_choices": "multi_select",
    "three_choices": "multi_select",
    "four_choices": "multi_select",
    "five_choices": "multi_select",
    "matching_information": "matching_information",
    "matching_headings": "matching_headings",
    "matching_features": "matching_features",
    "matching_sentence_endings": "matching_sentence_endings",
    "matching": "matching",
    "note_completion": "note_completion",
    "summary_completion": "summary_completion",
    "table_completion": "table_completion",
    "flow_chart_completion": "flowchart_completion",
    "flowchart_completion": "flowchart_completion",
    "sentence_completion": "sentence_completion",
    "short_answers": "short_answer",
    "short_answer": "short_answer",
    "diagram_labeling": "diagram_labelling",
    "diagram_labelling": "diagram_labelling",
    "form_completion": "form_completion",
    "map_labeling": "map_labelling",
    "plan_labeling": "plan_labelling",
}

INSTR_RE = re.compile(
    r"^\s*(complete|choose|write|answer|do the following|look at|reading passage|"
    r"which (paragraph|section)|match|classify|label|use (no|one|two|three)|nb\b|in boxes|"
    r"on your answer|true\b|false\b|yes\b|no\b|not given|the reading passage|"
    r"questions?\s+\d|for questions|select|read the|there are more|you may use|"
    r"drag|list of|the text on|the passage has|the article has|section [a-z] has|"
    r"identify|from the list|each (paragraph|section|statement)|for which|the text has|"
    r"which (text|advertisement|person|company)|the (article|text|passage) (has|on))",
    re.I,
)
OPTION_LINE_RE = re.compile(r"^\s*([A-Z]|[ivxlcIVXLC]{1,6})\s*[.)]?\s+(\S.*)$", re.S)


ROMANS = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv"]


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------- fetching
class Fetcher:
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.last = 0.0
        self.client = httpx.Client(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                                   follow_redirects=True, timeout=60)

    def _wait(self):
        dt = time.monotonic() - self.last
        if dt < self.delay:
            time.sleep(self.delay - dt)
        self.last = time.monotonic()

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        err = None
        for attempt in range(5):
            self._wait()
            try:
                r = self.client.request(method, url, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                err = e
                wait = 2 ** attempt * 2
                log(f"    retry {attempt + 1} for {url}: {e} (sleep {wait}s)")
                time.sleep(wait)
        raise RuntimeError(f"failed {method} {url}: {err}")

    def get_text(self, url: str, cache_file: Path | None = None, refresh: bool = False) -> str:
        if cache_file and cache_file.exists() and not refresh:
            return cache_file.read_text(encoding="utf-8")
        r = self.request("GET", url)
        r.raise_for_status()
        text = r.text
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(text, encoding="utf-8")
        return text

    def download(self, url: str, dest: Path) -> bool:
        if dest.exists() and dest.stat().st_size > 0:
            return True
        try:
            r = self.request("GET", url)
            if r.status_code != 200 or not r.content:
                log(f"    image HTTP {r.status_code}: {url}")
                return False
        except RuntimeError as e:
            log(f"    image failed: {e}")
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return True


# --------------------------------------------------------------------------- index
def slug_of(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def test_id_for(slug: str) -> str:
    m = re.match(r"cambridge-ielts-0*(\d+)-academic-reading-test-0*(\d+)$", slug)
    if m:
        return f"cam{int(m.group(1))}-reading-{int(m.group(2))}"
    m = re.match(r"cambridge-ielts-0*(\d+)-general-training-reading-test-0*(\d+)$", slug)
    if m:
        return f"cam{int(m.group(1))}-gt-reading-{int(m.group(2))}"
    return slug


def enumerate_tests(fx: Fetcher, refresh: bool, only_cats: list[str] | None) -> list[dict]:
    idx_dir = CACHE / "index"
    main = fx.get_text(BASE, idx_dir / "index.html", refresh)
    s = BeautifulSoup(main, "lxml")
    cats: dict[str, str] = {}
    for a in s.select("a.ielts_reading_test_category_filter_button, a[href*='category_type=']"):
        m = re.search(r"category_type=([a-z0-9-]+)", a.get("href", ""))
        if m and m.group(1) != "all" and "paged" not in a["href"]:
            label = a.get_text(" ", strip=True).replace("★", "").strip()
            if m.group(1) not in cats or (label and not cats[m.group(1)]):
                cats[m.group(1)] = label
    if only_cats:
        cats = {c: cats.get(c, c) for c in only_cats}
    tests: dict[str, dict] = {}
    for cat, label in cats.items():
        page = 1
        while page < 60:
            url = f"{BASE}?category_type={cat}&paged_full={page}"
            html = fx.get_text(url, idx_dir / f"{cat}_p{page}.html", refresh)
            ps = BeautifulSoup(html, "lxml")
            arts = ps.select("#ielts_reading_test_filter_results article")
            new = 0
            for art in arts:
                a = art.select_one("h2 a")
                if not a:
                    continue
                u = a["href"]
                if u in tests:
                    continue
                new += 1
                lt = art.select_one(".ielts-reading-test-length-type span")
                tests[u] = {
                    "url": u, "slug": slug_of(u), "title": a.get_text(" ", strip=True),
                    "category": cat, "category_label": label or cat,
                    "length": " ".join(lt.get("class", [])) if lt else None,
                    "length_label": lt.get_text(strip=True) if lt else None,
                }
            log(f"  index {cat} p{page}: {len(arts)} items, {new} new")
            if not arts or not new:
                break
            page += 1
    lst = list(tests.values())
    (CACHE / "index").mkdir(parents=True, exist_ok=True)
    (CACHE / "index" / "tests.json").write_text(json.dumps(lst, indent=1, ensure_ascii=False), encoding="utf-8")
    return lst


# --------------------------------------------------------------------------- answers
def form_fields(soup: BeautifulSoup) -> dict | None:
    form = soup.find("form", id="ielts-reading-test-form")
    if not form:
        return None
    d: dict[str, str] = {}
    # inputs may live outside the <form> (form="ielts-reading-test-form" attribute)
    els = form.find_all(["input", "select", "textarea"]) + soup.find_all(attrs={"form": "ielts-reading-test-form"})
    for el in els:
        n = el.get("name")
        if not n or n in d:
            continue
        t = (el.get("type") or "").lower()
        if el.name == "input" and t == "hidden" and not n.startswith("ielts_reading_answer_"):
            d[n] = el.get("value", "")
        else:
            d[n] = ""
    d.update(action="process_ielts_reading_test", time_taken_seconds="600", save_learner_progress="0")
    return d


def fetch_answers(fx: Fetcher, url: str, slug: str, page_html: str, refresh: bool) -> tuple[list[dict] | None, str]:
    """Return (results, page_html_used). Retries with a fresh page if the cached nonce is stale."""
    cache_file = CACHE / "answers" / f"{slug}.json"
    if cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text(encoding="utf-8")), page_html
    for fresh in (False, True):
        if fresh:
            page_html = fx.get_text(url, CACHE / "pages" / f"{slug}.html", refresh=True)
        fields = form_fields(BeautifulSoup(page_html, "lxml"))
        if not fields:
            return None, page_html
        r = fx.request("POST", AJAX, data=fields,
                       headers={"Referer": url, "X-Requested-With": "XMLHttpRequest",
                                "Origin": "https://engnovate.com"})
        try:
            j = r.json()
        except ValueError:
            j = None
        if isinstance(j, dict) and j.get("success") and isinstance(j.get("data"), dict) and j["data"].get("results"):
            res = j["data"]["results"]
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
            return res, page_html
        log(f"    answer request failed (fresh={fresh}): {r.status_code} {r.text[:200]!r}")
    return None, page_html


def split_answer(raw: str, multi: bool) -> list[str]:
    raw = htmlmod.unescape(raw or "").replace("\xa0", " ")
    raw = re.sub("[‘’ʼ`]", "'", raw).strip()
    if not raw:
        return []
    if multi:
        parts = re.split(r"\s*(?:/|,|;|&|\band\b|\s)\s*", raw)
    else:
        parts = re.split(r"\s+/\s+|\s*/\s*(?=\S)|\s+OR\s+", raw)
    out = []
    for p in parts:
        p = re.sub(r"\s+", " ", p).strip()
        if p and p not in out:
            out.append(p)
    return out


def explanation_html(res: dict) -> str | None:
    parts = []
    det = (res.get("detailed_explanation") or "").replace("\r\n", "\n").strip()
    if det:
        for line in det.split("\n"):
            line = line.strip()
            if not line:
                continue
            esc = htmlmod.escape(htmlmod.unescape(line), quote=False)
            if re.match(r"^(Excerpt/Passage Explanation|Answer Explanation|Reason For Correctness)\s*:?$", line, re.I):
                parts.append(f"<p><strong>{esc}</strong></p>")
            else:
                parts.append(f"<p>{esc}</p>")
    ev = [x.strip() for x in (res.get("explanation") or "").replace("\r\n", "\n").split("\n") if x.strip()]
    if ev:
        parts.append("<p><strong>Evidence from the passage:</strong></p>")
        parts.append("<blockquote>" + "".join(f"<p>{htmlmod.escape(htmlmod.unescape(x), quote=False)}</p>" for x in ev)
                     + "</blockquote>")
    return "".join(parts) or None


# --------------------------------------------------------------------------- HTML cleaning
KEEP_ATTRS = {"img": {"src", "alt"}, "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"},
              "ol": {"type", "start"}}
DROP_TAGS = ["script", "style", "noscript", "iframe", "ins", "button", "input", "select", "textarea",
             "svg", "form", "label"]


def clean_soup_inplace(root: Tag):
    for c in root.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    for t in root.find_all(DROP_TAGS):
        t.decompose()
    for t in root.select(".code-block, .dnd-panel, .dnd-drop-placeholder, .dnd-drop-value, "
                         ".ielts-reading-skimming-button-container, i.fa-solid, i.fa-regular, .correct-answer-info"):
        t.decompose()
    for t in root.find_all(True):
        if t.name == "div" and "heading-slot" in (t.get("class") or []):
            t.attrs = {"class": "heading-slot", "data-q": t.get("data-q")}
            continue
        if t.name in ("span", "a", "font", "section", "article", "mark", "div"):
            t.unwrap()
            continue
        keep = KEEP_ATTRS.get(t.name, set())
        t.attrs = {k: v for k, v in t.attrs.items() if k in keep}
    for s in root.find_all(string=True):
        ns = re.sub(r"[ \t]{2,}", " ", s.replace("\xa0", " ").replace("​", ""))
        if ns != str(s):
            s.replace_with(NavigableString(ns))
    # drop empty blocks
    changed = True
    while changed:
        changed = False
        for t in root.find_all(["p", "div", "strong", "b", "em", "i", "li", "h3", "h4", "ul"]):
            if t.name == "div" and "heading-slot" in (t.get("class") or []):
                continue
            if not t.get_text(strip=True) and not t.find(["img", "br", "table"]) and not t.find(class_="heading-slot"):
                if "{{" in t.get_text():
                    continue
                if t.name in ("strong", "b", "em", "i") and t.get_text() != "":
                    t.replace_with(NavigableString(" "))  # keep word separation ("boxes<b> </b>on")
                else:
                    t.decompose()
                changed = True
                break


def inner_html(root: Tag) -> str:
    s = "".join(str(c) for c in root.contents)
    s = re.sub(r"(\w)\{\{(\d+)\}\}", r"\1 {{\2}}", s)
    s = re.sub(r"\{\{(\d+)\}\}(\w)", r"{{\1}} \2", s)
    s = re.sub(r"\{\{(\d+)\}\}\s+([,.;:?!)])", r"{{\1}}\2", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    s = re.sub(r"<br/>\s*(</p>)", r"\1", s)
    s = re.sub(r"(<p>)\s*<br/>", r"\1", s)
    return s.strip()


def frag_html(nodes: list) -> str:
    wrap = BeautifulSoup("<div></div>", "lxml").div
    for n in nodes:
        wrap.append(copy.copy(n))
    clean_soup_inplace(wrap)
    return inner_html(wrap)


def text_of(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True).replace("\xa0", " ")).strip()


# --------------------------------------------------------------------------- images
class Images:
    def __init__(self, fx: Fetcher, test_id: str, page_url: str):
        self.fx, self.test_id, self.page_url = fx, test_id, page_url
        self.files: list[str] = []
        self.failed: list[str] = []

    def localise(self, root: Tag):
        for img in root.find_all("img"):
            src = img.get("data-src") or img.get("src") or ""
            if src.startswith("data:") or not src:
                img.decompose()
                continue
            url = urljoin(self.page_url, src)
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", unquote(urlparse(url).path.split("/")[-1])) or "image.png"
            dest = MEDIA_DIR / self.test_id / name
            if self.fx.download(url, dest):
                rel = f"media/reading/{self.test_id}/{name}"
                if rel not in self.files:
                    self.files.append(rel)
                img["src"] = f"/media/content/reading/{self.test_id}/{name}"
            else:
                self.failed.append(url)
                img["src"] = url
            for a in ("srcset", "sizes", "data-src", "loading", "decoding", "class", "width", "height", "style"):
                img.attrs.pop(a, None)


# --------------------------------------------------------------------------- parsing
class ParseError(Exception):
    pass


def roman_or_letter_key(k: str) -> str:
    return k.strip().rstrip(".").strip()


def normalise_key(ans: str, options: list[dict] | None) -> str:
    if not options:
        return ans
    for o in options:
        if o["key"].lower() == ans.strip().rstrip(".").lower():
            return o["key"]
    for o in options:
        if o.get("value") and o["value"].lower() == ans.strip().lower():
            return o["key"]
    return ans


def item_of(num_el: Tag) -> Tag | None:
    p = num_el.parent
    while p is not None and isinstance(p, Tag):
        if "ielts-reading-question-item" in (p.get("class") or []):
            return p
        p = p.parent
    return None


def strip_numbers(el: Tag):
    for n in el.select("strong.ielts-reading-question-number"):
        n.decompose()


def options_from_option_divs(item: Tag) -> list[dict]:
    opts = []
    for od in item.select(".ielts-reading-option"):
        lab = od.find("label")
        inp = od.find("input")
        sp = od.find("span")
        key = text_of(lab) if lab else (inp.get("value", "") if inp else "")
        opts.append({"key": key, "text": frag_html(list(sp.contents)) if sp else "",
                     "value": (inp.get("value") if inp else key) or key})
    return opts


def dnd_options(panel: Tag) -> list[dict]:
    opts = []
    for card in panel.select(".dnd-card"):
        key = card.get("data-value") or text_of(card.select_one(".dnd-label")).rstrip(".")
        t = card.select_one(".dnd-text")
        opts.append({"key": key.strip(), "text": text_of(t) if t else ""})
    return opts


def split_instruction_blocks(blocks: list[Tag]) -> tuple[list, list]:
    """Leading blocks that look like instructions vs the rest (actual content)."""
    instr, rest = [], []
    in_instr = True
    for b in blocks:
        if isinstance(b, NavigableString):
            if not b.strip():
                continue
            (instr if in_instr else rest).append(b)
            continue
        txt = text_of(b)
        has_q = bool(b.select("strong.ielts-reading-question-number")) or "{{" in txt
        if in_instr and not has_q and b.name in ("p", "div", "h3", "h4", "h5", "em", "strong") \
                and not b.find(["img", "table"]) and (INSTR_RE.match(txt) or not txt):
            instr.append(b)
        else:
            in_instr = False
            rest.append(b)
    return instr, rest


def _norm(s: str) -> str:
    return re.sub(r"[\s.,;:!?'’‘\"]+", " ", (s or "").lower()).strip()


def remove_option_lines(nodes: list, options: list[dict]) -> tuple[list, bool]:
    """Remove "A. Nick Antonio" style lines (duplicating options) from paragraphs. Returns nodes, removed?"""
    keys = {o["key"].lower(): re.sub(r"\s+", " ", o.get("text") or "").strip().lower() for o in options}
    removed = False
    out = []
    for n in nodes:
        if not isinstance(n, Tag) or n.name != "p":
            out.append(n)
            continue
        segs = re.split(r"<br\b[^>]*>", n.decode_contents())
        kept = []
        for seg in segs:
            t = re.sub(r"\s+", " ", BeautifulSoup(seg, "lxml").get_text(" ", strip=True).replace("\xa0", " ")).strip()
            m = OPTION_LINE_RE.match(t)
            if m and keys.get(m.group(1).lower()) and _norm(m.group(2)) == _norm(keys[m.group(1).lower()]):
                removed = True
                continue
            if t.lower() in ("list of headings", "list of people", "list of researchers"):
                removed = True
                continue
            kept.append(seg)
        if len(kept) == len(segs):
            out.append(n)
        elif any(BeautifulSoup(k, "lxml").get_text(strip=True) for k in kept):
            nn = BeautifulSoup(f"<p>{'<br/>'.join(kept)}</p>", "lxml").p
            out.append(nn)
    return out, removed


def options_from_lines(nodes: list, keys: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    want = {k.lower() for k in keys}
    for n in nodes:
        if not isinstance(n, Tag):
            continue
        for seg in re.split(r"<br\b[^>]*>", n.decode_contents() if n.name == "p" else str(n)):
            for line in BeautifulSoup(seg, "lxml").get_text("\n").split("\n"):
                t = re.sub(r"\s+", " ", line.replace("\xa0", " ")).strip()
                m = OPTION_LINE_RE.match(t)
                if m and m.group(1).lower() in want and m.group(1).lower() not in {k.lower() for k in found}:
                    found[m.group(1)] = m.group(2).strip()
    if len(found) * 2 < len(keys):  # not a real option list
        return {}
    return found


def parse_test(soup: BeautifulSoup, results: list[dict], test_id: str, imgs: Images) -> list[dict]:
    nq = len(results)
    sec_of = {i + 1: str(r.get("section_id")) for i, r in enumerate(results)}
    parts = []
    sections = soup.select(".ielts-reading-question-sections > .ielts-reading-question-section")
    if not sections:
        raise ParseError("no question sections")
    for sec in sections:
        pno = int(sec.get("data-part-number") or re.search(r"(\d+)$", sec.get("id", "")).group(1))
        transcript = soup.find(id=f"ielts-reading-transcript-{pno}")
        if transcript is None:
            raise ParseError(f"no passage for part {pno}")
        groups = []
        # ---- split into groups by h2 headings
        raw_groups: list[list[Tag]] = []
        for ch in sec.find_all(recursive=False):
            if ch.name == "h2":
                raw_groups.append([ch])
            elif raw_groups:
                raw_groups[-1].append(ch)
            else:
                raw_groups.append([ch])
        for rg in raw_groups:
            groups.extend(parse_group(rg, soup, results, sec_of, transcript, imgs))
        # ---- passage
        tr = copy.copy(transcript)
        for slot_item in tr.select(".ielts-reading-question-item"):
            n = slot_item.select_one("strong.ielts-reading-question-number")
            if n:
                slot = soup.new_tag("div", attrs={"class": "heading-slot", "data-q": text_of(n)})
                slot_item.replace_with(slot)
            else:
                slot_item.decompose()
        subheads = tr.select("p.ielts-reading-passage-subhead")
        titles = [text_of(h) for h in subheads if text_of(h)]
        if len(subheads) == 1:
            subheads[0].decompose()
        else:
            for h in subheads:  # keep as headings inside the passage
                h.name = "h4"
                h.attrs = {}
        imgs.localise(tr)
        clean_soup_inplace(tr)
        passage = inner_html(tr)
        title = " / ".join(titles) if titles else f"Passage {pno}"
        parts.append({"number": pno, "title": title, "audio": None, "audio_remote": None,
                      "transcript_html": None, "passage_html": passage, "groups": groups})
    parts.sort(key=lambda p: p["number"])
    seen = sorted(q["number"] for p in parts for g in p["groups"] for q in g["questions"])
    if seen != list(range(1, nq + 1)):
        raise ParseError(f"question numbers parsed {seen} != 1..{nq}")
    return parts


def parse_group(rg: list[Tag], soup: BeautifulSoup, results: list[dict], sec_of: dict,
                transcript: Tag, imgs: Images) -> list[dict]:
    content_el = next((x for x in rg if "ielts-reading-question-section-content" in (x.get("class") or [])), None)
    qarea = next((x for x in rg if "ielts-reading-questions" in (x.get("class") or [])), None)
    # numbers that live in this group's markup
    nums_here = []
    for x in rg:
        if x.name == "h2":
            continue
        for n in x.select("strong.ielts-reading-question-number"):
            nums_here.append(int(text_of(n)))
    # section id of this group
    sid = None
    for x in rg:
        for inp in x.select("input[name^=ielts_reading_answer_]"):
            m = re.match(r"ielts_reading_answer_(\d+)_", inp["name"])
            if m:
                sid = m.group(1)
                break
        if sid:
            break
        z = x.select_one("[data-dnd-group]")
        if z:
            sid = z["data-dnd-group"]
            break
    nums = sorted(set(nums_here) | {n for n, s in sec_of.items() if sid and s == sid})
    if not nums:
        return []
    etype = (results[nums[0] - 1].get("type") or "").strip()
    gtype = TYPE_MAP.get(etype)
    if not gtype:
        log(f"    WARNING unknown engnovate type {etype!r} for Q{nums[0]}")
        gtype = etype or "short_answer"

    # ---------- classify each question
    info: dict[int, dict] = {}
    for n in nums:
        num_el = soup.find(id=f"ielts-reading-question-number-{n}")
        if num_el is None:
            raise ParseError(f"Q{n} not found in page")
        it = item_of(num_el)
        if transcript in num_el.parents:
            kind = "heading"
        elif content_el is not None and content_el in num_el.parents:
            kind = "content"
        elif it is not None and it.name == "tr":
            kind = "matrix"
        elif it is not None and it.select("input[type=checkbox]"):
            kind = "check"
        elif it is not None and it.select("input[type=radio]"):
            kind = "radio"
        elif it is not None and it.select(".dnd-zone"):
            kind = "inline"
        elif it is not None and it.select("select"):
            kind = "select"
        else:
            kind = "prompt"
            if it is not None:
                # text after the input -> gap is mid-sentence
                inp = it.find("input", attrs={"type": "text"})
                after = ""
                if inp is not None:
                    for sib in inp.next_siblings:
                        after += sib.get_text(" ", strip=True) if isinstance(sib, Tag) else str(sib).strip()
                if after.strip():
                    kind = "inline"
        info[n] = {"kind": kind, "item": it, "num_el": num_el}

    kinds = {v["kind"] for v in info.values()}
    instructions_nodes: list = []
    content_nodes: list = []
    group_options: list[dict] | None = None

    # ---------- group-level options (dnd panels)
    panels = []
    for x in rg:
        panels += x.select(".dnd-panel")
    if not panels and "heading" in kinds:
        sid_h = info[nums[0]]["num_el"].find_parent(attrs={"data-dnd-group": True})
        if sid_h:
            panels = soup.select(f'.dnd-panel[data-dnd-group="{sid_h["data-dnd-group"]}"]')
    if panels:
        group_options = dnd_options(panels[0])

    # ---------- content blocks (instructions + content)
    if content_el is not None:
        c = copy.copy(content_el)
        for p in c.select(".dnd-panel"):
            p.decompose()
        # replace inline gaps with {{N}}
        for it in c.select(".ielts-reading-question-item"):
            n = it.select_one("strong.ielts-reading-question-number")
            if n:
                sel = it.find("select")
                if sel is not None and group_options is None:
                    group_options = [{"key": o.get("value") or text_of(o), "text": ""}
                                     for o in sel.find_all("option") if (o.get("value") or "").strip()]
                it.replace_with(NavigableString("{{%s}}" % text_of(n)))
            else:
                it.decompose()
        wrapper = c.select_one(".ielts-reading-section-content-wrapper")
        root = wrapper if wrapper is not None else c
        blocks = [b for b in root.contents if not (isinstance(b, NavigableString) and not b.strip())]
        if wrapper is not None:  # anything outside wrapper (rare)
            pass
        instructions_nodes, content_nodes = split_instruction_blocks(blocks)
        # no gaps in the content and nothing visual -> it is all instructions
        if not any("{{" in (n.get_text() if isinstance(n, Tag) else str(n)) for n in content_nodes) \
                and not any(isinstance(n, Tag) and (n.name in ("table", "img", "ul", "ol") or n.find(["img", "table"]))
                            for n in content_nodes) \
                and not (kinds & {"inline", "select"}):
            instructions_nodes, content_nodes = instructions_nodes + content_nodes, []

    # ---------- matrix options (matching table header) + option texts from content lines
    if "matrix" in kinds and group_options is None:
        table = info[nums[0]]["item"].find_parent("table")
        keys = [text_of(th) for th in table.select("thead th") if text_of(th)]
        texts = options_from_lines(instructions_nodes + content_nodes, keys)
        group_options = [{"key": k, "text": texts.get(k, "")} for k in keys]
    if gtype in ("multi_select",) or "check" in kinds:
        pass  # options added per item below

    if group_options:
        instructions_nodes, _ = remove_option_lines(instructions_nodes, group_options)
        content_nodes, _ = remove_option_lines(content_nodes, group_options)

    # ---------- build questions
    out_groups: list[dict] = []
    questions: list[dict] = []
    inline_mode = bool(kinds & {"content", "inline"})
    extra_content: list[str] = []
    check_items: list[tuple[Tag, list[int]]] = []

    def answer_for(n: int, opts: list[dict] | None, multi: bool = False) -> list[str]:
        raw = results[n - 1].get("correct_answer") or ""
        ans = split_answer(raw, multi)
        if opts:
            ans = [normalise_key(a, opts) for a in ans]
            keys = {o["key"] for o in opts}
            if any(a in keys for a in ans):  # drop free-text variants next to the letter key
                ans = [a for a in ans if a in keys]
        if gtype in ("tfng", "ynng"):
            ans = [a.upper() for a in ans]
        return ans

    for n in nums:
        k = info[n]["kind"]
        it = info[n]["item"]
        q = {"number": n, "prompt_html": "", "options": None, "answer": [],
             "explanation_html": explanation_html(results[n - 1])}
        if k == "content":
            q["answer"] = answer_for(n, group_options)
        elif k == "heading":
            # label from the paragraph after the slot
            label = None
            node = it
            for sib in node.find_next_siblings():
                t = text_of(sib)
                if t:
                    m = re.match(r"^(?:(Paragraph|Section)\s+)?([A-Z])\b[.:)]?\s", t + " ")
                    if m:
                        label = f"{m.group(1) or 'Paragraph'} {m.group(2)}"
                    else:
                        words = t.split()
                        label = "Paragraph beginning “" + " ".join(words[:6]) + "…”"
                    break
            q["prompt_html"] = label or f"Question {n}"
            q["answer"] = answer_for(n, group_options)
        elif k == "matrix":
            cell = copy.copy(it.select_one(".ielts-reading-matching-question-cell") or it.find("td"))
            strip_numbers(cell)
            q["prompt_html"] = frag_html(list(cell.contents))
            q["answer"] = answer_for(n, group_options)
        elif k == "radio":
            stem = copy.copy(it.find("span", recursive=False) or it.find("span"))
            opts = options_from_option_divs(it)
            if stem is not None:
                strip_numbers(stem)
                q["prompt_html"] = frag_html(list(stem.contents))
            if gtype in ("tfng", "ynng"):
                q["options"] = None
                vals = {o["value"].upper(): o for o in opts}
                ans = answer_for(n, None)
                q["answer"] = ans
            else:
                q["answer"] = answer_for(n, opts)
                q["options"] = [{"key": o["key"], "text": o["text"]} for o in opts]
        elif k == "check":
            if not check_items or check_items[-1][0] is not it:
                check_items.append((it, []))
            check_items[-1][1].append(n)
            continue  # built below
        elif k == "select":
            sel = it.find("select")
            opts = [{"key": o.get("value") or text_of(o), "text": text_of(o)}
                    for o in sel.find_all("option") if (o.get("value") or "").strip()]
            if group_options is None:
                group_options = opts
            c = copy.copy(it)
            for s in c.find_all("select"):
                s.replace_with(NavigableString("{{%d}}" % n))
            strip_numbers(c)
            if inline_mode:
                extra_content.append(f"<p>{frag_html(list(c.contents))}</p>")
            else:
                inline_mode = True
                extra_content.append(f"<p>{frag_html(list(c.contents))}</p>")
            q["answer"] = answer_for(n, group_options)
        else:  # inline / prompt (text input or dnd in question list)
            c = copy.copy(it)
            zone = c.select_one(".dnd-zone") or c.find("input", attrs={"type": "text"})
            if zone is None:
                zone = c.find("input")
            if zone is not None:
                zone.replace_with(NavigableString("{{%d}}" % n))
            strip_numbers(c)
            body = frag_html(list(c.contents))
            body = re.sub(r"^\s*[•·\-–]\s*", "", body)
            if k == "inline":
                extra_content.append(f"<p>{body}</p>")
            else:
                prompt = body.replace("{{%d}}" % n, "").strip()
                q["prompt_html"] = prompt
                q["_inline"] = f"<p>{body}</p>" if prompt else None
            q["answer"] = answer_for(n, group_options)
        questions.append(q)

    # mixed prompt + inline -> convert prompt questions into inline paragraphs
    has_picture = any(isinstance(n, Tag) and (n.name == "img" or n.find("img"))
                      for n in instructions_nodes + content_nodes)
    blank_prompts = any(info[q["number"]]["kind"] == "prompt" and not q["prompt_html"] for q in questions)
    if blank_prompts and not has_picture:
        inline_mode = True  # e.g. "List the FOUR main ways..." -> numbered gaps in content_html
    if inline_mode and any(info[q["number"]]["kind"] == "prompt" for q in questions):
        for q in questions:
            if info[q["number"]]["kind"] == "prompt":
                extra_content.append(q.get("_inline") or "<p>{{%d}}</p>" % q["number"])
                q["prompt_html"] = ""
    for q in questions:
        q.pop("_inline", None)

    # ---------- assemble html
    def build(nodes: list) -> str:
        wrap = BeautifulSoup("<div></div>", "lxml").div
        for nd in nodes:
            wrap.append(copy.copy(nd))
        imgs.localise(wrap)
        clean_soup_inplace(wrap)
        return inner_html(wrap)

    instructions_html = build(instructions_nodes) or None
    content_html = build(content_nodes)
    if extra_content:
        content_html = (content_html + "\n" if content_html else "") + "\n".join(extra_content)
    image = None
    if content_html:
        cs = BeautifulSoup(content_html, "lxml")
        imgs_in = cs.find_all("img")
        if len(imgs_in) == 1:
            p = imgs_in[0].find_parent("p")
            if p is not None and not p.get_text(strip=True):
                src = imgs_in[0]["src"]
                if src.startswith("/media/content/"):
                    image = "media/" + src[len("/media/content/"):]
                    p.decompose()
                    content_html = inner_html(cs.body)
    content_html = content_html or None

    # letter-answer groups rendered as plain text boxes on engnovate: derive the option list
    # from "A-H" / "i-viii" in the instructions (texts from "A. xxx" lines when present)
    if not group_options and gtype.startswith("matching") and not check_items:
        alltxt = BeautifulSoup((instructions_html or "") + (content_html or ""), "lxml").get_text("\n")
        keys: list[str] = []
        m = re.search(r"\b([ivx]{1,5})\s*[-–—]\s*([ivx]{1,6})\b", alltxt)
        if m and gtype == "matching_headings" and m.group(1) in ROMANS and m.group(2) in ROMANS:
            keys = ROMANS[ROMANS.index(m.group(1)):ROMANS.index(m.group(2)) + 1]
        else:
            m = re.search(r"\b([A-Z])\s*[-–—]\s*([A-Z])\b", alltxt)
            if m and m.group(1) < m.group(2):
                keys = [chr(c) for c in range(ord(m.group(1)), ord(m.group(2)) + 1)]
        if not keys:  # fall back to the answers themselves
            keys = sorted({a for q in questions for a in q["answer"]})
        texts = options_from_lines(instructions_nodes + content_nodes, keys)
        group_options = [{"key": k, "text": texts.get(k, "")} for k in keys]
        for q in questions:
            q["answer"] = [normalise_key(a, group_options) for a in q["answer"]]
        if texts:
            ins, _ = remove_option_lines(instructions_nodes, group_options)
            instructions_html = build(ins) or None

    base = {"range": None, "type": gtype, "instructions_html": instructions_html,
            "content_html": content_html, "image": image,
            "options": [{"key": o["key"], "text": o["text"]} for o in group_options] if group_options else None,
            "questions": []}

    if check_items:
        # one multi_select group per checkbox item (they each own an option list)
        for it, cnums in check_items:
            stem = copy.copy(it.find("span", recursive=False) or it.find("span"))
            strip_numbers(stem)
            stem_html = frag_html(list(stem.contents)) if stem is not None else ""
            opts = options_from_option_divs(it)
            raw_union: list[str] = []
            for n in cnums:
                for a in answer_for(n, opts, multi=True):
                    if a not in raw_union:
                        raw_union.append(a)
            g = dict(base)
            g["type"] = "multi_select"
            g["options"] = [{"key": o["key"], "text": o["text"]} for o in opts]
            g["content_html"] = None
            g["image"] = None
            g["questions"] = [{"number": n, "prompt_html": stem_html, "options": None,
                               "answer": list(raw_union), "explanation_html": explanation_html(results[n - 1])}
                              for n in cnums]
            g["range"] = [cnums[0], cnums[-1]]
            out_groups.append(g)
        if questions:
            g = dict(base)
            g["questions"] = questions
            g["range"] = [questions[0]["number"], questions[-1]["number"]]
            out_groups.append(g)
        out_groups.sort(key=lambda g: g["range"][0])
        return out_groups

    base["questions"] = questions
    base["range"] = [questions[0]["number"], questions[-1]["number"]]
    if base["type"] == "multi_select" and not base["options"]:
        base["type"] = "mcq"
    return [base]


# --------------------------------------------------------------------------- one test
def meta_for(t: dict, soup: BeautifulSoup) -> dict:
    slug = t["slug"]
    title = t.get("title") or (soup.title.string if soup.title else slug)
    title = re.sub(r"\s*\(Free Online Test.*$", "", title).strip()
    title = re.sub(r"\bIELTS 0(\d)\b", r"IELTS \1", title)
    m = re.match(r"cambridge-ielts-0*(\d+)-(academic|general-training)-reading-test-0*(\d+)$", slug)
    cat = t.get("category") or ""
    module = "general" if ("general" in cat or "general-training" in slug) else "academic"
    if m:
        book, test_no = int(m.group(1)), int(m.group(3))
        series = f"Cambridge IELTS {book}" + (" General Training" if m.group(2) != "academic" else "")
    else:
        book = test_no = None
        series = t.get("category_label") or cat
    return {"title": title, "module": module, "series": series, "book": book, "test_no": test_no}


def validate(test: dict) -> list[str]:
    errs = []
    qs = [q for p in test["parts"] for g in p["groups"] for q in g["questions"]]
    nums = [q["number"] for q in qs]
    if sorted(nums) != list(range(1, 41)):
        errs.append(f"question numbers not 1..40 (got {len(nums)}: {sorted(nums)[:3]}..{sorted(nums)[-3:]})")
    for q in qs:
        if not q["answer"] or not all(a.strip() for a in q["answer"]):
            errs.append(f"Q{q['number']} empty answer")
    for p in test["parts"]:
        for g in p["groups"]:
            ph = [int(x) for x in re.findall(r"\{\{(\d+)\}\}", g.get("content_html") or "")]
            gn = [q["number"] for q in g["questions"]]
            if ph and sorted(ph) != sorted(gn):
                errs.append(f"group {g['range']} placeholders {ph} != questions {gn}")
    return errs


def scrape_one(fx: Fetcher, t: dict, args) -> tuple[str, str]:
    slug = t["slug"]
    tid = test_id_for(slug)
    out = OUT_DIR / f"{tid}.json"
    if out.exists() and not args.force:
        return tid, "exists"
    page = fx.get_text(t["url"], CACHE / "pages" / f"{slug}.html", args.refresh)
    soup = BeautifulSoup(page, "lxml")
    btn = soup.find(id="ielts-reading-test-submit-button")
    if btn is not None and "locked" in (btn.get("class") or []):
        return tid, "skipped: premium (locked)"
    prem = soup.find(id="is_premium")
    if prem is not None and prem.get("value") == "1":
        return tid, "skipped: premium (is_premium=1)"
    if not soup.find("form", id="ielts-reading-test-form"):
        return tid, "skipped: no test form"
    nnum = len({n["id"] for n in soup.select("strong.ielts-reading-question-number[id]")})
    if nnum != 40:
        return tid, f"skipped: {nnum} questions (not a 40-question full test)"
    results, page2 = fetch_answers(fx, t["url"], slug, page, args.refresh)
    if page2 is not page:
        soup = BeautifulSoup(page2, "lxml")
    if not results:
        return tid, "skipped: answers unavailable"
    if len(results) != 40:
        return tid, f"skipped: answer key has {len(results)} entries"
    imgs = Images(fx, tid, t["url"])
    try:
        parts = parse_test(soup, results, tid, imgs)
    except ParseError as e:
        return tid, f"FAILED parse: {e}"
    meta = meta_for(t, soup)
    test = {"id": tid, "type": "reading", "module": meta["module"], "title": meta["title"],
            "series": meta["series"], "book": meta["book"], "test_no": meta["test_no"],
            "source": "engnovate", "source_url": t["url"], "duration_minutes": 60, "parts": parts}
    errs = validate(test)
    if imgs.failed:
        errs.append(f"{len(imgs.failed)} image(s) failed to download")
    if errs:
        rej = CACHE / "rejected" / f"{tid}.json"
        rej.parent.mkdir(parents=True, exist_ok=True)
        rej.write_text(json.dumps(test, indent=1, ensure_ascii=False), encoding="utf-8")
        return tid, "FAILED validation: " + "; ".join(errs[:5])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(test, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out)
    try:  # shared validator (tools/validate_tests.py), if present
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import validate_tests
        verrs, _ = validate_tests.validate(out)
    except ImportError:
        verrs = []
    if verrs:
        rej = CACHE / "rejected" / f"{tid}.json"
        rej.parent.mkdir(parents=True, exist_ok=True)
        out.replace(rej)
        return tid, "FAILED validate_tests: " + "; ".join(verrs[:5])
    return tid, "ok"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="test ids or slugs (e.g. cam20-reading-2)")
    ap.add_argument("--category", nargs="*", help="engnovate category_type slugs")
    ap.add_argument("--force", action="store_true", help="rebuild JSON even if it exists")
    ap.add_argument("--refresh", action="store_true", help="re-download cached test pages/answers")
    ap.add_argument("--refresh-index", action="store_true")
    ap.add_argument("--include-forecast", action="store_true")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fx = Fetcher(args.delay)

    tests: list[dict]
    idx_file = CACHE / "index" / "tests.json"
    if args.only and not args.category:
        tests = json.loads(idx_file.read_text(encoding="utf-8")) if idx_file.exists() and not args.refresh_index else []
        wanted = set(args.only)
        sel = [t for t in tests if t["slug"] in wanted or test_id_for(t["slug"]) in wanted]
        found = {t["slug"] for t in sel} | {test_id_for(t["slug"]) for t in sel}
        for w in wanted - found:  # construct URL directly
            slug = w
            m = re.match(r"cam(\d+)-(gt-)?reading-(\d+)$", w)
            if m:
                book = int(m.group(1))
                kind = "general-training" if m.group(2) else "academic"
                slug = f"cambridge-ielts-{book:02d}-{kind}-reading-test-{int(m.group(3))}" if book < 10 \
                    else f"cambridge-ielts-{book}-{kind}-reading-test-{int(m.group(3))}"
            sel.append({"url": BASE + slug + "/", "slug": slug, "title": None,
                        "category": "cambridge-general" if "general-training" in slug else
                        ("cambridge-academic" if slug.startswith("cambridge") else ""),
                        "category_label": None, "length": "full_test"})
        tests = sel
    else:
        tests = enumerate_tests(fx, args.refresh_index or not idx_file.exists(), args.category)
        if args.only:
            tests = [t for t in tests if t["slug"] in args.only or test_id_for(t["slug"]) in args.only]

    report_file = CACHE / "report.json"
    report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else {}
    done = 0
    for i, t in enumerate(tests, 1):
        tid = test_id_for(t["slug"])
        if t.get("category") in DERIVATIVE_CATEGORIES and not args.include_forecast:
            status = "skipped: forecast test (recombined from other tests)"
        elif t.get("length") and "full_test" not in t["length"]:
            status = f"skipped: not a full test ({t.get('length_label')})"
        else:
            try:
                tid, status = scrape_one(fx, t, args)
            except Exception as e:  # keep going
                status = f"FAILED error: {type(e).__name__}: {e}"
            done += 1
        log(f"[{i}/{len(tests)}] {tid}: {status}")
        report[tid] = {"status": status, "url": t["url"], "category": t.get("category")}
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        if args.limit and done >= args.limit:
            break
    from collections import Counter
    c = Counter(v["status"].split(":")[0] for k, v in report.items() if k in {test_id_for(t["slug"]) for t in tests})
    log("summary:", dict(c))


if __name__ == "__main__":
    main()
