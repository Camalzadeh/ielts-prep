// Listening / Reading test player (computer-delivered IELTS style).
import { api, mediaUrl } from '../api.js';
import { h, esc, icon, toast, modal, confirmDialog, fmtClock, store, sanitizeContent, parseMaybeJSON } from '../ui.js';
import { renderGroup, partQuestionNumbers } from '../components/questions.js';
import { attachHighlighter } from '../components/highlight.js';
import { splitPane } from '../components/split.js';
import { navigate, nav, setTitle } from '../app.js';
import { assistButton, setAssistContext, setAssistQType } from '../components/assist.js';

const AUTOSAVE_MS = 5000;

export async function render(root, params, query) {
  const [testId, attemptParam] = params;
  const mode = query.mode === 'mock' ? 'mock' : 'practice';
  const mockId = query.mock ? Number(query.mock) : null;
  const test = await api.get(`/api/tests/${encodeURIComponent(testId)}`);
  const type = test.type === 'listening' ? 'listening' : 'reading';
  const parts = (test.parts || []).slice().sort((a, b) => a.number - b.number);
  const durationSec = (Number(test.duration_minutes) || (type === 'listening' ? 30 : 60)) * 60;
  setTitle(test.title || testId);

  const allNums = parts.flatMap(partQuestionNumbers);
  const numToPart = new Map();
  parts.forEach((p, i) => partQuestionNumbers(p).forEach((n) => numToPart.set(n, i)));
  const activeKey = `active.${testId}.${mode}.${mockId || ''}`;

  // ------------------------------------------------------------------ state
  const S = {
    attemptId: attemptParam ? Number(attemptParam) : (store.get(activeKey) || null),
    answers: {}, flags: new Set(), highlights: {}, elapsed: 0, partIdx: 0,
    current: allNums[0] || 1, started: false, submitted: false, dirty: false,
    audio: { part: 0, pos: {}, finished: false }, timerHidden: store.get('timerHidden', false),
  };
  let resuming = !!S.attemptId;
  const localKey = () => `attempt.${S.attemptId}`;

  function loadLocal() {
    const l = store.get(localKey());
    if (!l) return false;
    S.answers = l.answers || {};
    S.flags = new Set(l.flags || []);
    S.highlights = l.highlights || {};
    S.elapsed = l.elapsed || 0;
    S.partIdx = Math.min(l.partIdx || 0, parts.length - 1);
    S.current = l.current || S.current;
    S.audio = { ...S.audio, ...(l.audio || {}) };
    S.audio.pos = S.audio.pos || {};
    if (S.audio.time) { S.audio.pos[S.audio.part] = S.audio.time; delete S.audio.time; }  // older saves: one shared position
    return true;
  }
  function saveLocal() {
    if (!S.attemptId || S.submitted) return;
    store.set(localKey(), {
      answers: S.answers, flags: [...S.flags], highlights: S.highlights, elapsed: Math.round(S.elapsed),
      partIdx: S.partIdx, current: S.current, audio: S.audio, testId, mode, mockId, savedAt: Date.now(),
    });
  }

  if (resuming) {
    try {
      const a = await api.get(`/api/attempts/${S.attemptId}`);
      if (a && a.status === 'submitted') {
        store.remove(activeKey);
        store.remove(localKey());
        navigate(`#/result/${S.attemptId}`, { replace: true });
        return;
      }
      const hadLocal = loadLocal();
      if (!hadLocal && a) {
        S.answers = parseMaybeJSON(a.answers_json, null) || a.answers || {};
        S.highlights = parseMaybeJSON(a.highlights_json, null) || a.highlights || {};
      }
    } catch (e) {
      if (e.status === 404) {  // the attempt was deleted: start fresh instead of "resuming" nothing
        store.remove(activeKey);
        store.remove(localKey());
        S.attemptId = null;
        resuming = false;
      } else {
        loadLocal();
      }
    }
  }

  // ------------------------------------------------------------------ layout
  setAssistContext({ section: type, mock: mode === 'mock' });
  const qTypeOf = (n) => { for (const p of test.parts || []) for (const g of p.groups || []) if (g.range && n >= g.range[0] && n <= g.range[1]) return g.type; return null; };
  const player = h('div', { class: `player ${type} fs-${store.get('fontSize', 'm')}` });
  const timerEl = h('div', { class: `timer${S.timerHidden ? ' hidden-time' : ''}`, role: 'timer', 'aria-live': 'off', html: `${icon('clock')}<span class="t-val">--:--</span>` });
  const tabs = h('div', { class: 'pl-tabs', role: 'tablist', 'aria-label': type === 'reading' ? 'Passages' : 'Parts' });
  const hideBtn = h('button', { class: 'icon-btn', type: 'button', title: 'Hide / show timer', 'aria-label': 'Hide or show timer', html: icon(S.timerHidden ? 'eyeOff' : 'eye') });
  const fontBtn = h('button', { class: 'icon-btn', type: 'button', title: 'Text size', 'aria-label': 'Change text size', html: '<b style="font-size:13px">Aa</b>' });
  const exitBtn = h('button', { class: 'btn sm ghost', type: 'button', html: `${icon('close')} Exit` });
  const top = h('header', { class: 'pl-top' },
    h('div', { class: 'pl-title', title: test.title || '' }, test.title || testId,
      h('small', null, `${type === 'listening' ? 'Listening' : 'Reading'} · ${mode === 'mock' ? 'Mock exam' : 'Practice mode'}`)),
    tabs,
    h('div', { class: 'pl-actions' }, timerEl, hideBtn, fontBtn, assistButton({ compact: true }), exitBtn),
  );
  player.append(top);

  let audioBar = null;
  const audio = type === 'listening' ? new Audio() : null;
  if (audio) {
    audio.preload = 'auto';
    audioBar = h('div', { class: 'audio-bar' });
    player.append(audioBar);
  }

  const body = h('div', { class: 'pl-body' });
  player.append(body);
  const passagePane = h('div', { class: 'pane passage', tabindex: '0', 'aria-label': 'Reading passage' });
  const questionsPane = h('div', { class: `pane questions${type === 'listening' ? ' full' : ''}`, 'aria-label': 'Questions' });
  if (type === 'reading') {
    body.append(splitPane(passagePane, questionsPane, { key: 'reading', initial: store.get('splitPct', 50), label: 'Resize passage and questions' }));
  } else {
    body.append(questionsPane);
  }

  const palette = h('footer', { class: 'pl-palette', 'aria-label': 'Question navigation' });
  player.append(palette);
  root.replaceChildren(player);

  // ------------------------------------------------------------------ question ctx
  const ctx = {
    mode: 'test',
    getAnswer: (n) => S.answers[n] ?? '',
    setAnswer: (n, v) => {
      if (S.submitted) return;
      const val = typeof v === 'string' ? v : String(v ?? '');
      if (val.trim() === '') delete S.answers[n]; else S.answers[n] = val;
      S.dirty = true;
      saveLocal();
      updatePalette();
      setSave('Autosave pending');
    },
    detail: () => undefined,
    toast,
  };

  // Parts content
  const partEls = parts.map((part, i) => {
    const qWrap = h('div', { class: 'part-questions', dataset: { part: i } });
    const nums = partQuestionNumbers(part);
    const label = type === 'reading' ? 'Passage' : 'Part';
    qWrap.append(h('div', { class: 'part-banner', html: `<b>${label} ${part.number}</b> &nbsp;·&nbsp; ${type === 'reading' ? 'Read the text and answer' : 'Listen and answer'} questions ${nums[0] ?? ''}–${nums[nums.length - 1] ?? ''}.` }));
    for (const g of part.groups || []) qWrap.append(renderGroup(g, ctx));
    let pWrap = null, hl = null;
    if (type === 'reading') {
      pWrap = h('div', { class: 'part-passage', dataset: { part: i } });
      const title = part.title && !/^passage\s*\d+$/i.test(part.title) ? part.title : '';
      if (title) pWrap.append(h('div', { class: 'passage-title' }, title));
      const pb = h('div', { class: 'passage-body' });
      const original = sanitizeContent(part.passage_html || '<p class="muted">No passage text.</p>');
      pb.innerHTML = original;
      pWrap.append(pb);
      hl = attachHighlighter(pb, {
        getRanges: () => S.highlights[part.number] || [],
        setRanges: (r) => { S.highlights[part.number] = r; S.dirty = true; saveLocal(); setSave('Autosave pending'); },
        rerender: () => { pb.innerHTML = original; },
      });
    }
    return { qWrap, pWrap, hl, nums, scroll: { q: 0, p: 0 } };
  });
  questionsPane.append(...partEls.map((p) => p.qWrap));
  if (type === 'reading') passagePane.append(...partEls.map((p) => p.pWrap));

  questionsPane.addEventListener('focusin', (e) => {
    const el = e.target.closest('[data-q]');
    if (el) setCurrent(Number(el.dataset.q), false);
  });

  // ------------------------------------------------------------------ tabs + parts
  function drawTabs() {
    tabs.replaceChildren(...parts.map((p, i) => {
      const nums = partEls[i].nums;
      const done = nums.filter((n) => S.answers[n]).length;
      return h('button', {
        type: 'button', role: 'tab', 'aria-selected': String(i === S.partIdx),
        onclick: () => showPart(i, true),
      }, `${type === 'reading' ? 'Passage' : 'Part'} ${p.number}`, h('span', { class: 'cnt' }, `${done}/${nums.length}`));
    }));
  }

  function showPart(i, jumpFirst = false) {
    if (i < 0 || i >= parts.length) return;
    const prev = partEls[S.partIdx];
    if (prev) { prev.scroll.q = questionsPane.scrollTop; prev.scroll.p = passagePane.scrollTop; }
    S.partIdx = i;
    partEls.forEach((p, k) => {
      p.qWrap.hidden = k !== i;
      if (p.pWrap) p.pWrap.hidden = k !== i;
    });
    questionsPane.scrollTop = partEls[i].scroll.q;
    passagePane.scrollTop = partEls[i].scroll.p;
    if (type === 'listening') body.scrollTop = 0;
    if (jumpFirst && !partEls[i].nums.includes(S.current)) setCurrent(partEls[i].nums[0], false);
    drawTabs();
    drawPalette();
    if (audio && mode === 'practice') loadAudioForPart(i, false);
    saveLocal();
  }

  // ------------------------------------------------------------------ palette
  let palNums = new Map();
  const flagBtn = h('button', { class: 'btn sm', type: 'button', title: 'Flag for review (Alt+F)', html: `${icon('flag')} Flag` });
  const prevBtn = h('button', { class: 'icon-btn', type: 'button', title: 'Previous question (Alt+←)', 'aria-label': 'Previous question', html: icon('chevronLeft') });
  const nextBtn = h('button', { class: 'icon-btn', type: 'button', title: 'Next question (Alt+→)', 'aria-label': 'Next question', html: icon('chevronRight') });
  const saveEl = h('span', { class: 'save-state', 'aria-live': 'polite' }, '');
  const submitBtn = h('button', { class: 'btn primary', type: 'button', html: `${icon('check')} Submit` });
  const partsBox = h('div', { class: 'pal-parts' });
  palette.append(partsBox, h('div', { class: 'pal-ctrl' }, saveEl, flagBtn, prevBtn, nextBtn, submitBtn));

  function drawPalette() {
    palNums = new Map();
    partsBox.replaceChildren(...parts.map((p, i) => {
      const nums = partEls[i].nums;
      const active = i === S.partIdx;
      const done = nums.filter((n) => S.answers[n]).length;
      const box = h('div', { class: `pal-part${active ? ' active' : ''}` },
        h('button', { class: 'pal-label', type: 'button', onclick: () => showPart(i, true), 'aria-label': `${type === 'reading' ? 'Passage' : 'Part'} ${p.number}, ${done} of ${nums.length} answered` },
          `${type === 'reading' ? 'Passage' : 'Part'} ${p.number}`, h('span', { class: 'cnt' }, `${done}/${nums.length}`)));
      if (active) {
        const wrap = h('div', { class: 'pal-nums' });
        for (const n of nums) {
          const b = h('button', { class: 'pal-num', type: 'button', onclick: () => jumpTo(n) }, String(n));
          palNums.set(n, b);
          wrap.append(b);
        }
        box.append(wrap);
      }
      return box;
    }));
    updatePalette();
  }
  function updatePalette() {
    for (const [n, b] of palNums) {
      b.classList.toggle('answered', !!S.answers[n]);
      b.classList.toggle('flagged', S.flags.has(n));
      b.classList.toggle('current', n === S.current);
      b.setAttribute('aria-label', `Question ${n}${S.answers[n] ? ', answered' : ', unanswered'}${S.flags.has(n) ? ', flagged' : ''}`);
      if (n === S.current) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current');
    }
    flagBtn.classList.toggle('flagged', S.flags.has(S.current));
    flagBtn.innerHTML = `${icon('flag')} ${S.flags.has(S.current) ? 'Flagged' : 'Flag'}`;
    // tab counts
    tabs.querySelectorAll('button').forEach((b, i) => {
      const nums = partEls[i].nums;
      const c = b.querySelector('.cnt');
      if (c) c.textContent = `${nums.filter((n) => S.answers[n]).length}/${nums.length}`;
    });
    partsBox.querySelectorAll('.pal-part .pal-label .cnt').forEach((c, i) => {
      const nums = partEls[i].nums;
      c.textContent = `${nums.filter((n) => S.answers[n]).length}/${nums.length}`;
    });
  }

  function qElement(n) {
    return document.getElementById(`q-${n}`);
  }
  function setCurrent(n, scroll) {
    if (!numToPart.has(n)) return;
    document.querySelectorAll('.player .current').forEach((e) => { if (!e.classList.contains('pal-num')) e.classList.remove('current'); });
    S.current = n;
    setAssistQType(qTypeOf(n));
    let el = qElement(n);
    if (el && el.classList.contains('anchor')) el = el.parentElement;
    if (el) {
      el.classList.add('current');
      if (scroll) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
    updatePalette();
  }
  function jumpTo(n) {
    const pi = numToPart.get(n);
    if (pi === undefined) return;
    if (pi !== S.partIdx) showPart(pi);
    setCurrent(n, true);
    let el = qElement(n);
    if (el && el.classList.contains('anchor')) el = el.parentElement;
    const focusable = el && (el.matches('input,select') ? el : el.querySelector('input:not([type=radio]):not(:disabled), select, input[type=radio]:checked, input[type=radio], input[type=checkbox]'));
    if (focusable) setTimeout(() => focusable.focus({ preventScroll: true }), 250);
  }
  function step(d) {
    const i = allNums.indexOf(S.current);
    const n = allNums[Math.max(0, Math.min(allNums.length - 1, i + d))];
    if (n !== undefined) jumpTo(n);
  }
  flagBtn.addEventListener('click', () => {
    if (S.flags.has(S.current)) S.flags.delete(S.current); else S.flags.add(S.current);
    saveLocal(); updatePalette();
  });
  prevBtn.addEventListener('click', () => step(-1));
  nextBtn.addEventListener('click', () => step(1));

  // ------------------------------------------------------------------ timer
  let tickHandle = null, lastTick = 0, timeUpShown = false;
  function drawTimer() {
    const rem = durationSec - S.elapsed;
    const v = timerEl.querySelector('.t-val');
    v.textContent = rem >= 0 ? fmtClock(rem) : `+${fmtClock(-rem)}`;
    timerEl.classList.toggle('warn', rem < 600 && rem >= 300);
    timerEl.classList.toggle('danger', rem < 300);
    timerEl.title = `${fmtClock(Math.max(0, rem))} remaining`;
  }
  function startTimer() {
    lastTick = performance.now();
    tickHandle = setInterval(() => {
      const now = performance.now();
      S.elapsed += (now - lastTick) / 1000;
      lastTick = now;
      drawTimer();
      if (S.elapsed >= durationSec && !timeUpShown) { timeUpShown = true; onTimeUp(); }
    }, 500);
  }
  async function onTimeUp() {
    if (mode === 'mock') {
      toast('Time is up — submitting your answers.');
      submit(true);
      return;
    }
    const v = await modal({
      title: "Time's up",
      body: '<p>The recommended time for this test has finished. You can submit now or keep working (overtime is recorded).</p>',
      actions: [{ label: 'Keep working', value: false }, { label: 'Submit now', kind: 'primary', value: true }],
    });
    if (v) submit(true);
  }
  hideBtn.addEventListener('click', () => {
    S.timerHidden = !S.timerHidden;
    store.set('timerHidden', S.timerHidden);
    timerEl.classList.toggle('hidden-time', S.timerHidden);
    hideBtn.innerHTML = icon(S.timerHidden ? 'eyeOff' : 'eye');
  });
  fontBtn.addEventListener('click', () => {
    const order = ['s', 'm', 'l'];
    const cur = store.get('fontSize', 'm');
    const next = order[(order.indexOf(cur) + 1) % 3];
    store.set('fontSize', next);
    player.classList.remove('fs-s', 'fs-m', 'fs-l');
    player.classList.add(`fs-${next}`);
    toast(`Text size: ${{ s: 'small', m: 'medium', l: 'large' }[next]}`);
  });

  // ------------------------------------------------------------------ autosave
  function setSave(t) { saveEl.textContent = t; }
  async function autosave(keepalive = false) {
    if (!S.attemptId || !S.dirty || S.submitted) return;
    S.dirty = false;
    setSave('Saving…');
    try {
      await api.put(`/api/attempts/${S.attemptId}/autosave`, { answers: S.answers, highlights: S.highlights }, { keepalive });
      setSave('Saved');
    } catch (e) {
      S.dirty = true;
      setSave('Offline — saved locally');
    }
  }
  const saveHandle = setInterval(() => autosave(), AUTOSAVE_MS);

  // ------------------------------------------------------------------ audio (listening)
  let audioFailed = false;
  function audioSrcFor(i) {
    const p = parts[i];
    return { local: p.audio_url || (p.audio ? mediaUrl(p.audio) : ''), remote: p.audio_remote || '' };
  }
  function loadAudioForPart(i, autoplay) {
    if (!audio) return;
    const { local, remote } = audioSrcFor(i);
    const want = local || remote;
    S.audio.part = i;
    audioFailed = false;
    if (!want) { audio.removeAttribute('src'); drawAudio(); return; }
    if (audio.dataset.part !== String(i)) {
      audio.pause();
      audio.dataset.part = String(i);
      audio.dataset.triedRemote = '';
      audio.src = want;
      audio.load();
    }
    if (autoplay) audio.play().catch(() => drawAudio());
    drawAudio();
  }
  if (audio) {
    audio.addEventListener('error', () => {
      const i = Number(audio.dataset.part || 0);
      const { local, remote } = audioSrcFor(i);
      if (local && remote && !audio.dataset.triedRemote) {
        audio.dataset.triedRemote = '1';
        audio.src = remote;
        audio.load();
        if (S.started && mode === 'mock') audio.play().catch(() => {});
        return;
      }
      audioFailed = true;
      drawAudio();
      if (mode === 'mock' && S.started) setTimeout(() => onAudioEnded(), 1500);
    });
    audio.addEventListener('loadedmetadata', () => {
      const t = S.audio.pos[Number(audio.dataset.part)];  // each part resumes where it was left
      if (t && t < audio.duration) {
        try { audio.currentTime = t; } catch { /* ignore */ }
      }
      drawAudio();
    });
    audio.addEventListener('timeupdate', () => {
      if (!audio.ended) S.audio.pos[Number(audio.dataset.part)] = audio.currentTime;
      updateAudioProgress();
    });
    audio.addEventListener('play', drawAudio);
    audio.addEventListener('pause', drawAudio);
    audio.addEventListener('ended', onAudioEnded);
    audio.volume = store.get('volume', 1);
    audio.playbackRate = 1;
  }
  function onAudioEnded() {
    // a finished part starts again from 0:00: reset its position and the counter
    S.audio.pos[Number(audio.dataset.part)] = 0;
    try { audio.currentTime = 0; } catch { /* no source */ }
    if (mode !== 'mock') { drawAudio(); saveLocal(); return; }
    const next = S.audio.part + 1;
    if (next < parts.length) {
      toast(`Part ${parts[next].number} is starting.`);
      showPart(next, true);
      loadAudioForPart(next, true);
    } else {
      S.audio.finished = true;
      drawAudio();
      toast('The recording has finished. Check your answers, then submit.');
    }
    saveLocal();
  }
  let progressEls = null;
  function updateAudioProgress() {
    if (!progressEls) return;
    const d = audio.duration || 0;
    const t = audio.currentTime || 0;
    progressEls.time.textContent = `${fmtClock(t)} / ${d ? fmtClock(d) : '--:--'}`;
    if (progressEls.range && !progressEls.range.dragging) {
      progressEls.range.max = d || 0;
      progressEls.range.value = t;
    }
    if (progressEls.bar) progressEls.bar.style.width = d ? `${(t / d) * 100}%` : '0';
  }
  function drawAudio() {
    if (!audioBar) return;
    const i = mode === 'mock' ? S.audio.part : S.partIdx;
    const p = parts[i];
    const has = !!(p && (p.audio_url || p.audio || p.audio_remote));
    const playing = !audio.paused && !audio.ended;
    const time = h('span', { class: 'a-time' }, '');
    if (mode === 'practice') {
      const play = h('button', { class: 'play', type: 'button', 'aria-label': playing ? 'Pause' : 'Play', html: icon(playing ? 'pause' : 'play'), disabled: !has || audioFailed,
        onclick: () => { if (audio.paused) audio.play().catch((e) => toast(`Cannot play audio: ${e.message}`, 'error')); else audio.pause(); } });
      const back = h('button', { class: 'btn sm ghost', type: 'button', title: 'Back 5 seconds', onclick: () => { audio.currentTime = Math.max(0, audio.currentTime - 5); } }, '−5s');
      const fwd = h('button', { class: 'btn sm ghost', type: 'button', title: 'Forward 5 seconds', onclick: () => { audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 5); } }, '+5s');
      const range = h('input', { type: 'range', class: 'a-seek', min: '0', step: '0.1', 'aria-label': 'Seek' });
      range.addEventListener('input', () => { range.dragging = true; time.textContent = `${fmtClock(range.value)} / ${fmtClock(audio.duration || 0)}`; });
      range.addEventListener('change', () => { audio.currentTime = Number(range.value); range.dragging = false; });
      const speed = h('select', { class: 'select', 'aria-label': 'Playback speed', title: 'Playback speed' },
        ...[0.75, 0.9, 1, 1.1, 1.25, 1.5].map((r) => h('option', { value: r, selected: audio.playbackRate === r }, `${r}×`)));
      speed.addEventListener('change', () => { audio.playbackRate = Number(speed.value); });
      const vol = h('input', { type: 'range', class: 'a-vol', min: '0', max: '1', step: '0.05', value: String(audio.volume), 'aria-label': 'Volume' });
      vol.addEventListener('input', () => { audio.volume = Number(vol.value); store.set('volume', audio.volume); });
      audioBar.replaceChildren(
        play, h('span', { class: 'a-label' }, `Part ${p?.number ?? ''} audio`), back, range, fwd, time, speed,
        h('span', { html: icon('volume'), style: { color: 'var(--text-3)', display: 'inline-flex', width: '18px' } }), vol,
      );
      if (!has) audioBar.append(h('span', { class: 'a-msg' }, 'No audio for this part'));
      if (audioFailed) audioBar.append(h('span', { class: 'a-msg' }, 'Audio could not be loaded'));
      progressEls = { time, range, bar: null };
    } else {
      const bar = h('div', { class: 'a-progress', 'aria-hidden': 'true' }, h('i'));
      const vol = h('input', { type: 'range', class: 'a-vol', min: '0', max: '1', step: '0.05', value: String(audio.volume), 'aria-label': 'Volume' });
      vol.addEventListener('input', () => { audio.volume = Number(vol.value); store.set('volume', audio.volume); });
      let label;
      if (!S.started) label = 'The recording will start when you begin the test.';
      else if (S.audio.finished) label = 'Recording finished';
      else if (audioFailed) label = `Part ${p?.number} audio unavailable — moving on`;
      else label = playing ? `Playing Part ${p?.number} — the recording plays once` : `Part ${p?.number} — paused`;
      const children = [
        h('span', { class: 'play', style: { cursor: 'default' }, html: icon(playing ? 'volume' : 'pause') }),
        h('span', { class: 'a-label' }, label), bar, time,
        h('span', { html: icon('volume'), style: { color: 'var(--text-3)', display: 'inline-flex', width: '18px' } }), vol,
      ];
      if (S.started && !playing && !S.audio.finished && !audioFailed) {
        children.splice(2, 0, h('button', { class: 'btn sm primary', type: 'button', onclick: () => audio.play().catch((e) => toast(e.message, 'error')) }, 'Resume audio'));
      }
      audioBar.replaceChildren(...children);
      progressEls = { time, range: null, bar: bar.firstChild };
    }
    updateAudioProgress();
  }

  // ------------------------------------------------------------------ submit
  async function submit(auto = false) {
    if (S.submitted) return;
    if (!S.attemptId) { toast('Start the test first.'); return; }
    if (!auto) {
      const unanswered = allNums.filter((n) => !S.answers[n]).length;
      const flagged = S.flags.size;
      const msg = `<p>You have answered <b>${allNums.length - unanswered}</b> of <b>${allNums.length}</b> questions.</p>`
        + (unanswered ? `<p style="color:var(--bad)"><b>${unanswered}</b> question${unanswered > 1 ? 's are' : ' is'} unanswered.</p>` : '')
        + (flagged ? `<p>${flagged} question${flagged > 1 ? 's are' : ' is'} flagged for review.</p>` : '')
        + '<p>Once submitted you cannot change your answers.</p>';
      const ok = await confirmDialog('Submit test?', msg, 'Submit answers');
      if (!ok) return;
    }
    submitBtn.disabled = true;
    const overlay = h('div', { class: 'pl-done' }, h('div', { class: 'loading-block' }, h('span', { class: 'spinner' }), ' Marking your answers…'));
    body.append(overlay);
    try {
      const res = await api.post(`/api/attempts/${S.attemptId}/submit`, {
        answers: S.answers, duration_sec: Math.round(S.elapsed), highlights: S.highlights,
      });
      S.submitted = true;
      cleanupAll();
      store.remove(localKey());
      store.remove(activeKey);
      if (mockId) {
        try { await api.post(`/api/mock/${mockId}/link`, { section: type, ref_id: S.attemptId }); } catch (e) { toast(`Could not link to mock: ${e.message}`, 'error'); }
        toast(`${type === 'listening' ? 'Listening' : 'Reading'} submitted — band ${res?.band ?? '?'}`, 'good');
        navigate(`#/mock/${mockId}`);
      } else {
        navigate(`#/result/${S.attemptId}`);
      }
    } catch (e) {
      overlay.remove();
      submitBtn.disabled = false;
      toast(`Submit failed: ${e.message}`, 'error');
    }
  }
  submitBtn.addEventListener('click', () => submit(false));
  exitBtn.addEventListener('click', () => {
    navigate(mockId ? `#/mock/${mockId}` : `#/${type}`);
  });

  // ------------------------------------------------------------------ keyboard
  const onKey = (e) => {
    if (!S.started) return;
    if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); step(1); }
    else if (e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    else if (e.altKey && (e.key === 'f' || e.key === 'F')) { e.preventDefault(); flagBtn.click(); }
  };
  document.addEventListener('keydown', onKey);
  const onUnload = () => { saveLocal(); autosave(true); };
  window.addEventListener('pagehide', onUnload);

  // leave guard
  nav.guard = async () => {
    if (S.submitted || !S.started) return true;
    const ok = await confirmDialog('Leave the test?', '<p>Your answers are saved — you can resume this attempt later from the library.</p>', 'Leave test');
    if (ok) { saveLocal(); await autosave(); }
    return ok;
  };

  function cleanupAll() {
    clearInterval(tickHandle);
    clearInterval(saveHandle);
    document.removeEventListener('keydown', onKey);
    window.removeEventListener('pagehide', onUnload);
    partEls.forEach((p) => p.hl?.destroy());
    if (audio) { audio.pause(); audio.removeAttribute('src'); try { audio.load(); } catch { /* ignore */ } }
  }

  // ------------------------------------------------------------------ intro + start
  drawTabs();
  showPart(S.partIdx);
  drawTimer();
  drawAudio();
  setCurrent(S.current, false);
  setSave(resuming ? 'Restored' : '');

  async function begin() {
    if (!S.attemptId) {
      const a = await api.post('/api/attempts', { test_id: testId, mode, mock_id: mockId || undefined });
      S.attemptId = a.id;
      store.set(activeKey, a.id);
      const newHash = `#/test/${encodeURIComponent(testId)}/${a.id}${location.hash.includes('?') ? '?' + location.hash.split('?')[1] : ''}`;
      history.replaceState(null, '', newHash);
      nav.lastHash = newHash;
    }
    S.started = true;
    saveLocal();
    startTimer();
    if (audio) {
      if (mode === 'mock') {
        if (!S.audio.finished) { showPart(S.audio.part, true); loadAudioForPart(S.audio.part, true); }
      } else {
        loadAudioForPart(S.partIdx, false);
      }
    }
    drawAudio();
    setTimeout(() => jumpTo(S.current), 50);
  }

  const answeredCount = Object.keys(S.answers).length;
  const intro = h('div', { class: 'pl-intro' });
  const card = h('div', { class: 'card' });
  card.innerHTML = `
    <div class="badge accent" style="margin-bottom:10px">${type === 'listening' ? 'Listening' : 'Academic Reading'} · ${mode === 'mock' ? 'Mock exam' : 'Practice'}</div>
    <h1>${esc(test.title || testId)}</h1>
    <div class="facts">
      <div><b>${allNums.length}</b><span>questions</span></div>
      <div><b>${parts.length}</b><span>${type === 'reading' ? 'passages' : 'parts'}</span></div>
      <div><b>${Math.round(durationSec / 60)}</b><span>minutes</span></div>
    </div>
    <ul>
      ${type === 'listening'
        ? (mode === 'mock'
          ? '<li>The recording plays <b>once only</b> and moves through the parts automatically.</li><li>You cannot pause, rewind or skip.</li>'
          : '<li>Practice mode: play, pause and seek the audio freely, and change playback speed.</li>')
        : '<li>Select text in the passage to <b>highlight</b> it; click a highlight to remove it.</li><li>Drag the divider to resize the passage and question panes.</li>'}
      <li>Use the question palette at the bottom to jump between questions and flag ones to review (<span class="mono">Alt+F</span>).</li>
      <li>Answers are saved automatically every few seconds — you can leave and resume later.</li>
    </ul>
    ${resuming ? `<p class="small muted">Resuming attempt #${S.attemptId}: ${answeredCount} answer${answeredCount === 1 ? '' : 's'} restored, ${fmtClock(Math.max(0, durationSec - S.elapsed))} left.</p>` : ''}`;
  const startBtn = h('button', { class: 'btn primary lg', type: 'button' }, resuming ? 'Resume test' : 'Start test');
  const actions = h('div', { class: 'row', style: { marginTop: '18px' } }, startBtn);
  if (resuming) {
    actions.append(h('button', { class: 'btn', type: 'button', onclick: async () => {
      if (!(await confirmDialog('Start over?', 'This discards the answers of the unfinished attempt.', 'Start over', 'danger'))) return;
      store.remove(localKey());
      store.remove(activeKey);
      S.attemptId = null; S.answers = {}; S.flags = new Set(); S.highlights = {}; S.elapsed = 0; S.audio = { part: 0, pos: {}, finished: false };
      nav.guard = null;
      cleanupAll();
      navigate(`#/test/${encodeURIComponent(testId)}${mode === 'mock' ? `?mode=mock${mockId ? `&mock=${mockId}` : ''}` : ''}`, { replace: true });
    } }, 'Start over'));
  }
  actions.append(h('a', { class: 'btn ghost', href: mockId ? `#/mock/${mockId}` : `#/${type}` }, 'Back'));
  card.append(actions);
  intro.append(card);
  body.append(intro);
  startBtn.addEventListener('click', async () => {
    startBtn.disabled = true;
    try {
      await begin();
      intro.remove();
    } catch (e) {
      startBtn.disabled = false;
      toast(`Could not start: ${e.message}`, 'error');
    }
  });
  setTimeout(() => startBtn.focus(), 30);

  return () => {
    if (!S.submitted) { saveLocal(); autosave(true); }
    cleanupAll();
  };
}
