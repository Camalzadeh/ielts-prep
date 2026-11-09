"""Draw the Task 1 visuals of the History essay prompts (this branch) as SVG, IELTS style.

Reads knowledge/data/writing_prompts.history.json; every Task 1 item with a "chart" gets
content/media/writing/history/<slug>.svg, and its "image" and "image_description" (the data, for the AI
marker) are filled in. Re-run after editing a chart: .venv\\Scripts\\python.exe tools\\history_charts.py

chart:  bar / line  {"x_label", "y_label", "categories": [...], "series": [{"name", "values": [...]}]}
        pie         {"categories": [...], "series": [{"name", "values": [... ~100]}]}
        table       {"columns": [...], "rows": [[...], ...]}
Line charts place years at their true distance when every category is a year.
"""
from __future__ import annotations

import json
import math
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "knowledge" / "data" / "writing_prompts.history.json"
OUT = ROOT / "content" / "media" / "writing" / "history"

W, H = 760, 460
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8b5cf6", "#d6407f"]
FONT = "font-family=\"Arial, Helvetica, sans-serif\""


def nice_max(v: float) -> tuple[float, float]:
    """A round axis maximum and step for values up to v."""
    if v <= 0:
        return 1, 0.2
    raw = v / 5
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return step * math.ceil(v / step), step


def fmt(v: float) -> str:
    return f"{v:,.1f}".rstrip("0").rstrip(".") if isinstance(v, float) and v != int(v) else f"{int(v):,}"


def wrap(text: str, width: int) -> list[str]:
    """Break a long axis label into lines of about `width` characters."""
    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines or [""]


def frame(title: str, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
            f'<rect width="{W}" height="{H}" fill="#fff"/>'
            f'<text x="{W / 2}" y="30" text-anchor="middle" {FONT} font-size="17" font-weight="bold" fill="#17181a">{escape(title)}</text>'
            f"{body}</svg>")


def legend(series: list[dict], y: float) -> str:
    out, x = [], 0.0
    items = [(s["name"], COLORS[i % len(COLORS)]) for i, s in enumerate(series)]
    total = sum(22 + 8 * len(n) + 26 for n, _ in items)
    x = (W - total) / 2
    for name, color in items:
        out.append(f'<rect x="{x:.1f}" y="{y - 10}" width="14" height="14" fill="{color}"/>'
                   f'<text x="{x + 20:.1f}" y="{y + 2}" {FONT} font-size="13" fill="#333">{escape(name)}</text>')
        x += 22 + 8 * len(name) + 26
    return "".join(out)


def axes(c: dict, vmax: float, step: float, left: float, top: float, pw: float, ph: float) -> str:
    out = []
    v = 0.0
    while v <= vmax + 1e-9:
        y = top + ph - ph * v / vmax
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + pw}" y2="{y:.1f}" stroke="#e3e5e0"/>'
                   f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" {FONT} font-size="12" fill="#555">{fmt(v)}</text>')
        v += step
    out.append(f'<line x1="{left}" y1="{top + ph}" x2="{left + pw}" y2="{top + ph}" stroke="#555"/>'
               f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + ph}" stroke="#555"/>')
    out.append(f'<text x="{left + pw / 2}" y="{H - 50}" text-anchor="middle" {FONT} font-size="13" fill="#333">{escape(c.get("x_label", ""))}</text>')
    out.append(f'<text transform="translate(22 {top + ph / 2}) rotate(-90)" text-anchor="middle" {FONT} font-size="13" fill="#333">{escape(c.get("y_label", ""))}</text>')
    return "".join(out)


def bar(title: str, c: dict) -> str:
    cats, series = c["categories"], c["series"]
    vmax, step = nice_max(max(v for s in series for v in s["values"]))
    left, top, pw, ph = 80, 60, W - 120, H - 170
    out = [axes(c, vmax, step, left, top, pw, ph)]
    group = pw / len(cats)
    bw = min(56, group * 0.7 / len(series))
    for i, cat in enumerate(cats):
        x0 = left + group * i + (group - bw * len(series)) / 2
        for k, s in enumerate(series):
            v = s["values"][i]
            bh = ph * v / vmax
            x = x0 + k * bw
            out.append(f'<rect x="{x:.1f}" y="{top + ph - bh:.1f}" width="{bw - 4:.1f}" height="{bh:.1f}" fill="{COLORS[k % len(COLORS)]}"/>'
                       f'<text x="{x + (bw - 4) / 2:.1f}" y="{top + ph - bh - 6:.1f}" text-anchor="middle" {FONT} font-size="12" fill="#333">{fmt(v)}</text>')
        cx = left + group * i + group / 2
        lines = wrap(str(cat), max(8, int(group / 7.5)))
        out.append(f'<text x="{cx:.1f}" y="{top + ph + 20}" text-anchor="middle" {FONT} font-size="13" fill="#333">'
                   + "".join(f'<tspan x="{cx:.1f}" dy="{0 if k == 0 else 15}">{escape(t)}</tspan>' for k, t in enumerate(lines))
                   + "</text>")
    if len(series) > 1:
        out.append(legend(series, H - 22))
    return frame(title, "".join(out))


def line(title: str, c: dict) -> str:
    cats, series = c["categories"], c["series"]
    vmax, step = nice_max(max(v for s in series for v in s["values"]))
    left, top, pw, ph = 90, 60, W - 140, H - 170
    out = [axes(c, vmax, step, left, top, pw, ph)]
    years = [int(x) for x in cats] if all(re.fullmatch(r"\d{4}", str(x)) for x in cats) else None
    if years and years[-1] > years[0]:
        xs = [left + pw * (y - years[0]) / (years[-1] - years[0]) for y in years]
    else:
        xs = [left + pw * i / max(1, len(cats) - 1) for i in range(len(cats))]
    for x, cat in zip(xs, cats):
        out.append(f'<line x1="{x:.1f}" y1="{top + ph}" x2="{x:.1f}" y2="{top + ph + 5}" stroke="#555"/>'
                   f'<text x="{x:.1f}" y="{top + ph + 20}" text-anchor="middle" {FONT} font-size="13" fill="#333">{escape(str(cat))}</text>')
    for k, s in enumerate(series):
        color = COLORS[k % len(COLORS)]
        pts = [(x, top + ph - ph * v / vmax) for x, v in zip(xs, s["values"])]
        out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="{color}" stroke-width="3"/>')
        for (x, y), v in zip(pts, s["values"]):
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{color}"/>'
                       f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" {FONT} font-size="12" fill="#333">{fmt(v)}</text>')
    if len(series) > 1:
        out.append(legend(series, H - 22))
    return frame(title, "".join(out))


def pie(title: str, c: dict) -> str:
    cats, vals = c["categories"], c["series"][0]["values"]
    total = sum(vals) or 1
    cx, cy, r = 250, H / 2 + 15, 150
    out, a = [], -math.pi / 2
    for i, (cat, v) in enumerate(zip(cats, vals)):
        b = a + 2 * math.pi * v / total
        large = 1 if b - a > math.pi else 0
        x1, y1, x2, y2 = cx + r * math.cos(a), cy + r * math.sin(a), cx + r * math.cos(b), cy + r * math.sin(b)
        out.append(f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f} Z" fill="{COLORS[i % len(COLORS)]}" stroke="#fff" stroke-width="2"/>')
        m = (a + b) / 2
        out.append(f'<text x="{cx + r * 0.62 * math.cos(m):.1f}" y="{cy + r * 0.62 * math.sin(m) + 5:.1f}" text-anchor="middle" {FONT} font-size="14" font-weight="bold" fill="#fff">{fmt(v)}%</text>')
        out.append(f'<rect x="460" y="{120 + 30 * i}" width="16" height="16" fill="{COLORS[i % len(COLORS)]}"/>'
                   f'<text x="484" y="{133 + 30 * i}" {FONT} font-size="14" fill="#333">{escape(str(cat))}</text>')
        a = b
    return frame(title, "".join(out))


def table(title: str, c: dict) -> str:
    cols, rows = c["columns"], c["rows"]
    left, top = 40, 60
    cw = (W - 2 * left) / len(cols)
    rh = min(44, (H - top - 30) / (len(rows) + 1))
    out = [f'<rect x="{left}" y="{top}" width="{W - 2 * left}" height="{rh}" fill="#eef0ec"/>']
    for r, row in enumerate([cols] + rows):
        y = top + r * rh
        for k, cell in enumerate(row):
            out.append(f'<text x="{left + cw * k + 10:.1f}" y="{y + rh / 2 + 5:.1f}" {FONT} font-size="13" '
                       f'{"font-weight=\"bold\" " if r == 0 else ""}fill="#17181a">{escape(str(cell))}</text>')
        out.append(f'<line x1="{left}" y1="{y + rh:.1f}" x2="{W - left}" y2="{y + rh:.1f}" stroke="#cfd2cb"/>')
    out.append(f'<rect x="{left}" y="{top}" width="{W - 2 * left}" height="{rh * (len(rows) + 1):.1f}" fill="none" stroke="#999"/>')
    return frame(title, "".join(out))


def describe(item: dict) -> str:
    """The chart's data in words, for the AI marker (it cannot see the image)."""
    c, kind = item["chart"], item.get("essay_type")
    if kind == "table":
        return f"Table '{item['title']}'. Columns: {', '.join(map(str, c['columns']))}. Rows: " + "; ".join(
            ", ".join(map(str, r)) for r in c["rows"]) + "."
    unit = c.get("y_label", "")
    parts = [f"{s['name']}: " + ", ".join(f"{cat} {fmt(v)}" for cat, v in zip(c["categories"], s["values"])) for s in c["series"]]
    return f"{kind.capitalize()} chart '{item['title']}'{f' ({unit})' if unit else ''}. " + "; ".join(parts) + "."


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def main() -> None:
    items = json.loads(DATA.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    draw = {"bar": bar, "line": line, "pie": pie, "table": table}
    n = 0
    for it in items:
        if it.get("task") != 1 or not it.get("chart"):
            continue
        name = f"{(it.get('tags') or '').split(',')[-1].lower()}-{slug(it['title'])}.svg"
        (OUT / name).write_text(draw[it["essay_type"]](it["title"], it["chart"]), encoding="utf-8")
        it["image"] = f"media/writing/history/{name}"
        it["image_description"] = describe(it)
        n += 1
    DATA.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{n} charts drawn into {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
