// Text highlighting stored as character offsets into a container's textContent.
import { h, icon } from '../ui.js';

function textNodes(root) {
  const out = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) out.push(n);
  return out;
}

/** Offset of (node, offset) within root's textContent. */
function absOffset(root, node, offset) {
  if (node.nodeType !== Node.TEXT_NODE) {
    // Convert element boundary to a text boundary.
    const r = document.createRange();
    r.setStart(root, 0);
    r.setEnd(node, offset);
    return r.toString().length;
  }
  let total = 0;
  for (const t of textNodes(root)) {
    if (t === node) return total + offset;
    total += t.data.length;
  }
  return total;
}

export function selectionOffsets(root) {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const r = sel.getRangeAt(0);
  if (!root.contains(r.commonAncestorContainer)) return null;
  const a = absOffset(root, r.startContainer, r.startOffset);
  const b = absOffset(root, r.endContainer, r.endOffset);
  if (b - a < 1) return null;
  return [Math.min(a, b), Math.max(a, b)];
}

/** Merge overlapping ranges. */
export function mergeRanges(ranges) {
  const s = ranges.filter((r) => Array.isArray(r) && r[1] > r[0]).map((r) => [r[0], r[1]]).sort((x, y) => x[0] - y[0]);
  const out = [];
  for (const r of s) {
    const last = out[out.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else out.push(r);
  }
  return out;
}

/** Wrap ranges in <mark class="hl">. Assumes the root currently has no marks. */
export function applyHighlights(root, ranges) {
  const merged = mergeRanges(ranges);
  merged.forEach((range, idx) => {
    const [start, end] = range;
    let pos = 0;
    for (const t of textNodes(root)) {
      const len = t.data.length;
      const tStart = pos, tEnd = pos + len;
      pos = tEnd;
      if (tEnd <= start || tStart >= end) continue;
      if (!t.data.trim() && t.parentNode && /^(TABLE|TBODY|TR|UL|OL)$/.test(t.parentNode.nodeName)) continue;
      const s = Math.max(0, start - tStart), e = Math.min(len, end - tStart);
      let node = t;
      if (s > 0) node = node.splitText(s);
      if (e - s < node.data.length) node.splitText(e - s);
      const mark = document.createElement('mark');
      mark.className = 'hl';
      mark.dataset.hl = String(idx);
      node.parentNode.insertBefore(mark, node);
      mark.appendChild(node);
    }
  });
  return merged;
}

/**
 * Attach highlighting behaviour to a passage container.
 * getRanges() / setRanges(ranges) persist; rerender() must restore the original HTML.
 */
export function attachHighlighter(root, { getRanges, setRanges, rerender }) {
  let pop = null;
  const closePop = () => { if (pop) { pop.remove(); pop = null; } };
  const showPop = (x, y, buttons) => {
    closePop();
    pop = h('div', { class: 'hl-pop', role: 'toolbar' });
    for (const b of buttons) {
      pop.append(h('button', { type: 'button', html: `${icon(b.icon)}${b.label}`, onmousedown: (e) => e.preventDefault(), onclick: () => { b.run(); closePop(); } }));
    }
    document.body.append(pop);
    const r = pop.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - r.width - 8, x - r.width / 2))}px`;
    pop.style.top = `${Math.max(8, y - r.height - 10)}px`;
  };
  const redraw = () => {
    rerender();
    applyHighlights(root, getRanges());
  };
  const onUp = (e) => {
    if (pop && pop.contains(e.target)) return;
    setTimeout(() => {
      const off = selectionOffsets(root);
      if (off) {
        const rect = window.getSelection().getRangeAt(0).getBoundingClientRect();
        showPop(rect.left + rect.width / 2, rect.top, [
          { icon: 'highlight', label: 'Highlight', run: () => { setRanges(mergeRanges([...getRanges(), off])); window.getSelection().removeAllRanges(); redraw(); } },
          { icon: 'eraser', label: 'Clear', run: () => { setRanges(subtract(getRanges(), off)); window.getSelection().removeAllRanges(); redraw(); } },
        ]);
        return;
      }
      const mark = e.target.closest && e.target.closest('mark.hl');
      if (mark && root.contains(mark)) {
        const idx = Number(mark.dataset.hl);
        const rect = mark.getBoundingClientRect();
        showPop(rect.left + rect.width / 2, rect.top, [
          { icon: 'eraser', label: 'Remove highlight', run: () => { const m = mergeRanges(getRanges()); m.splice(idx, 1); setRanges(m); redraw(); } },
          { icon: 'trash', label: 'Clear all', run: () => { setRanges([]); redraw(); } },
        ]);
        return;
      }
      closePop();
    }, 0);
  };
  const onDocDown = (e) => { if (pop && !pop.contains(e.target)) closePop(); };
  const onKey = (e) => { if (e.key === 'Escape') closePop(); };
  root.addEventListener('mouseup', onUp);
  root.addEventListener('keyup', (e) => { if (e.shiftKey) onUp(e); });
  document.addEventListener('mousedown', onDocDown);
  document.addEventListener('keydown', onKey);
  const scroller = root.closest('.pane');
  scroller?.addEventListener('scroll', closePop, { passive: true });
  redraw();
  return {
    redraw,
    destroy() {
      closePop();
      document.removeEventListener('mousedown', onDocDown);
      document.removeEventListener('keydown', onKey);
    },
  };
}

function subtract(ranges, [a, b]) {
  const out = [];
  for (const [s, e] of mergeRanges(ranges)) {
    if (e <= a || s >= b) { out.push([s, e]); continue; }
    if (s < a) out.push([s, a]);
    if (e > b) out.push([b, e]);
  }
  return out;
}
