// Dashboard: estimated bands, trend chart, weak question types, streak, recent activity, AI progress analysis.
import { api } from '../api.js';
import { h, esc, icon, fmtBand, withStates, qtypeLabel, timeAgo, parseDate, emptyState, asList } from '../ui.js';
import { analysisPanel } from '../components/analysis.js';
import { setTitle } from '../app.js';

const SKILLS = [
  ['listening', 'Listening', '--series-1'],
  ['reading', 'Reading', '--series-2'],
  ['writing', 'Writing', '--series-3'],
  ['speaking', 'Speaking', '--series-4'],
];

export function roundBand(x) {
  // IELTS overall: average rounded to nearest half band (.25 -> .5, .75 -> next whole)
  return Math.floor(x * 2 + 0.5) / 2;
}

function estimate(points) {
  if (!points || !points.length) return null;
  const sorted = points.filter((p) => p.band !== null && p.band !== undefined).sort((a, b) => (parseDate(a.date)?.getTime() || 0) - (parseDate(b.date)?.getTime() || 0));
  if (!sorted.length) return null;
  const last = sorted.slice(-3).map((p) => Number(p.band));
  return roundBand(last.reduce((s, b) => s + b, 0) / last.length);
}

export async function render(root) {
  setTitle('Dashboard');
  let chart = null;
  const onTheme = () => chart && chart.redraw && chart.redraw();
  window.addEventListener('themechange', onTheme);

  const hour = new Date().getHours();
  const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const name = await api.get('/api/settings').then((s) => (s.user_name || '').split(',')[0].trim()).catch(() => '');
  root.replaceChildren(h('div', { class: 'page-head' },
    h('div', null, h('h1', null, name ? `${greet}, ${name}` : greet), h('p', null, 'Your IELTS preparation at a glance.')),
    h('div', { class: 'page-actions' },
      h('a', { class: 'btn', href: '#/mock', html: `${icon('mock')} Full mock exam` }),
      h('a', { class: 'btn primary', href: '#/reading', html: `${icon('play')} Practise now` }))));
  const content = h('div');
  root.append(content);

  await withStates(content, () => api.get('/api/stats'), (stats) => {
    const bot = stats?.bands_over_time || {};
    const est = Object.fromEntries(SKILLS.map(([k]) => [k, estimate(bot[k])]));
    const have = SKILLS.filter(([k]) => est[k] !== null);
    const overall = have.length ? roundBand(have.reduce((s, [k]) => s + est[k], 0) / have.length) : null;

    // ------------------------------------------- band tiles
    const tiles = h('div', { class: 'grid grid-5', style: { marginBottom: '16px' } });
    tiles.append(h('div', { class: 'card stat hero', html: `
      <div class="stat-label">${icon('target', '')} Overall estimate</div>
      <div class="stat-value">${overall === null ? '–' : fmtBand(overall)}</div>
      <div class="stat-sub">${have.length === 4 ? 'Average of all four skills' : have.length ? `Based on ${have.length} of 4 skills` : 'Complete a test to get an estimate'}</div>` }));
    for (const [k, label, color] of SKILLS) {
      const pts = bot[k] || [];
      const last = pts.length ? pts[pts.length - 1] : null;
      const prev = pts.length > 1 ? pts[pts.length - 2] : null;
      let delta = '';
      if (last && prev && last.band != null && prev.band != null) {
        const d = Number(last.band) - Number(prev.band);
        delta = d > 0 ? `<span style="color:var(--good)">▲ ${d.toFixed(1)}</span> vs previous` : d < 0 ? `<span style="color:var(--bad)">▼ ${Math.abs(d).toFixed(1)}</span> vs previous` : 'Same as previous';
      }
      tiles.append(h('a', { class: 'card stat', href: `#/${k}`, style: { color: 'inherit', textDecoration: 'none' }, html: `
        <div class="stat-label"><span class="swatch" style="background:var(${color})"></span>${label}</div>
        <div class="stat-value">${est[k] === null ? '–' : fmtBand(est[k])}</div>
        <div class="stat-sub">${pts.length ? `${pts.length} scored · ${delta || 'last ' + fmtBand(last?.band)}` : 'No scores yet'}</div>` }));
    }
    content.append(tiles);

    // ------------------------------------------- chart + streak/quick
    const chartCard = h('div', { class: 'card span-2' },
      h('div', { class: 'card-head' }, h('h2', null, 'Band trend'), h('span', { class: 'muted small' }, 'Each point is a scored attempt')),
      h('div', { class: 'card-body' }));
    const chartBody = chartCard.querySelector('.card-body');
    const totalPts = SKILLS.reduce((s, [k]) => s + (bot[k]?.length || 0), 0);
    if (!totalPts) {
      chartBody.append(emptyState('No scores yet', 'Finish a listening or reading test and your band trend will appear here.', 'dashboard'));
    } else {
      const box = h('div', { class: 'chart-box' });
      const canvas = h('canvas', { role: 'img', 'aria-label': 'Band score over time per skill' });
      box.append(canvas);
      chartBody.append(box);
      chart = makeTrendChart(canvas, bot);
    }

    const counts = stats?.counts || {};
    const streak = Number(stats?.streak_days || 0);
    const side = h('div', { class: 'card' });
    side.innerHTML = `
      <div class="card-head"><h2>Study streak</h2></div>
      <div class="card-body">
        <div class="row" style="gap:14px">
          <div style="width:52px;height:52px;border-radius:14px;background:var(--warn-soft);color:var(--flag);display:grid;place-items:center">${icon('fire')}</div>
          <div><div class="stat-value" style="margin:0">${streak} day${streak === 1 ? '' : 's'}</div>
          <div class="stat-sub">${streak ? 'Keep it going — practise something today.' : 'Start a streak with a quick practice.'}</div></div>
        </div>
        <div class="grid grid-2" style="margin-top:16px;gap:10px">
          ${countTile('Tests done', sumCounts(counts, ['listening_attempts', 'reading_attempts']))}
          ${countTile('Essays', counts.writing_submissions_app ?? counts.writing_submissions)}
          ${countTile('Speaking sessions', counts.speaking_sessions)}
          ${countTile('Words due', counts.vocab_due)}
        </div>
      </div>`;
    side.querySelector('.card-head svg')?.remove();
    side.querySelectorAll('svg').forEach((s) => { s.style.width = '26px'; s.style.height = '26px'; });
    content.append(h('div', { class: 'grid grid-3', style: { marginBottom: '16px' } }, chartCard, side));

    // ------------------------------------------- weak types + recent
    const qt = asList(stats?.by_question_type).filter((x) => Number(x.total) > 0)
      .map((x) => ({ ...x, rate: Number(x.correct) / Number(x.total) }))
      .sort((a, b) => a.rate - b.rate || b.total - a.total);
    const weak = h('div', { class: 'card' },
      h('div', { class: 'card-head' }, h('h2', null, 'Accuracy by question type'), h('span', { class: 'muted small' }, 'Weakest first')),
      h('div', { class: 'card-body' }));
    const wb = weak.querySelector('.card-body');
    if (!qt.length) wb.append(emptyState('No data yet', 'Question-type accuracy appears after your first test.', 'target'));
    for (const x of qt.slice(0, 10)) {
      const skill = x.skill || x.test_type || (x.type && /^(tfng|matching_headings|matching_information|matching_features|matching_sentence_endings|ynng)$/.test(x.type) ? 'reading' : null);
      const href = skill ? `#/${skill}` : (x.type === 'tfng' || x.type === 'ynng' ? '#/reading' : '#/listening');
      const pct = Math.round(x.rate * 100);
      const row = h('div', { class: 'qtype-row' });
      row.innerHTML = `<span>${esc(qtypeLabel(x.type))}${skill ? ` <span class="muted small">· ${esc(skill)}</span>` : ''}</span>
        <div class="bar-track" role="img" aria-label="${pct}% correct"><div class="bar-fill ${pct >= 75 ? 'high' : pct >= 50 ? 'mid' : 'low'}" style="width:${pct}%"></div></div>
        <span class="small num" title="${x.correct}/${x.total}">${pct}%</span>`;
      row.append(h('a', { class: 'btn sm ghost', href, title: `Practise ${qtypeLabel(x.type)}` }, 'Practise →'));
      wb.append(row);
    }

    const recent = asList(stats?.recent);
    const rc = h('div', { class: 'card' },
      h('div', { class: 'card-head' }, h('h2', null, 'Recent activity'), h('a', { class: 'small', href: '#/history' }, 'View all')),
      h('div', { class: 'card-body' }));
    const rb = rc.querySelector('.card-body');
    if (!recent.length) rb.append(emptyState('Nothing yet', 'Your tests, essays and speaking sessions will show up here.', 'history'));
    else {
      const ul = h('ul', { class: 'activity' });
      for (const r of recent.slice(0, 8)) ul.append(activityItem(r));
      rb.append(ul);
    }
    content.append(h('div', { class: 'grid grid-2', style: { marginBottom: '16px' } }, weak, rc));

    // ------------------------------------------- quick start
    content.append(h('div', { class: 'card card-pad', style: { marginBottom: '16px' } },
      h('h2', null, 'Quick start'),
      h('div', { class: 'quick', html: `
        <a href="#/listening">${icon('listening')}<b>Listening test</b><span>30 min · 40 questions</span></a>
        <a href="#/reading">${icon('reading')}<b>Reading test</b><span>60 min · 3 passages</span></a>
        <a href="#/writing">${icon('writing')}<b>Write an essay</b><span>Task 1 or Task 2</span></a>
        <a href="#/speaking">${icon('speaking')}<b>Speaking practice</b><span>Record and get feedback</span></a>` })));

    // ------------------------------------------- AI
    content.append(analysisPanel({
      target_type: 'progress', target_id: 0, title: 'Analyse my overall progress with AI',
      subtitle: 'Looks across all your attempts, essays and speaking to find patterns and a study plan.',
      buttonLabel: 'Analyse my progress',
      emptyText: 'Ask the AI to look at all your history and suggest what to focus on next.',
    }));
  });

  return () => {
    window.removeEventListener('themechange', onTheme);
    chart?.destroy();
  };
}

function sumCounts(c, keys) {
  let s = 0, any = false;
  for (const k of keys) if (typeof c[k] === 'number') { s += c[k]; any = true; }
  return any ? s : undefined;
}
function countTile(label, v) {
  return `<div style="background:var(--surface-2);border:1px solid var(--border);border-radius:10px;padding:8px 12px">
    <div class="small muted">${label}</div><div style="font-weight:680;font-size:18px">${v ?? 0}</div></div>`;
}

const KIND_ICON = { listening: 'listening', reading: 'reading', writing: 'writing', speaking: 'speaking', mock: 'mock', analysis: 'sparkles', attempt: 'reading' };
export function activityLink(r) {
  const kind = r.kind || r.type || r.target_type;
  if (r.link) return r.link.startsWith('#') ? r.link : `#${r.link}`;
  if (kind === 'listening' || kind === 'reading' || kind === 'attempt') return `#/result/${r.id}`;
  if (kind === 'writing') return `#/writing/submission/${r.id}`;
  if (kind === 'speaking' || kind === 'speaking_session') return `#/speaking/session/${r.id}`;
  if (kind === 'mock') return `#/mock/${r.id}`;
  return '#/history';
}
function activityItem(r) {
  const kind = r.kind || r.type || r.target_type || '';
  const li = h('li');
  li.innerHTML = `<div class="a-icon">${icon(KIND_ICON[kind] || 'doc')}</div>
    <div class="a-main"><div class="a-title">${esc(r.title || r.test_title || r.prompt || kind)}</div>
    <div class="small muted">${esc(kind)} · ${esc(timeAgo(r.at || r.date || r.created_at || r.finished_at))}</div></div>
    ${r.band != null ? `<span class="band-pill">${fmtBand(r.band)}</span>` : ''}`;
  li.querySelector('.a-title').innerHTML = `<a href="${activityLink(r)}" style="color:inherit">${esc(r.title || r.test_title || r.prompt || kind)}</a>`;
  return li;
}

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function makeTrendChart(canvas, bot) {
  if (!window.Chart) {
    canvas.replaceWith(h('p', { class: 'muted' }, 'Chart library failed to load.'));
    return null;
  }
  let inst = null;
  const build = () => {
    if (inst) inst.destroy();
    const text2 = cssVar('--text-3'), grid = cssVar('--border'), surface = cssVar('--surface');
    // Category axis of distinct days; one value per skill per day (the day's last score).
    const day = (d) => String(d || '').slice(0, 10);
    const days = [...new Set(SKILLS.flatMap(([k]) => (bot[k] || []).map((p) => day(p.date))).filter(Boolean))].sort();
    let minBand = 9;
    const datasets = SKILLS.filter(([k]) => (bot[k] || []).length).map(([k, label, color]) => {
      const c = cssVar(color);
      const byDay = new Map();
      for (const p of (bot[k] || [])) if (p.band != null) byDay.set(day(p.date), { b: Number(p.band), n: (byDay.get(day(p.date))?.n || 0) + 1 });
      byDay.forEach((v) => { minBand = Math.min(minBand, v.b); });
      return {
        label,
        data: days.map((d) => (byDay.has(d) ? byDay.get(d).b : null)),
        counts: days.map((d) => byDay.get(d)?.n || 0),
        borderColor: c, backgroundColor: c, borderWidth: 2, tension: 0.25, spanGaps: true,
        pointRadius: 4, pointHoverRadius: 6, pointBorderColor: surface, pointBorderWidth: 2,
      };
    });
    const fmtDay = (d) => { const dt = parseDate(d); return dt ? dt.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : d; };
    inst = new window.Chart(canvas, {
      type: 'line',
      data: { labels: days, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { offset: true, grid: { display: false }, border: { color: grid }, ticks: { color: text2, maxTicksLimit: 8, callback(v) { return fmtDay(this.getLabelForValue(v)); } } },
          y: { min: Math.max(0, Math.min(4, Math.floor(minBand) - 1)), max: 9, ticks: { stepSize: 1, color: text2 }, grid: { color: grid }, border: { display: false } },
        },
        plugins: {
          legend: { position: 'top', align: 'end', labels: { color: cssVar('--text-2'), usePointStyle: true, boxWidth: 8, boxHeight: 8 } },
          tooltip: {
            callbacks: {
              title: (items) => { const dt = parseDate(items[0].label); return dt ? dt.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : items[0].label; },
              label: (it) => `${it.dataset.label}: ${Number(it.parsed.y).toFixed(1)}${it.dataset.counts[it.dataIndex] > 1 ? ` (last of ${it.dataset.counts[it.dataIndex]})` : ''}`,
            },
          },
        },
      },
    });
  };
  build();
  return { redraw: build, destroy: () => inst && inst.destroy() };
}
