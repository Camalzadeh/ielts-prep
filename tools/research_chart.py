"""Draw an IELTS Task 1 chart (SVG, no dependencies) for an AI Research lesson.

    .venv/Scripts/python.exe tools/research_chart.py spec.json content/media/writing/research/<name>.svg

spec.json:
  {"type": "bar" | "line", "title": "...", "y_label": "...", "x_label": "...",
   "categories": ["2019", "2020", ...],                       # x axis (bar groups / line points)
   "series": [{"name": "English-German", "values": [24.6, ...]}, ...],
   "y_min": 0, "y_max": 50, "y_step": 10,                    # optional; derived from the data otherwise
   "decimals": 1, "show_values": true}                        # optional: bar labels (26 -> "26.0")

Plain black-and-grey style like the charts in the exam; values may be null (gap / no bar).
"""
from __future__ import annotations

import json
import math
import sys
from html import escape
from pathlib import Path

W, H = 760, 460
L, R, T, B = 78, 24, 64, 96          # plot margins
FILLS = ["#2b2b2b", "#8c8c8c", "#cfcfcf", "#5a5a5a", "#b0b0b0"]
DASH = ["", "6 4", "2 3", "10 3 2 3", "1 0"]
MARK = ["circle", "square", "triangle", "diamond", "circle"]


def _nice_step(span: float) -> float:
    raw = span / 6 or 1
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)


def _fmt(v: float) -> str:
    return f"{v:g}"


def _marker(kind: str, x: float, y: float, color: str) -> str:
    if kind == "square":
        return f'<rect x="{x-4:.1f}" y="{y-4:.1f}" width="8" height="8" fill="{color}"/>'
    if kind == "triangle":
        return f'<polygon points="{x:.1f},{y-5:.1f} {x+5:.1f},{y+4:.1f} {x-5:.1f},{y+4:.1f}" fill="{color}"/>'
    if kind == "diamond":
        return f'<polygon points="{x:.1f},{y-5:.1f} {x+5:.1f},{y:.1f} {x:.1f},{y+5:.1f} {x-5:.1f},{y:.1f}" fill="{color}"/>'
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"/>'


def render(spec: dict) -> str:
    cats, series = spec["categories"], spec["series"]
    vals = [v for s in series for v in s["values"] if v is not None]
    y_min = spec.get("y_min", 0 if min(vals) >= 0 else math.floor(min(vals)))
    step = spec.get("y_step") or _nice_step(max(vals) - y_min)
    y_max = spec.get("y_max") or math.ceil(max(vals) / step) * step
    pw, ph = W - L - R, H - T - B
    y = lambda v: T + ph - (v - y_min) / (y_max - y_min) * ph
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           'font-family="Arial, Helvetica, sans-serif" font-size="13">',
           f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
           f'<text x="{W/2}" y="30" text-anchor="middle" font-size="16" font-weight="bold">{escape(spec.get("title", ""))}</text>']
    v = y_min
    while v <= y_max + 1e-9:   # grid + y ticks
        out.append(f'<line x1="{L}" x2="{W-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e3e3e3"/>'
                   f'<text x="{L-8}" y="{y(v)+4:.1f}" text-anchor="end">{_fmt(round(v, 6))}</text>')
        v += step
    out.append(f'<line x1="{L}" x2="{L}" y1="{T}" y2="{T+ph}" stroke="#000"/>'
               f'<line x1="{L}" x2="{W-R}" y1="{T+ph}" y2="{T+ph}" stroke="#000"/>')
    if spec.get("y_label"):
        out.append(f'<text transform="translate(20 {T+ph/2}) rotate(-90)" text-anchor="middle">{escape(spec["y_label"])}</text>')
    gw = pw / len(cats)
    for i, c in enumerate(cats):   # x labels
        out.append(f'<text x="{L+gw*(i+.5):.1f}" y="{T+ph+20}" text-anchor="middle">{escape(str(c))}</text>')
    if spec.get("x_label"):
        out.append(f'<text x="{L+pw/2}" y="{T+ph+44}" text-anchor="middle">{escape(spec["x_label"])}</text>')
    if spec.get("type", "bar") == "bar":
        bw = gw * 0.78 / len(series)
        for si, s in enumerate(series):
            for i, val in enumerate(s["values"]):
                if val is None:
                    continue
                x = L + gw * i + gw * 0.11 + bw * si
                out.append(f'<rect x="{x:.1f}" y="{y(val):.1f}" width="{bw-2:.1f}" height="{y(y_min)-y(val):.1f}" '
                           f'fill="{FILLS[si % 5]}" stroke="#000" stroke-width=".6"/>')
                if spec.get("show_values", True):
                    out.append(f'<text x="{x+(bw-2)/2:.1f}" y="{y(val)-5:.1f}" text-anchor="middle" font-size="11">{_fmt(val) if spec.get("decimals") is None else f"{val:.{spec['decimals']}f}"}</text>')
    else:
        for si, s in enumerate(series):
            pts = [(L + gw * (i + .5), y(val)) for i, val in enumerate(s["values"]) if val is not None]
            color = "#000" if si % 2 == 0 else "#555"
            out.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="{DASH[si % 5]}" '
                       f'points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}"/>')
            out += [_marker(MARK[si % 5], a, b, color) for a, b in pts]
    lx = L   # legend
    for si, s in enumerate(series):
        ly = H - 22
        if spec.get("type", "bar") == "bar":
            out.append(f'<rect x="{lx}" y="{ly-11}" width="14" height="14" fill="{FILLS[si % 5]}" stroke="#000" stroke-width=".6"/>')
        else:
            color = "#000" if si % 2 == 0 else "#555"
            out.append(f'<line x1="{lx}" x2="{lx+22}" y1="{ly-4}" y2="{ly-4}" stroke="{color}" stroke-width="2" '
                       f'stroke-dasharray="{DASH[si % 5]}"/>' + _marker(MARK[si % 5], lx + 11, ly - 4, color))
        out.append(f'<text x="{lx+28}" y="{ly}">{escape(s["name"])}</text>')
        lx += 40 + 7.5 * len(s["name"])
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    Path(sys.argv[2]).parent.mkdir(parents=True, exist_ok=True)
    Path(sys.argv[2]).write_text(render(spec), encoding="utf-8")
    print("wrote", sys.argv[2])
