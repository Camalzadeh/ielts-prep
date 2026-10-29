// Listening / Reading test library grouped by series.
import { api } from '../api.js';
import { h, esc, icon, withStates, emptyState, fmtBand, store, asList, debounce } from '../ui.js';
import { setTitle } from '../app.js';

export async function render(root, params) {
  const type = params[0] === 'reading' ? 'reading' : 'listening';
  const label = type === 'reading' ? 'Reading' : 'Listening';
  setTitle(label);
  const filt = store.get(`libFilter.${type}`, { q: '', status: 'all', series: '' });

  root.replaceChildren();
  const head = h('div', { class: 'page-head' },
    h('div', null, h('h1', null, `${label} tests`),
      h('p', null, type === 'reading'
        ? 'Academic reading — 3 passages, 40 questions, 60 minutes. Highlight text, resize panes, review every answer.'
        : 'Computer-delivered style listening — 4 parts, 40 questions, 30 minutes.')),
    h('div', { class: 'page-actions' }));
  const toolbar = h('div', { class: 'toolbar' });
  const list = h('div');
  root.append(head, toolbar, list);

  await withStates(list, () => Promise.all([
    api.get('/api/tests', { type }),
    api.get('/api/attempts', { type, limit: 500 }).catch(() => []),
  ]), ([data, attemptsData]) => {
    const tests = asList(data, 'tests');
    const lastAttempt = new Map();
    for (const a of asList(attemptsData, 'attempts')) {
      if (a.status && a.status !== 'submitted') continue;
      const prev = lastAttempt.get(a.test_id);
      if (!prev || (a.id || 0) > prev) lastAttempt.set(a.test_id, a.id);
    }
    for (const t of tests) if (!t.last_attempt_id && lastAttempt.has(t.id)) t.last_attempt_id = lastAttempt.get(t.id);
    if (!tests.length) {
      list.append(emptyState(`No ${label.toLowerCase()} tests yet`, 'Tests appear here after the scrapers write JSON into content/tests and the content is (re)imported (Settings → Reimport content).', type));
      return;
    }
    const seriesList = [...new Set(tests.map((t) => t.series || 'Other'))];
    seriesList.sort(seriesSort);

    const search = h('div', { class: 'search' }, h('span', { html: icon('search') }),
      h('input', { class: 'input', type: 'search', placeholder: `Search ${label.toLowerCase()} tests…`, value: filt.q, 'aria-label': 'Search tests' }));
    const seriesSel = h('select', { class: 'select', 'aria-label': 'Series' }, h('option', { value: '' }, 'All series'),
      ...seriesList.map((s) => h('option', { value: s, selected: filt.series === s }, s)));
    const chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Status filter' });
    const statuses = [['all', 'All'], ['new', 'Not attempted'], ['done', 'Completed'], ['progress', 'In progress']];
    const drawChips = () => chips.replaceChildren(...statuses.map(([k, l]) => h('button', {
      class: 'chip', type: 'button', 'aria-pressed': String(filt.status === k),
      onclick: () => { filt.status = k; drawChips(); draw(); },
    }, l)));
    drawChips();
    const random = h('button', { class: 'btn', type: 'button', html: `${icon('shuffle')} Random unseen`, onclick: () => {
      const pool = tests.filter((t) => !t.attempts);
      const pick = (pool.length ? pool : tests)[Math.floor(Math.random() * (pool.length || tests.length))];
      location.hash = `#/test/${encodeURIComponent(pick.id)}`;
    } });
    toolbar.append(search, seriesSel, chips, h('div', { class: 'spacer' }), random);
    const input = search.querySelector('input');
    input.addEventListener('input', debounce(() => { filt.q = input.value; draw(); }, 120));
    seriesSel.addEventListener('change', () => { filt.series = seriesSel.value; draw(); });

    const total = tests.length, done = tests.filter((t) => t.attempts).length;
    head.querySelector('.page-actions').append(h('span', { class: 'badge' }, `${done} / ${total} completed`));

    function draw() {
      store.set(`libFilter.${type}`, filt);
      const q = filt.q.trim().toLowerCase();
      const shown = tests.filter((t) => {
        const inProg = !!(store.get(`active.${t.id}.practice.`) || t.in_progress_attempt);
        if (q && !`${t.title} ${t.series} ${t.id}`.toLowerCase().includes(q)) return false;
        if (filt.series && (t.series || 'Other') !== filt.series) return false;
        if (filt.status === 'new' && (t.attempts || inProg)) return false;
        if (filt.status === 'done' && !t.attempts) return false;
        if (filt.status === 'progress' && !inProg) return false;
        return true;
      });
      list.replaceChildren();
      if (!shown.length) { list.append(emptyState('No tests match', 'Try a different search or filter.', 'search')); return; }
      const bySeries = new Map();
      for (const t of shown) {
        const s = t.series || 'Other';
        if (!bySeries.has(s)) bySeries.set(s, []);
        bySeries.get(s).push(t);
      }
      for (const s of [...bySeries.keys()].sort(seriesSort)) {
        const items = bySeries.get(s).sort((a, b) => (a.test_no ?? 99) - (b.test_no ?? 99) || String(a.title).localeCompare(b.title));
        const block = h('section', { class: 'series-block' },
          h('div', { class: 'series-head' }, h('h2', null, s), h('span', { class: 'muted small' }, `${items.length} test${items.length > 1 ? 's' : ''}`)));
        const grid = h('div', { class: 'test-grid' });
        for (const t of items) grid.append(testCard(t, type));
        block.append(grid);
        list.append(block);
      }
    }
    draw();
  });
}

function seriesSort(a, b) {
  const na = (a.match(/(\d+)/) || [])[1], nb = (b.match(/(\d+)/) || [])[1];
  const ca = /cambridge/i.test(a), cb = /cambridge/i.test(b);
  if (ca !== cb) return ca ? -1 : 1;
  if (na && nb) return Number(na) - Number(nb);
  return a.localeCompare(b);
}

function testCard(t, type) {
  const active = store.get(`active.${t.id}.practice.`) || t.in_progress_attempt;
  const short = t.test_no ? `Test ${t.test_no}` : t.title;
  const card = h('article', { class: `card test-card${t.attempts ? ' done' : ''}` });
  card.innerHTML = `
    <div>
      <div class="t-title">${esc(short)}</div>
      <div class="small muted" title="${esc(t.title)}" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.title)}</div>
    </div>
    <div class="t-bands">
      <div class="t-band">Best<span class="band-pill ${t.best_band == null ? 'none' : ''}">${fmtBand(t.best_band)}</span></div>
      <div class="t-band">Last<span class="band-pill ${t.last_band == null ? 'none' : ''}">${fmtBand(t.last_band)}</span></div>
      <div class="t-band">Attempts<b style="font-size:15px;color:var(--text)">${t.attempts || 0}</b></div>
    </div>
    <div class="t-meta"><span>${t.question_count || 40} questions</span>${active ? '<span class="badge warn">In progress</span>' : ''}</div>`;
  const actions = h('div', { class: 't-actions' });
  if (active) {
    actions.append(h('a', { class: 'btn primary sm', href: `#/test/${encodeURIComponent(t.id)}/${active}` }, 'Resume'));
  } else {
    actions.append(h('a', { class: 'btn primary sm', href: `#/test/${encodeURIComponent(t.id)}` }, t.attempts ? 'Retake' : 'Start'));
  }
  if (t.attempts && t.last_attempt_id) actions.append(h('a', { class: 'btn sm', href: `#/result/${t.last_attempt_id}` }, 'Review'));
  card.append(actions);
  return card;
}
