// Learn: knowledge base (markdown), the Writing notes (konspekt, EN / AZ), vocabulary flashcards (SM-2).
import { api } from '../api.js';
import { h, esc, icon, toast, withStates, emptyState, renderMarkdown, asList, debounce, store, loading, errorState, zoomImage } from '../ui.js';
import { navigate, nav, setTitle } from '../app.js';

export async function render(root, params, query) {
  const [sub, slug] = params;
  const tab = sub === 'vocab' ? 'vocab' : sub === 'konspekt' ? 'konspekt' : 'kb';
  setTitle(tab === 'vocab' ? 'Vocabulary' : tab === 'konspekt' ? 'Writing notes' : 'Learn');
  root.replaceChildren(h('div', { class: 'page-head' },
    h('div', null, h('h1', null, 'Learn'), h('p', null, 'Strategies, model answers and vocabulary curated from your study archives.'))));
  const tabs = h('div', { class: 'tabs', role: 'tablist' },
    h('a', { href: '#/learn', role: 'tab', 'aria-selected': String(tab === 'kb') }, 'Knowledge base'),
    h('a', { href: '#/learn/konspekt', role: 'tab', 'aria-selected': String(tab === 'konspekt') }, 'Writing notes'),
    h('a', { href: '#/learn/vocab', role: 'tab', 'aria-selected': String(tab === 'vocab') }, 'Vocabulary flashcards'));
  const body = h('div');
  root.append(tabs, body);
  if (tab === 'vocab') return renderVocab(body);
  if (tab === 'konspekt') return renderKonspekt(body, query.s || '');
  return renderKb(body, slug ? decodeURIComponent(slug) : null, query.q || '');
}

// ------------------------------------------------------------------ writing notes (konspekt)
// Static guide built from the teacher's handouts, in English (konspekt/writing.en.html) or Azerbaijani
// (konspekt/writing.html), plus two live panels computed from the learner's own essays. The routes are
// hash-based, so in-page links (#t1-line) are intercepted and scrolled to instead of navigated.
const KONSPEKT_URL = { en: 'konspekt/writing.en.html', az: 'konspekt/writing.html' };
const MIN_WORDS = { 1: 150, 2: 250 };
const KT = {
  en: {
    load: 'Could not load the notes', colour: 'Colour the essay structure', mine: 'Your essays', mineTask: (n) => `Your Task ${n} essays`,
    loadMine: 'Could not load your essays', src: 'from the app: essays you wrote in Writing and imported teacher marks',
    none: (n) => `No Task ${n} essays yet. As you write in Writing, your word counts and bands appear here.`,
    essays: 'essays', under: (m) => `under ${m} words`, avg: 'average band', short: (m) => `Essays under ${m} words`, words: 'words',
    tip1: 'Write 4–5 sentences in each body paragraph: the start, the change and the final figure for each category.',
    tip2: 'Make each body paragraph 5–6 sentences (TEER) and you get 280+ words. Under 250 words lowers your TR band.',
    allOk: (m) => `All your essays are ${m}+ words`, keep: 'Keep it up.', bands: 'Bands (oldest to newest)', teacher: 'teacher',
    bandNote: 'The teacher’s band if there is one, otherwise the AI band. Click an essay for the full feedback.',
  },
  az: {
    load: 'Konspekti yükləmək olmadı', colour: 'Esse strukturunu rənglə', mine: 'Sənin yazıların', mineTask: (n) => `Sənin Task ${n} yazıların`,
    loadMine: 'Yazıları yükləmək olmadı', src: 'proqramdakı bazadan: Writing bölməsində yazdıqların və idxal olunmuş müəllim qiymətləri',
    none: (n) => `Hələ Task ${n} yazın yoxdur. Writing bölməsində yazdıqca burada söz sayın və qiymətlərin görünəcək.`,
    essays: 'yazı', under: (m) => `${m} sözdən az`, avg: 'orta qiymət', short: (m) => `${m} sözə çatmayan yazılar`, words: 'söz',
    tip1: 'Hər body abzasında 4–5 cümlə yaz: hər kateqoriya üçün başlanğıc, dəyişiklik və son rəqəm.',
    tip2: 'Hər body abzası 5–6 cümlə olsun (TEER), onda avtomatik 280+ söz alınır. 250-dən az TR balını kəsir.',
    allOk: (m) => `Bütün yazıların ${m}+ sözdür`, keep: 'Belə davam et.', bands: 'Qiymətlər (köhnədən yeniyə)', teacher: 'müəllim',
    bandNote: 'Müəllimin qiyməti varsa o, yoxdursa AI qiyməti göstərilir. Ətraflı rəy üçün yazıya kliklə.',
  },
};

async function renderKonspekt(body, startSection) {
  body.replaceChildren(loading());
  const lang = store.get('konspektLang', 'en') === 'az' ? 'az' : 'en';
  const t = KT[lang];
  let html;
  try {
    const r = await fetch(KONSPEKT_URL[lang], { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${t.load} (HTTP ${r.status})`);
    html = await r.text();
  } catch (e) {
    body.replaceChildren(errorState(e, () => renderKonspekt(body, startSection)));
    return;
  }

  const hlOn = store.get('konspektHl', true);
  const page = h('div', { class: `wk${hlOn ? ' hl' : ''}` });
  page.innerHTML = html;

  // contents rail, built from the parts (Task 1 / Task 2) and each sheet's heading
  const toc = h('nav', { class: 'card kb-nav wk-toc', 'aria-label': 'Konspekt contents' });
  const toggle = h('input', { type: 'checkbox', id: 'wk-hl', checked: hlOn });
  toggle.addEventListener('change', () => { page.classList.toggle('hl', toggle.checked); store.set('konspektHl', toggle.checked); });
  // language switch: English / Azərbaycanca (remembered)
  toc.append(h('div', { class: 'chips wk-lang', role: 'group', 'aria-label': 'Language' },
    ...[['en', 'English'], ['az', 'Azərbaycanca']].map(([k, l]) => h('button', { class: 'chip', type: 'button', 'aria-pressed': String(lang === k),
      onclick: () => { if (k === lang) return; store.set('konspektLang', k); renderKonspekt(body, startSection); } }, l))));
  toc.append(h('label', { class: 'wk-tools', for: 'wk-hl' }, toggle, t.colour));
  const links = [];
  for (const el of page.querySelectorAll('.part, .sheet[id]')) {
    if (el.classList.contains('part')) { toc.append(h('div', { class: 'kb-cat' }, el.querySelector('.tag')?.textContent || '')); continue; }
    const title = el.dataset.me ? t.mine : (el.querySelector(':scope > h3')?.textContent || el.id).replace(/^\d+\.\s*/, '');
    const a = h('a', { href: `#/learn/konspekt?s=${el.id}`, 'data-target': el.id }, title);
    links.push(a);
    toc.append(a);
  }

  const goTo = (id, smooth = true) => {
    const el = id && page.querySelector(`#${CSS.escape(id)}`);
    if (!el) return false;
    el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
    history.replaceState(null, '', `#/learn/konspekt?s=${id}`);
    nav.lastHash = location.hash;
    return true;
  };
  // in-page links (#t2-opinion) and rail links scroll instead of routing
  const onClick = (e) => {
    const a = e.target.closest('a[href]');
    if (a) {
      const href = a.getAttribute('href');
      const id = a.dataset.target || (href.startsWith('#') && !href.startsWith('#/') ? href.slice(1) : null);
      if (id && goTo(id)) e.preventDefault();
      return;
    }
    const img = e.target.closest('.essay figure img');
    if (img) zoomImage(img.src, img.alt);
  };
  page.addEventListener('click', onClick);
  toc.addEventListener('click', onClick);

  body.replaceChildren(h('div', { class: 'wk-layout' }, toc, page));
  fillMyEssays(page, t);

  // highlight the rail entry for the section in view
  const spy = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      links.forEach((a) => a.classList.toggle('active', a.dataset.target === en.target.id));
    }
  }, { rootMargin: '-80px 0px -70% 0px' });
  page.querySelectorAll('.sheet[id]').forEach((s) => spy.observe(s));

  if (startSection) requestAnimationFrame(() => goTo(startSection, false));
  return () => spy.disconnect();
}

// "Your essays": word counts against the minimum and marks, per task, from the DB.
async function fillMyEssays(page, t) {
  const slots = page.querySelectorAll('[data-me]');
  if (!slots.length) return;
  let subs = [];
  try {
    subs = asList(await api.get('/api/writing/submissions', { limit: 500 }));
  } catch (e) {
    slots.forEach((s) => s.replaceChildren(h('h3', null, t.mine), h('p', { class: 'muted' }, `${t.loadMine}: ${e.message}`)));
    return;
  }
  for (const slot of slots) {
    const task = Number(slot.dataset.me);
    const min = MIN_WORDS[task];
    const mine = subs.filter((s) => s.task === task && s.word_count != null);
    slot.replaceChildren(h('h3', null, t.mineTask(task)), h('p', { class: 'src' }, t.src));
    if (!mine.length) {
      slot.append(h('p', { class: 'muted' }, t.none(task)));
      continue;
    }
    const short = mine.filter((s) => s.word_count < min);
    const bands = mine.map((s) => ({ s, band: s.teacher_band ?? s.band })).filter((x) => x.band != null);
    const avg = bands.length ? bands.reduce((t, x) => t + x.band, 0) / bands.length : null;
    const stat = (value, label) => h('div', { class: 'me-stat' }, h('b', null, value), h('span', null, label));
    slot.append(h('div', { class: 'me-stats' },
      stat(String(mine.length), t.essays),
      stat(String(short.length), t.under(min)),
      stat(avg == null ? '—' : avg.toFixed(1), t.avg)));

    const cols = h('div', { class: 'cols' });
    if (short.length) {
      cols.append(h('div', { class: 'note me' }, h('b', null, t.short(min)),
        h('ul', null, ...short.slice(0, 8).map((s) => h('li', null,
          h('a', { href: `#/writing/submission/${s.id}` }, `${fmtDate(s.created_at)} · ${s.essay_type || 'essay'}`), ` — ${s.word_count} ${t.words}`))),
        h('p', null, task === 1 ? t.tip1 : t.tip2)));
    } else {
      cols.append(h('div', { class: 'note' }, h('b', { class: 'ok' }, t.allOk(min)), h('p', null, t.keep)));
    }
    if (bands.length) {
      const cls = (b) => (b < 6 ? 'lo' : b >= 7 ? 'hi' : '');
      cols.append(h('div', { class: 'note' }, h('b', null, t.bands),
        h('div', { class: 'me-bands' }, ...bands.slice().reverse().map(({ s, band }) =>
          h('a', { class: `me-band ${cls(band)}`, href: `#/writing/submission/${s.id}`, title: `${fmtDate(s.created_at)} · ${s.essay_type || ''}${s.teacher_band != null ? ` · ${t.teacher}` : ' · AI'}` }, band.toFixed(1)))),
        h('p', { class: 'small muted', style: { marginTop: '8px' } }, t.bandNote)));
    }
    slot.append(cols);
  }
}

const fmtDate = (s) => (s ? String(s).slice(0, 10) : '');

const CAT_LABELS = {
  'writing-task1': 'Writing Task 1', 'writing-task2': 'Writing Task 2', writing: 'Writing', speaking: 'Speaking',
  reading: 'Reading', listening: 'Listening', vocabulary: 'Vocabulary', grammar: 'Grammar', general: 'General',
};
const catLabel = (c) => CAT_LABELS[c] || (c ? c.replace(/[-_]/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase()) : 'Other');

function stripFrontMatter(md) {
  return (md || '').replace(/^﻿?---\r?\n[\s\S]*?\r?\n---\r?\n?/, '');
}

async function renderKb(body, slug, initialQ) {
  const layout = h('div', { class: 'kb-layout' });
  const navCard = h('nav', { class: 'card kb-nav', 'aria-label': 'Knowledge base' });
  const article = h('article', { class: 'card kb-article' });
  layout.append(navCard, article);
  body.replaceChildren(layout);

  const search = h('div', { class: 'search', style: { marginBottom: '6px' } }, h('span', { html: icon('search') }),
    h('input', { class: 'input', type: 'search', placeholder: 'Search the knowledge base…', value: initialQ, 'aria-label': 'Search knowledge base' }));
  const listEl = h('div');
  navCard.append(search, listEl);

  let docs = [];
  try {
    docs = asList(await api.get('/api/kb'), 'docs');
  } catch (e) {
    listEl.append(errorState(e));
  }
  const drawList = (results) => {
    listEl.replaceChildren();
    if (results) {
      if (!results.length) { listEl.append(h('p', { class: 'muted small', style: { padding: '8px' } }, 'No matches.')); return; }
      listEl.append(h('div', { class: 'kb-cat' }, `${results.length} result${results.length > 1 ? 's' : ''}`));
      for (const r of results) {
        const a = h('a', { href: `#/learn/kb/${encodeURIComponent(r.slug)}`, class: r.slug === slug ? 'active' : '' }, h('div', null, r.title));
        if (r.snippet) a.append(h('div', { class: 'small muted', html: esc(r.snippet).replace(/\[([^\]]*)\]/g, '<mark class="hl">$1</mark>') }));
        listEl.append(a);
      }
      return;
    }
    if (!docs.length) { listEl.append(h('p', { class: 'muted small', style: { padding: '8px' } }, 'No documents yet.')); return; }
    const byCat = new Map();
    for (const d of docs) { const c = d.category || 'other'; if (!byCat.has(c)) byCat.set(c, []); byCat.get(c).push(d); }
    for (const [c, items] of [...byCat.entries()].sort((a, b) => catLabel(a[0]).localeCompare(catLabel(b[0])))) {
      listEl.append(h('div', { class: 'kb-cat' }, catLabel(c)));
      for (const d of items) listEl.append(h('a', { href: `#/learn/kb/${encodeURIComponent(d.slug)}`, class: d.slug === slug ? 'active' : '', 'aria-current': d.slug === slug ? 'page' : undefined }, d.title));
    }
  };
  const doSearch = async (q) => {
    if (!q.trim()) { drawList(null); return; }
    try { drawList(asList(await api.get('/api/kb/search', { q }))); } catch (e) { listEl.replaceChildren(h('p', { class: 'small', style: { color: 'var(--bad)', padding: '8px' } }, e.message)); }
  };
  search.querySelector('input').addEventListener('input', debounce((e) => doSearch(e.target.value), 250));
  if (initialQ) doSearch(initialQ); else drawList(null);

  if (!slug) {
    // overview
    const byCat = new Map();
    for (const d of docs) { const c = d.category || 'other'; if (!byCat.has(c)) byCat.set(c, []); byCat.get(c).push(d); }
    article.append(h('h2', null, 'Knowledge base'), h('p', { class: 'muted' }, `${docs.length} guides. Pick a topic on the left or search.`));
    if (!docs.length) { article.append(emptyState('Nothing here yet', 'Curated guides from knowledge/kb appear after import.', 'learn')); return; }
    const grid = h('div', { class: 'grid grid-2' });
    for (const [c, items] of byCat) {
      grid.append(h('div', { class: 'card card-pad', style: { background: 'var(--surface-2)' } },
        h('h3', null, catLabel(c)),
        h('ul', { style: { margin: 0, paddingLeft: '1.1em' } }, ...items.slice(0, 8).map((d) => h('li', null, h('a', { href: `#/learn/kb/${encodeURIComponent(d.slug)}` }, d.title)))),
        items.length > 8 ? h('div', { class: 'small muted' }, `+${items.length - 8} more`) : null));
    }
    article.append(grid);
    return;
  }

  article.append(loading());
  try {
    const d = await api.get(`/api/kb/${encodeURIComponent(slug)}`);
    setTitle(d.title || 'Learn');
    const md = h('div', { class: 'md' });
    md.innerHTML = renderMarkdown(stripFrontMatter(d.content_md), { base: '/media/kb/' });
    md.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href');
      const m = href.match(/^(?:\.\/)?([\w-]+)\.md(#.*)?$/);
      if (m) a.setAttribute('href', `#/learn/kb/${m[1]}`);
      else if (href.startsWith('#') && !href.startsWith('#/')) {
        a.addEventListener('click', (e) => { e.preventDefault(); md.querySelector(href)?.scrollIntoView({ behavior: 'smooth' }); });
      }
    });
    md.querySelectorAll('h1, h2, h3').forEach((hd) => { if (!hd.id) hd.id = hd.textContent.toLowerCase().trim().replace(/[^\w]+/g, '-'); });
    const tags = (Array.isArray(d.tags) ? d.tags : String(d.tags || '').replace(/[[\]"]/g, '').split(',')).map((t) => t.trim()).filter(Boolean);
    article.replaceChildren(
      h('div', { class: 'row', style: { marginBottom: '14px' } }, h('span', { class: 'badge accent' }, catLabel(d.category)), ...tags.slice(0, 8).map((t) => h('span', { class: 'badge' }, t))),
      md);
  } catch (e) {
    article.replaceChildren(errorState(e));
  }
}

// ------------------------------------------------------------------ vocabulary
async function renderVocab(body) {
  const f = store.get('vocabFilter', { topic: '', due: true });
  const toolbar = h('div', { class: 'toolbar' });
  const main = h('div');
  body.replaceChildren(toolbar, main);
  const topicSel = h('select', { class: 'select', 'aria-label': 'Topic' }, h('option', { value: '' }, 'All topics'));
  const dueChips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Card selection' });
  const drawChips = () => dueChips.replaceChildren(
    h('button', { class: 'chip', type: 'button', 'aria-pressed': String(f.due), onclick: () => { f.due = true; drawChips(); load(); } }, 'Due for review'),
    h('button', { class: 'chip', type: 'button', 'aria-pressed': String(!f.due), onclick: () => { f.due = false; drawChips(); load(); } }, 'All cards'));
  drawChips();
  const stats = h('span', { class: 'small muted' });
  toolbar.append(topicSel, dueChips, h('div', { class: 'spacer' }), stats);
  try {
    const topics = asList(await api.get('/api/vocab/topics'));
    topicSel.append(...topics.map((t) => h('option', { value: t.topic || '', selected: (t.topic || '') === f.topic }, `${t.topic || 'Untitled'} (${t.due ?? 0} due / ${t.terms})`)));
  } catch { /* optional endpoint */ }
  topicSel.addEventListener('change', () => { f.topic = topicSel.value; load(); });

  let cards = [], i = 0, flipped = false, reviewed = 0;
  let keyHandler = null;
  const load = () => {
    store.set('vocabFilter', f);
    withStates(main, () => api.get('/api/vocab', { topic: f.topic, due: f.due ? 1 : '' }), (data) => {
      cards = asList(data, 'vocab');
      if (f.due) cards = cards.slice(0, 200);
      else cards = shuffle(cards);
      i = 0; reviewed = 0;
      draw();
    });
  };
  const draw = () => {
    main.replaceChildren();
    stats.textContent = cards.length ? `Card ${Math.min(i + 1, cards.length)} of ${cards.length} · ${reviewed} reviewed` : '';
    if (!cards.length) {
      main.append(emptyState(f.due ? 'Nothing due — great work!' : 'No vocabulary yet', f.due ? 'Switch to “All cards” to keep practising.' : 'Vocabulary from knowledge/data/vocabulary.json appears after import.', 'learn'));
      return;
    }
    if (i >= cards.length) {
      main.append(emptyState('Session complete', `You reviewed ${reviewed} card${reviewed === 1 ? '' : 's'}.`, 'check',
        '<button class="btn primary" type="button" id="vocab-again">Load more</button>'));
      main.querySelector('#vocab-again')?.addEventListener('click', load);
      return;
    }
    const c = cards[i];
    flipped = false;
    const card = h('div', { class: 'flashcard', tabindex: '0', role: 'button', 'aria-label': 'Flashcard — press Space to flip' });
    card.innerHTML = `<div class="face front"><div class="small muted" style="margin-bottom:10px">${esc(c.topic || '')}</div><div class="term">${esc(c.term)}</div>
        <div class="small muted" style="margin-top:18px">Click or press Space to reveal</div></div>
      <div class="face back"><div class="small muted" style="margin-bottom:8px">${esc(c.term)}</div><div class="meaning">${esc(c.meaning || '—')}</div>
        ${c.example ? `<div class="example">“${esc(c.example)}”</div>` : ''}
        ${c.reps ? `<div class="small muted" style="margin-top:14px">Reviewed ${c.reps}× · interval ${c.interval_days || 0} d</div>` : ''}</div>`;
    const flip = () => { flipped = !flipped; card.classList.toggle('flipped', flipped); grades.classList.toggle('hidden', !flipped); };
    card.addEventListener('click', flip);
    const grades = h('div', { class: 'grade-btns hidden' });
    const G = [['again', 'Again', 1, '<1 day'], ['', 'Hard', 3, ''], ['good', 'Good', 4, ''], ['', 'Easy', 5, '']];
    G.forEach(([cls, label, grade], k) => grades.append(h('button', { class: `btn ${cls}`, type: 'button', onclick: () => grade_(grade) },
      label, h('small', null, `key ${k + 1}`))));
    async function grade_(g) {
      grades.querySelectorAll('button').forEach((b) => { b.disabled = true; });
      try {
        await api.post(`/api/vocab/${c.id}/review`, { grade: g });
        reviewed++;
        if (g < 3 && f.due) cards.push(c); // see it again this session
        i++;
        draw();
      } catch (e) {
        toast(e.message, 'error');
        grades.querySelectorAll('button').forEach((b) => { b.disabled = false; });
      }
    }
    main.append(h('div', { class: 'flashcard-wrap' }, card), grades,
      h('p', { class: 'small muted', style: { textAlign: 'center', marginTop: '14px' } }, 'Space: flip · 1–4: grade · → skip'));
    if (keyHandler) document.removeEventListener('keydown', keyHandler);
    keyHandler = (e) => {
      if (!main.isConnected) { document.removeEventListener('keydown', keyHandler); return; }
      if (e.target.closest('input, select, textarea')) return;
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); flip(); }
      else if (flipped && ['1', '2', '3', '4'].includes(e.key)) grade_(G[Number(e.key) - 1][2]);
      else if (e.key === 'ArrowRight') { i++; draw(); }
    };
    document.addEventListener('keydown', keyHandler);
    card.focus({ preventScroll: true });
  };
  load();
  return () => { if (keyHandler) document.removeEventListener('keydown', keyHandler); };
}

function shuffle(a) {
  const b = a.slice();
  for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; }
  return b;
}

export { navigate, nav };
