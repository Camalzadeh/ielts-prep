// Progress views: every attempt at one test / prompt (with its band trend) and a per-skill progress card.
// Charts use Chart.js (loaded globally) with the app's own series and text tokens.
import { api } from '../api.js';
import { h, esc, icon, fmtBand, fmtDate, fmtDuration, modal, parseDate, qtypeLabel, asList, store } from '../ui.js';

const SKILL_COLOR = { listening: '--series-1', reading: '--series-2', writing: '--series-3', speaking: '--series-4' };
const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

/** One-series band line (points oldest first: [{label, band, title?}]). Returns {destroy}. */
export function bandLine(canvas, points, { color = '--series-1', name = 'Band' } = {}) {
  if (!window.Chart) { canvas.replaceWith(h('p', { class: 'muted small' }, 'Chart library failed to load.')); return { destroy() {} }; }
  const text = cssVar('--text-3'), grid = cssVar('--border'), surface = cssVar('--surface'), c = cssVar(color);
  const vals = points.map((p) => Number(p.band));
  const lo = Math.max(0, Math.min(4, Math.floor(Math.min(...vals)) - 1));
  const chart = new window.Chart(canvas, {
    type: 'line',
    data: {
      labels: points.map((p) => p.label),
      datasets: [{ label: name, data: vals, borderColor: c, backgroundColor: c, borderWidth: 2, tension: 0.25,
        pointRadius: 4, pointHoverRadius: 6, pointBorderColor: surface, pointBorderWidth: 2 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: { grid: { display: false }, border: { color: grid }, ticks: { color: text, maxTicksLimit: 8 } },
        y: { min: lo, max: 9, ticks: { stepSize: 1, color: text }, grid: { color: grid }, border: { display: false } },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: (it) => points[it[0].dataIndex].title || it[0].label,
          label: (it) => `${name}: ${fmtBand(it.parsed.y)}`,
        } },
      },
    },
  });
  return { destroy: () => chart.destroy() };
}

const shortDate = (d) => { const dt = parseDate(d); return dt ? dt.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : 'no date'; };

/**
 * Pop-up with every attempt at one test (kind 'test', testId) or every essay on one prompt (kind 'writing', promptId),
 * oldest first, with a band trend when two or more are scored. Unfinished test attempts are listed too (Resume).
 */
export async function showAttempts({ kind, testId, promptId, title }) {
  let rows;
  try {
    rows = kind === 'writing'
      ? asList(await api.get('/api/writing/submissions', { prompt_id: promptId, limit: 500 }))
      : asList(await api.get('/api/attempts', { test_id: testId, limit: 500 }));
  } catch (e) { rows = []; }
  const items = rows.map((r) => kind === 'writing'
    ? { date: r.created_at, band: r.teacher_band ?? r.band, bandNote: r.teacher_band != null ? 'teacher' : r.band != null ? 'AI' : '',
        detail: `${r.word_count ?? '?'} words${r.time_spent_sec ? ` · ${fmtDuration(r.time_spent_sec)}` : ''}`,
        mode: r.mock_id ? 'mock' : r.origin === 'app' ? 'practice' : (r.origin || '').replace(/_/g, ' '),
        href: `#/writing/submission/${r.id}`, open: 'Open', done: true }
    : { date: r.finished_at || r.started_at, band: r.band, bandNote: '',
        detail: r.status !== 'submitted' ? 'Not finished' : r.raw_score == null ? 'Band only (imported)' : `${r.raw_score}/${r.total ?? 40}${r.duration_sec ? ` · ${fmtDuration(r.duration_sec)}` : ''}`,
        mode: r.mode, done: r.status === 'submitted',
        href: r.status === 'submitted' ? `#/result/${r.id}` : `#/test/${encodeURIComponent(r.test_id)}/${r.id}${r.mock_id ? `?mode=mock&mock=${r.mock_id}` : ''}`,
        open: r.status === 'submitted' ? 'Review' : 'Resume' })
    .sort((a, b) => (parseDate(a.date)?.getTime() || 0) - (parseDate(b.date)?.getTime() || 0));

  const body = h('div');
  const scored = items.filter((x) => x.done && x.band != null);
  if (scored.length) {
    const bands = scored.map((x) => Number(x.band));
    const first = bands[0], last = bands[bands.length - 1];
    const d = last - first;
    body.append(h('div', { class: 'grid grid-4 attempt-stats' },
      stat('Attempts', String(items.length)), stat('Best', fmtBand(Math.max(...bands))), stat('Latest', fmtBand(last)),
      stat('Change', scored.length > 1 ? `${d > 0 ? '▲ +' : d < 0 ? '▼ ' : ''}${d === 0 ? 'same' : d.toFixed(1)}` : '–',
        d > 0 ? 'good' : d < 0 ? 'bad' : '')));
  }
  let chartBox = null;
  if (scored.length > 1) {
    chartBox = h('div', { class: 'chart-box', style: { height: '170px', margin: '12px 0' } },
      h('canvas', { role: 'img', 'aria-label': `Band per attempt: ${scored.map((x) => fmtBand(x.band)).join(', ')}` }));
    body.append(chartBox);
  }
  if (!items.length) body.append(h('p', { class: 'muted' }, 'No attempts yet.'));
  else {
    const table = h('div', { class: 'table-wrap' });
    table.innerHTML = `<table class="table"><thead><tr><th>#</th><th>Date</th><th>Type</th><th>Result</th><th>Band</th><th></th></tr></thead><tbody>
      ${items.map((x, i) => `<tr${x.done ? '' : ' class="muted"'}><td>${i + 1}</td><td class="nowrap">${esc(x.date ? fmtDate(x.date) : 'date unknown')}</td>
        <td><span class="badge">${esc(x.mode || 'practice')}</span></td>
        <td class="small">${esc(x.detail)}${x.done ? '' : ' <span class="badge warn">In progress</span>'}</td>
        <td>${x.band != null ? `<span class="band-pill">${fmtBand(x.band)}</span>${x.bandNote ? ` <span class="small muted">${x.bandNote}</span>` : ''}` : '<span class="muted small">–</span>'}</td>
        <td><a class="btn sm ${x.done ? 'ghost' : 'primary'}" href="${x.href}">${x.open}</a></td></tr>`).reverse().join('')}</tbody></table>`;
    body.append(table);
  }
  let chart = null;
  await modal({
    title: title || 'Your attempts', body, wide: true, actions: [{ label: 'Close', value: null }],
    onOpen: (el, close) => {
      el.querySelectorAll('a[href^="#"]').forEach((a) => a.addEventListener('click', () => close(null)));
      if (chartBox) chart = bandLine(chartBox.querySelector('canvas'), scored.map((x) => ({ label: shortDate(x.date), band: x.band, title: x.date ? fmtDate(x.date) : 'date unknown' })));
    },
  });
  chart?.destroy();
}

function stat(label, value, tone = '') {
  return h('div', { class: 'card stat compact' }, h('div', { class: 'stat-label' }, label),
    h('div', { class: `stat-value${tone ? ` tone-${tone}` : ''}` }, value));
}

let statsCache = null;
export const statsOnce = () => (statsCache ||= api.get('/api/stats').finally(() => setTimeout(() => { statsCache = null; }, 30000)));

/**
 * Per-skill progress card for the top of the Listening / Reading / Writing / Speaking pages:
 * band trend, latest / best / recent average, and (listening, reading) the weakest question types.
 * Collapsible; the open/closed state is remembered per skill.
 */
export function skillProgress(skill) {
  const label = skill[0].toUpperCase() + skill.slice(1);
  const openKey = `progressOpen.${skill}`;
  const card = h('details', { class: 'card progress-card', open: store.get(openKey, true) });
  card.addEventListener('toggle', () => store.set(openKey, card.open));
  const sumEl = h('span', { class: 'muted small' }, 'Loading…');
  card.append(h('summary', null, h('span', { class: 'p-title', html: `${icon('dashboard')} Your ${label.toLowerCase()} progress` }), sumEl));
  const body = h('div', { class: 'progress-body' });
  card.append(body);
  let chart = null;
  statsOnce().then((stats) => {
    const all = asList(stats?.bands_over_time?.[skill]).filter((p) => p.band != null);
    const dated = all.filter((p) => p.date).sort((a, b) => String(a.date).localeCompare(String(b.date)));
    if (!all.length) {
      sumEl.textContent = 'No scores yet';
      body.append(h('p', { class: 'muted small', style: { margin: '4px 0 0' } },
        skill === 'writing' || skill === 'speaking' ? 'Bands appear after an AI analysis or a teacher’s mark.' : 'Finish a test to start your trend.'));
      return;
    }
    const bands = all.map((p) => Number(p.band));
    const recent = (dated.length ? dated : all).slice(-5).map((p) => Number(p.band));
    const avg = recent.reduce((s, b) => s + b, 0) / recent.length;
    const latest = dated.length ? Number(dated[dated.length - 1].band) : bands[bands.length - 1];
    sumEl.textContent = `${all.length} scored · latest ${fmtBand(latest)} · best ${fmtBand(Math.max(...bands))}`;
    const tiles = h('div', { class: 'progress-tiles' },
      stat('Latest', fmtBand(latest)), stat('Best', fmtBand(Math.max(...bands))),
      stat(`Average of last ${recent.length}`, (Math.round(avg * 4) / 4).toFixed(2).replace(/0$/, '')), stat('Scored', String(all.length)));
    const left = h('div', { class: 'progress-left' }, tiles);
    if (all.length > dated.length) left.append(h('div', { class: 'small muted' }, `${all.length - dated.length} result${all.length - dated.length > 1 ? 's' : ''} without a date are counted but not drawn.`));
    if (skill === 'listening' || skill === 'reading') {
      const qt = asList(stats?.by_question_type).filter((x) => x.skill === skill && Number(x.total) >= 3)
        .map((x) => ({ ...x, rate: Number(x.correct) / Number(x.total) })).sort((a, b) => a.rate - b.rate).slice(0, 4);
      if (qt.length) {
        const ul = h('div', { class: 'weak-types' }, h('div', { class: 'small muted' }, 'Weakest question types'));
        for (const x of qt) {
          const pct = Math.round(x.rate * 100);
          const row = h('div', { class: 'qtype-row compact' });
          row.innerHTML = `<span class="small">${esc(qtypeLabel(x.type))}</span>
            <div class="bar-track" role="img" aria-label="${pct}% correct"><div class="bar-fill ${pct >= 75 ? 'high' : pct >= 50 ? 'mid' : 'low'}" style="width:${pct}%"></div></div>
            <span class="small num" title="${x.correct}/${x.total}">${pct}%</span>`;
          ul.append(row);
        }
        left.append(ul);
      }
    }
    body.append(left);
    if (dated.length > 1) {
      const box = h('div', { class: 'chart-box progress-chart' },
        h('canvas', { role: 'img', 'aria-label': `${label} band over time` }));
      body.append(box);
      const draw = () => {
        chart?.destroy();
        chart = bandLine(box.querySelector('canvas'), dated.map((p) => ({ label: shortDate(p.date), band: p.band, title: fmtDate(p.date) })),
          { color: SKILL_COLOR[skill], name: label });
      };
      if (card.open) draw(); else card.addEventListener('toggle', () => { if (card.open && !chart) draw(); }, { once: true });
    }
  }).catch(() => { sumEl.textContent = ''; });
  return card;
}
