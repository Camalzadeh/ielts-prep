// Writing: prompt bank, editor, submissions and submission detail with AI analysis.
import { api, mediaUrl } from '../api.js';
import { h, esc, icon, toast, modal, withStates, emptyState, debounce, fmtDate, fmtDuration, essayTypeLabel, ESSAY_TYPES, asList, store, wordCount } from '../ui.js';
import { writerView } from '../components/writer.js';
import { analysisPanel } from '../components/analysis.js';
import { annotatedText, writingCorrections, fixesToggle } from '../components/inline-fix.js';
import { splitPane } from '../components/split.js';
import { navigate, nav, setTitle } from '../app.js';

export async function render(root, params, query) {
  const [sub, id] = params;
  if (sub === 'write') return renderWrite(root, Number(id));
  if (sub === 'submission') return renderSubmission(root, Number(id));
  return renderBank(root, sub === 'submissions' ? 'subs' : (query.tab || 'bank'));
}

export async function getPrompt(id) {
  try {
    return await api.get(`/api/writing/prompts/${id}`);
  } catch (e) {
    if (e.status && e.status !== 404 && e.status !== 405) throw e;
    const all = asList(await api.get('/api/writing/prompts'), 'prompts');
    const p = all.find((x) => Number(x.id) === Number(id));
    if (!p) throw new Error(`Prompt #${id} not found`);
    return p;
  }
}

// ------------------------------------------------------------------ bank + submissions
function renderBank(root, tab) {
  setTitle('Writing');
  root.replaceChildren(h('div', { class: 'page-head' },
    h('div', null, h('h1', null, 'Writing'), h('p', null, 'Real exam prompts, teacher tasks and your own essays — write under time and get criterion-based AI feedback.')),
    h('div', { class: 'page-actions' },
      h('button', { class: 'btn', type: 'button', html: `${icon('shuffle')} Random Task 1`, onclick: () => randomPrompt(1) }),
      h('button', { class: 'btn primary', type: 'button', html: `${icon('shuffle')} Random Task 2`, onclick: () => randomPrompt(2) }))));
  const tabs = h('div', { class: 'tabs', role: 'tablist' });
  const body = h('div');
  root.append(tabs, body);
  const draw = (t) => {
    tabs.replaceChildren(
      h('button', { role: 'tab', type: 'button', 'aria-selected': String(t === 'bank'), onclick: () => draw('bank') }, 'Prompt bank'),
      h('button', { role: 'tab', type: 'button', 'aria-selected': String(t === 'subs'), onclick: () => draw('subs') }, 'My submissions'));
    if (t === 'bank') bankView(body); else submissionsView(body);
    history.replaceState(null, '', t === 'bank' ? '#/writing' : '#/writing/submissions');
    nav.lastHash = location.hash;
  };
  draw(tab);
}

async function randomPrompt(task) {
  try {
    const p = await api.get('/api/writing/prompts/random', { task });
    if (!p || !p.id) { toast('No prompts available for this task yet.'); return; }
    navigate(`#/writing/write/${p.id}`);
  } catch (e) { toast(`Could not get a random prompt: ${e.message}`, 'error'); }
}

function bankView(body) {
  const f = store.get('writingFilter', { task: '', essay_type: '', source: '', q: '' });
  const toolbar = h('div', { class: 'toolbar' });
  const list = h('div');
  body.replaceChildren(toolbar, list);

  const search = h('div', { class: 'search' }, h('span', { html: icon('search') }),
    h('input', { class: 'input', type: 'search', placeholder: 'Search prompts…', value: f.q, 'aria-label': 'Search prompts' }));
  const taskChips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Task' });
  const drawChips = () => taskChips.replaceChildren(...[['', 'All tasks'], ['1', 'Task 1'], ['2', 'Task 2']].map(([v, l]) =>
    h('button', { class: 'chip', type: 'button', 'aria-pressed': String(String(f.task) === v), onclick: () => { f.task = v; drawChips(); drawTypeSel(); load(); } }, l)));
  drawChips();
  const typeSel = h('select', { class: 'select', 'aria-label': 'Essay type' });
  const drawTypeSel = () => {
    const t1 = ['line', 'bar', 'pie', 'table', 'map', 'process', 'mixed'];
    const keys = Object.keys(ESSAY_TYPES).filter((k) => !f.task || (f.task === '1' ? t1.includes(k) : !t1.includes(k)));
    if (f.essay_type && !keys.includes(f.essay_type)) f.essay_type = '';
    typeSel.replaceChildren(h('option', { value: '' }, 'All types'), ...keys.map((k) => h('option', { value: k, selected: f.essay_type === k }, essayTypeLabel(k))));
  };
  drawTypeSel();
  const srcSel = h('select', { class: 'select', 'aria-label': 'Source' });
  const addBtn = h('button', { class: 'btn', type: 'button', html: `${icon('plus')} Add prompt`, onclick: () => addPrompt(() => load()) });
  toolbar.append(search, taskChips, typeSel, srcSel, h('div', { class: 'spacer' }), addBtn);

  let all = [];
  const load = () => {
    store.set('writingFilter', f);
    withStates(list, () => api.get('/api/writing/prompts', { task: f.task, essay_type: f.essay_type, q: f.q }), (data) => {
      all = asList(data, 'prompts');
      const sources = [...new Set(all.map((p) => p.source).filter(Boolean))].sort();
      const cur = f.source;
      srcSel.replaceChildren(h('option', { value: '' }, 'All sources'), ...sources.map((s) => h('option', { value: s, selected: s === cur }, s.replace(/_/g, ' '))));
      drawList();
    });
  };
  const drawList = () => {
    const shown = all.filter((p) => !f.source || p.source === f.source);
    list.replaceChildren();
    if (!shown.length) { list.append(emptyState('No prompts found', 'Try a different filter, or add your own prompt.', 'writing')); return; }
    list.append(h('div', { class: 'small muted', style: { marginBottom: '10px' } }, `${shown.length} prompt${shown.length > 1 ? 's' : ''}`));
    const ul = h('div', { class: 'prompt-list' });
    for (const p of shown.slice(0, 300)) ul.append(promptItem(p));
    list.append(ul);
    if (shown.length > 300) list.append(h('p', { class: 'muted small' }, `Showing first 300 — refine your search.`));
  };
  search.querySelector('input').addEventListener('input', debounce((e) => { f.q = e.target.value; load(); }, 250));
  typeSel.addEventListener('change', () => { f.essay_type = typeSel.value; load(); });
  srcSel.addEventListener('change', () => { f.source = srcSel.value; store.set('writingFilter', f); drawList(); });
  load();
}

function promptItem(p) {
  const done = Number(p.submission_count || p.submissions || 0);
  const draft = store.get(`draft.writing.${p.id}`);
  const el = h('article', { class: 'card prompt-item' });
  el.innerHTML = `<div style="min-width:0">
      <div class="p-meta">
        <span class="badge accent">Task ${esc(p.task)}</span>
        ${p.essay_type ? `<span class="badge">${esc(essayTypeLabel(p.essay_type))}</span>` : ''}
        ${p.source ? `<span class="badge">${esc(String(p.source).replace(/_/g, ' '))}</span>` : ''}
        ${p.source_date ? `<span class="badge">${esc(p.source_date)}</span>` : ''}
        ${p.image_path ? `<span class="badge">${icon('dashboard')} visual</span>` : ''}
        ${done ? `<span class="badge good">${done} submitted</span>` : ''}
        ${draft?.text ? '<span class="badge warn">Draft</span>' : ''}
      </div>
      <div class="p-text">${esc(p.prompt)}</div>
    </div>`;
  el.querySelectorAll('.badge svg').forEach((s) => { s.style.width = '12px'; s.style.height = '12px'; });
  el.append(h('a', { class: 'btn primary sm', href: `#/writing/write/${p.id}` }, draft?.text ? 'Continue' : 'Write'));
  return el;
}

async function addPrompt(done) {
  const body = h('div', { class: 'stack' });
  body.innerHTML = `
    <div class="field"><label for="np-task">Task</label><select id="np-task" class="select"><option value="2">Task 2 (essay)</option><option value="1">Task 1 (report)</option></select></div>
    <div class="field"><label for="np-type">Type</label><select id="np-type" class="select">${Object.entries(ESSAY_TYPES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select></div>
    <div class="field"><label for="np-text">Prompt</label><textarea id="np-text" class="textarea" rows="6" placeholder="Paste the question…"></textarea></div>`;
  const v = await modal({
    title: 'Add your own prompt', body,
    actions: [{ label: 'Cancel', value: null }, { label: 'Add prompt', kind: 'primary', value: (b) => ({
      task: Number(b.querySelector('#np-task').value), essay_type: b.querySelector('#np-type').value,
      prompt: b.querySelector('#np-text').value.trim(), source: 'user' }) }],
  });
  if (!v) return;
  if (!v.prompt) { toast('The prompt text is empty.', 'error'); return; }
  try { await api.post('/api/writing/prompts', v); toast('Prompt added.', 'good'); done(); }
  catch (e) { toast(`Could not add: ${e.message}`, 'error'); }
}

function submissionsView(body) {
  const list = h('div');
  body.replaceChildren(list);
  withStates(list, () => api.get('/api/writing/submissions'), (data) => {
    const subs = asList(data, 'submissions').sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    if (!subs.length) { list.append(emptyState('No essays yet', 'Your submitted essays (and essays imported from Telegram) appear here.', 'writing')); return; }
    const wrap = h('div', { class: 'card table-wrap' });
    wrap.innerHTML = `<table class="table"><thead><tr><th>Date</th><th>Task</th><th>Prompt</th><th class="num">Words</th><th class="num">Time</th><th>Origin</th><th>AI band</th></tr></thead><tbody>
      ${subs.map((s) => `<tr>
        <td class="nowrap">${esc(fmtDate(s.created_at, false))}</td>
        <td><span class="badge accent">T${esc(s.task ?? s.prompt?.task ?? '?')}</span></td>
        <td style="max-width:460px"><a href="#/writing/submission/${s.id}" style="color:inherit;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(s.prompt_excerpt || s.prompt_text || s.prompt?.prompt || '(prompt)')}</a></td>
        <td class="num">${esc(s.word_count ?? '')}</td>
        <td class="num">${s.time_spent_sec ? esc(fmtDuration(s.time_spent_sec)) : '–'}</td>
        <td>${s.origin === 'telegram_import' ? '<span class="badge">Telegram</span>' : '<span class="badge">App</span>'}</td>
        <td>${s.band != null ? `<span class="band-pill">${Number(s.band).toFixed(1)}</span>` : '<span class="muted small">–</span>'}</td></tr>`).join('')}
      </tbody></table>`;
    wrap.querySelectorAll('tbody tr').forEach((tr, i) => {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', (e) => { if (!e.target.closest('a')) navigate(`#/writing/submission/${subs[i].id}`); });
    });
    list.append(wrap);
  });
}

// ------------------------------------------------------------------ editor
async function renderWrite(root, promptId) {
  const prompt = await getPrompt(promptId);
  setTitle(`Writing — Task ${prompt.task}`);
  const task = Number(prompt.task) === 1 ? 1 : 2;
  const w = writerView({
    title: `Writing Task ${task}`,
    subtitle: `${essayTypeLabel(prompt.essay_type)} · ${task === 1 ? '20' : '40'} minutes`,
    tasks: [{ prompt, draftKey: `draft.writing.${prompt.id}` }],
    minutes: task === 1 ? 20 : 40,
    onExit: () => navigate('#/writing'),
    onSubmit: async ([t]) => {
      const res = await api.post('/api/writing/submissions', { prompt_id: prompt.id, text: t.text, time_spent_sec: t.time_spent_sec });
      nav.guard = null;
      toast(`Essay saved (${res.word_count ?? wordCount(t.text)} words).`, 'good');
      navigate(`#/writing/submission/${res.id}`);
    },
  });
  root.replaceChildren(w.el);
  return () => { w.destroy(); };
}

// ------------------------------------------------------------------ submission detail
async function renderSubmission(root, id) {
  const s = await api.get(`/api/writing/submissions/${id}`);
  const p = (s.prompt && typeof s.prompt === 'object') ? s.prompt : {
    id: s.prompt_id, task: s.task, prompt: s.prompt_text || s.prompt, essay_type: s.essay_type, image_path: s.image_path, source: s.source,
  };
  const task = Number(p.task) === 1 ? 1 : 2;
  setTitle(`Essay #${id}`);
  const wc = s.word_count ?? wordCount(s.text);
  const min = task === 1 ? 150 : 250;
  root.replaceChildren(h('div', { class: 'page-head' },
    h('div', null,
      h('div', { class: 'small' }, h('a', { href: s.mock_id ? `#/mock/${s.mock_id}` : '#/writing/submissions' }, s.mock_id ? '← Mock exam' : '← My submissions')),
      h('h1', null, `Task ${task} essay`),
      h('p', null, `${fmtDate(s.created_at)} · ${s.origin === 'telegram_import' ? 'Imported from Telegram' : 'Written in app'}`)),
    h('div', { class: 'page-actions' },
      p.id ? h('a', { class: 'btn', href: `#/writing/write/${p.id}`, html: `${icon('writing')} Write again` }) : null)));

  const promptCard = h('div', { class: 'card card-pad' });
  promptCard.innerHTML = `<div class="row" style="margin-bottom:8px"><span class="badge accent">Task ${task}</span>
      ${p.essay_type ? `<span class="badge">${esc(essayTypeLabel(p.essay_type))}</span>` : ''}
      ${p.source ? `<span class="badge">${esc(String(p.source).replace(/_/g, ' '))}</span>` : ''}</div>
    <div style="white-space:pre-wrap;line-height:1.65">${esc(p.prompt || '(prompt not available)')}</div>
    ${p.image_path ? `<img class="zoomable" src="${esc(mediaUrl(p.image_path))}" alt="Task visual" title="Click to enlarge" style="margin-top:12px;border:1px solid var(--border);border-radius:8px;background:#fff">` : ''}`;
  const essayCard = h('div', { class: 'card card-pad' });
  essayCard.innerHTML = `<div class="row between" style="margin-bottom:10px"><h2 style="margin:0">Your answer</h2>
      <div class="row small"><span class="fix-toggle-slot"></span><span class="badge ${wc >= min ? 'good' : 'bad'}">${wc} words</span>
      ${s.time_spent_sec ? `<span class="badge">${esc(fmtDuration(s.time_spent_sec))}</span>` : ''}</div></div>
    <div class="essay-text">${esc(s.text || '')}</div>
    <div class="small muted essay-ai-hint hidden" style="margin-top:8px">AI corrections are shown under each sentence (switch to Compact to see only the marks — click one to open it); the full report is below.</div>`;
  // Under each sentence: the AI's corrections for it (when an analysis is on screen).
  const showCorrections = (j) => {
    const fixes = writingCorrections(j);
    const old = essayCard.querySelector('.essay-text, .annotated');
    const next = fixes.length ? annotatedText(s.text || '', fixes) : h('div', { class: 'essay-text' }, s.text || '');
    old.replaceWith(next);
    essayCard.querySelector('.essay-ai-hint').classList.toggle('hidden', !fixes.length);
    essayCard.querySelector('.fix-toggle-slot').replaceChildren(fixes.length ? fixesToggle(essayCard) : '');
  };
  const split = splitPane(promptCard, essayCard, { key: 'essay', initial: 38, min: 22, max: 60, page: true, stackBelow: 820, label: 'Resize task and essay' });
  split.classList.add('essay-split');
  root.append(split);
  root.append(analysisPanel({
    target_type: 'writing', target_id: id, title: 'Analyse with AI',
    subtitle: `Band per criterion (${task === 1 ? 'TA' : 'TR'}, CC, LR, GRA), corrected sentences and a higher-band rewrite.`,
    onResult: showCorrections,
  }));
}
