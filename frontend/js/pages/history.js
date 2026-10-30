// History: every attempt, essay, speaking session, mock and AI analysis in one filterable table.
import { api } from '../api.js';
import { h, esc, icon, withStates, emptyState, fmtDate, fmtBand, fmtDuration, asList, store, debounce, parseDate } from '../ui.js';
import { providerName, providerBadge } from '../state.js';
import { modeLabel } from './speaking.js';
import { confirmDeleteAttempt } from './result.js';
import { setTitle } from '../app.js';

const KINDS = [
  ['all', 'All'], ['listening', 'Listening'], ['reading', 'Reading'], ['writing', 'Writing'],
  ['speaking', 'Speaking'], ['mock', 'Mocks'], ['analysis', 'AI analyses'],
];

function targetLink(t, id) {
  return { attempt: `#/result/${id}`, writing: `#/writing/submission/${id}`, speaking_session: `#/speaking/session/${id}`, mock: `#/mock/${id}`, progress: '#/' }[t] || '#/history';
}

export async function render(root) {
  setTitle('History');
  const f = store.get('historyFilter', { kind: 'all', q: '' });
  root.replaceChildren(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'History'), h('p', null, 'Everything you have done in the app, newest first.'))));
  const toolbar = h('div', { class: 'toolbar' });
  const body = h('div');
  root.append(toolbar, body);

  await withStates(body, async () => {
    const safe = (p) => p.catch((e) => { console.warn(e); return []; });
    const [attempts, subs, sessions, mocks, analyses] = await Promise.all([
      safe(api.get('/api/attempts', { limit: 1000 })), safe(api.get('/api/writing/submissions', { limit: 1000 })),
      safe(api.get('/api/speaking/sessions', { limit: 500 })), safe(api.get('/api/mock')), safe(api.get('/api/ai/analyses', { limit: 500 })),
    ]);
    const rows = [];
    for (const a of asList(attempts)) {
      rows.push({
        kind: a.type, date: a.finished_at || a.started_at, title: a.title || a.test_id,
        detail: a.mode === 'imported' ? 'Imported · band only'
          : a.status === 'submitted' ? `${a.raw_score ?? '?'}/${a.total ?? 40} · ${fmtDuration(a.duration_sec)}` : '',
        band: a.band, status: a.status === 'submitted' ? '' : 'In progress', mode: a.mode,
        attempt: a.mode === 'imported' ? null : a,   // deletable here (imported bands live in My Results.docx)
        href: a.status === 'submitted' ? `#/result/${a.id}` : `#/test/${encodeURIComponent(a.test_id)}/${a.id}${a.mock_id ? `?mode=mock&mock=${a.mock_id}` : ''}`,
      });
    }
    for (const s of asList(subs)) {
      rows.push({
        kind: 'writing', date: s.created_at, title: `Task ${s.task ?? '?'} — ${s.prompt_excerpt || ''}`,
        detail: `${s.word_count ?? '?'} words${s.time_spent_sec ? ' · ' + fmtDuration(s.time_spent_sec) : ''}`, band: s.band,
        status: s.origin === 'telegram_import' ? 'Telegram' : '', mode: s.mock_id ? 'mock' : '', href: `#/writing/submission/${s.id}`,
      });
    }
    for (const s of asList(sessions)) {
      rows.push({ kind: 'speaking', date: s.created_at, title: s.notes ? `Speaking — ${s.notes}` : `Speaking — ${modeLabel(s.mode)}`,
        detail: s.teacher_band != null ? 'Imported · teacher band' : `${s.responses ?? 0} answers`, band: s.band ?? s.teacher_band,
        mode: s.mock_id ? 'mock' : '', href: `#/speaking/session/${s.id}` });
    }
    for (const m of asList(mocks)) {
      rows.push({ kind: 'mock', date: m.finished_at || m.created_at, title: `Mock exam #${m.id}`,
        detail: `L ${fmtBand(m.listening_band)} · R ${fmtBand(m.reading_band)} · W ${fmtBand(m.writing_band)} · S ${fmtBand(m.speaking_band)}`,
        band: m.overall_band, status: m.status === 'finished' ? '' : 'In progress', href: `#/mock/${m.id}` });
    }
    for (const a of asList(analyses)) {
      const res = typeof a.result_json === 'object' && a.result_json ? a.result_json : null;
      rows.push({ kind: 'analysis', date: a.created_at, title: `AI analysis — ${a.target_type.replace('_', ' ')}${a.target_type === 'progress' ? '' : ' #' + a.target_id}`,
        detail: providerName(a.provider), band: res?.band ?? null, status: a.status === 'done' ? '' : a.status, provider: a.provider, href: targetLink(a.target_type, a.target_id) });
    }
    rows.sort((x, y) => (parseDate(y.date)?.getTime() || 0) - (parseDate(x.date)?.getTime() || 0));
    return rows;
  }, (rows) => {
    const counts = Object.fromEntries(KINDS.map(([k]) => [k, k === 'all' ? rows.length : rows.filter((r) => r.kind === k).length]));
    const chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Type' });
    const drawChips = () => chips.replaceChildren(...KINDS.map(([k, l]) => h('button', { class: 'chip', type: 'button', 'aria-pressed': String(f.kind === k), onclick: () => { f.kind = k; drawChips(); draw(); } }, `${l} · ${counts[k]}`)));
    drawChips();
    const search = h('div', { class: 'search' }, h('span', { html: icon('search') }), h('input', { class: 'input', type: 'search', placeholder: 'Filter…', value: f.q, 'aria-label': 'Filter history' }));
    search.querySelector('input').addEventListener('input', debounce((e) => { f.q = e.target.value; draw(); }, 150));
    toolbar.replaceChildren(search, chips);
    const table = h('div', { class: 'card table-wrap' });
    body.append(table);
    function draw() {
      store.set('historyFilter', f);
      const q = f.q.trim().toLowerCase();
      const shown = rows.filter((r) => (f.kind === 'all' || r.kind === f.kind) && (!q || `${r.title} ${r.detail} ${r.kind}`.toLowerCase().includes(q)));
      if (!shown.length) { table.replaceChildren(emptyState('Nothing to show', rows.length ? 'Try another filter.' : 'Start practising and your history will appear here.', 'history')); return; }
      table.innerHTML = `<table class="table"><thead><tr><th>Date</th><th>Type</th><th>Item</th><th>Details</th><th>Band</th><th></th></tr></thead><tbody>
        ${shown.slice(0, 500).map((r) => `<tr>
          <td class="nowrap">${esc(fmtDate(r.date))}</td>
          <td><span class="badge ${r.kind === 'analysis' ? 'accent' : ''}">${esc(KINDS.find((k) => k[0] === r.kind)?.[1] || r.kind)}</span>${r.mode === 'mock' ? ' <span class="badge">mock</span>' : ''}</td>
          <td style="max-width:420px"><a href="${r.href}" style="color:inherit;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.title)}</a></td>
          <td class="small muted">${r.provider ? `<span class="prov-badge ${esc(r.provider)}">${esc(providerBadge(r.provider))}</span> ` : ''}${esc(r.detail || '')}${r.status ? ` <span class="badge warn">${esc(r.status)}</span>` : ''}</td>
          <td>${r.band != null ? `<span class="band-pill">${fmtBand(r.band)}</span>` : '<span class="muted small">–</span>'}</td>
          <td class="nowrap"><a class="btn sm ghost" href="${r.href}">Open</a>${r.attempt ? `<button class="icon-btn sm-del" type="button" data-del="${r.attempt.id}" title="Delete this result" aria-label="Delete this result">${icon('trash')}</button>` : ''}</td></tr>`).join('')}</tbody></table>
        ${shown.length > 500 ? '<p class="small muted" style="padding:10px 14px">Showing the latest 500.</p>' : ''}`;
    }
    table.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-del]');
      if (!b) return;
      const i = rows.findIndex((r) => r.attempt && String(r.attempt.id) === b.dataset.del);
      if (i < 0 || !(await confirmDeleteAttempt(rows[i].attempt))) return;
      rows.splice(i, 1);
      draw();
    });
    draw();
  });
}
