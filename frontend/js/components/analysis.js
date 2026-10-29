// "Analyse with AI" panel: enqueue, poll, render markdown + JSON highlights, history with re-analyse.
import { api } from '../api.js';
import { h, esc, icon, toast, renderMarkdown, parseMaybeJSON, fmtDate, fmtBand, asList, sanitize } from '../ui.js';
import { state, providerName, onStateChange } from '../state.js';

const POLL_MS = 2000;

/**
 * opts: { target_type, target_id, title, subtitle, buttonLabel }
 * Returns a DOM element. Polling stops automatically when the element is detached.
 */
export function analysisPanel(opts) {
  const { target_type, target_id } = opts;
  const el = h('section', { class: 'card ai-panel', 'aria-label': opts.title || 'AI analysis' });
  const providerLabel = h('span', { class: 'muted small' });
  const head = h('div', { class: 'ai-head' },
    h('div', { class: 'ai-icon', html: icon('sparkles') }),
    h('div', { style: { flex: '1', minWidth: '0' } }, h('h2', null, opts.title || 'AI feedback'), h('p', null, opts.subtitle || 'A detailed report from your selected AI tutor.')),
  );
  const actionBox = h('div', { class: 'row' });
  head.append(actionBox);
  const bodyEl = h('div', { class: 'ai-body' });
  const histEl = h('div', { class: 'ai-history hidden' });
  el.append(head, bodyEl, histEl);

  let history = [];
  let shownId = null;
  let pollTimer = null;
  let pollStart = 0;

  const drawActions = () => {
    const latest = history[0];
    const busy = latest && (latest.status === 'queued' || latest.status === 'running');
    const hasDone = history.some((a) => a.status === 'done');
    providerLabel.textContent = `via ${providerName(state.provider)}`;
    const btn = h('button', { class: `btn ${hasDone ? '' : 'primary'}`, type: 'button', disabled: busy,
      html: `${icon(hasDone ? 'refresh' : 'sparkles')} ${hasDone ? 'Re-analyse' : (opts.buttonLabel || 'Analyse with AI')}`,
      onclick: () => start(hasDone) });
    actionBox.replaceChildren(providerLabel, btn);
  };
  let mounted = false;
  const unsub = onStateChange(() => {
    if (el.isConnected) { mounted = true; drawActions(); } else if (mounted) unsub();
  });

  async function loadHistory() {
    try {
      const data = await api.get('/api/ai/analyses', { target_type, target_id });
      history = asList(data, 'analyses').sort((a, b) => (b.id || 0) - (a.id || 0));
    } catch (e) {
      history = [];
      bodyEl.replaceChildren(h('div', { class: 'error-box' }, `Could not load analyses: ${e.message}`));
      drawActions();
      return;
    }
    drawActions();
    drawHistory();
    const latest = history[0];
    if (!latest) { drawEmpty(); return; }
    if (latest.status === 'queued' || latest.status === 'running') { show(latest); poll(latest.id); return; }
    const done = history.find((a) => a.status === 'done');
    show(done || latest);
  }

  function drawEmpty() {
    bodyEl.replaceChildren(h('div', { class: 'empty', style: { padding: '22px 10px' } },
      h('p', { style: { margin: '0' } }, opts.emptyText || 'No AI analysis yet. Run one to get a detailed, personalised breakdown.')));
  }

  async function start(force) {
    try {
      const res = await api.post('/api/ai/analyze', { target_type, target_id, provider: state.provider, force: !!force });
      const id = res.id;
      if (res.status === 'done' && !force) {
        const full = res.result_md !== undefined ? res : await api.get(`/api/ai/analyses/${id}`);
        upsert(full);
        show(full);
        toast('Showing the existing analysis. Use “Re-analyse” for a fresh one.');
        return;
      }
      const row = { id, status: res.status || 'queued', provider: res.provider || state.provider, created_at: new Date().toISOString() };
      upsert(row);
      show(row);
      poll(id);
    } catch (e) {
      toast(`AI request failed: ${e.message}`, 'error');
    }
  }

  function upsert(row) {
    const i = history.findIndex((a) => a.id === row.id);
    if (i >= 0) history[i] = { ...history[i], ...row }; else history.unshift(row);
    history.sort((a, b) => (b.id || 0) - (a.id || 0));
    drawActions();
    drawHistory();
  }

  function poll(id) {
    clearTimeout(pollTimer);
    pollStart = pollStart || Date.now();
    const tick = async () => {
      if (!el.isConnected) { stop(); return; }
      try {
        const row = await api.get(`/api/ai/analyses/${id}`);
        upsert(row);
        if (shownId === id) show(row);
        if (row.status === 'queued' || row.status === 'running') {
          pollTimer = setTimeout(tick, POLL_MS);
        } else {
          pollStart = 0;
          if (row.status === 'done') toast('AI analysis is ready.', 'good');
          else if (row.status === 'error') toast('AI analysis failed.', 'error');
        }
      } catch (e) {
        pollTimer = setTimeout(tick, POLL_MS * 2);
      }
    };
    pollTimer = setTimeout(tick, 600);
  }
  function stop() { clearTimeout(pollTimer); }

  function show(row) {
    shownId = row.id;
    drawHistory();
    if (row.status === 'queued' || row.status === 'running') {
      bodyEl.replaceChildren(progressView(row));
      return;
    }
    if (row.status === 'error') {
      bodyEl.replaceChildren(h('div', { class: 'error-box', role: 'alert' },
        h('div', null, h('b', null, 'The AI run failed.'), h('div', { class: 'small', style: { whiteSpace: 'pre-wrap' } }, row.error || 'Unknown error'),
          row.log_path ? h('div', { class: 'small muted' }, `Log: ${row.log_path}`) : null)));
      return;
    }
    bodyEl.replaceChildren(resultView(row));
  }

  function progressView(row) {
    const wrap = h('div', { class: 'ai-progress', role: 'status' });
    const elapsed = h('div', { class: 'small muted' });
    const started = Date.parse(row.started_at || row.created_at || '') || pollStart || Date.now();
    const upd = () => {
      const s = Math.max(0, Math.round((Date.now() - started) / 1000));
      elapsed.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} elapsed · usually 1–4 minutes`;
    };
    upd();
    const t = setInterval(() => { if (!wrap.isConnected) clearInterval(t); else upd(); }, 1000);
    const running = row.status === 'running';
    wrap.append(
      h('div', { class: 'pulse', html: icon('sparkles') }),
      h('b', null, running ? `${providerName(row.provider)} is analysing…` : 'Waiting in queue…'),
      h('div', { class: 'ai-steps' },
        h('span', { class: 'on' }, 'Queued'), '→', h('span', { class: running ? 'on' : '' }, 'Reading your answers'), '→',
        h('span', { class: running ? 'on' : '' }, 'Writing report')),
      elapsed,
      h('div', { class: 'small muted' }, 'You can leave this page — the analysis keeps running and will be here when you come back.'),
    );
    return wrap;
  }

  function resultView(row) {
    const wrap = h('div');
    const j = parseMaybeJSON(row.result_json, null);
    if (j && typeof j === 'object') wrap.append(highlightsView(j));
    const md = h('div', { class: 'md' });
    md.innerHTML = renderMarkdown(row.result_md || (j ? '' : '_No report text returned._'));
    wrap.append(md);
    wrap.append(h('div', { class: 'small muted', style: { marginTop: '14px' } },
      `${providerName(row.provider)} · ${fmtDate(row.finished_at || row.created_at)}`));
    return wrap;
  }

  function drawHistory() {
    if (history.length <= 0) { histEl.classList.add('hidden'); return; }
    histEl.classList.remove('hidden');
    const list = h('div', { class: 'ai-history-list' });
    for (const a of history) {
      const st = a.status === 'done' ? '' : a.status === 'error' ? ' · failed' : ` · ${a.status}`;
      list.append(h('button', { type: 'button', 'aria-current': String(a.id === shownId), onclick: () => { show(a); if (a.status === 'queued' || a.status === 'running') poll(a.id); else if (a.result_md === undefined && a.status === 'done') api.get(`/api/ai/analyses/${a.id}`).then((r) => { upsert(r); show(r); }).catch(() => {}); } },
        h('span', { class: `prov-badge ${esc(a.provider || '')}` }, a.provider === 'antigravity' ? 'AGY' : (a.provider || '?')),
        `#${a.id} · ${fmtDate(a.created_at)}${st}`));
    }
    histEl.replaceChildren(h('div', { class: 'small muted' }, `Analysis history (${history.length})`), list);
  }

  drawActions();
  bodyEl.append(h('div', { class: 'loading-block' }, h('span', { class: 'spinner' }), ' Loading…'));
  loadHistory();
  return el;
}

const CRIT_NAMES = {
  TA: 'Task Achievement', TR: 'Task Response', CC: 'Coherence & Cohesion', LR: 'Lexical Resource',
  GRA: 'Grammar Range & Accuracy', FC: 'Fluency & Coherence', P: 'Pronunciation', PR: 'Pronunciation',
};

export function highlightsView(j) {
  const wrap = h('div');
  const band = j.band ?? j.overall_band ?? j.estimated_band;
  const crit = j.criteria && typeof j.criteria === 'object' ? j.criteria : null;
  if (band !== undefined && band !== null || crit) {
    const row = h('div', { class: 'ai-highlights' });
    row.append(band !== undefined && band !== null
      ? h('div', { class: 'ai-band' }, h('b', null, fmtBand(band) === '–' ? String(band) : fmtBand(band)), h('span', null, 'Est. band'))
      : h('div'));
    const cbox = h('div', { class: 'criteria' });
    if (crit) {
      for (const [k, v] of Object.entries(crit)) {
        const val = v && typeof v === 'object' ? (v.band ?? v.score ?? '') : v;
        const note = v && typeof v === 'object' ? (v.comment || v.note || v.summary || '') : '';
        cbox.append(h('div', { class: 'criterion', title: CRIT_NAMES[k] || k },
          h('div', { class: 'c-name' }, CRIT_NAMES[k] ? k : k.replace(/_/g, ' ')),
          h('div', { class: 'c-val' }, typeof val === 'number' ? fmtBand(val) : String(val ?? '–')),
          note ? h('div', { class: 'c-note' }, String(note)) : null));
      }
    }
    row.append(cbox);
    wrap.append(row);
  }
  const mistakes = Array.isArray(j.mistakes) ? j.mistakes : [];
  if (mistakes.length) {
    wrap.append(h('h3', null, `Key mistakes (${mistakes.length})`));
    const ul = h('ul', { class: 'mistakes' });
    for (const m of mistakes.slice(0, 30)) {
      if (typeof m === 'string') { ul.append(h('li', null, m)); continue; }
      const li = h('li');
      const q = m.question ?? m.q ?? m.number;
      const orig = m.original || m.user_answer || m.yours || m.wrong;
      const fix = m.correction || m.corrected || m.correct || m.correct_answer || m.fix;
      const why = m.explanation || m.why || m.reason || m.issue || m.note || m.type;
      if (q !== undefined) li.append(h('b', null, `Q${q} `));
      if (orig) li.append(h('span', { class: 'm-orig' }, String(orig)), ' ');
      if (fix) li.append('→ ', h('span', { class: 'm-fix' }, String(fix)));
      if (why) li.append(h('div', { class: 'small muted' }, String(why)));
      if (!li.childNodes.length) li.textContent = JSON.stringify(m);
      ul.append(li);
    }
    wrap.append(ul);
  }
  const corrected = Array.isArray(j.corrected_sentences) ? j.corrected_sentences : (Array.isArray(j.corrections) ? j.corrections : []);
  if (corrected.length) {
    wrap.append(h('h3', null, 'Corrected sentences'));
    const ul = h('ul', { class: 'mistakes' });
    for (const c of corrected.slice(0, 30)) {
      if (typeof c === 'string') { ul.append(h('li', null, c)); continue; }
      ul.append(h('li', null, h('span', { class: 'm-orig' }, c.original || c.before || ''), ' → ', h('span', { class: 'm-fix' }, c.corrected || c.after || c.correction || ''),
        (c.explanation || c.why) ? h('div', { class: 'small muted' }, c.explanation || c.why) : null));
    }
    wrap.append(ul);
  }
  const tips = Array.isArray(j.tips) ? j.tips : [];
  if (tips.length) {
    wrap.append(h('h3', null, 'Tips'));
    wrap.append(h('ul', { class: 'tips' }, ...tips.map((t) => h('li', { html: sanitize(typeof t === 'string' ? esc(t) : esc(t.text || JSON.stringify(t))) }))));
  }
  if (wrap.childNodes.length) wrap.append(h('hr', { style: { border: '0', borderTop: '1px solid var(--border)', margin: '18px 0' } }));
  return wrap;
}
