// Shared UI helpers: DOM building, icons, toasts, modals, states, formatting, markdown.
import { marked } from '../vendor/marked.esm.js';
import DOMPurify from '../vendor/purify.es.mjs';

export function esc(s) {
  if (s === null || s === undefined) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Parse an HTML string into a single element (or a fragment if several roots). */
export function frag(htmlStr) {
  const t = document.createElement('template');
  t.innerHTML = htmlStr.trim();
  return t.content.childElementCount === 1 && t.content.childNodes.length === 1
    ? t.content.firstElementChild
    : t.content;
}

/** Hyperscript-style element builder. */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function sanitize(htmlStr) {
  return DOMPurify.sanitize(htmlStr || '', { ADD_ATTR: ['target'] });
}

/** Sanitise scraped test HTML and resolve content-relative media paths (e.g. "media/reading/x.png"). */
export function sanitizeContent(htmlStr) {
  const clean = sanitize(htmlStr);
  if (!/<(img|audio|source)/i.test(clean)) return clean;
  const t = document.createElement('template');
  t.innerHTML = clean;
  t.content.querySelectorAll('img[src], audio[src], source[src]').forEach((el) => {
    const src = el.getAttribute('src');
    if (!/^(https?:|data:|blob:|\/)/.test(src)) {
      el.setAttribute('src', '/media/content/' + src.replace(/^(\.\/)?(content\/)?/, ''));
    }
    if (el.tagName === 'IMG') el.setAttribute('loading', 'lazy');
  });
  return t.innerHTML;
}

marked.setOptions({ gfm: true, breaks: false });

/** Render markdown to sanitised HTML. `base` rewrites relative image/link URLs. */
export function renderMarkdown(md, { base } = {}) {
  let out = marked.parse(md || '');
  out = sanitize(out);
  if (base) {
    const t = document.createElement('template');
    t.innerHTML = out;
    t.content.querySelectorAll('img[src]').forEach((img) => {
      const src = img.getAttribute('src');
      if (!/^(https?:|data:|\/)/.test(src)) {
        img.setAttribute('src', base + src.replace(/^(\.\/)?(assets\/)?/, ''));
      }
      img.setAttribute('loading', 'lazy');
    });
    t.content.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href');
      if (/^https?:/.test(href)) { a.setAttribute('target', '_blank'); a.setAttribute('rel', 'noopener'); }
    });
    out = t.innerHTML;
  }
  return out;
}

export function parseMaybeJSON(v, fallback = null) {
  if (v === null || v === undefined || v === '') return fallback;
  if (typeof v !== 'string') return v;
  try { return JSON.parse(v); } catch { return fallback; }
}

// ---------------------------------------------------------------- icons
const P = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  listening: '<path d="M3 14v-2a9 9 0 0 1 18 0v2"/><path d="M21 15a2 2 0 0 1-2 2h-1v-6h1a2 2 0 0 1 2 2zM3 15a2 2 0 0 0 2 2h1v-6H5a2 2 0 0 0-2 2z"/>',
  reading: '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
  writing: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  speaking: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4M8 22h8"/>',
  mock: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  learn: '<path d="M22 10L12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l4 2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  play: '<path d="M7 4l13 8-13 8z" fill="currentColor"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1" fill="currentColor"/><rect x="14" y="4" width="4" height="16" rx="1" fill="currentColor"/>',
  flag: '<path d="M4 22V4M4 4h13l-2 4 2 4H4"/>',
  chevronLeft: '<path d="M15 18l-6-6 6-6"/>',
  chevronRight: '<path d="M9 18l6-6-6-6"/>',
  close: '<path d="M18 6L6 18M6 6l12 12"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  eye: '<path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M17.9 17.9A10 10 0 0 1 12 19c-7 0-11-7-11-7a18 18 0 0 1 5-5.9M9.9 4.2A9 9 0 0 1 12 4c7 0 11 7 11 7a18 18 0 0 1-2.2 3.2M1 1l22 22"/><path d="M14.1 14.1a3 3 0 1 1-4.2-4.2"/>',
  sparkles: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8zM5 2l.6 1.4L7 4l-1.4.6L5 6l-.6-1.4L3 4l1.4-.6z"/>',
  mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
  volume: '<path d="M11 5L6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
  shuffle: '<path d="M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/>',
  highlight: '<path d="M9 11l-6 6v3h9l3-3"/><path d="M22 12l-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/>',
  eraser: '<path d="M20 20H7L3 16a1.5 1.5 0 0 1 0-2L13 4a1.5 1.5 0 0 1 2 0l6 6a1.5 1.5 0 0 1 0 2l-8 8"/>',
  doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h6"/>',
  fire: '<path d="M12 22c4 0 7-2.7 7-7 0-4-3-6.5-4-9-1 2-2 3-3.5 3.5C11 7 11 4 9 2c0 4-4 6.5-4 12 0 4.3 3 8 7 8z"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  card: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
  arrowRight: '<path d="M5 12h14M13 5l7 7-7 7"/>',
  menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
  layers: '<path d="M12 2L2 7l10 5 10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/>',
  speaker: '<path d="M11 5L6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
};

export function icon(name, cls = '') {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ''}</svg>`;
}

// ---------------------------------------------------------------- toasts & modals
export function toast(msg, kind = '') {
  const root = document.getElementById('toasts');
  if (!root) return;
  const t = h('div', { class: `toast ${kind}`, role: kind === 'error' ? 'alert' : 'status' }, msg);
  root.append(t);
  setTimeout(() => { t.style.transition = 'opacity .3s'; t.style.opacity = '0'; }, kind === 'error' ? 5200 : 3000);
  setTimeout(() => t.remove(), kind === 'error' ? 5600 : 3400);
}

/** Generic modal; resolves with the value passed to close(). */
export function modal({ title, body, actions = [], wide = false, onOpen }) {
  return new Promise((resolve) => {
    const prevFocus = document.activeElement;
    const back = h('div', { class: 'modal-backdrop' });
    const box = h('div', { class: `modal${wide ? ' wide' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title });
    const close = (v) => {
      back.remove();
      document.removeEventListener('keydown', onKey, true);
      if (prevFocus && prevFocus.focus) prevFocus.focus();
      resolve(v);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); close(undefined); }
      if (e.key === 'Tab') {
        const f = box.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    box.append(h('div', { class: 'modal-head' }, h('h2', null, title)));
    const bodyEl = h('div', { class: 'modal-body' });
    if (typeof body === 'string') bodyEl.innerHTML = body; else if (body) bodyEl.append(body);
    box.append(bodyEl);
    const foot = h('div', { class: 'modal-foot' });
    for (const a of actions) {
      foot.append(h('button', { class: `btn ${a.kind || ''}`, onclick: () => close(typeof a.value === 'function' ? a.value(bodyEl) : a.value) }, a.label));
    }
    box.append(foot);
    back.append(box);
    back.addEventListener('mousedown', (e) => { if (e.target === back) close(undefined); });
    document.addEventListener('keydown', onKey, true);
    document.body.append(back);
    const primary = foot.querySelector('.btn.primary') || foot.querySelector('.btn');
    if (onOpen) onOpen(bodyEl, close);
    setTimeout(() => (bodyEl.querySelector('input, textarea, select') || primary)?.focus(), 10);
  });
}

export function confirmDialog(title, message, okLabel = 'OK', kind = 'primary') {
  return modal({
    title, body: message,
    actions: [{ label: 'Cancel', value: false }, { label: okLabel, kind, value: true }],
  }).then((v) => !!v);
}

// ---------------------------------------------------------------- states
export function loading(text = 'Loading…') {
  return frag(`<div class="loading-block"><span class="spinner"></span> ${esc(text)}</div>`);
}
export function emptyState(title, text = '', iconName = 'doc', action = '') {
  return frag(`<div class="empty">${icon(iconName)}<h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`);
}
export function errorState(err, onRetry) {
  const el = frag(`<div class="error-box" role="alert">${icon('info')}<div><b>Something went wrong.</b><div class="small">${esc(err?.message || String(err))}</div></div></div>`);
  if (onRetry) el.append(h('button', { class: 'btn sm', onclick: onRetry }, 'Retry'));
  return el;
}

/** Load async data into a container, showing loading/error states. */
export async function withStates(container, loader, render) {
  container.replaceChildren(loading());
  try {
    const data = await loader();
    container.replaceChildren();
    await render(data);
  } catch (e) {
    console.warn(e);
    container.replaceChildren(errorState(e, () => withStates(container, loader, render)));
  }
}

// ---------------------------------------------------------------- format
export function fmtBand(b) {
  if (b === null || b === undefined || b === '' || Number.isNaN(Number(b))) return '–';
  return Number(b).toFixed(1);
}
export function bandPill(b) {
  return b === null || b === undefined || b === ''
    ? '<span class="band-pill none">–</span>'
    : `<span class="band-pill">${fmtBand(b)}</span>`;
}
export function fmtClock(sec) {
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  if (m >= 60) return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
export function fmtDuration(sec) {
  if (sec === null || sec === undefined) return '–';
  sec = Math.round(sec);
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m} min${sec % 60 ? ` ${sec % 60}s` : ''}`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
export function parseDate(d) {
  if (!d) return null;
  if (d instanceof Date) return d;
  let s = String(d);
  if (/^\d{4}-\d{2}-\d{2} \d/.test(s)) s = s.replace(' ', 'T');
  const dt = new Date(s);
  return Number.isNaN(dt.getTime()) ? null : dt;
}
export function fmtDate(d, withTime = true) {
  const dt = parseDate(d);
  if (!dt) return d ? String(d) : '–';
  const opts = { day: 'numeric', month: 'short', year: dt.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined };
  if (withTime) { opts.hour = '2-digit'; opts.minute = '2-digit'; }
  return dt.toLocaleString(undefined, opts);
}
export function timeAgo(d) {
  const dt = parseDate(d);
  if (!dt) return '';
  const s = (Date.now() - dt.getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return fmtDate(dt, false);
}
export function wordCount(text) {
  const m = (text || '').trim().match(/[A-Za-z0-9À-ɏ]+(?:['’\-][A-Za-z0-9À-ɏ]+)*/g);
  return m ? m.length : 0;
}

export const QTYPE_LABELS = {
  note_completion: 'Note completion', form_completion: 'Form completion', table_completion: 'Table completion',
  flowchart_completion: 'Flow-chart completion', summary_completion: 'Summary completion',
  sentence_completion: 'Sentence completion', short_answer: 'Short answer', diagram_labelling: 'Diagram labelling',
  map_labelling: 'Map labelling', plan_labelling: 'Plan labelling', mcq: 'Multiple choice',
  multi_select: 'Multiple choice (multi)', matching: 'Matching', matching_headings: 'Matching headings',
  matching_information: 'Matching information', matching_features: 'Matching features',
  matching_sentence_endings: 'Sentence endings', tfng: 'True / False / Not Given', ynng: 'Yes / No / Not Given',
};
export function qtypeLabel(t) {
  return QTYPE_LABELS[t] || (t ? String(t).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) : 'Other');
}

export const ESSAY_TYPES = {
  opinion: 'Opinion', discussion: 'Discussion', adv_disadv: 'Advantages / Disadvantages',
  problem_solution: 'Problem / Solution', cause_effect: 'Causes / Effects', direct_question: 'Two-part question',
  outweigh: 'Outweigh', positive_negative: 'Positive / Negative', line: 'Line graph', bar: 'Bar chart',
  pie: 'Pie chart', table: 'Table', map: 'Map', process: 'Process', mixed: 'Mixed charts',
};
export function essayTypeLabel(t) { return ESSAY_TYPES[t] || (t ? String(t).replace(/_/g, ' ') : 'Other'); }

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export const store = {
  get(key, fallback = null) {
    try { const v = localStorage.getItem('ielts.' + key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem('ielts.' + key, JSON.stringify(value)); } catch { /* ignore */ }
  },
  remove(key) { try { localStorage.removeItem('ielts.' + key); } catch { /* ignore */ } },
};

/** Normalise list responses that may come back as {items:[...]} or similar. */
export function asList(data, ...keys) {
  if (Array.isArray(data)) return data;
  if (!data || typeof data !== 'object') return [];
  for (const k of [...keys, 'items', 'results', 'data', 'rows']) if (Array.isArray(data[k])) return data[k];
  return [];
}
