"""Scrape IELTS listening tests from engnovate.com into content/tests/listening/<id>.json.

For the user's personal offline study. Output schema: ARCHITECTURE.md section 1.

How it works
------------
* Enumerates https://engnovate.com/ielts-listening-tests/?category_type=<cat>&paged_full=<n>
  for every category and keeps "full" 4-part / 40-question tests.
* Each test page contains the question widgets, 4 transcripts and 4 audio sources.
* Answer keys (+ transcript excerpts and AI explanations) come from the page's own grading
  endpoint: POST wp-admin/admin-ajax.php action=process_ielts_listening_test with an empty
  answer set returns `results[]` (one per question, in order 1..40) with `correct_answer`.
* Premium tests are skipped: hidden input is_premium=1, or a "locked" submit button (answer
  checking is a paid feature - true for every non-Cambridge series at the time of writing).
* Cambridge General Training listening tests are the same recordings as the Academic ones;
  duplicates (same part-1 audio URL) are skipped.
* Audio: downloaded for Cambridge tests by default (--audio-scope all for everything) and
  re-encoded with ffmpeg to mono MP3 (--bitrate 64k, 'none' keeps the original ~128k file).
  Tests without local audio keep `audio: null` + `audio_remote`.
* Group extras beyond ARCHITECTURE.md: `audio_start_sec` (engnovate "Listen from here" offset
  within the part audio); test-level `question_count` when an old Cambridge test has 41-43 items.

Usage
-----
  .venv\\Scripts\\python.exe tools\\scrape_engnovate_listening.py            # everything free
  ... --only cam11-listening-1     # one test (id or engnovate slug)
  ... --category cambridge-academic --limit 3
  ... --force                      # rebuild JSON even if it exists
  ... --no-audio                   # skip mp3 downloads
  ... --list                       # just enumerate and print the index

Raw HTML / ajax responses are cached under content/_cache/engnovate/ (delete to refresh).
"""
from __future__ import annotations

import argparse
import copy
import html as htmlmod
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
OUT_DIR = CONTENT / "tests" / "listening"
MEDIA_DIR = CONTENT / "media" / "listening"
CACHE = CONTENT / "_cache" / "engnovate"

BASE = "https://engnovate.com"
INDEX_URL = BASE + "/ielts-listening-tests/"
AJAX_URL = BASE + "/wp-admin/admin-ajax.php"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# categories that are not full IELTS tests
SKIP_CATEGORIES = {"all", "basic-ielts-listening"}


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------
class Fetcher:
    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.last = 0.0
        self.client = httpx.Client(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                                   follow_redirects=True, timeout=httpx.Timeout(60, connect=20))

    def _wait(self):
        dt = time.time() - self.last
        if dt < self.delay:
            time.sleep(self.delay - dt)
        self.last = time.time()

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        err = None
        for attempt in range(6):
            self._wait()
            try:
                r = self.client.request(method, url, **kw)
                if r.status_code in (429, 500, 502, 503, 504, 520, 522, 524):
                    raise httpx.HTTPStatusError(f"status {r.status_code}", request=r.request, response=r)
                return r
            except (httpx.HTTPError, OSError) as e:
                err = e
                back = min(60, 2 ** attempt * 2)
                log(f"    ! {method} {url} failed ({e}); retry in {back}s")
                time.sleep(back)
        raise RuntimeError(f"giving up on {url}: {err}")

    def get_text(self, url: str, cache_file: Path | None = None, refresh: bool = False) -> str:
        if cache_file and cache_file.exists() and not refresh:
            return cache_file.read_text(encoding="utf-8")
        r = self.request("GET", url)
        r.raise_for_status()
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(r.text, encoding="utf-8")
        return r.text

    def download(self, urls: list[str], dest: Path) -> str | None:
        """Download first working url to dest (atomic). Returns url used or None."""
        if dest.exists() and dest.stat().st_size > 0:
            return "cached"
        dest.parent.mkdir(parents=True, exist_ok=True)
        for url in urls:
            if not url:
                continue
            tmp = dest.with_suffix(dest.suffix + ".part")
            for attempt in range(4):
                self._wait()
                try:
                    with self.client.stream("GET", url) as r:
                        if r.status_code != 200:
                            raise httpx.HTTPStatusError(f"status {r.status_code}", request=r.request, response=r)
                        with open(tmp, "wb") as f:
                            for chunk in r.iter_bytes(1 << 16):
                                f.write(chunk)
                    if tmp.stat().st_size < 1000:
                        raise IOError("file too small")
                    os.replace(tmp, dest)
                    return url
                except Exception as e:  # noqa: BLE001
                    log(f"    ! download {url} failed ({e})")
                    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (403, 404):
                        break
                    time.sleep(min(30, 2 ** attempt * 2))
            if tmp.exists():
                tmp.unlink()
        return None


# --------------------------------------------------------------------------------------
# Enumeration
# --------------------------------------------------------------------------------------
def slug_of(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


def enumerate_tests(fx: Fetcher, refresh: bool = False, only_cats: list[str] | None = None) -> list[dict]:
    idx_file = CACHE / "listening_index.json"
    if idx_file.exists() and not refresh and not only_cats:
        return json.loads(idx_file.read_text(encoding="utf-8"))
    html = fx.get_text(INDEX_URL, CACHE / "index" / "root.html", refresh=refresh)
    soup = BeautifulSoup(html, "lxml")
    cats = []
    for a in soup.select('a[href*="category_type="]'):
        m = re.search(r"category_type=([a-z0-9-]+)$", a["href"])
        if m and m.group(1) not in SKIP_CATEGORIES and m.group(1) not in cats:
            cats.append(m.group(1))
    if only_cats:
        cats = [c for c in cats if c in only_cats]
    tests: dict[str, dict] = {}
    for cat in cats:
        page = 1
        while True:
            url = f"{INDEX_URL}?category_type={cat}&paged_full={page}"
            h = fx.get_text(url, CACHE / "index" / f"{cat}-{page}.html", refresh=refresh)
            s = BeautifulSoup(h, "lxml")
            box = s.select_one(f"#ielts_listening_test_filter_results_{cat}") or s
            new = 0
            for art in box.select("article"):
                a = art.select_one("h2 a")
                if not a:
                    continue
                url_t = a["href"]
                slug = slug_of(url_t)
                kind = art.select_one(".ielts-listening-test-length-type span")
                btn = art.select_one("[data-parts]")
                parts = json.loads(btn["data-parts"]) if btn else []
                sections = json.loads(btn["data-sections"]) if btn and btn.get("data-sections") else []
                if slug in tests:
                    continue
                new += 1
                tests[slug] = {
                    "slug": slug, "url": url_t, "title": a.get_text(" ", strip=True), "category": cat,
                    "length": kind["class"][0] if kind and kind.get("class") else None,
                    "parts": parts, "sections": sections,
                }
            log(f"  index {cat} p{page}: +{new}")
            if new == 0:
                break
            page += 1
            if page > 40:
                break
    out = list(tests.values())
    if not only_cats:
        idx_file.parent.mkdir(parents=True, exist_ok=True)
        idx_file.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def page_cache(slug: str) -> Path:
    return CACHE / "pages" / f"{slug}.html"


def fetch_page(fx: Fetcher, entry: dict, refresh: bool = False) -> str:
    return fx.get_text(entry["url"], page_cache(entry["slug"]), refresh=refresh)


def cached_answers_file(slug: str) -> Path:
    return CACHE / "answers" / f"{slug}.json"


def fetch_answers(fx: Fetcher, entry: dict, refresh: bool = False) -> dict:
    """Submit an empty answer sheet to the page's grading endpoint -> results with keys."""
    cf = cached_answers_file(entry["slug"])
    if cf.exists() and not refresh:
        return json.loads(cf.read_text(encoding="utf-8"))
    # fresh page (nonce + cookies), also refreshes the HTML cache
    html = fx.get_text(entry["url"], page_cache(entry["slug"]), refresh=True)
    soup = BeautifulSoup(html, "lxml")
    form = soup.find(id="ielts-listening-test-form")
    if form is None:
        raise RuntimeError("test form not found")
    data: dict[str, str] = {}
    for el in form.find_all(["input", "select", "textarea"]):
        name = el.get("name")
        if not name or name in data:
            continue
        if el.name == "input" and el.get("type") in ("radio", "checkbox"):
            data[name] = ""
        elif el.name == "input":
            data[name] = el.get("value", "")
        else:
            data[name] = ""
    data.update({"action": "process_ielts_listening_test", "time_taken_seconds": "1800",
                 "save_learner_progress": "0"})
    r = fx.request("POST", AJAX_URL, data=data,
                   headers={"Referer": entry["url"], "X-Requested-With": "XMLHttpRequest",
                            "Origin": BASE})
    r.raise_for_status()
    js = r.json()
    if not js.get("success"):
        raise RuntimeError(f"ajax refused: {str(js)[:200]}")
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    return js


# --------------------------------------------------------------------------------------
# HTML helpers
# --------------------------------------------------------------------------------------
KEEP_ATTRS = {"img": {"src", "alt", "width", "height"}, "td": {"colspan", "rowspan"},
              "th": {"colspan", "rowspan"}, "ol": {"start", "type"}, "a": set()}
DROP_TAGS = {"script", "style", "button", "noscript", "iframe", "form", "input", "select", "label",
             "textarea", "svg"}
UNWRAP_TAGS = {"span", "font", "a", "mark", "section", "article", "center", "u_"}
VOID_OK = {"img", "br", "hr"}


def has_class(el, cls: str) -> bool:
    return isinstance(el, Tag) and cls in (el.get("class") or [])


def text_of(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True) if isinstance(el, Tag) else str(el)).strip()


def clean_fragment(nodes) -> str:
    """Return cleaned HTML for a list of nodes (deep-copied)."""
    wrapper = BeautifulSoup("<div></div>", "lxml").div
    for n in nodes:
        if getattr(n, "decomposed", False):
            continue
        wrapper.append(copy.copy(n))
    for el in list(wrapper.find_all(list(DROP_TAGS))):
        el.decompose()
    for el in list(wrapper.find_all("i")):  # font-awesome icons, keep real italics
        if any(c.startswith("fa") for c in (el.get("class") or [])) and not el.get_text(strip=True):
            el.decompose()
    for el in list(wrapper.find_all(True)):
        if el.name in UNWRAP_TAGS:
            el.unwrap()
            continue
        keep = KEEP_ATTRS.get(el.name, set())
        el.attrs = {k: v for k, v in el.attrs.items() if k in keep}
    # nested <strong><strong> -> single
    for el in list(wrapper.find_all(["strong", "b", "em"])):
        kids = [c for c in el.contents if not (isinstance(c, NavigableString) and not c.strip())]
        if len(kids) == 1 and isinstance(kids[0], Tag) and kids[0].name == el.name:
            kids[0].unwrap()
    # drop empty block elements (repeat for nesting)
    for _ in range(3):
        for el in list(wrapper.find_all(["p", "div", "li", "ul", "ol", "strong", "em", "b", "h3", "h4"])):
            if not el.get_text(strip=True) and not el.find(["img", "br", "table"]) and "{{" not in el.get_text():
                el.decompose()
    out = "".join(str(c) for c in wrapper.contents)
    out = out.replace("\xa0", " ")
    out = re.sub(r"[ \t\r\f\v]+", " ", out)
    out = re.sub(r"\s*\n\s*", "\n", out).strip()
    return out


INSTR_RE = re.compile(
    r"^(complete|write|choose|answer|label|which|what|match|list|select|circle|fill|look\b|use\b|"
    r"you (will|should|must)|for each|questions?\b|tick|classify|identify|where|who\b|when\b|how\b|"
    r"according|name\b|give|decide|do the|listen|in which|in what|click|now\b|drag|note\b|NB\b|N\.B)", re.I)
INSTR_HINT_RE = re.compile(r"NO MORE THAN|ONE WORD|TWO WORDS|THREE WORDS|A NUMBER|correct letter|"
                           r"letters?\s*,?\s*[A-Z]\s*[-–]\s*[A-Z]|from the box|next to question", re.I)


def is_instruction(el) -> bool:
    if not isinstance(el, Tag) or el.name not in ("p", "div", "h3", "h4", "h5", "h6"):
        return False
    if el.find(class_="ielts-listening-question-number") or el.find(["img", "table", "ul", "ol"]):
        return False
    t = text_of(el)
    if not t:
        return True  # empty spacer
    if INSTR_HINT_RE.search(t):
        return True
    if INSTR_RE.match(t):
        # a bold-only heading such as "Looking for Asian honey bees" is a title, not an instruction
        if re.match(r"^(complete|choose|label|answer|write|match|circle)\b.*\b(below|letters?|answers?|questions?|words?)\b", t, re.I):
            return True
        bold = " ".join(text_of(b) for b in el.find_all(["strong", "b"]) if not b.find_parent(["strong", "b"]))
        if bold and len(bold) >= len(t) - 2:
            return False
        if has_class(el, "ielts-listening-transcript-subhead"):
            return False
        return True
    return False


def hms_to_sec(s: str | None) -> int | None:
    if not s:
        return None
    try:
        parts = [int(x) for x in s.strip().split(":")]
    except ValueError:
        return None
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


# --------------------------------------------------------------------------------------
# Answers
# --------------------------------------------------------------------------------------
def split_text_answer(raw: str) -> list[str]:
    s = htmlmod.unescape(raw or "").replace("\xa0", " ").strip()
    s = re.sub(r"<[^>]+>", "", s)
    parts = []
    for chunk in re.split(r"\s+/\s+|\s+OR\s+|\s*;\s*", s) if s else []:
        parts.extend(re.split(r"(?<=[^\d\s])/(?=[^\d\s])", chunk))
    out: list[str] = []
    for p in parts:
        p = p.strip().strip(",").strip()
        if not p:
            continue
        if "(" in p and ")" in p:
            full = re.sub(r"\s+", " ", re.sub(r"[()]", "", p)).strip()
            short = re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", p)).strip()
            for v in (full, short):
                if v and v not in out:
                    out.append(v)
        elif p not in out:
            out.append(p)
    return out


def split_letter_answer(raw: str, keys=None) -> list[str]:
    s = htmlmod.unescape(raw or "").strip()
    if keys and any(len(k) > 1 for k in keys):
        toks = [t.strip(" .") for t in re.split(r"\s*(?:/|,|&|;|\band\b|\bor\b|\bOR\b)\s*|\s+", s)]
        hit = [t for t in toks if t in keys] or [t.upper() for t in toks if t.upper() in keys]
        if hit:
            return list(dict.fromkeys(hit))
    s = s.upper()
    letters = re.findall(r"(?<![A-Z])([A-Z])(?![A-Z])", s)
    out = []
    for l in letters:
        if l not in out:
            out.append(l)
    return out


def explanation_html(res: dict) -> str | None:
    bits = []
    exc = (res.get("explanation") or "").strip()
    if exc:
        lines = [htmlmod.escape(l.strip()) for l in exc.split("\n") if l.strip()]
        bits.append("<p><b>From the transcript:</b> " + " … ".join(f"“{l}”" for l in lines) + "</p>")
    det = (res.get("detailed_explanation") or "").strip()
    if det:
        bits.append("<p><i>(engnovate's auto-generated explanation — may not be entirely accurate)</i></p>")
        for line in det.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.endswith(":") and len(line) < 60:
                bits.append(f"<p><b>{htmlmod.escape(line)}</b></p>")
            else:
                bits.append(f"<p>{htmlmod.escape(line)}</p>")
    return "".join(bits) or None


# --------------------------------------------------------------------------------------
# Page parsing
# --------------------------------------------------------------------------------------
TYPE_MAP = {
    "note_completion": "note_completion", "form_completion": "form_completion",
    "table_completion": "table_completion", "flow_chart_completion": "flowchart_completion",
    "flowchart_completion": "flowchart_completion", "summary_completion": "summary_completion",
    "sentence_completion": "sentence_completion", "short_answers": "short_answer",
    "short_answer": "short_answer", "diagram_labeling": "diagram_labelling",
    "diagram_labelling": "diagram_labelling", "visual_labeling": "diagram_labelling",
    "map_labeling": "map_labelling", "map_labelling": "map_labelling",
    "plan_labeling": "plan_labelling", "plan_labelling": "plan_labelling",
    "one_choice": "mcq", "two_choices": "multi_select", "three_choices": "multi_select",
    "four_choices": "multi_select", "five_choices": "multi_select", "matching": "matching",
}
LABELLING = {"map_labelling", "plan_labelling", "diagram_labelling"}
LETTER_TYPES = {"mcq", "multi_select", "matching"} | LABELLING


def norm_type(s):
    if not s:
        return None
    k = re.sub(r"[^a-z]+", "_", s.lower()).strip("_")
    return TYPE_MAP.get(k)


def qnum(strong) -> int:
    return int(re.sub(r"\D", "", strong.get_text()))


def control_of(strong):
    """Classify the answer widget belonging to a question-number <strong>."""
    zone = strong.find_parent(class_="dnd-zone")
    if zone is not None:
        if zone.find_parent(class_="matching-dnd-questions") is not None:
            return "dnd_list", zone
        return "dnd_inline", zone
    item = strong.find_parent(class_="ielts-listening-question-item")
    if item is None:
        return "unknown", None
    if item.name == "tr" and item.find_parent("table", class_="ielts-listening-matching-table"):
        return "radio_table", item
    if item.find("input", {"type": "checkbox"}):
        return "checkbox", item
    if item.find("input", {"type": "radio"}):
        return "radio", item
    sel = item.find("select")
    if sel is not None:
        return "select", sel
    inp = item.find("input", {"type": "text"}) or item.find("textarea")
    if inp is not None:
        return "text", item
    return "unknown", item


class Ctx:
    def __init__(self, test_id: str):
        self.test_id = test_id
        self.images: list[tuple[str, str]] = []  # (remote_url, local_rel)

    def image_rel(self, src: str) -> str:
        name = os.path.basename(urlparse(src).path) or "image.png"
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
        rel = f"media/listening/{self.test_id}/{name}"
        if (src, rel) not in self.images:
            self.images.append((src, rel))
        return rel


def rewrite_imgs(nodes, ctx: Ctx):
    for n in nodes:
        if not isinstance(n, Tag):
            continue
        imgs = [n] if n.name == "img" else n.find_all("img")
        for img in imgs:
            src = img.get("data-lazy-src") or img.get("data-src") or img.get("src") or ""
            if not src or src.startswith("data:"):
                img.decompose()
                continue
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = BASE + src
            img["src"] = ctx.image_rel(src)


def option_box_texts(nodes, keys) -> dict:
    """Find an options box like 'A  the river' / table rows 'A | text' in the given nodes."""
    found: dict = {}
    cands = []
    for n in nodes:
        if isinstance(n, Tag):
            cands.append(n)
            cands.extend(n.find_all(["li", "p", "tr", "div", "td"]))
    keys = [k for k in keys if k]
    if not keys:
        return found
    kalt = "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True))
    split_re = re.compile(r"(?<=\S)\s+(?=(?:%s)[.)]\s)|\s{3,}(?=(?:%s)\s)" % (kalt, kalt))
    item_re = re.compile(r"^(%s)(?:\s*[.):\-–]\s*|\s+)(\S.*)$" % kalt)
    for el in cands:
        if el.name == "tr":
            cells = [text_of(td) for td in el.find_all(["td", "th"])]
            cells = [c for c in cells if c]
            if len(cells) >= 2 and cells[0].rstrip(".)") in keys:
                found.setdefault(cells[0].rstrip(".)"), " ".join(cells[1:]))
            continue
        if el.find(["p", "li", "tr", "div", "br"]):
            # multi-line container: try line by line
            lines = re.split(r"\n+", el.get_text("\n"))
        else:
            lines = [el.get_text(" ")]
        pieces = []
        for line in lines:
            # several options on one line: "A. foo | B. bar" or "A foo     B bar"
            for chunk in re.split(r"\s*\|\s*", line):
                pieces.extend(split_re.split(chunk))
        for t in pieces:
            t = re.sub(r"\s+", " ", t).strip()
            m = item_re.match(t)
            if m and not re.fullmatch(r"(?:[A-Z]\s*)+", t):
                found.setdefault(m.group(1), m.group(2).strip())
    return found


def split_part_children(part_div) -> list:
    groups, cur = [], None
    for ch in part_div.children:
        if not isinstance(ch, Tag):
            continue
        if has_class(ch, "ielts-listening-question-section-heading"):
            cur = {"heading": text_of(ch), "start": None, "content": [], "questions": []}
            groups.append(cur)
        elif cur is None:
            continue
        elif has_class(ch, "ielts-listening-section-start-time-button"):
            cur["start"] = hms_to_sec(ch.get("data-start-time"))
        elif has_class(ch, "ielts-listening-question-section-content"):
            for c in list(ch.children):
                if has_class(c, "ielts-listening-section-content-wrapper"):
                    cur["content"].extend(list(c.children))
                else:
                    cur["content"].append(c)
        elif has_class(ch, "ielts-listening-questions"):
            cur["questions"].append(ch)
        else:
            cur["content"].append(ch)
    return groups


def _options_from_item(item):
    opts = []
    for o in item.select(".ielts-listening-option"):
        lab = o.select_one(".ielts-listening-option-letter")
        inp = o.find("input")
        key = text_of(lab) if lab else (inp.get("value", "") if inp else "")
        body = [c for c in o.children if not (isinstance(c, Tag) and c.name in ("label", "input"))]
        txt = text_of(BeautifulSoup("<div>" + clean_fragment(body) + "</div>", "lxml").div)
        opts.append({"key": key.strip(), "text": txt})
    for o in item.select(".ielts-listening-option"):
        o.decompose()
    return opts


def _pull_single_image(nodes):
    imgs = []
    for n in nodes:
        if isinstance(n, Tag):
            imgs.extend([n] if n.name == "img" else n.find_all("img"))
    if len(imgs) != 1:
        return None
    src = imgs[0]["src"]
    par = imgs[0].parent
    imgs[0].decompose()
    while isinstance(par, Tag) and par.name in ("p", "figure", "div", "a", "span") \
            and not par.get_text(strip=True) and not par.find(["img", "table"]):
        nxt = par.parent
        par.decompose()
        par = nxt
    return src


def build_group(g: dict, ctx: Ctx, qtypes: dict, warnings: list) -> list:
    content_nodes = [n for n in g["content"] if not (isinstance(n, NavigableString) and not n.strip())]
    q_nodes = g["questions"]
    strongs = []
    for n in content_nodes + q_nodes:
        if isinstance(n, Tag):
            strongs.extend(n.find_all(class_="ielts-listening-question-number"))
    if not strongs:
        warnings.append(f"group '{g['heading']}' has no questions")
        return []
    nums = [qnum(s) for s in strongs]
    kinds = [control_of(s) for s in strongs]
    kindset = {k for k, _ in kinds}
    eng_type = next((qtypes.get(n) for n in nums if qtypes.get(n)), None)
    gtype = norm_type(eng_type)

    # instructions = leading instruction-like paragraphs of the content block
    instr, rest = [], list(content_nodes)
    while rest and (isinstance(rest[0], NavigableString) or is_instruction(rest[0])):
        n = rest.pop(0)
        if isinstance(n, Tag):
            instr.append(n)
    rewrite_imgs(rest + q_nodes + instr, ctx)
    base = {"range": [min(nums), max(nums)], "type": gtype,
            "instructions_html": clean_fragment(instr) or None}
    if g.get("start") is not None:
        base["audio_start_sec"] = g["start"]

    # ---------------- gap-fill (text / select / inline drag&drop) ----------------
    if kindset <= {"text", "select", "dnd_inline"}:
        options = []
        for s, (kind, ctl) in zip(strongs, kinds):
            marker = NavigableString("{{%d}}" % qnum(s))
            if kind == "dnd_inline":
                ctl.replace_with(marker)
            elif kind == "select":
                if not options:
                    for o in ctl.find_all("option"):
                        v = (o.get("value") or "").strip()
                        if v and len(v) <= 4:
                            t = text_of(o)
                            options.append({"key": v, "text": "" if t == v else re.sub(r"^%s[.)]?\s*" % re.escape(v), "", t)})
                item = s.find_parent(class_="ielts-listening-question-item")
                s.replace_with(marker)
                ctl.decompose()
                if item is not None:
                    item.unwrap()
            elif ctl.name in ("div", "li", "p", "tr"):
                # question-list item "<n> <prompt> [input]" -> "<p><prompt> {{n}}</p>"
                s.decompose()
                inp = ctl.find(["input", "textarea"])
                inp.replace_with(marker)
                for el in ctl.find_all(["input", "textarea"]):
                    el.decompose()
                if ctl.name == "div":
                    ctl.name = "p"
            else:
                s.replace_with(marker)
                for el in ctl.find_all(["input", "textarea"]):
                    el.decompose()
                ctl.unwrap()
        for qn in rest + q_nodes:
            if not isinstance(qn, Tag) or getattr(qn, "decomposed", False):
                continue
            for card in ([qn] if has_class(qn, "dnd-card") else qn.select(".dnd-card")):
                k = card.get("data-value", "").strip()
                if k and k not in [o["key"] for o in options]:
                    options.append({"key": k, "text": text_of(card.select_one(".dnd-text") or card)})
            panels = [qn] if (has_class(qn, "dnd-panel") or has_class(qn, "options-dnd-panel"))                 else qn.select(".dnd-panel, .options-dnd-panel")
            for p in panels:
                p.decompose()
        if options and any(not o["text"] for o in options):
            box = option_box_texts(rest, [o["key"] for o in options])
            for o in options:
                o["text"] = o["text"] or box.get(o["key"], "")
        grp = dict(base)
        if grp["type"] is None or (options and grp["type"] in ("mcq", "multi_select")):
            grp["type"] = "matching" if options else "note_completion"
        image = _pull_single_image(rest + q_nodes) if grp["type"] in LABELLING else None
        q_children = [c for qn in q_nodes if not getattr(qn, "decomposed", False) for c in qn.children]
        html = (clean_fragment(rest) + "\n" + clean_fragment(q_children)).strip()
        grp["content_html"] = html
        if image:
            grp["image"] = image
        if options:
            grp["options"] = options
        grp["questions"] = [{"number": n, "prompt_html": "", "answer": [], "explanation_html": None}
                            for n in sorted(set(nums))]
        return [grp]

    # ---------------- single-answer MCQ ----------------
    if kindset == {"radio"}:
        qs, seen = [], set()
        for s, (kind, item) in zip(strongs, kinds):
            n = qnum(s)
            if n in seen:
                continue
            seen.add(n)
            opts = _options_from_item(item)
            s.decompose()
            qs.append({"number": n, "prompt_html": clean_fragment(list(item.children)).strip(), "options": opts,
                       "answer": [], "explanation_html": None})
        grp = dict(base)
        grp["type"] = "mcq"
        image = _pull_single_image(rest)
        html_c = clean_fragment(rest)
        if html_c:
            grp["content_html"] = html_c
        if image:
            grp["image"] = image
        grp["questions"] = qs
        return [grp]

    # ---------------- multi-select (choose TWO / THREE ...) ----------------
    if kindset == {"checkbox"}:
        items = []
        for s, (kind, item) in zip(strongs, kinds):
            if not items or items[-1][0] is not item:
                items.append((item, []))
            items[-1][1].append(qnum(s))
        html_c = clean_fragment(rest)
        out = []
        for idx, (item, ns) in enumerate(items):
            opts = _options_from_item(item)
            for s in item.find_all(class_="ielts-listening-question-number"):
                s.decompose()
            grp = dict(base)
            grp["range"] = [min(ns), max(ns)]
            grp["type"] = "multi_select"
            if idx > 0:
                grp.pop("audio_start_sec", None)
            if html_c and idx == 0:
                grp["content_html"] = html_c
            grp["options"] = opts
            prompt = clean_fragment(list(item.children)).strip()
            grp["questions"] = [{"number": n, "prompt_html": prompt, "answer": [], "explanation_html": None}
                                for n in ns]
            out.append(grp)
        return out

    # ---------------- matching (radio grid or drag&drop list) ----------------
    if kindset <= {"radio_table", "dnd_list"}:
        keys, card_text = [], {}
        for qn in rest + q_nodes:
            if not isinstance(qn, Tag):
                continue
            for t in qn.select("table.ielts-listening-matching-table thead th"):
                k = text_of(t)
                if k and k not in keys:
                    keys.append(k)
            for card in qn.select(".dnd-card"):
                k = card.get("data-value", "").strip()
                if k and k not in keys:
                    keys.append(k)
                card_text[k] = text_of(card.select_one(".dnd-text") or card)
        for qn in rest + q_nodes:
            if isinstance(qn, Tag) and not getattr(qn, "decomposed", False):
                panels = [qn] if (has_class(qn, "dnd-panel") or has_class(qn, "options-dnd-panel"))                     else qn.select(".dnd-panel, .options-dnd-panel")
                for p in panels:
                    p.decompose()
        box = option_box_texts(rest, keys) if len(card_text) < len(keys) else {}
        options = [{"key": k, "text": card_text.get(k) or box.get(k, "")} for k in keys]
        qs = []
        for s, (kind, ctl) in zip(strongs, kinds):
            n = qnum(s)
            if kind == "radio_table":
                cell = ctl.select_one(".ielts-listening-matching-question-cell") or ctl
                prompt_nodes = [c for c in cell.children if c is not s]
            else:
                item = ctl.find_parent(class_="ielts-listening-question-item")
                prompt_nodes = [c for c in item.children if c is not ctl]
            prompt = clean_fragment(prompt_nodes)
            prompt = re.sub(r"^\s*[•·●▪\-–]\s*", "", prompt).strip()
            qs.append({"number": n, "prompt_html": prompt, "answer": [], "explanation_html": None})
        grp = dict(base)
        has_img = any(isinstance(n, Tag) and (n.name == "img" or n.find("img")) for n in rest)
        if grp["type"] not in LABELLING:
            grp["type"] = "map_labelling" if (has_img and not card_text and not box) else "matching"
        image = _pull_single_image(rest) if grp["type"] in LABELLING else None
        html_c = clean_fragment(rest)
        if html_c:
            grp["content_html"] = html_c
        if image:
            grp["image"] = image
        grp["options"] = options
        grp["questions"] = qs
        return [grp]

    warnings.append(f"group '{g['heading']}' has unsupported widget mix {sorted(kindset)}")
    return []


# --------------------------------------------------------------------------------------
# Test assembly
# --------------------------------------------------------------------------------------
CAM_RE = re.compile(r"^cambridge-ielts-(\d+)-(academic|general-training)-listening-test-(\d+)$")


def identity(entry: dict) -> dict:
    slug = entry["slug"]
    module = "general" if ("general" in slug or entry.get("category", "").endswith("-general")) else "academic"
    m = CAM_RE.match(slug)
    if m:
        book, test = int(m.group(1)), int(m.group(3))
        tid = f"cam{book}-listening-{test}" if module == "academic" else f"cam{book}-gt-listening-{test}"
        return {"id": tid, "module": module, "series": f"Cambridge IELTS {book}", "book": book, "test_no": test}
    title = entry.get("title") or slug
    series = re.sub(r"\s*(Academic|General Training)?\s*Listening\s+Test\s*\d+.*$", "", title, flags=re.I).strip()
    if module == "general" and "general" not in series.lower():
        series += " (General Training)"
    return {"id": slug, "module": module, "series": series or title, "book": None, "test_no": None}


def audio_sources(soup) -> dict:
    out = {}
    auds = soup.select("audio.ielts-listening-test-audio") or soup.select("audio[id^=ielts-listening-test-audio]")
    for a in auds:
        m = re.search(r"(\d+)$", a.get("id", ""))
        n = int(m.group(1)) if m else len(out) + 1
        srcs = [s.get("src") for s in a.find_all("source") if s.get("src")]
        if a.get("src"):
            srcs.insert(0, a["src"])
        out[n] = srcs
    return out


def section_ids_by_number(form) -> dict:
    out = {}
    for s in form.select(".ielts-listening-question-number"):
        n = qnum(s)
        kind, ctl = control_of(s)
        scope = ctl if ctl is not None else s.parent
        inp = scope.find(["input", "select", "textarea"], attrs={"name": re.compile("ielts_listening_answer_")}) \
            if isinstance(scope, Tag) else None
        if inp is not None:
            m = re.match(r"ielts_listening_answer_(\d+)_", inp["name"])
            if m:
                out[n] = int(m.group(1))
    return out


def parse_test(html: str, entry: dict, answers_js: dict | None) -> tuple:
    """-> (test_dict, ctx, warnings, audio_sources)"""
    soup = BeautifulSoup(html, "lxml")
    ident = identity(entry)
    ctx = Ctx(ident["id"])
    warnings: list = []
    form = soup.find(id="ielts-listening-test-form")
    if form is None:
        raise RuntimeError("no test form on page")
    results = (answers_js or {}).get("data", {}).get("results") or []
    qtypes = {i + 1: r.get("type") for i, r in enumerate(results)}
    secmap = section_ids_by_number(form)
    for i, r in enumerate(results):
        n = i + 1
        if n in secmap and r.get("section_id") and int(r["section_id"]) != secmap[n]:
            warnings.append(f"Q{n}: answer section {r['section_id']} != page section {secmap[n]}")

    h1 = soup.find("h1")
    title = text_of(h1) if h1 else entry.get("title")
    if not title or len(title) > 150:
        title = entry.get("title")
    title = re.sub(r"\s*\((Online|Free)[^)]*\)\s*$", "", title, flags=re.I).strip()
    if ident["book"] is not None:
        title = (f"Cambridge IELTS {ident['book']} "
                 f"{'Academic' if ident['module'] == 'academic' else 'General Training'} "
                 f"Listening Test {ident['test_no']}")
    auds = audio_sources(soup)

    parts = []
    part_divs = form.select(".ielts-listening-question-section[data-part-number]")
    for pdiv in part_divs:
        pn = int(pdiv["data-part-number"])
        groups = []
        for g in split_part_children(pdiv):
            groups.extend(build_group(g, ctx, qtypes, warnings))
        tr = soup.find(id=f"ielts-listening-transcript-{pn}")
        transcript = clean_fragment(list(tr.children)) if tr is not None else None
        srcs = auds.get(pn) or []
        parts.append({
            "number": pn, "title": f"Part {pn}",
            "audio": f"media/listening/{ident['id']}/part{pn}.mp3" if srcs else None,
            "audio_remote": srcs[0] if srcs else None,
            "transcript_html": transcript or None,
            "groups": groups,
        })

    # ---- answers
    for p in parts:
        for grp in p["groups"]:
            lettered = grp["type"] in ("mcq", "multi_select", "matching") or bool(grp.get("options"))
            if grp["type"] == "multi_select":
                union = []
                for q in grp["questions"]:
                    r = results[q["number"] - 1] if 0 < q["number"] <= len(results) else {}
                    for l in split_letter_answer(r.get("correct_answer", "")):
                        if l not in union:
                            union.append(l)
                union.sort()
                for q in grp["questions"]:
                    r = results[q["number"] - 1] if 0 < q["number"] <= len(results) else {}
                    q["answer"] = list(union)
                    q["explanation_html"] = explanation_html(r) if r else None
                if len(union) != len(grp["questions"]):
                    warnings.append(f"multi_select {grp['range']}: answer set {union} vs {len(grp['questions'])} questions")
                continue
            if not lettered:
                raws = [(results[q["number"] - 1] if 0 < q["number"] <= len(results) else {}).get("correct_answer", "")
                        for q in grp["questions"]]
                if raws and all(re.fullmatch(r"\s*[A-J]\s*", x or "") for x in raws):
                    # letter answers in a completion group: options are defined in the instructions,
                    # e.g. "Write A if he says KEEP UNCHANGED" -> derive them
                    frag = BeautifulSoup("<div>" + (grp.get("instructions_html") or "") +
                                         (grp.get("content_html") or "") + "</div>", "lxml").div
                    opts = {}
                    for m in re.finditer(r"\bWrite\s+([A-J])\s+(?:if|for|when)\s+([^.\n<]+)", frag.get_text("\n")):
                        opts.setdefault(m.group(1), m.group(2).strip())
                    if not opts:
                        opts = option_box_texts([frag], list("ABCDEFGHIJ"))
                    if opts:
                        grp["options"] = [{"key": k, "text": opts[k]} for k in sorted(opts)]
                        lettered = True
                    else:
                        warnings.append(f"group {grp['range']}: letter answers but no options found")
            for q in grp["questions"]:
                r = results[q["number"] - 1] if 0 < q["number"] <= len(results) else {}
                raw = r.get("correct_answer", "")
                okeys = [o["key"] for o in (q.get("options") or grp.get("options") or [])]
                q["answer"] = split_letter_answer(raw, okeys) if lettered else split_text_answer(raw)
                q["explanation_html"] = explanation_html(r) if r else None
                if lettered:
                    keys = {o["key"] for o in (q.get("options") or grp.get("options") or [])}
                    if keys and not set(q["answer"]) <= keys:
                        warnings.append(f"Q{q['number']}: answer {q['answer']} not in options {sorted(keys)}")

    test = {
        "id": ident["id"], "type": "listening", "module": ident["module"], "title": title,
        "series": ident["series"], "book": ident["book"], "test_no": ident["test_no"],
        "source": "engnovate", "source_url": entry["url"], "duration_minutes": 30,
        "parts": parts,
    }
    nums = [q["number"] for p in parts for g in p["groups"] for q in g["questions"]]
    # Old Cambridge books (1-3) genuinely have 41-43 questions; anything else must be 1..40.
    total = max(40, len(results))
    if sorted(nums) != list(range(1, total + 1)):
        warnings.append(f"question numbers not 1..{total} (got {len(nums)}: missing {sorted(set(range(1, total + 1)) - set(nums))}, dupes {sorted({n for n in nums if nums.count(n) > 1})})")
    if len(results) < 40 or len(results) > 45:
        warnings.append(f"answer key has {len(results)} results")
    elif len(results) != 40:
        test["question_count"] = len(results)
    return test, ctx, warnings, auds


# --------------------------------------------------------------------------------------
# Media
# --------------------------------------------------------------------------------------
def find_ffmpeg() -> str | None:
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if base.exists():
        for c in base.glob("*FFmpeg*/**/bin/ffmpeg.exe"):
            return str(c)
    return None


def fetch_audio(fx: Fetcher, srcs: list, dest: Path, bitrate: str | None, ffmpeg: str | None) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    if not bitrate or not ffmpeg:
        return fx.download(srcs, dest) is not None
    import subprocess
    raw = CACHE / "audio_tmp" / (dest.parent.name + "-" + dest.name)
    if fx.download(srcs, raw) is None:
        return False
    tmp = dest.with_suffix(".tmp.mp3")
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(raw), "-vn", "-ac", "1", "-b:a", bitrate,
                        "-map_metadata", "-1", str(tmp)], capture_output=True, text=True)
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 1000:
        log(f"    ! ffmpeg failed ({r.stderr.strip()[:200]}); keeping original")
        if tmp.exists():
            tmp.unlink()
        os.replace(raw, dest)
        return True
    os.replace(tmp, dest)
    raw.unlink()
    return True


def ensure_media(fx: Fetcher, test: dict, images: list, auds: dict, want_audio: bool,
                 bitrate: str | None, ffmpeg: str | None) -> list:
    problems = []
    for src, rel in images:
        dest = CONTENT / rel
        if fx.download([src], dest) is None:
            problems.append(f"image failed: {src}")
    for p in test["parts"]:
        if not p.get("audio"):
            continue
        dest = CONTENT / p["audio"]
        if want_audio:
            if not fetch_audio(fx, auds.get(p["number"]) or [p["audio_remote"]], dest, bitrate, ffmpeg):
                problems.append(f"audio failed: part {p['number']}")
        if not dest.exists():
            # not downloaded: keep only the remote URL so the app can stream it
            p["audio"] = None
    return problems


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def order_key(e: dict):
    cat = e["category"]
    return (0 if cat == "cambridge-academic" else 1 if cat.endswith("-academic") else 2, cat, e["slug"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", help="test id or engnovate slug (repeatable)")
    ap.add_argument("--category", action="append", help="engnovate category_type (repeatable)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--force", action="store_true", help="rebuild JSON even if it exists")
    ap.add_argument("--refresh", action="store_true", help="ignore HTML/answer caches")
    ap.add_argument("--refresh-index", action="store_true")
    ap.add_argument("--no-audio", action="store_true", help="do not download audio")
    ap.add_argument("--audio-scope", choices=["cambridge", "all"], default="cambridge",
                    help="which tests get local audio (others keep audio_remote only). default: cambridge")
    ap.add_argument("--bitrate", default="64k",
                    help="re-encode audio to mono MP3 at this bitrate with ffmpeg ('none' = keep original)")
    ap.add_argument("--list", action="store_true", help="print the index and exit")
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args(argv)

    fx = Fetcher(delay=args.delay)
    entries = enumerate_tests(fx, refresh=args.refresh_index)
    entries = [e for e in entries if len(e.get("parts") or []) == 4 and e["slug"] != "custom"]
    if args.category:
        entries = [e for e in entries if e["category"] in args.category]
    if args.only:
        want = set(args.only)
        entries = [e for e in entries if e["slug"] in want or identity(e)["id"] in want]
    entries.sort(key=order_key)
    if args.list:
        for e in entries:
            print(f"{identity(e)['id']:55s} {e['category']:40s} {e['url']}")
        print(len(entries), "tests")
        return 0
    if args.limit:
        entries = entries[: args.limit]

    bitrate = None if args.bitrate.lower() == "none" else args.bitrate
    ffmpeg = find_ffmpeg() if bitrate else None
    if bitrate and not ffmpeg:
        log("ffmpeg not found - audio kept at original bitrate")

    report_file = CACHE / "listening_report.json"
    report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else {}
    seen_audio = {}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, e in enumerate(entries, 1):
        ident = identity(e)
        tid = ident["id"]
        log(f"[{i}/{len(entries)}] {tid}")
        try:
            html = fetch_page(fx, e, refresh=args.refresh)
            soup = BeautifulSoup(html, "lxml")
            prem = soup.find(id="is_premium")
            if soup.find(id="ielts-listening-test-form") is None:
                report[tid] = {"status": "skipped", "reason": "no test form", "url": e["url"]}
                continue
            sub = soup.find(id="ielts-listening-test-submit-button")
            if sub is not None and "locked" in (sub.get("class") or []):
                # answer checking is a paid feature for this test (submit opens the upgrade popup)
                report[tid] = {"status": "skipped", "reason": "premium (locked submit / answer key)", "url": e["url"]}
                log("    premium (locked) - skipped")
                continue
            if prem is not None and prem.get("value", "0") != "0":
                report[tid] = {"status": "skipped", "reason": "premium", "url": e["url"]}
                log("    premium - skipped")
                continue
            auds = audio_sources(soup)
            key = (auds.get(1) or [None])[0]
            if key and key in seen_audio and seen_audio[key] != tid:
                report[tid] = {"status": "skipped", "reason": f"duplicate of {seen_audio[key]}", "url": e["url"]}
                log(f"    duplicate of {seen_audio[key]} - skipped")
                continue
            if key:
                seen_audio[key] = tid
            out_file = OUT_DIR / f"{tid}.json"
            want_audio = not args.no_audio and (args.audio_scope == "all" or ident["book"] is not None)
            if out_file.exists() and not args.force:
                test = json.loads(out_file.read_text(encoding="utf-8"))
                # resume missing media only
                need = want_audio and any(p.get("audio_remote") and not (CONTENT / f"media/listening/{tid}/part{p['number']}.mp3").exists()
                                          for p in test["parts"])
                if need:
                    for p in test["parts"]:
                        if p.get("audio_remote"):
                            p["audio"] = f"media/listening/{tid}/part{p['number']}.mp3"
                    probs = ensure_media(fx, test, [], auds, want_audio, bitrate, ffmpeg)
                    out_file.write_text(json.dumps(test, ensure_ascii=False, indent=1), encoding="utf-8")
                    if probs:
                        log("    " + "; ".join(probs))
                report.setdefault(tid, {"status": "ok", "url": e["url"]})
                continue
            answers = fetch_answers(fx, e, refresh=args.refresh)
            html = page_cache(e["slug"]).read_text(encoding="utf-8")  # fetch_answers refreshed it
            test, ctx, warnings, auds = parse_test(html, e, answers)
            probs = ensure_media(fx, test, ctx.images, auds, want_audio, bitrate, ffmpeg)
            fatal = [w for w in warnings if w.startswith(("question numbers", "answer key"))]
            empty = [q["number"] for p in test["parts"] for g in p["groups"] for q in g["questions"] if not q["answer"]]
            if empty:
                fatal.append(f"empty answers for {empty}")
            for w in warnings + probs:
                log("    ! " + w)
            if fatal:
                report[tid] = {"status": "error", "reason": "; ".join(fatal), "warnings": warnings, "url": e["url"]}
                continue
            out_file.write_text(json.dumps(test, ensure_ascii=False, indent=1), encoding="utf-8")
            report[tid] = {"status": "ok", "warnings": warnings + probs, "url": e["url"]}
        except Exception as ex:  # noqa: BLE001
            log(f"    ERROR {type(ex).__name__}: {ex}")
            report[tid] = {"status": "error", "reason": f"{type(ex).__name__}: {ex}", "url": e["url"]}
        finally:
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    log("summary:", dict(Counter(v["status"] for v in report.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
