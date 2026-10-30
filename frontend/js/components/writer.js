// Full-screen writing editor used for single-task practice and the mock exam (task 1 + task 2).
import { mediaUrl } from '../api.js';
import { h, esc, icon, toast, fmtClock, wordCount, store, confirmDialog, essayTypeLabel, modal } from '../ui.js';
import { assistButton, setAssistContext } from './assist.js';
import { splitPane } from './split.js';

/**
 * opts: {
 *   title, subtitle,
 *   tasks: [{ prompt, draftKey }],     // prompt = writing_prompts row
 *   minutes,                            // total time
 *   onSubmit: async ([{prompt, text, time_spent_sec}]) => void,
 *   onExit: () => void,
 *   strictTime: bool                    // mock: auto-submit when time is up
 * }
 * Returns { el, destroy }
 */
export function writerView(opts) {
  const tasks = opts.tasks.map((t) => ({
    ...t,
    text: store.get(t.draftKey)?.text || '',
    spent: store.get(t.draftKey)?.spent || 0,
  }));
  const timeKey = `${tasks.map((t) => t.draftKey).join('|')}.elapsed`;
  let elapsed = store.get(timeKey, 0);
  const total = opts.minutes * 60;
  let idx = 0;
  let submitted = false;
  let timeUp = false;

  const el = h('div', { class: 'player writing-player' });
  const timerEl = h('div', { class: 'timer', role: 'timer', html: `${icon('clock')}<span class="t-val"></span>` });
  const tabs = h('div', { class: 'pl-tabs', role: 'tablist' });
  const exitBtn = h('button', { class: 'btn sm ghost', type: 'button', html: `${icon('close')} Exit` });
  const hideBtn = h('button', { class: 'icon-btn', type: 'button', title: 'Hide / show timer', 'aria-label': 'Hide or show timer', html: icon('eye') });
  el.append(h('header', { class: 'pl-top' },
    h('div', { class: 'pl-title' }, opts.title, h('small', null, opts.subtitle || '')),
    tabs, h('div', { class: 'pl-actions' }, timerEl, hideBtn, assistButton({ compact: true, mock: !!opts.strictTime }), exitBtn)));

  const left = h('div', { class: 'writer-left' });
  const ta = h('textarea', { class: 'essay-input', spellcheck: 'false', autocomplete: 'off', 'aria-label': 'Your essay', placeholder: 'Start writing your answer here…' });
  const wcEl = h('div', { class: 'wc-meter' });
  const saveEl = h('span', { class: 'small muted' });
  const submitBtn = h('button', { class: 'btn primary', type: 'button', html: `${icon('check')} ${tasks.length > 1 ? 'Submit both tasks' : 'Submit essay'}` });
  const right = h('div', { class: 'writer-right' }, ta,
    h('div', { class: 'writer-foot' }, wcEl, h('span', { class: 'spacer' }), saveEl, submitBtn));
  const split = splitPane(left, right, { key: 'writer', initial: 44, min: 20, max: 70, label: 'Resize task and essay' });
  split.classList.add('writer');
  el.append(split);

  function minWords(t) { return Number(t.prompt.task) === 1 ? 150 : 250; }
  function drawLeft() {
    const t = tasks[idx];
    const p = t.prompt;
    const task = Number(p.task) === 1 ? 1 : 2;
    setAssistContext({ section: task === 1 ? 'writing1' : 'writing2', essayType: p.essay_type, mock: !!opts.strictTime });
    left.innerHTML = `
      <div class="row" style="margin-bottom:10px">
        <span class="badge accent">Task ${task}</span>
        ${p.essay_type ? `<span class="badge">${esc(essayTypeLabel(p.essay_type))}</span>` : ''}
        ${p.source ? `<span class="badge">${esc(String(p.source).replace(/_/g, ' '))}</span>` : ''}
      </div>
      <p class="muted small" style="margin-bottom:12px">${task === 1
        ? 'You should spend about 20 minutes on this task. Write at least 150 words.'
        : 'You should spend about 40 minutes on this task. Write at least 250 words.'}</p>
      <div class="prompt-text">${esc(p.prompt)}</div>
      ${p.image_path || p.image ? `<img class="zoomable" src="${esc(mediaUrl(p.image_path || p.image))}" alt="Task 1 visual" title="Click to enlarge">` : ''}
      ${task === 2 ? '<p class="muted small" style="margin-top:14px">Give reasons for your answer and include any relevant examples from your own knowledge or experience.</p>' : ''}`;
    const img = left.querySelector('img');
    if (img) img.addEventListener('error', () => { img.replaceWith(h('div', { class: 'error-box small' }, 'Image not found: ' + (p.image_path || p.image))); });
  }
  function drawTabs() {
    if (tasks.length < 2) { tabs.replaceChildren(); return; }
    tabs.replaceChildren(...tasks.map((t, i) => h('button', {
      type: 'button', role: 'tab', 'aria-selected': String(i === idx), onclick: () => switchTo(i),
    }, `Task ${t.prompt.task}`, h('span', { class: 'cnt' }, `${wordCount(t.text)} w`))));
  }
  function drawWc() {
    const t = tasks[idx];
    const n = wordCount(t.text), min = minWords(t);
    const pct = Math.min(100, (n / min) * 100);
    wcEl.innerHTML = `<b style="font-variant-numeric:tabular-nums">${n}</b> words
      <div class="bar-track" title="${n} of ${min} minimum"><div class="bar-fill ${n >= min ? 'high' : n >= min * 0.7 ? 'mid' : 'low'}" style="width:${pct}%"></div></div>
      <span class="small ${n >= min ? '' : 'muted'}" style="${n >= min ? 'color:var(--good)' : ''}">${n >= min ? '✓ minimum reached' : `min ${min}`}</span>`;
    const tab = tabs.children[idx]?.querySelector('.cnt');
    if (tab) tab.textContent = `${n} w`;
  }
  function switchTo(i) {
    tasks[idx].text = ta.value;
    idx = i;
    ta.value = tasks[idx].text;
    drawLeft(); drawTabs(); drawWc();
    ta.focus();
  }
  const persist = () => {
    for (const t of tasks) store.set(t.draftKey, { text: t.text, spent: Math.round(t.spent), at: Date.now() });
    store.set(timeKey, Math.round(elapsed));
    saveEl.textContent = 'Draft saved';
  };
  let saveT = null;
  ta.addEventListener('input', () => {
    tasks[idx].text = ta.value;
    drawWc();
    saveEl.textContent = '';
    clearTimeout(saveT);
    saveT = setTimeout(persist, 800);
  });
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey) { /* allow default focus move */ }
  });

  let hidden = store.get('timerHidden', false);
  timerEl.classList.toggle('hidden-time', hidden);
  hideBtn.addEventListener('click', () => {
    hidden = !hidden; store.set('timerHidden', hidden);
    timerEl.classList.toggle('hidden-time', hidden);
    hideBtn.innerHTML = icon(hidden ? 'eyeOff' : 'eye');
  });
  const drawTimer = () => {
    const rem = total - elapsed;
    timerEl.querySelector('.t-val').textContent = rem >= 0 ? fmtClock(rem) : `+${fmtClock(-rem)}`;
    timerEl.classList.toggle('warn', rem < 600 && rem >= 300);
    timerEl.classList.toggle('danger', rem < 300);
  };
  let last = performance.now();
  const tick = setInterval(() => {
    const now = performance.now();
    const d = (now - last) / 1000;
    last = now;
    if (document.hidden && !opts.strictTime) return;
    elapsed += d;
    tasks[idx].spent += d;
    drawTimer();
    if (elapsed >= total && !timeUp) {
      timeUp = true;
      if (opts.strictTime) { toast('Time is up — submitting your writing.'); doSubmit(true); }
      else toast("Time's up! You can keep writing, but in the exam you'd stop now.");
    }
    if (Math.round(elapsed) % 10 === 0) persist();
  }, 1000);

  async function doSubmit(auto) {
    if (submitted) return;
    tasks[idx].text = ta.value;
    if (!auto) {
      const lines = tasks.map((t) => {
        const n = wordCount(t.text), min = minWords(t);
        return `<li>Task ${t.prompt.task}: <b>${n}</b> words${n < min ? ` <span style="color:var(--bad)">(below ${min})</span>` : ''}</li>`;
      }).join('');
      const empty = tasks.some((t) => !t.text.trim());
      const ok = await confirmDialog('Submit writing?', `<ul>${lines}</ul>${empty ? '<p style="color:var(--bad)">One of your tasks is empty.</p>' : ''}<p>You can ask the AI to analyse it on the next page.</p>`, 'Submit');
      if (!ok) return;
    }
    submitted = true;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span> Submitting…';
    try {
      await opts.onSubmit(tasks.map((t) => ({ prompt: t.prompt, text: t.text, time_spent_sec: Math.round(t.spent) })));
      for (const t of tasks) store.remove(t.draftKey);
      store.remove(timeKey);
    } catch (e) {
      submitted = false;
      submitBtn.disabled = false;
      submitBtn.innerHTML = `${icon('check')} Submit`;
      toast(`Submit failed: ${e.message}`, 'error');
    }
  }
  submitBtn.addEventListener('click', () => doSubmit(false));
  exitBtn.addEventListener('click', () => opts.onExit());

  ta.value = tasks[0].text;
  drawLeft(); drawTabs(); drawWc(); drawTimer();
  if (tasks.some((t) => t.text)) saveEl.textContent = 'Draft restored';
  setTimeout(() => ta.focus(), 50);

  return {
    el,
    isDirty: () => !submitted && tasks.some((t) => t.text.trim()),
    destroy() { clearInterval(tick); clearTimeout(saveT); if (!submitted) { tasks[idx].text = ta.value; persist(); } },
  };
}

export { modal };
