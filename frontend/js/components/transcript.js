// Find a quoted excerpt (the evidence an explanation cites) inside a rendered transcript, and mark it.
// Matching ignores case, punctuation, curly quotes and spacing, so "It's £120 - but…" still finds its line.

const FOLD = { '‘': "'", '’': "'", '`': "'", '´': "'", '“': '"', '”': '"', '–': '-', '—': '-', '…': '.' };
// one character in, one character out, so positions in the folded text are positions in the original
const fold = (s) => s.replace(/[‘’`´“”–—…]/g, (c) => FOLD[c]).toLowerCase();

function textIndex(root) {
  const nodes = [];
  let text = '';
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) { nodes.push({ node: n, start: text.length }); text += n.data; }
  return { nodes, text: fold(text) };
}

function search(text, words) {
  if (!words.length) return null;
  // the gap may be empty: lines of the transcript are separate elements, so their texts touch
  const re = new RegExp(words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[^a-z0-9£$%]*'));
  const m = re.exec(text);
  return m ? [m.index, m.index + m[0].length] : null;
}

/** An evidence quote can hold several sentences joined with " … ": each one is located on its own. */
export function excerptPieces(excerpt) {
  return String(excerpt || '').split(/\s*…\s*/).map((s) => s.replace(/^["'“”‘’\s]+|["'“”‘’\s]+$/g, ''))
    .filter((s) => s.split(/\s+/).length >= 2);
}

/** [start, end] of `excerpt` in the text of `root`; falls back to its first or last words. */
export function locate(root, excerpt, index = textIndex(root)) {
  const words = fold(excerpt || '').split(/[^a-z0-9£$%]+/).filter(Boolean);
  if (!words.length) return null;
  return search(index.text, words)
    || (words.length > 8 && (search(index.text, words.slice(0, 6)) || search(index.text, words.slice(-6))))
    || null;
}

/**
 * Wrap the excerpt in marks made by `makeMark()` (one per text node it spans). Returns the marks, or [].
 * Marking changes the text nodes, so each call re-reads them.
 */
export function markExcerpt(root, excerpt, makeMark) {
  const index = textIndex(root);
  const span = locate(root, excerpt, index);
  if (!span) return [];
  const [start, end] = span;
  const marks = [];
  for (const { node, start: at } of index.nodes) {
    const len = node.data.length;   // read before splitText shortens the node
    const from = Math.max(start, at), to = Math.min(end, at + len);
    if (from >= to) continue;
    let piece = node;
    if (from > at) piece = piece.splitText(from - at);
    if (to < at + len) piece.splitText(to - from);
    const mark = makeMark();
    piece.replaceWith(mark);
    mark.append(piece);
    marks.push(mark);
  }
  return marks;
}

/** The block (paragraph / line) holding the excerpt, for "show me roughly where" without marking the answer. */
export function excerptBlock(root, excerpt) {
  const index = textIndex(root);
  const span = locate(root, excerpt, index);
  if (!span) return null;
  const hit = index.nodes.find(({ node, start }) => span[0] < start + node.data.length);
  return hit?.node.parentElement?.closest('p, li, div, tr') || null;
}

/** Scroll `el` into view inside its scroller and flash it. */
export function flash(el) {
  if (!el) return;
  el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  el.classList.remove('flash');
  void el.offsetWidth; // restart the animation
  el.classList.add('flash');
}
