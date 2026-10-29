// AI feedback shown next to the item it belongs to: under a wrong question, under the sentence
// the learner wrote or said. Reads the analysis JSON keys described in the ielts-analysis skill.
import { h, esc } from '../ui.js';

/** Question numbers a mistake refers to ("Q14", "Q21-22", "Q21, Q22", or a number field). */
function mistakeNumbers(m) {
  const raw = m.ref ?? m.question ?? m.q ?? m.number;
  if (raw === undefined || raw === null) return [];
  const out = [];
  for (const part of String(raw).split(/[,&/]|\band\b/)) {
    const r = part.match(/(\d+)(?:\s*[-–]\s*Q?\s*(\d+))?/i);
    if (!r) continue;
    const a = Number(r[1]), b = r[2] ? Number(r[2]) : a;
    for (let n = a; n <= b && n - a < 10; n++) out.push(n);
  }
  return out;
}

/** Map question number -> list of AI mistake entries (attempt analyses). */
export function mistakesByQuestion(j) {
  const map = new Map();
  for (const m of Array.isArray(j?.mistakes) ? j.mistakes : []) {
    if (!m || typeof m !== 'object') continue;
    for (const n of mistakeNumbers(m)) {
      if (!map.has(n)) map.set(n, []);
      map.get(n).push(m);
    }
  }
  return map;
}

/** The note shown under one wrong question. */
export function questionNote(list) {
  const box = h('div', { class: 'ai-note' });
  for (const m of list) {
    const what = m.what || m.user_answer || m.original;
    const correct = m.correct || m.correct_answer;
    const evidence = m.evidence || m.quote;
    const why = m.why || m.explanation || m.reason;
    const fix = m.fix || m.correction || m.tip;
    box.append(h('div', { class: 'ai-note-head' }, h('span', { class: 'ai-tag' }, 'AI'), what ? h('span', null, String(what)) : null,
      correct ? h('span', null, ' → ', h('b', { class: 'm-fix' }, String(correct))) : null));
    if (evidence) box.append(h('div', { class: 'ai-note-line' }, h('span', { class: 'muted' }, 'Evidence: '), h('i', null, `“${String(evidence).replace(/^["“]|["”]$/g, '')}”`)));
    if (why) box.append(h('div', { class: 'ai-note-line' }, h('span', { class: 'muted' }, 'Why: '), String(why)));
    if (fix) box.append(h('div', { class: 'ai-note-line' }, h('span', { class: 'muted' }, 'Next time: '), String(fix)));
  }
  return box;
}

function normCorrection(c) {
  if (!c || typeof c !== 'object') return null;
  const original = String(c.original || c.before || c.what || '').trim();
  const corrected = String(c.corrected || c.after || c.correction || c.fix || '').trim();
  if (!original || !corrected) return null;
  return { original, corrected, why: String(c.why || c.explanation || c.reason || '').trim() };
}

/**
 * Older analyses have no `corrections`, but their `mistakes` often quote the learner (`what`) and
 * give a `fix`; those are shown only where the quote is found in the text (`optional`).
 */
export function mistakeCorrections(j) {
  return (Array.isArray(j?.mistakes) ? j.mistakes : []).map((m) => {
    const c = normCorrection({ original: String(m?.what || '').replace(/^["“']|["”']$/g, ''), corrected: m?.fix, why: m?.why });
    return c && { ...c, optional: true };
  }).filter(Boolean);
}

/** Corrections from a writing analysis (new `corrections` key, or older `corrected_sentences` / `mistakes`). */
export function writingCorrections(j) {
  const src = Array.isArray(j?.corrections) ? j.corrections : Array.isArray(j?.corrected_sentences) ? j.corrected_sentences : null;
  return src ? src.map(normCorrection).filter(Boolean) : mistakeCorrections(j);
}

/** Per-response feedback from a speaking analysis: Map response id -> {feedback, better, corrections}. */
export function speakingAnswers(j) {
  const map = new Map();
  for (const a of Array.isArray(j?.answers) ? j.answers : []) {
    const id = Number(a?.response ?? a?.response_id ?? a?.id);
    if (!id) continue;
    map.set(id, {
      feedback: a.feedback || a.comment || '',
      better: a.better || a.model || a.upgrade || '',
      corrections: (Array.isArray(a.corrections) ? a.corrections : []).map(normCorrection).filter(Boolean),
    });
  }
  return map;
}

/** Find `needle` in `text` ignoring case and whitespace differences; returns [start, end] or null. */
function findSpan(text, needle, taken) {
  const words = needle.split(/\s+/).filter(Boolean).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (!words.length) return null;
  const re = new RegExp(words.join('\\s+'), 'gi');
  let m;
  while ((m = re.exec(text))) {
    const s = m.index, e = s + m[0].length;
    if (!taken.some(([a, b]) => s < b && e > a)) return [s, e];
    if (m[0].length === 0) re.lastIndex++;
  }
  return null;
}

/**
 * Render `text` sentence by sentence; every sentence holding corrections gets its errors marked
 * and a note right under it. `plain(str) -> html` renders unmarked stretches (default: escaped).
 */
export function annotatedText(text, corrections, { plain = esc } = {}) {
  const wrap = h('div', { class: 'annotated' });
  const taken = [];
  const placed = [];
  const missed = [];
  for (const c of corrections) {
    const span = findSpan(text, c.original, taken);
    if (span) { taken.push(span); placed.push({ ...c, original: text.slice(span[0], span[1]), s: span[0], e: span[1] }); } else if (!c.optional) missed.push(c);
  }
  placed.sort((a, b) => a.s - b.s);
  const paraRe = /[^\n]+/g;
  let pm;
  while ((pm = paraRe.exec(text))) {
    const pStart = pm.index, para = pm[0];
    const p = h('div', { class: 'an-para' });
    const sentRe = /[^.!?]+(?:[.!?]+["'”’)\]]*|$)\s*/g;
    let sm;
    while ((sm = sentRe.exec(para))) {
      if (!sm[0]) { sentRe.lastIndex++; continue; }
      const sStart = pStart + sm.index, sEnd = sStart + sm[0].length;
      const inside = placed.filter((c) => c.s >= sStart && c.s < sEnd);
      if (!inside.length) { p.append(h('span', { html: plain(sm[0]) })); continue; }
      let html = '', at = sStart;
      for (const c of inside) {
        html += plain(text.slice(at, c.s)) + `<mark class="fix-mark">${esc(text.slice(c.s, c.e))}</mark>`;
        at = Math.max(at, c.e);
      }
      html += plain(text.slice(at, Math.max(at, sEnd)));
      const block = h('div', { class: 'an-sent' }, h('span', { html }));
      const note = h('div', { class: 'fix-note' });
      for (const c of inside) note.append(fixLine(c));
      block.append(note);
      p.append(block);
    }
    wrap.append(p);
  }
  if (missed.length) {
    const note = h('div', { class: 'fix-note', style: { marginTop: '10px' } }, h('div', { class: 'small muted' }, 'Other corrections'));
    for (const c of missed) note.append(fixLine(c));
    wrap.append(note);
  }
  return wrap;
}

function fixLine(c) {
  return h('div', { class: 'fix-line' },
    h('span', { class: 'm-orig' }, c.original), ' → ', h('span', { class: 'm-fix' }, c.corrected),
    c.why ? h('span', { class: 'muted' }, ` — ${c.why}`) : null);
}
