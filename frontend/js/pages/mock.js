// Full mock exam: create plan, stepper L -> R -> W -> S, final bands + AI analysis.
import { api } from '../api.js';
import { h, esc, icon, toast, withStates, emptyState, fmtDate, fmtBand, asList, store, confirmDialog } from '../ui.js';
import { analysisPanel } from '../components/analysis.js';
import { writerView } from '../components/writer.js';
import { speakingRunner } from './speaking.js';
import { getPrompt } from './writing.js';
import { bandRing } from './result.js';
import { navigate, nav, setTitle } from '../app.js';

const SECTIONS = [
  { key: 'listening', label: 'Listening', icon: 'listening', time: '30 min' },
  { key: 'reading', label: 'Reading', icon: 'reading', time: '60 min' },
  { key: 'writing', label: 'Writing', icon: 'writing', time: '60 min' },
  { key: 'speaking', label: 'Speaking', icon: 'speaking', time: '11–14 min' },
];

export async function render(root, params) {
  const [id, sub] = params;
  if (!id) return renderList(root);
  if (sub === 'writing') return renderWriting(root, Number(id));
  if (sub === 'speaking') return renderSpeaking(root, Number(id));
  return renderMock(root, Number(id));
}

async function startNew() {
  try {
    const res = await api.post('/api/mock', { sections: SECTIONS.map((s) => s.key), random: true });
    navigate(`#/mock/${res.id}`);
  } catch (e) { toast(`Could not create mock: ${e.message}`, 'error'); }
}

function renderList(root) {
  setTitle('Mock Exam');
  root.replaceChildren(h('div', { class: 'page-head' },
    h('div', null, h('h1', null, 'Mock exam'), h('p', null, 'A full IELTS exam with random unseen materials: Listening → Reading → Writing → Speaking.')),
    h('div', { class: 'page-actions' }, h('button', { class: 'btn primary lg', type: 'button', html: `${icon('play')} Start a full mock`, onclick: startNew }))));
  const how = h('div', { class: 'grid grid-4', style: { marginBottom: '26px' } }, ...SECTIONS.map((s, i) => h('div', { class: 'card card-pad' },
    h('div', { class: 'row' }, h('span', { class: 'badge accent' }, `Step ${i + 1}`), h('span', { class: 'muted small' }, s.time)),
    h('h3', { style: { marginTop: '10px' } }, s.label),
    h('p', { class: 'small muted', style: { margin: 0 } }, {
      listening: 'Recording plays once; parts advance automatically.',
      reading: 'Three passages, strict 60-minute timer.',
      writing: 'Task 1 + Task 2 with one shared 60-minute timer.',
      speaking: 'Parts 1–3 recorded with examiner prompts.',
    }[s.key]))));
  root.append(how, h('h2', null, 'Your mock exams'));
  const list = h('div');
  root.append(list);
  withStates(list, () => api.get('/api/mock'), (data) => {
    const rows = asList(data, 'mocks');
    if (!rows.length) { list.append(emptyState('No mock exams yet', 'Start your first full mock to get an overall band estimate.', 'mock')); return; }
    const wrap = h('div', { class: 'card table-wrap' });
    wrap.innerHTML = `<table class="table"><thead><tr><th>#</th><th>Started</th><th>Status</th><th class="num">L</th><th class="num">R</th><th class="num">W</th><th class="num">S</th><th>Overall</th><th></th></tr></thead><tbody>
      ${rows.map((m) => `<tr><td>${m.id}</td><td>${esc(fmtDate(m.created_at))}</td>
        <td>${m.status === 'finished' ? '<span class="badge good">Finished</span>' : '<span class="badge warn">In progress</span>'}</td>
        <td class="num">${fmtBand(m.listening_band)}</td><td class="num">${fmtBand(m.reading_band)}</td><td class="num">${fmtBand(m.writing_band)}</td><td class="num">${fmtBand(m.speaking_band)}</td>
        <td>${m.overall_band != null ? `<span class="band-pill">${fmtBand(m.overall_band)}</span>` : '<span class="muted small">–</span>'}</td>
        <td><a class="btn sm" href="#/mock/${m.id}">${m.status === 'finished' ? 'View' : 'Continue'}</a></td></tr>`).join('')}</tbody></table>`;
    list.append(wrap);
  });
}

function sectionState(mock, key) {
  const links = mock.links || {};
  const plan = mock.plan || {};
  const ids = asList(links[key]);
  if (key === 'writing') {
    const need = [plan.writing?.task1, plan.writing?.task2].filter(Boolean).length || 2;
    return { done: ids.length >= need, ids };
  }
  return { done: ids.length > 0, ids };
}

async function renderMock(root, id) {
  setTitle(`Mock exam #${id}`);
  const mock = await api.get(`/api/mock/${id}`);
  const plan = mock.plan || {};
  const sections = SECTIONS.filter((s) => !plan.sections || plan.sections.includes(s.key));
  const live = mock.live_bands || {};
  const bands = {
    listening: mock.listening_band ?? live.listening, reading: mock.reading_band ?? live.reading,
    writing: mock.writing_band ?? live.writing, speaking: mock.speaking_band ?? live.speaking,
    overall: mock.overall_band ?? live.overall,
  };
  // Only show an overall band once every planned section has a band.
  const complete = SECTIONS.filter((s) => !plan.sections || plan.sections.includes(s.key)).every((s) => bands[s.key] != null);
  if (!complete && mock.overall_band == null) bands.overall = null;
  const states = Object.fromEntries(sections.map((s) => [s.key, sectionState(mock, s.key)]));
  const currentIdx = sections.findIndex((s) => !states[s.key].done);
  const allDone = currentIdx === -1;
  const finished = mock.status === 'finished';

  root.replaceChildren(h('div', { class: 'page-head' },
    h('div', null, h('div', { class: 'small' }, h('a', { href: '#/mock' }, '← All mocks')), h('h1', null, `Mock exam #${id}`),
      h('p', null, `Started ${fmtDate(mock.created_at)}${finished ? ` · finished ${fmtDate(mock.finished_at)}` : ''}`)),
    h('div', { class: 'page-actions' })));

  // stepper
  const stepper = h('div', { class: 'stepper', role: 'list' });
  sections.forEach((s, i) => {
    const st = states[s.key];
    const cls = st.done ? 'done' : i === currentIdx ? 'current' : '';
    stepper.append(h('div', { class: `step ${cls}`, role: 'listitem', 'aria-current': i === currentIdx ? 'step' : undefined },
      h('span', { class: 's-num', html: st.done ? icon('check') : String(i + 1) }),
      h('div', null, h('div', { class: 's-title' }, s.label), h('div', { class: 's-sub' }, st.done ? (bands[s.key] != null ? `Band ${fmtBand(bands[s.key])}` : 'Completed') : s.time))));
  });
  stepper.querySelectorAll('.s-num svg').forEach((s) => { s.style.width = '15px'; s.style.height = '15px'; });
  root.append(stepper);

  // section cards
  const grid = h('div', { class: 'grid grid-2', style: { marginBottom: '22px' } });
  for (const [i, s] of sections.entries()) grid.append(sectionCard(mock, s, states[s.key], bands[s.key], i === currentIdx, id));
  root.append(grid);

  // final
  const final = h('div', { class: 'card card-pad', style: { marginBottom: '22px' } });
  const tiles = SECTIONS.map((s) => `<div class="card stat" style="text-align:center"><div class="stat-label" style="justify-content:center">${s.label}</div>
      <div class="stat-value">${fmtBand(bands[s.key])}</div></div>`).join('');
  final.innerHTML = `<div class="row" style="gap:26px;align-items:center">
      ${bandRing(bands.overall, 130, 'Overall')}
      <div style="flex:1;min-width:280px"><h2>${allDone ? (finished ? 'Final result' : 'All sections complete') : 'Results so far'}</h2>
      <p class="muted small">${allDone ? 'Writing and speaking bands come from AI analysis — run “Analyse with AI” on each, then finish the mock to lock in the overall band.' : 'Complete each section in order. Writing and speaking bands appear after AI analysis.'}</p>
      <div class="grid grid-4" style="gap:10px">${tiles}</div></div></div>`;
  const actions = h('div', { class: 'row', style: { marginTop: '16px' } });
  if (allDone || states.listening?.done) {
    actions.append(h('button', { class: `btn ${finished ? '' : 'primary'}`, type: 'button', html: `${icon('check')} ${finished ? 'Recalculate overall band' : 'Finish mock & compute overall'}`, onclick: async () => {
      try {
        const r = await api.post(`/api/mock/${id}/finish`);
        if (r.missing?.length) toast(`Missing bands: ${r.missing.join(', ')} — run AI analysis for those sections.`);
        else toast('Mock finished.', 'good');
        navigate(`#/mock/${id}`);
      } catch (e) { toast(e.message, 'error'); }
    } }));
  }
  final.append(actions);
  root.append(final);

  root.append(analysisPanel({
    target_type: 'mock', target_id: id, title: 'Analyse whole mock with AI',
    subtitle: 'One report across all four skills: band per section, weakest areas, and a study plan.',
    buttonLabel: 'Analyse whole mock',
  }));
}

function sectionCard(mock, s, st, band, isCurrent, id) {
  const plan = mock.plan || {};
  const card = h('div', { class: 'card card-pad' });
  const head = h('div', { class: 'row between' },
    h('div', { class: 'row' }, h('span', { class: 'm-icon', html: icon(s.icon), style: { width: '34px', height: '34px', borderRadius: '9px', background: 'var(--accent-soft)', color: 'var(--accent)', display: 'grid', placeItems: 'center' } }), h('h3', { style: { margin: 0 } }, s.label)),
    st.done ? h('span', { class: 'band-pill' }, band != null ? fmtBand(band) : '✓') : h('span', { class: 'badge' }, s.time));
  card.append(head);
  const body = h('div', { class: 'small', style: { marginTop: '10px' } });
  card.append(body);
  const btns = h('div', { class: 'row', style: { marginTop: '12px' } });
  card.append(btns);

  if (s.key === 'listening' || s.key === 'reading') {
    const testId = plan[s.key];
    body.append(h('div', { class: 'muted' }, testId ? `Test: ${testId}` : 'No test available.'));
    if (st.done) {
      st.ids.forEach((aid) => btns.append(h('a', { class: 'btn sm', href: `#/result/${aid}` }, 'Review answers')));
    } else if (testId) {
      const active = store.get(`active.${testId}.mock.${id}`);
      btns.append(h('a', { class: `btn ${isCurrent ? 'primary' : ''}`, href: `#/test/${encodeURIComponent(testId)}${active ? `/${active}` : ''}?mode=mock&mock=${id}` }, active ? 'Resume' : `Start ${s.label}`));
    }
  } else if (s.key === 'writing') {
    const w = plan.writing || {};
    body.append(h('div', { class: 'muted' }, `Task 1 prompt #${w.task1 ?? '–'} · Task 2 prompt #${w.task2 ?? '–'}`));
    if (st.ids.length) {
      st.ids.forEach((sid, i) => btns.append(h('a', { class: 'btn sm', href: `#/writing/submission/${sid}` }, `Essay ${i + 1} — analyse`)));
    }
    if (!st.done && (w.task1 || w.task2)) btns.append(h('a', { class: `btn ${isCurrent ? 'primary' : ''}`, href: `#/mock/${id}/writing` }, 'Start Writing'));
    if (st.done && band == null) body.append(h('div', { style: { color: 'var(--warn)', marginTop: '6px' } }, 'Run AI analysis on both essays to get the writing band.'));
  } else if (s.key === 'speaking') {
    const sp = plan.speaking || {};
    body.append(h('div', { class: 'muted' }, `${asList(sp.part1).length} Part 1 questions · ${sp.part2 ? 'cue card: ' + sp.part2.question : 'no cue card'} · ${asList(sp.part3).length} Part 3 questions`));
    st.ids.forEach((sid) => btns.append(h('a', { class: 'btn sm', href: `#/speaking/session/${sid}` }, 'Open session — analyse')));
    if (!st.done) btns.append(h('a', { class: `btn ${isCurrent ? 'primary' : ''}`, href: `#/mock/${id}/speaking` }, 'Start Speaking'));
    if (st.done && band == null) body.append(h('div', { style: { color: 'var(--warn)', marginTop: '6px' } }, 'Run AI analysis on the session to get the speaking band.'));
  }
  return card;
}

async function renderWriting(root, id) {
  const mock = await api.get(`/api/mock/${id}`);
  const w = mock.plan?.writing || {};
  const ids = [w.task1, w.task2].filter(Boolean);
  if (!ids.length) { root.replaceChildren(emptyState('No writing prompts in this mock')); return; }
  const prompts = await Promise.all(ids.map((pid) => getPrompt(pid)));
  setTitle(`Mock #${id} — Writing`);
  const view = writerView({
    title: `Mock exam #${id} — Writing`,
    subtitle: 'Task 1 + Task 2 · 60 minutes',
    tasks: prompts.map((p) => ({ prompt: p, draftKey: `draft.mock.${id}.writing.${p.id}` })),
    minutes: 60,
    strictTime: true,
    onExit: () => navigate(`#/mock/${id}`),
    onSubmit: async (items) => {
      for (const it of items) {
        if (!it.text.trim()) continue;
        const r = await api.post('/api/writing/submissions', { prompt_id: it.prompt.id, text: it.text, time_spent_sec: it.time_spent_sec, mock_id: id });
        try { await api.post(`/api/mock/${id}/link`, { section: 'writing', ref_id: r.id }); } catch { /* already linked via mock_id */ }
      }
      nav.guard = null;
      toast('Writing submitted.', 'good');
      navigate(`#/mock/${id}`);
    },
  });
  root.replaceChildren(view.el);
  nav.guard = async () => !view.isDirty() || confirmDialog('Leave writing?', 'Your drafts are saved and the timer pauses while you are away.', 'Leave');
  return () => view.destroy();
}

async function renderSpeaking(root, id) {
  const mock = await api.get(`/api/mock/${id}`);
  setTitle(`Mock #${id} — Speaking`);
  const plan = mock.plan?.speaking || await api.get('/api/speaking/random-set', { mode: 'full' });
  return speakingRunner(root, {
    plan, mode: 'mock', sessionMode: 'mock', mockId: id, title: `Mock exam #${id} — Speaking`,
    onDone: async (sid) => {
      try { await api.post(`/api/mock/${id}/link`, { section: 'speaking', ref_id: sid }); } catch { /* linked via mock_id */ }
      toast('Speaking section saved.', 'good');
      navigate(`#/mock/${id}`);
    },
  });
}
