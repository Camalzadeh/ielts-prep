// Study assistant: a side drawer with tactics per question type, the teacher's phrase bank (click to insert
// into an essay), the course rules/tips (knowledge base), vocabulary and a translator,
// plus "select text -> translate" anywhere in the app. Pages say what they are about with setAssistContext();
// in mock exams the assistant is off unless the `assist_in_mock` setting is on (a real exam has no help).
import { api } from '../api.js';
import { h, esc, icon, toast, renderMarkdown, qtypeLabel, debounce, store, sanitizeContent } from '../ui.js';
import { excerptBlock, excerptPieces, flash } from './transcript.js';

// Which knowledge-base categories belong to which section.
const SECTION_CATEGORIES = {
  reading: ['reading', 'vocabulary'],
  listening: ['listening', 'vocabulary'],
  writing1: ['writing-task1', 'vocabulary', 'exam-info'],
  writing2: ['writing-task2', 'vocabulary', 'exam-info'],
  speaking: ['speaking', 'vocabulary', 'exam-info'],
};
const SECTION_LABEL = { reading: 'Reading', listening: 'Listening', writing1: 'Writing Task 1', writing2: 'Writing Task 2', speaking: 'Speaking' };

// Words that find the right heading of a strategy page for a question / essay type.
const TYPE_KEYWORDS = {
  tfng: ['true / false / not given', 'true/false/not given', 'not given'],
  ynng: ['yes / no / not given', 'yes/no/not given', 'not given'],
  matching_headings: ['heading'],
  matching_information: ['matching information', 'which paragraph', 'information'],
  matching_features: ['matching features', 'features'],
  matching_sentence_endings: ['sentence ending'],
  matching: ['matching'],
  mcq: ['multiple choice', 'multiple-choice'],
  multi_select: ['multiple choice', 'choose two', 'multiple-choice'],
  summary_completion: ['summary'],
  note_completion: ['note', 'completion'],
  form_completion: ['form', 'completion'],
  table_completion: ['table', 'completion'],
  flowchart_completion: ['flow', 'completion'],
  sentence_completion: ['sentence completion', 'completion'],
  short_answer: ['short answer', 'short-answer'],
  map_labelling: ['map', 'plan'],
  plan_labelling: ['plan', 'map'],
  diagram_labelling: ['diagram', 'label'],
};

// transcript (listening practice only): { attemptId(), part(), question() } from the player
const EMPTY = { section: null, qtype: null, essayType: null, mock: false, part: null, topic: '', transcript: null };
const ctx = { ...EMPTY };

// Tabs per section, in the order they are offered (the first one opens by default).
const TABS = {
  tactics: ['target', 'Tactics'], phrases: ['writing', 'Phrases'], rules: ['rules', 'Rules'],
  vocab: ['book', 'Words'], translate: ['translate', 'Translate'], transcript: ['listening', 'Transcript'],
};
const SECTION_TABS = {
  reading: ['tactics', 'rules', 'vocab', 'translate'],
  listening: ['tactics', 'transcript', 'rules', 'vocab', 'translate'],
  writing1: ['phrases', 'tactics', 'rules', 'vocab', 'translate'],
  writing2: ['phrases', 'tactics', 'rules', 'vocab', 'translate'],
  speaking: ['tactics', 'phrases', 'vocab', 'rules', 'translate'],
};
// The transcript is a practice aid: never offered in exam mode (the server refuses it there too).
const tabsFor = () => (SECTION_TABS[ctx.section] || ['rules', 'vocab', 'translate'])
  .filter((t) => t !== 'transcript' || (ctx.transcript && !ctx.mock));
let lastTextarea = null;   // the essay box phrases are inserted into
let settings = { translate_to: 'az', assist_in_mock: '0' };
let kbList = null;
let drawer = null;

export const LANGS = { az: 'Azərbaycan', ru: 'Русский', tr: 'Türkçe', en: 'English' };

export function setAssistContext(next) {
  Object.assign(ctx, EMPTY, next);
  if (drawer && drawer.isConnected) openDrawer(tabsFor().includes(drawer.dataset.tab) ? drawer.dataset.tab : undefined);
  else if (store.get('assist.open', false) && enabled()) openDrawer();  // it was open on the previous screen
}
/** Listening: the part on screen changed (the transcript tab follows it). */
export function assistPartChanged() {
  if (drawer && drawer.isConnected && drawer.dataset.tab === 'transcript') openDrawer('transcript');
}
/** Speaking: the part / topic of the question on screen. */
export function setAssistDetail(detail) {
  Object.assign(ctx, detail);
  if (drawer && drawer.isConnected && ['tactics', 'vocab', 'phrases'].includes(drawer.dataset.tab)) openDrawer(drawer.dataset.tab);
}
/** Update just the question type (player calls this as the current question changes). */
export function setAssistQType(qtype) {
  if (ctx.qtype === qtype) return;
  ctx.qtype = qtype;
}
export function clearAssistContext() { Object.assign(ctx, EMPTY); closeDrawer(false); }

function enabled() { return !ctx.mock || settings.assist_in_mock === '1'; }

export async function loadAssistSettings() {
  try { settings = { ...settings, ...(await api.get('/api/settings')) }; } catch { /* defaults */ }
}

/** Toolbar button that opens the drawer (hidden in mock exams unless allowed). */
export function assistButton({ compact = false, mock = ctx.mock } = {}) {
  const b = h('button', { class: compact ? 'icon-btn' : 'btn sm', type: 'button', title: 'Tactics, phrases, rules, vocabulary & translator (Alt+H)',
    'aria-label': 'Open study assistant', html: compact ? icon('rules') : `${icon('rules')} Help` });
  b.addEventListener('click', () => (drawer?.isConnected ? closeDrawer() : openDrawer()));
  if (mock && settings.assist_in_mock !== '1') b.hidden = true;
  return b;
}

// ------------------------------------------------------------------ remembered state
// The drawer keeps what the learner set up: whether it is open, the last tab per section and, per section and
// tab, their choices (guide, card, view, search text) and scroll position. Plain localStorage via `store`.
const scopeKey = (tab) => `assist.${ctx.section || 'any'}.${tab}`;
const memory = (tab) => store.get(scopeKey(tab), {}) || {};
const remember = (tab, patch) => store.set(scopeKey(tab), { ...memory(tab), ...patch });

/** Restore the body's scroll for `tab` (optionally under a sub-key) and keep saving it. */
function keepScroll(body, tab, key = 'scroll') {
  const y = memory(tab)[key];
  if (y) body.scrollTop = y;
  body.onscroll = debounce(() => { if (drawer?.dataset.tab === tab) remember(tab, { [key]: body.scrollTop }); }, 150);
}

// ------------------------------------------------------------------ drawer
/** `byUser`: the learner closed it (stay closed); otherwise the page went away (reopen on the next one). */
function closeDrawer(byUser = true) {
  if (drawer) { drawer.remove(); drawer = null; }
  if (byUser) store.set('assist.open', false);
  dock();
}

// Width: drag the drawer's left edge (or focus it and use the arrow keys; double-click resets). On a wide
// screen the page moves aside (docked) so the drawer never covers the essay or the questions.
const DRAWER_W = 480;
let drawerW = store.get('assistW', DRAWER_W);
const maxDrawerW = () => Math.max(320, Math.min(900, Math.round(window.innerWidth * 0.7)));
function setDrawerW(w, save = true) {
  drawerW = Math.round(Math.max(320, Math.min(maxDrawerW(), w)));
  document.documentElement.style.setProperty('--assist-w', `${drawerW}px`);
  if (save) store.set('assistW', drawerW);
  dock();
}
function dock() {
  const on = !!(drawer && drawer.isConnected) && window.innerWidth >= 1180 && window.innerWidth - drawerW >= 780;
  document.documentElement.classList.toggle('assist-docked', on);
}
window.addEventListener('resize', () => { if (drawer) setDrawerW(drawerW, false); });
function drawerGrip() {
  const grip = h('div', { class: 'assist-grip', role: 'separator', tabindex: '0', 'aria-orientation': 'vertical',
    'aria-label': 'Resize the study assistant', title: 'Drag to resize · double-click to reset' });
  let dragging = false;
  grip.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    dragging = true; grip.classList.add('drag'); grip.setPointerCapture(e.pointerId);
    document.body.classList.add('resizing-col'); e.preventDefault();
  });
  grip.addEventListener('pointermove', (e) => { if (dragging) setDrawerW(window.innerWidth - e.clientX); });
  const end = () => { dragging = false; grip.classList.remove('drag'); document.body.classList.remove('resizing-col'); };
  grip.addEventListener('pointerup', end);
  grip.addEventListener('pointercancel', end);
  grip.addEventListener('dblclick', () => setDrawerW(DRAWER_W));
  grip.addEventListener('keydown', (e) => {
    const step = e.shiftKey ? 80 : 24;
    if (e.key === 'ArrowLeft') { e.preventDefault(); setDrawerW(drawerW + step); }
    if (e.key === 'ArrowRight') { e.preventDefault(); setDrawerW(drawerW - step); }
  });
  return grip;
}

/** The tab row scrolls sideways when it does not fit (mouse wheel works too); the active tab is kept in view. */
function tabStrip(tabs, active) {
  const strip = h('div', { class: 'assist-tabs', role: 'tablist' }, ...tabs.map((id) =>
    h('button', { type: 'button', role: 'tab', class: active === id ? 'active' : '', 'aria-selected': String(active === id),
      html: `${icon(TABS[id][0])}<span>${TABS[id][1]}</span>`, onclick: () => openDrawer(id) })));
  strip.addEventListener('wheel', (e) => {
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX) || strip.scrollWidth <= strip.clientWidth) return;
    strip.scrollLeft += e.deltaY;
    e.preventDefault();
  }, { passive: false });
  requestAnimationFrame(() => strip.querySelector('.active')?.scrollIntoView({ block: 'nearest', inline: 'nearest' }));
  return strip;
}

export function openDrawer(tab, { text } = {}) {
  const tabs = tabsFor();
  if (!tab || !TABS[tab]) {
    const last = store.get(`assist.${ctx.section || 'any'}.tab`);
    tab = tabs.includes(last) ? last : tabs[0];
  }
  if (!tabs.includes(tab)) tabs.push(tab);
  if (!enabled()) { toast('The study assistant is off during mock exams (Settings → Study assistant).'); return; }
  if (!drawer || !drawer.isConnected) {
    drawer = h('aside', { class: 'assist-drawer', role: 'complementary', 'aria-label': 'Study assistant' });
    document.body.append(drawer);
  }
  drawer.dataset.tab = tab;
  store.set(`assist.${ctx.section || 'any'}.tab`, tab);
  store.set('assist.open', true);
  drawer.replaceChildren(
    drawerGrip(),
    h('div', { class: 'assist-head' },
      tabStrip(tabs, tab),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', title: 'Close (Esc)', html: icon('close'), onclick: () => closeDrawer() })),
    h('div', { class: 'assist-body' }));
  setDrawerW(drawerW, false);
  if (tab === 'rules') renderRules();
  else if (tab === 'tactics') renderTactics();
  else if (tab === 'phrases') renderPhrases();
  else if (tab === 'vocab') renderVocab();
  else if (tab === 'transcript') renderTranscript();
  else renderTranslate(text);
}

async function renderRules() {
  const body = drawer.querySelector('.assist-body');
  body.replaceChildren(h('p', { class: 'muted small' }, 'Loading…'));
  try { kbList = kbList || await api.get('/api/kb'); } catch (e) { body.replaceChildren(h('p', { class: 'muted' }, e.message)); return; }
  const cats = SECTION_CATEGORIES[ctx.section] || null;
  const docs = (cats ? kbList.filter((d) => cats.includes(d.category)) : kbList)
    .sort((a, b) => (cats ? cats.indexOf(a.category) - cats.indexOf(b.category) : 0) || a.title.localeCompare(b.title));
  if (!docs.length) { body.replaceChildren(h('p', { class: 'muted' }, 'No guides for this section yet.')); return; }
  // pick the guide that best fits what is on screen
  const want = (ctx.essayType || '').replace(/_/g, ' ').toLowerCase();
  const mem = memory('rules');
  const pick = docs.find((d) => d.slug === mem.slug)
    || (want && docs.find((d) => `${d.title} ${d.tags || ''}`.toLowerCase().includes(want.split(' ')[0])))
    || docs.find((d) => d.category === (cats || [])[0]) || docs[0];
  const select = h('select', { class: 'input', 'aria-label': 'Guide' },
    ...docs.map((d) => h('option', { value: d.slug, selected: d.slug === pick.slug ? '' : null }, d.title)));
  const content = h('div', { class: 'assist-doc md' });
  const hint = h('div', { class: 'assist-hint small' });
  body.replaceChildren(
    h('div', { class: 'assist-sticky' },
      h('div', { class: 'small muted', style: { marginBottom: '6px' } },
        ctx.section ? `Guides for ${SECTION_LABEL[ctx.section]}` : 'All guides'),
      select, hint),
    content);
  // the same guide for the same question type reopens where it was left; otherwise jump to the type's tips
  const show = async (slug, restore) => {
    content.replaceChildren(h('p', { class: 'muted small' }, 'Loading…'));
    try {
      const d = await api.get(`/api/kb/${encodeURIComponent(slug)}`);
      content.innerHTML = renderMarkdown((d.content_md || '').replace(/^﻿?---\r?\n[\s\S]*?\r?\n---\r?\n?/, ''), { base: '/media/kb/' });
      jumpToType(content, hint, !restore);
      if (!restore) remember('rules', { slug, qtype: ctx.qtype, scroll: 0 });
      keepScroll(body, 'rules');
    } catch (e) { content.replaceChildren(h('p', { class: 'muted' }, e.message)); }
  };
  select.addEventListener('change', () => show(select.value, false));
  show(pick.slug, pick.slug === mem.slug && mem.qtype === ctx.qtype);
}

/** Scroll to the part of the guide about the current question type and mark it. */
function jumpToType(content, hint, scroll = true) {
  hint.replaceChildren();
  const words = TYPE_KEYWORDS[ctx.qtype] || (ctx.qtype ? [qtypeLabel(ctx.qtype).toLowerCase()] : []);
  if (!words.length) return;
  const heads = [...content.querySelectorAll('h1,h2,h3,h4')];
  const target = words.map((w) => heads.find((el) => el.textContent.toLowerCase().includes(w))).find(Boolean);
  if (!target) return;
  target.classList.add('assist-target');
  target.style.scrollMarginTop = `${(content.parentElement.querySelector('.assist-sticky')?.offsetHeight || 0) + 24}px`;
  hint.append(h('button', { class: 'btn sm', type: 'button', html: `${icon('target')} Tips for this question type: ${esc(qtypeLabel(ctx.qtype))}`,
    onclick: () => target.scrollIntoView({ block: 'start', behavior: 'smooth' }) }));
  if (scroll) setTimeout(() => target.scrollIntoView({ block: 'start' }), 50);
}

// ------------------------------------------------------------------ tactics
function tacticsTarget() {
  if (ctx.section === 'reading' || ctx.section === 'listening') return { skill: ctx.section, type: ctx.qtype };
  if (ctx.section === 'writing1') return { skill: 'writing', type: ctx.essayType ? `task1_${ctx.essayType}` : null };
  if (ctx.section === 'writing2') return { skill: 'writing', type: ctx.essayType ? `task2_${ctx.essayType}` : null };
  if (ctx.section === 'speaking') return { skill: 'speaking', type: ctx.part ? `part${ctx.part}` : null };
  return null;
}

const tacticTitle = (c) => c.title || (c.type === 'general' ? 'General strategy' : qtypeLabel(c.type));

/** Quick view: the golden rule, then Do / Avoid / Remember; the full explanation is folded away. */
function tacticCard(c, current) {
  const q = c.quick || { do: (c.steps || []).slice(0, 4), avoid: (c.traps || []).slice(0, 3), remember: [] };
  const box = (cls, title, items, ordered) => (items && items.length
    ? h('div', { class: `tq-box ${cls}` }, h('h4', null, title), h(ordered ? 'ol' : 'ul', null, ...items.map((x) => h('li', null, x))))
    : '');
  const list = (title, items, cls) => (items && items.length
    ? h('div', { class: `tac-block ${cls}` }, h('h4', null, title), h(cls === 'tac-steps' ? 'ol' : 'ul', null, ...items.map((x) => h('li', null, x))))
    : '');
  return h('div', { class: `tac-card${current ? ' current' : ''}` },
    h('div', { class: 'row between', style: { alignItems: 'flex-start', gap: '8px' } },
      h('h3', null, tacticTitle(c)), current ? h('span', { class: 'badge accent' }, 'Now') : ''),
    h('div', { class: 'tq-rule', html: `${icon('target')}<span>${esc(c.rule || c.summary || '')}</span>` }),
    box('tq-do', 'Do', q.do, true), box('tq-avoid', 'Avoid', q.avoid), box('tq-remember', 'Remember', q.remember),
    c.language && c.language.length ? h('div', { class: 'tq-box tq-words' }, h('h4', null, 'Words to watch for'),
      h('div', { class: 'chips' }, ...c.language.map((w) => h('span', { class: 'chip' }, w)))) : '',
    h('details', { class: 'tq-full' }, h('summary', null, 'Full explanation'),
      c.summary && c.rule ? h('p', { class: 'small muted' }, c.summary) : '',
      list('Steps', c.steps, 'tac-steps'), list('Traps', c.traps, 'tac-traps'), list('Tips', c.tips, 'tac-tips'),
      c.example ? h('div', { class: 'tac-block' }, h('h4', null, 'Example'), h('blockquote', null, c.example)) : ''));
}

async function renderTactics() {
  const body = drawer.querySelector('.assist-body');
  const target = tacticsTarget();
  if (!target) { body.replaceChildren(h('p', { class: 'muted' }, 'Open a test, essay or speaking practice to see tactics for it.')); return; }
  body.replaceChildren(h('p', { class: 'muted small' }, 'Loading…'));
  let cards = [], tables = [];
  try {
    [cards, tables] = await Promise.all([api.get('/api/tactics', { skill: target.skill }),
      ['reading', 'listening'].includes(target.skill) ? api.get('/api/cheatsheets', { skill: target.skill }).catch(() => []) : []]);
  } catch (e) { body.replaceChildren(h('p', { class: 'muted' }, e.message)); return; }
  if (!cards.length) { body.replaceChildren(h('p', { class: 'muted' }, 'No tactics for this section yet.')); return; }
  const current = cards.find((c) => c.type === target.type) || null;
  const general = cards.find((c) => c.type === 'general');
  // writing: only the cards of the task being written (task1_* or task2_*)
  const prefix = ctx.section === 'writing1' ? 'task1_' : ctx.section === 'writing2' ? 'task2_' : '';
  const all = cards.filter((c) => !prefix || c.type.startsWith(prefix) || c.type === 'general');
  // a card picked by hand stays picked while the question type on screen is the same
  const mem = memory('tactics');
  let shown = (mem.for === (target.type || null) && all.find((c) => c.type === mem.shown)) || current || general || all[0];
  const slot = h('div');
  const chips = h('div', { class: 'tq-types' });
  const draw = () => {
    const card = tacticCard(shown, shown === current);
    const full = card.querySelector('.tq-full');
    full.open = !!memory('tactics').full;
    full.addEventListener('toggle', () => remember('tactics', { full: full.open }));
    slot.replaceChildren(
      !current && target.type ? h('p', { class: 'small muted' }, `No card for "${qtypeLabel(target.type)}" yet.`) : '',
      card);
    chips.replaceChildren(...all.map((c) => h('button', { type: 'button', class: `tq-type${c === shown ? ' active' : ''}${c === current ? ' now' : ''}`,
      onclick: () => { shown = c; remember('tactics', { shown: c.type, for: target.type || null, scroll: 0 }); draw(); body.scrollTop = 0; } }, tacticTitle(c))));
  };
  draw();
  const fits = (tb) => !(tb.applies_to || []).length || (target.type && tb.applies_to.includes(target.type));
  const useful = tables.filter(fits);
  body.replaceChildren(slot,
    h('h4', { class: 'tq-heading' }, 'Other question types'), chips,
    useful.length ? h('h4', { class: 'tq-heading' }, 'Word tables') : '',
    ...useful.map((tb) => cheatTable(tb, { canInsert: false })));
  if (mem.for === (target.type || null)) keepScroll(body, 'tactics');
  else { remember('tactics', { for: target.type || null, shown: shown.type, scroll: 0 }); keepScroll(body, 'tactics'); }
}

// ------------------------------------------------------------------ phrase bank
function insertIntoEssay(text) {
  const ta = lastTextarea && lastTextarea.isConnected ? lastTextarea : document.querySelector('.player textarea, .writer textarea');
  if (!ta) { navigator.clipboard?.writeText(text); toast('Copied - no essay box is open.'); return; }
  const start = ta.selectionStart ?? ta.value.length, end = ta.selectionEnd ?? start;
  const before = ta.value.slice(0, start);
  const sep = before && !/\s$/.test(before) ? ' ' : '';
  ta.focus();
  ta.setRangeText(sep + text + ' ', start, end, 'end');
  ta.dispatchEvent(new Event('input', { bubbles: true }));
}

/** Click a word chip: insert it into the essay (writing) or copy it. */
function useChunk(text, canInsert) {
  const clean = text.replace(/\s*…\s*$/, '').trim();
  if (canInsert) insertIntoEssay(clean);
  else { navigator.clipboard?.writeText(clean); toast(`Copied "${clean}"`); }
}

/** One of the teacher's word tables: coloured header, rows tinted by tone, every alternative a clickable chip. */
function cheatTable(tb, { canInsert, forTask = false, query = '' }) {
  const q = query.toLowerCase();
  const rows = (tb.rows || []).filter((r) => !q || `${tb.title} ${r.cells.join(' ')}`.toLowerCase().includes(q));
  if (!rows.length) return '';
  const cell = (text, i) => {
    if (i === 0 && tb.columns[0] !== undefined && rows.length > 1 && text.length < 40 && !text.includes(' · ')) return h('th', { scope: 'row' }, text);
    const parts = String(text || '').split(' · ').filter(Boolean);
    return h('td', null, ...(parts.length ? parts.map((x) => h('button', { type: 'button', class: 'cs-chip', title: canInsert ? 'Insert into my essay' : 'Copy',
      onmousedown: (e) => e.preventDefault(), onclick: () => useChunk(x, canInsert) }, x)) : ['–']));
  };
  return h('section', { class: `cs-card cs-${tb.color || 'blue'}` },
    h('header', null, h('b', null, tb.title), forTask ? h('span', { class: 'cs-tag' }, 'for this task') : ''),
    tb.note ? h('div', { class: 'cs-note' }, tb.note) : '',
    h('div', { class: 'cs-scroll' }, h('table', { class: 'cs-table' },
      tb.columns.some(Boolean) ? h('thead', null, h('tr', null, ...tb.columns.map((c) => h('th', { scope: 'col' }, c)))) : '',
      h('tbody', null, ...rows.map((r) => h('tr', { class: r.tone ? `tone-${r.tone}` : '' }, ...r.cells.map(cell)))))),
    tb.example ? h('div', { class: 'cs-example' }, tb.example) : '');
}


// Category colour by its group ("Trends: ...", "Overview: ...") so related lists look alike.
const CAT_COLORS = ['blue', 'green', 'purple', 'amber', 'teal', 'pink', 'red'];
const catColor = (name) => {
  const key = name.split(':')[0];
  let n = 0;
  for (const ch of key) n = (n * 31 + ch.charCodeAt(0)) >>> 0;
  return CAT_COLORS[n % CAT_COLORS.length];
};

async function renderPhrases() {
  const body = drawer.querySelector('.assist-body');
  const skill = ['writing1', 'writing2', 'speaking'].includes(ctx.section) ? ctx.section : null;
  if (!skill) { body.replaceChildren(h('p', { class: 'muted' }, 'Phrases are available while writing an essay or practising speaking.')); return; }
  body.replaceChildren(h('p', { class: 'muted small' }, 'Loading…'));
  let cats = [], tables = [];
  try {
    [cats, tables] = await Promise.all([api.get('/api/phrases', { skill }), api.get('/api/cheatsheets', { skill }).catch(() => [])]);
  } catch (e) { body.replaceChildren(h('p', { class: 'muted' }, e.message)); return; }
  const tag = ctx.essayType || (ctx.part ? `part${ctx.part}` : null);
  const fits = (x) => !!tag && (x.applies_to || []).includes(tag);
  const orderedCats = [...cats.filter(fits), ...cats.filter((c) => !fits(c))];
  const orderedTables = [...tables.filter(fits), ...tables.filter((tb) => !fits(tb))];
  const canInsert = skill !== 'speaking';
  const mem = memory('phrases');
  let view = tables.length ? (mem.view || 'tables') : 'list';
  const openCats = new Set(mem.open || []);   // categories the learner opened or closed by hand
  const closedCats = new Set(mem.closed || []);

  const search = h('input', { class: 'input', type: 'search', value: mem.q || '', placeholder: 'Search (e.g. increase, however, in my opinion)', 'aria-label': 'Search phrases' });
  const seg = h('div', { class: 'provider-switch', role: 'group', 'aria-label': 'Phrase view' });
  const list = h('div', { class: 'phr-list' });
  const drawSeg = () => seg.replaceChildren(...[['tables', 'Tables'], ['list', 'All phrases']].map(([k, l]) =>
    h('button', { type: 'button', 'aria-pressed': String(view === k), onclick: () => {
      view = k; remember('phrases', { view: k, scroll: 0 });
      drawSeg(); draw();
    } }, l)));
  const trackCat = (el, name) => el.addEventListener('toggle', () => {
    if (search.value.trim()) return;  // opened by a search, not by hand
    (el.open ? openCats : closedCats).add(name);
    (el.open ? closedCats : openCats).delete(name);
    remember('phrases', { open: [...openCats], closed: [...closedCats] });
  });

  const item = (it) => h('div', { class: `phr-item${it.level === 'advanced' ? ' adv' : ''}` },
    h('div', { class: 'row between', style: { gap: '6px', alignItems: 'flex-start' } },
      h('button', { type: 'button', class: 'cs-chip phr-main', title: canInsert ? 'Insert into my essay' : 'Copy',
        onmousedown: (e) => e.preventDefault(), onclick: () => useChunk(it.phrase.split(' / ')[0], canInsert) }, it.phrase),
      it.level === 'advanced' ? h('span', { class: 'badge', title: 'Band 7+' }, '7+') : ''),
    it.pattern ? h('div', { class: 'phr-pattern' }, it.pattern) : '',
    it.example ? h('div', { class: 'phr-example' }, it.example) : '',
    it.note ? h('div', { class: 'small muted' }, it.note) : '');

  const drawList = (q) => {
    const shown = orderedCats
      .map((c) => ({ c, items: (c.items || []).filter((it) => !q || `${c.category} ${it.phrase} ${it.pattern || ''} ${it.example || ''}`.toLowerCase().includes(q)) }))
      .filter((x) => x.items.length);
    return shown.length ? shown.map(({ c, items }) => {
      const open = q || openCats.has(c.category) || (fits(c) && !closedCats.has(c.category));
      const el = h('details', { class: `phr-cat cs-${catColor(c.category)}`, open: open ? '' : null },
        h('summary', null, h('span', { class: 'phr-dot' }), c.category,
          fits(c) ? h('span', { class: 'cs-tag' }, 'for this task') : '',
          h('span', { class: 'muted small', style: { marginLeft: 'auto' } }, `${items.length}`)),
        c.when ? h('div', { class: 'small muted', style: { margin: '2px 0 6px' } }, c.when) : '',
        ...items.map(item));
      trackCat(el, c.category);
      return el;
    }) : [h('p', { class: 'muted small' }, 'No phrase matches.')];
  };
  const drawTables = (q) => {
    const out = orderedTables.map((tb) => cheatTable(tb, { canInsert, forTask: fits(tb), query: q })).filter(Boolean);
    return out.length ? out : [h('p', { class: 'muted small' }, 'No table matches - try "All phrases".')];
  };
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    list.replaceChildren(...(view === 'tables' ? drawTables(q) : drawList(q)));
  };
  search.addEventListener('input', debounce(() => { remember('phrases', { q: search.value }); draw(); }, 120));
  drawSeg();
  body.replaceChildren(h('div', { class: 'assist-sticky' },
    tables.length ? h('div', { class: 'row between', style: { marginBottom: '8px', gap: '8px' } }, seg,
      h('span', { class: 'small muted' }, canInsert ? 'Click a word to insert it' : 'Click a word to copy it')) : '',
    search), list);
  draw();
  keepScroll(body, 'phrases');
}

async function renderVocab() {
  const body = drawer.querySelector('.assist-body');
  const input = h('input', { class: 'input', type: 'search', value: memory('vocab').q || '', placeholder: 'Search course words & phrases', 'aria-label': 'Search vocabulary' });
  let restored = false;
  const list = h('div', { class: 'assist-vocab' });
  const topicBox = h('div');
  body.replaceChildren(topicBox, input, list);
  if (ctx.section === 'speaking' && ctx.topic) {
    api.get('/api/speaking/topic-vocab', { topic: ctx.topic }).then((tv) => {
      if (!tv.words || !tv.words.length) return;
      topicBox.replaceChildren(h('h4', { style: { margin: '0 0 6px' } }, `Useful for "${tv.topic}"`),
        h('div', { class: 'assist-vocab', style: { marginBottom: '14px' } }, ...tv.words.map((w) => h('div', { class: 'assist-word' },
          h('b', null, w.term), w.meaning ? h('div', { class: 'small' }, w.meaning) : '',
          w.example ? h('div', { class: 'small muted' }, `"${w.example}"`) : ''))));
    }).catch(() => {});
  }
  const run = debounce(async () => {
    const q = input.value.trim();
    try {
      const rows = await api.get('/api/vocab', q ? { q, limit: 60 } : { limit: 40 });
      list.replaceChildren(...(rows.length ? rows.map((v) => h('div', { class: 'assist-word' },
        h('div', null, h('b', null, v.term), v.topic ? h('span', { class: 'badge', style: { marginLeft: '6px' } }, v.topic) : ''),
        v.meaning ? h('div', { class: 'small' }, v.meaning) : '',
        v.example ? h('div', { class: 'small muted' }, `“${v.example}”`) : ''))
        : [h('p', { class: 'muted small' }, 'No match. Try the Translate tab.')]));
      if (!restored) { restored = true; keepScroll(body, 'vocab'); }   // back where it was, once the list is there
    } catch (e) { list.replaceChildren(h('p', { class: 'muted' }, e.message)); }
  }, 200);
  input.addEventListener('input', () => { remember('vocab', { q: input.value, scroll: 0 }); run(); });
  run();
  setTimeout(() => input.focus({ preventScroll: true }), 0);
}

// ------------------------------------------------------------------ transcript (listening practice only)
const transcripts = new Map();   // `${attemptId}.${part}` -> { transcript_html, anchors }

async function renderTranscript() {
  const body = drawer.querySelector('.assist-body');
  const t = ctx.transcript;
  if (!t || ctx.mock) { body.replaceChildren(h('p', { class: 'muted' }, 'The transcript is only available in practice mode.')); return; }
  const id = t.attemptId(), part = t.part();
  if (!id) { body.replaceChildren(h('p', { class: 'muted' }, 'Start the test to read along with the part you are listening to.')); return; }
  const key = `${id}.${part}`;
  let data = transcripts.get(key);
  if (!data) {
    body.replaceChildren(h('p', { class: 'muted small' }, 'Loading…'));
    try { data = await api.get(`/api/attempts/${id}/transcript`, { part }); transcripts.set(key, data); }
    catch (e) { body.replaceChildren(h('p', { class: 'muted' }, e.message)); return; }
    if (drawer?.dataset.tab !== 'transcript' || t.part() !== part) return;  // moved on while loading
  }
  const text = h('div', { class: 'assist-doc transcript-text',
    html: sanitizeContent(data.transcript_html || '<p class="muted">No transcript for this part.</p>') });
  // shows the line around the question on screen, without marking the answer itself
  const find = h('button', { class: 'btn sm', type: 'button', html: `${icon('target')} Find my question`, onclick: () => {
    const n = t.question();
    const block = data.anchors?.[n] && excerptBlock(text, excerptPieces(data.anchors[n])[0]);
    if (block) flash(block); else toast(`No transcript location for question ${n}.`);
  } });
  body.replaceChildren(
    h('div', { class: 'assist-sticky' },
      h('div', { class: 'row between' }, h('b', null, `Part ${part} transcript`), find),
      h('div', { class: 'small muted', style: { marginTop: '4px' } }, 'Practice aid: read along when the audio is hard to follow. Off in exam mode.')),
    text);
  keepScroll(body, 'transcript', `scroll.${key}`);
}

/** `text` comes from "open in the assistant"; otherwise the last text is shown again with its translation. */
function renderTranslate(text) {
  const body = drawer.querySelector('.assist-body');
  const area = h('textarea', { class: 'input', rows: '4', placeholder: 'Type or paste English (or Azerbaijani) text…', 'aria-label': 'Text to translate' });
  if (text === undefined) text = memory('translate').text || '';
  area.value = text;
  const out = h('div', { class: 'assist-result' });
  const go = async () => {
    if (!area.value.trim()) return;
    remember('translate', { text: area.value });
    out.replaceChildren(await translationView(area.value.trim(), langSelect.value));
  };
  const langSelect = langPicker(go);
  area.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) go(); });
  area.addEventListener('input', debounce(() => remember('translate', { text: area.value }), 300));
  body.replaceChildren(area,
    h('div', { class: 'row', style: { gap: '8px', margin: '8px 0' } },
      h('button', { class: 'btn primary sm', type: 'button', html: `${icon('translate')} Translate`, onclick: go }),
      h('span', { class: 'small muted' }, 'to'), langSelect, h('span', { class: 'small muted' }, 'Ctrl+Enter')),
    out);
  if (text) go(); else setTimeout(() => area.focus(), 0);
}

function langPicker(onChange) {
  const s = h('select', { class: 'input sm', 'aria-label': 'Target language' },
    ...Object.entries(LANGS).map(([k, v]) => h('option', { value: k, selected: k === settings.translate_to ? '' : null }, v)));
  s.addEventListener('change', () => {
    settings.translate_to = s.value;
    api.put('/api/settings', { translate_to: s.value }).catch(() => {});
    onChange && onChange();
  });
  return s;
}

// ------------------------------------------------------------------ translation result
async function translationView(text, to) {
  const box = h('div', { class: 'tr-view' }, h('p', { class: 'muted small' }, 'Translating…'));
  try {
    const r = await api.get('/api/translate', { q: text, to: to || settings.translate_to });
    box.replaceChildren();
    const d = r.dictionary;
    const isWord = !!d || /^[A-Za-z][A-Za-z'-]*$/.test(text);
    if (isWord) {
      const head = h('div', { class: 'tr-word' }, h('b', null, text), d?.phonetic ? h('span', { class: 'muted' }, ` ${d.phonetic}`) : '');
      if (d?.audio) {
        const a = new Audio(d.audio);
        head.append(h('button', { class: 'icon-btn', type: 'button', title: 'Pronunciation', 'aria-label': 'Play pronunciation', html: icon('speaker'), onclick: () => a.play().catch(() => {}) }));
      }
      box.append(head);
    }
    box.append(h('div', { class: 'tr-main' }, r.translation));
    for (const w of r.words || []) box.append(h('div', { class: 'small' }, h('span', { class: 'tr-pos' }, w.pos || ''), ' ', w.terms.join(', ')));
    if (d?.meanings?.length) {
      const defs = h('details', { class: 'tr-defs' }, h('summary', { class: 'small' }, 'English definitions'));
      for (const m of d.meanings) {
        defs.append(h('div', { class: 'small' }, h('span', { class: 'tr-pos' }, m.pos || ''),
          h('ol', null, ...m.definitions.map((x) => h('li', null, x.definition, x.example ? h('div', { class: 'muted' }, `“${x.example}”`) : '')))));
      }
      box.append(defs);
    }
    if (isWord && text.split(/\s+/).length <= 4) {
      box.append(h('button', { class: 'btn sm', type: 'button', html: `${icon('plus')} Add to my flashcards`, onclick: async (e) => {
        try {
          const example = d?.meanings?.flatMap((m) => m.definitions).find((x) => x.example)?.example || '';
          await api.post('/api/vocab', { term: text, meaning: [r.translation, ...(r.words || []).flatMap((w) => w.terms.slice(0, 2))].filter((v, i, a) => v && a.indexOf(v) === i).join(', '), example, topic: 'My words' });
          e.target.closest('button').replaceWith(h('span', { class: 'small good' }, '✓ Added to “My words” flashcards'));
        } catch (err) { toast(err.message, 'error'); }
      } }));
    }
    box.append(h('div', { class: 'tr-src small muted' }, `${r.provider === 'mymemory' ? 'MyMemory' : 'Google Translate'}${r.cached ? ' · saved' : ''}`));
  } catch (e) {
    box.replaceChildren(h('p', { class: 'small bad' }, e.message || 'Translation failed.'));
  }
  return box;
}

// ------------------------------------------------------------------ select text -> translate
let chip = null, pop = null;
function closeChip() { chip?.remove(); chip = null; }
function closePop() { pop?.remove(); pop = null; }

/** Show the translation popover for `text` near a viewport rect (also used by the passage highlighter). */
export async function translatePopover(text, rect) {
  if (!enabled()) return;
  closeChip(); closePop();
  pop = h('div', { class: 'tr-pop', role: 'dialog', 'aria-label': 'Translation' },
    h('div', { class: 'row between', style: { marginBottom: '4px' } },
      langPicker(async () => { const v = await translationView(text, settings.translate_to); pop?.querySelector('.tr-view')?.replaceWith(v); }),
      h('div', null,
        h('button', { class: 'icon-btn', type: 'button', title: 'Open in the assistant', 'aria-label': 'Open in the assistant', html: icon('arrowRight'), onclick: () => { closePop(); openDrawer('translate', { text }); } }),
        h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', html: icon('close'), onclick: closePop }))),
    h('div', { class: 'tr-view' }, h('p', { class: 'muted small' }, 'Translating…')));
  document.body.append(pop);
  place(pop, rect);
  const view = await translationView(text, settings.translate_to);
  if (pop) { pop.querySelector('.tr-view').replaceWith(view); place(pop, rect); }
}

function place(el, rect) {
  const r = el.getBoundingClientRect();
  const below = rect.bottom + 8 + r.height < window.innerHeight;
  el.style.left = `${Math.max(8, Math.min(window.innerWidth - r.width - 8, rect.left + rect.width / 2 - r.width / 2))}px`;
  el.style.top = `${below ? rect.bottom + 8 : Math.max(8, rect.top - r.height - 8)}px`;
}

export function installSelectionTranslator() {
  document.addEventListener('focusin', (e) => {
    if (e.target.matches?.('textarea') && !e.target.closest('.assist-drawer, .tr-pop')) lastTextarea = e.target;
  });
  document.addEventListener('mouseup', (e) => {
    if (pop?.contains(e.target) || chip?.contains(e.target) || drawer?.contains(e.target) && e.target.closest('textarea,input')) return;
    setTimeout(() => {
      closeChip();
      if (!enabled()) return;
      const sel = window.getSelection();
      const text = sel && !sel.isCollapsed ? sel.toString().trim() : '';
      if (!text || text.length > 2000) return;
      const node = sel.anchorNode?.nodeType === 1 ? sel.anchorNode : sel.anchorNode?.parentElement;
      // the reading passage has its own popup (Highlight / Clear / Translate)
      if (!node || node.closest('[data-hl-root], input, textarea, .tr-pop, .assist-tabs, button')) return;
      const rect = sel.getRangeAt(0).getBoundingClientRect();
      chip = h('button', { class: 'tr-chip', type: 'button', html: `${icon('translate')} Translate`,
        onmousedown: (ev) => ev.preventDefault(), onclick: () => translatePopover(text, rect) });
      document.body.append(chip);
      place(chip, rect);
    }, 0);
  });
  document.addEventListener('mousedown', (e) => {
    if (chip && !chip.contains(e.target)) closeChip();
    if (pop && !pop.contains(e.target)) closePop();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeChip(); closePop(); if (drawer && document.activeElement?.closest?.('.assist-drawer')) closeDrawer(); }
    if (e.altKey && (e.key === 'h' || e.key === 'H')) { e.preventDefault(); if (drawer?.isConnected) closeDrawer(); else openDrawer(); }
  });
  window.addEventListener('scroll', () => { closeChip(); }, { passive: true, capture: true });
}
