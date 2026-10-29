// Speaking: practice runner (record + live transcript), sessions, question bank.
import { api, uploadUrl } from '../api.js';
import { h, esc, icon, toast, withStates, emptyState, fmtDate, fmtBand, fmtClock, asList, store, debounce, confirmDialog, parseMaybeJSON } from '../ui.js';
import { analysisPanel } from '../components/analysis.js';
import { navigate, nav, setTitle } from '../app.js';

const MODES = {
  part1: { title: 'Part 1', sub: 'Introduction & interview · 4–5 min', session: 'practice_part1', icon: 'speaking' },
  part2: { title: 'Part 2', sub: 'Cue card · 1 min prep + 2 min talk', session: 'practice_part2', icon: 'card' },
  part3: { title: 'Part 3', sub: 'Discussion · 4–5 min', session: 'practice_part3', icon: 'layers' },
  full: { title: 'Full test', sub: 'Parts 1, 2 and 3 · 11–14 min', session: 'full', icon: 'mock' },
};

export async function render(root, params) {
  const [sub, arg] = params;
  if (sub === 'practice') return renderPractice(root, arg);
  if (sub === 'session') return renderSession(root, Number(arg));
  if (sub === 'bank') return renderBank(root);
  return renderHome(root);
}

// ------------------------------------------------------------------ home
function renderHome(root) {
  setTitle('Speaking');
  root.replaceChildren(h('div', { class: 'page-head' },
    h('div', null, h('h1', null, 'Speaking'), h('p', null, 'Practise with real recent questions. Your answers are recorded, transcribed locally and can be analysed by AI.')),
    h('div', { class: 'page-actions' }, h('a', { class: 'btn', href: '#/speaking/bank', html: `${icon('book')} Question bank` }))));
  const modes = h('div', { class: 'grid grid-4', style: { marginBottom: '26px' } });
  for (const [k, m] of Object.entries(MODES)) {
    modes.append(h('a', { class: 'card mode-card', href: `#/speaking/practice/${k}`, style: { textDecoration: 'none' } },
      h('div', { class: 'm-icon', html: icon(m.icon) }), h('b', null, m.title), h('span', null, m.sub)));
  }
  root.append(modes);
  const sup = supportInfo();
  if (sup.length) root.append(h('div', { class: 'card card-pad small', style: { marginBottom: '20px', borderColor: 'var(--warn)' } }, ...sup.map((s) => h('div', null, '⚠ ', s))));
  root.append(h('h2', null, 'Recent sessions'));
  const list = h('div');
  root.append(list);
  withStates(list, () => api.get('/api/speaking/sessions'), (data) => {
    const rows = asList(data, 'sessions');
    if (!rows.length) { list.append(emptyState('No sessions yet', 'Pick a practice mode above to record your first answers.', 'mic')); return; }
    const wrap = h('div', { class: 'card table-wrap' });
    const band = (s) => s.band ?? s.teacher_band;
    wrap.innerHTML = `<table class="table"><thead><tr><th>Date</th><th>Mode</th><th class="num">Answers</th><th>Band</th><th></th></tr></thead><tbody>
      ${rows.map((s) => `<tr><td>${esc(fmtDate(s.created_at))}</td><td>${esc(s.notes || modeLabel(s.mode))}${s.mock_id ? ' <span class="badge">mock</span>' : ''}${s.teacher_band != null ? ' <span class="badge">teacher</span>' : ''}</td>
        <td class="num">${esc(s.teacher_band != null ? '–' : (s.responses ?? ''))}</td><td>${band(s) != null ? `<span class="band-pill">${Number(band(s)).toFixed(1)}</span>` : '<span class="muted small">–</span>'}</td>
        <td><a class="btn sm" href="#/speaking/session/${s.id}">Open</a></td></tr>`).join('')}</tbody></table>`;
    list.append(wrap);
  });
}

export function modeLabel(m) {
  return { practice_part1: 'Part 1', practice_part2: 'Part 2', practice_part3: 'Part 3', full: 'Full test', mock: 'Mock exam' }[m] || m || '–';
}

function supportInfo() {
  const out = [];
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) out.push('Audio recording is not supported in this browser.');
  if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) out.push('Live browser transcript is not available (Edge/Chrome support it). Whisper transcription still runs on the server.');
  return out;
}

// ------------------------------------------------------------------ practice
async function renderPractice(root, mode) {
  if (!MODES[mode]) mode = 'full';
  setTitle(`Speaking — ${MODES[mode].title}`);
  const plan = await api.get('/api/speaking/random-set', { mode });
  return speakingRunner(root, { plan, mode, sessionMode: MODES[mode].session, title: `Speaking practice — ${MODES[mode].title}` });
}

/** Build the ordered list of steps for a plan. */
function stepsFromPlan(plan, mode) {
  const steps = [];
  const p1 = asList(plan?.part1), p3 = asList(plan?.part3);
  const p2 = plan?.part2 || null;
  if (mode === 'part1' || mode === 'full' || mode === 'mock') p1.forEach((q) => steps.push({ part: 1, q }));
  if ((mode === 'part2' || mode === 'full' || mode === 'mock') && p2) steps.push({ part: 2, q: p2 });
  if (mode === 'part3' || mode === 'full' || mode === 'mock') p3.forEach((q) => steps.push({ part: 3, q }));
  return steps;
}

/**
 * Generic runner, also used by the mock exam.
 * opts: { plan, mode, sessionMode, title, mockId, onDone(sessionId) }
 */
export async function speakingRunner(root, opts) {
  const steps = stepsFromPlan(opts.plan, opts.mode);
  root.replaceChildren();
  if (!steps.length) {
    root.append(emptyState('No questions available', 'The speaking question bank is empty. Reimport content from Settings.', 'speaking'));
    return;
  }
  const S = { idx: 0, sessionId: null, uploads: [], recording: false, prepDone: false, autoExaminer: store.get('speakAuto', true) };
  let stream = null, audioCtx = null, analyser = null, rafId = 0, recorder = null, chunks = [], recStart = 0, recog = null;
  let finalText = '', interimText = '';
  let timerId = 0;

  const head = h('div', { class: 'page-head' },
    h('div', null, h('h1', null, opts.title || 'Speaking'), h('p', null, `${steps.length} question${steps.length > 1 ? 's' : ''} · answers are uploaded as you go`)),
    h('div', { class: 'page-actions' }));
  const autoToggle = h('label', { class: 'switch', title: 'Read each question aloud and start recording automatically' },
    h('input', { type: 'checkbox', checked: S.autoExaminer }), 'Examiner mode');
  autoToggle.querySelector('input').addEventListener('change', (e) => { S.autoExaminer = e.target.checked; store.set('speakAuto', S.autoExaminer); });
  head.querySelector('.page-actions').append(autoToggle);
  const progress = h('div', { class: 'row small muted', style: { marginBottom: '12px' } });
  const stage = h('div', { class: 'grid', style: { gridTemplateColumns: 'minmax(0,1.3fr) minmax(0,1fr)', alignItems: 'start' } });
  const left = h('div', { class: 'stack' });
  const right = h('div', { class: 'stack' });
  stage.append(left, right);
  root.append(head, progress, stage);

  const uploadsCard = h('div', { class: 'card card-pad' }, h('h3', null, 'Your answers'), h('div', { class: 'uploads small' }, h('span', { class: 'muted' }, 'Recorded answers appear here.')));
  right.append(uploadsCard);
  const sup = supportInfo();
  if (sup.length) right.append(h('div', { class: 'card card-pad small' }, ...sup.map((s) => h('div', { class: 'muted' }, '⚠ ', s))));

  async function ensureSession() {
    if (S.sessionId) return S.sessionId;
    const res = await api.post('/api/speaking/sessions', { mode: opts.sessionMode, plan: opts.plan, mock_id: opts.mockId || undefined });
    S.sessionId = res.id;
    return S.sessionId;
  }
  async function ensureStream() {
    if (stream) return stream;
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = audioCtx.createMediaStreamSource(stream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    src.connect(analyser);
    return stream;
  }

  function speak(text) {
    return new Promise((resolve) => {
      if (!('speechSynthesis' in window) || !text) { resolve(); return; }
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'en-GB';
      u.rate = 0.95;
      const voices = window.speechSynthesis.getVoices();
      const v = voices.find((x) => /en-GB/i.test(x.lang) && /natural|online/i.test(x.name)) || voices.find((x) => /en-GB/i.test(x.lang)) || voices.find((x) => /^en/i.test(x.lang));
      if (v) u.voice = v;
      u.onend = () => resolve();
      u.onerror = () => resolve();
      window.speechSynthesis.speak(u);
      setTimeout(resolve, 20000);
    });
  }

  function drawProgress() {
    progress.replaceChildren(...steps.map((s, i) => h('span', {
      class: `badge ${i < S.idx ? 'good' : i === S.idx ? 'accent' : ''}`, title: s.q.question,
    }, `P${s.part}·${i + 1}`)));
  }

  function levelBars() {
    const el = h('div', { class: 'level', 'aria-hidden': 'true' }, ...Array.from({ length: 28 }, () => h('i')));
    return el;
  }
  function animateLevel(el) {
    cancelAnimationFrame(rafId);
    if (!analyser) return;
    const data = new Uint8Array(analyser.frequencyBinCount);
    const bars = [...el.children];
    const loop = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const v of data) sum += ((v - 128) / 128) ** 2;
      const rms = Math.sqrt(sum / data.length);
      const lvl = Math.min(1, rms * 4);
      bars.forEach((b, i) => {
        const shape = 0.55 + 0.45 * Math.sin((i / bars.length) * Math.PI);
        b.style.height = `${4 + lvl * 32 * shape * (0.7 + Math.random() * 0.3)}px`;
      });
      rafId = requestAnimationFrame(loop);
    };
    loop();
  }

  function startRecognition(liveEl) {
    finalText = ''; interimText = '';
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { liveEl.innerHTML = '<span class="muted">Live transcript unavailable in this browser.</span>'; return; }
    try {
      recog = new SR();
      recog.lang = 'en-GB';
      recog.continuous = true;
      recog.interimResults = true;
      recog.onresult = (e) => {
        interimText = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const r = e.results[i];
          if (r.isFinal) finalText += r[0].transcript.trim() + ' ';
          else interimText += r[0].transcript;
        }
        liveEl.innerHTML = `${esc(finalText)}<span class="interim">${esc(interimText)}</span>` || '<span class="muted">Listening…</span>';
      };
      recog.onerror = (e) => { if (e.error === 'not-allowed' || e.error === 'service-not-allowed') liveEl.innerHTML = '<span class="muted">Live transcript blocked.</span>'; };
      recog.onend = () => { if (S.recording && recog) { try { recog.start(); } catch { /* ignore */ } } };
      recog.start();
      liveEl.innerHTML = '<span class="muted">Listening…</span>';
    } catch (e) {
      liveEl.innerHTML = '<span class="muted">Live transcript unavailable.</span>';
    }
  }
  function stopRecognition() {
    if (recog) { const r = recog; recog = null; try { r.stop(); } catch { /* ignore */ } }
  }

  function pickMime() {
    const c = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
    return c.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) || '';
  }

  async function startRecording(ui) {
    if (S.recording) return;
    try { await ensureStream(); } catch (e) {
      toast(`Microphone not available: ${e.message}`, 'error');
      return;
    }
    if (audioCtx && audioCtx.state === 'suspended') await audioCtx.resume();
    try { await ensureSession(); } catch (e) { toast(`Could not create session: ${e.message}`, 'error'); return; }
    chunks = [];
    const mime = pickMime();
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    recorder.start(500);
    recStart = performance.now();
    S.recording = true;
    ui.onStart();
    animateLevel(ui.level);
    startRecognition(ui.live);
  }

  function stopRecording(step) {
    return new Promise((resolve) => {
      if (!S.recording || !recorder) { resolve(null); return; }
      S.recording = false;
      cancelAnimationFrame(rafId);
      stopRecognition();
      const dur = (performance.now() - recStart) / 1000;
      recorder.onstop = () => {
        const type = recorder.mimeType || 'audio/webm';
        const blob = new Blob(chunks, { type });
        const transcript = (finalText + ' ' + interimText).trim();
        upload(step, blob, dur, transcript);
        resolve({ blob, dur });
      };
      try { recorder.stop(); } catch { resolve(null); }
    });
  }

  function upload(step, blob, dur, transcript) {
    const entry = { step, status: 'uploading', dur, transcript, url: URL.createObjectURL(blob) };
    S.uploads.push(entry);
    drawUploads();
    const fd = new FormData();
    fd.append('session_id', String(S.sessionId));
    if (step.q.id) fd.append('question_id', String(step.q.id));
    fd.append('part', String(step.part));
    fd.append('question_text', step.q.question || '');
    fd.append('duration_sec', String(Math.round(dur * 10) / 10));
    fd.append('browser_transcript', transcript);
    const ext = /ogg/.test(blob.type) ? 'ogg' : /mp4/.test(blob.type) ? 'm4a' : 'webm';
    fd.append('audio', blob, `answer.${ext}`);
    entry.promise = api.upload('/api/speaking/responses', fd)
      .then((r) => { entry.status = 'saved'; entry.id = r.id; })
      .catch((e) => { entry.status = 'error'; entry.error = e.message; toast(`Upload failed: ${e.message}`, 'error'); })
      .finally(drawUploads);
  }

  function drawUploads() {
    const box = uploadsCard.querySelector('.uploads');
    if (!S.uploads.length) return;
    box.replaceChildren(...S.uploads.map((u, i) => h('div', { style: { padding: '8px 0', borderBottom: '1px solid var(--border)' } },
      h('div', { class: 'row between' }, h('b', null, `${i + 1}. Part ${u.step.part}`),
        h('span', { class: `badge ${u.status === 'saved' ? 'good' : u.status === 'error' ? 'bad' : 'warn'}` }, u.status === 'saved' ? `Saved · ${fmtClock(u.dur)}` : u.status === 'error' ? 'Upload failed' : 'Uploading…')),
      h('div', { class: 'muted', style: { whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, u.step.q.question),
      h('audio', { controls: true, src: u.url, preload: 'none', style: { width: '100%', height: '32px', marginTop: '4px' } }))));
  }

  function cueCard(step) {
    const q = step.q;
    const card = h('div', { class: 'cue-card' });
    const cues = asList(q.cue_points);
    card.innerHTML = `<div class="row between"><span class="cue-part">Part ${step.part}${q.topic ? ` · ${esc(q.topic)}` : ''}</span>
        <span class="cue-topic">${q.season ? esc(q.season) : ''}</span></div>
      <div class="cue-q">${esc(q.question)}</div>
      ${cues.length ? `<div class="small muted" style="margin-bottom:4px">You should say:</div><ul>${cues.map((c) => `<li>${esc(c)}</li>`).join('')}</ul>` : ''}
      ${step.part === 2 && cues.length ? '<div class="small muted" style="margin-top:8px">and explain why.</div>' : ''}`;
    const readBtn = h('button', { class: 'btn sm ghost', type: 'button', html: `${icon('speaker')} Read aloud`, style: { position: 'absolute', right: '14px', bottom: '12px' }, onclick: () => speak(q.question) });
    if ('speechSynthesis' in window) card.append(readBtn);
    return card;
  }

  async function showStep() {
    clearInterval(timerId);
    drawProgress();
    const step = steps[S.idx];
    left.replaceChildren(cueCard(step));
    if (step.part === 2 && !step.prepDone) return showPrep(step);
    showRecorder(step);
  }

  function showPrep(step) {
    const notesKey = `speakNotes.${step.q.id}`;
    const notes = h('textarea', { class: 'textarea notes-box', placeholder: 'Make notes here (keywords, ideas)…', 'aria-label': 'Preparation notes' });
    notes.value = store.get(notesKey, '');
    notes.addEventListener('input', () => store.set(notesKey, notes.value));
    let rem = 60;
    const t = h('div', { class: 'big-timer' }, fmtClock(rem));
    const skip = h('button', { class: 'btn primary', type: 'button', html: `${icon('mic')} Start speaking now` });
    const box = h('div', { class: 'card card-pad' },
      h('div', { class: 'row between' }, h('div', null, h('b', null, 'Preparation time'), h('div', { class: 'small muted' }, 'You have one minute to think and make notes.')), t),
      notes, h('div', { class: 'row', style: { marginTop: '12px' } }, skip));
    left.append(box);
    if (S.autoExaminer) speak(`Here is your topic. ${step.q.question}. You have one minute to prepare.`);
    const done = () => {
      clearInterval(timerId);
      step.prepDone = true;
      step.notes = notes.value;
      showRecorder(step, true);
    };
    timerId = setInterval(() => {
      rem--;
      t.textContent = fmtClock(rem);
      if (rem <= 10) t.style.color = 'var(--bad)';
      if (rem <= 0) done();
    }, 1000);
    skip.addEventListener('click', done);
    notes.focus();
  }

  function showRecorder(step, forceAuto = false) {
    left.replaceChildren(cueCard(step));
    if (step.part === 2 && step.notes) left.append(h('div', { class: 'card card-pad small' }, h('b', null, 'Your notes'), h('div', { style: { whiteSpace: 'pre-wrap', marginTop: '4px' } }, step.notes)));
    const maxSec = step.part === 2 ? 120 : step.part === 1 ? 60 : 90;
    const level = levelBars();
    const time = h('div', { class: 'big-timer' }, '00:00');
    const hint = h('div', { class: 'small muted' }, step.part === 2 ? 'Speak for 1–2 minutes. Recording stops automatically at 2:00.' : step.part === 1 ? 'Aim for 2–4 sentences (15–30 seconds).' : 'Aim for a developed answer (30–60 seconds).');
    const recBtn = h('button', { class: 'rec-btn', type: 'button', 'aria-label': 'Start recording', html: icon('mic') });
    const live = h('div', { class: 'live-transcript', 'aria-live': 'polite' }, h('span', { class: 'muted' }, 'Your live transcript will appear here.'));
    const nextBtn = h('button', { class: 'btn', type: 'button', html: S.idx < steps.length - 1 ? `Next question ${icon('chevronRight')}` : `${icon('check')} Finish` });
    const redo = h('button', { class: 'btn ghost', type: 'button', disabled: true, html: `${icon('refresh')} Re-record` });
    const card = h('div', { class: 'card recorder' }, h('div', { class: 'row', style: { gap: '18px' } }, recBtn, h('div', null, time, hint)), level, live, h('div', { class: 'row' }, redo, nextBtn));
    left.append(card);
    let elapsedT = 0;
    let recorded = false;
    const ui = {
      level, live,
      onStart() {
        recBtn.classList.add('recording');
        recBtn.innerHTML = icon('stop');
        recBtn.setAttribute('aria-label', 'Stop recording');
        elapsedT = 0;
        clearInterval(timerId);
        timerId = setInterval(() => {
          elapsedT = (performance.now() - recStart) / 1000;
          time.textContent = fmtClock(elapsedT);
          if (elapsedT > maxSec - 10) time.style.color = 'var(--bad)';
          if (step.part === 2 && elapsedT >= maxSec) { toast('Thank you — time is up.'); stop(); }
        }, 250);
      },
    };
    async function stop() {
      clearInterval(timerId);
      recBtn.disabled = true;
      await stopRecording(step);
      recorded = true;
      recBtn.disabled = false;
      recBtn.classList.remove('recording');
      recBtn.innerHTML = icon('mic');
      recBtn.setAttribute('aria-label', 'Record again');
      redo.disabled = false;
      nextBtn.classList.add('primary');
      nextBtn.focus();
    }
    recBtn.addEventListener('click', () => { if (S.recording) stop(); else startRecording(ui); });
    redo.addEventListener('click', () => { if (!S.recording) { time.style.color = ''; startRecording(ui); } });
    nextBtn.addEventListener('click', async () => {
      if (S.recording) await stop();
      if (!recorded && !(await confirmDialog('Skip this question?', 'You have not recorded an answer for this question.', 'Skip'))) return;
      if (S.idx < steps.length - 1) { S.idx++; showStep(); } else finish();
    });
    if (S.autoExaminer || forceAuto) {
      (async () => {
        if (step.part !== 2) await speak(step.q.question);
        else if (forceAuto && S.autoExaminer) await speak('Now please start speaking.');
        if (left.contains(card) && !S.recording && S.autoExaminer) startRecording(ui);
      })();
    }
  }

  async function finish() {
    left.replaceChildren(h('div', { class: 'card card-pad' }, h('div', { class: 'loading-block' }, h('span', { class: 'spinner' }), ' Saving your answers…')));
    await Promise.all(S.uploads.map((u) => u.promise).filter(Boolean));
    cleanup();
    if (!S.sessionId) { toast('No answers were recorded.'); navigate(opts.mockId ? `#/mock/${opts.mockId}` : '#/speaking'); return; }
    try { await api.post(`/api/speaking/sessions/${S.sessionId}/finish`); } catch (e) { console.warn(e); }
    nav.guard = null;
    if (opts.onDone) await opts.onDone(S.sessionId);
    else navigate(`#/speaking/session/${S.sessionId}`);
  }

  function cleanup() {
    clearInterval(timerId);
    cancelAnimationFrame(rafId);
    stopRecognition();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    try { if (recorder && recorder.state !== 'inactive') recorder.stop(); } catch { /* ignore */ }
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    if (audioCtx) audioCtx.close().catch(() => {});
    audioCtx = null;
  }

  // intro
  const intro = h('div', { class: 'card card-pad' });
  intro.innerHTML = `<h2>Ready?</h2>
    <ul class="muted" style="padding-left:1.2em">
      <li>Each question is shown on a card${'speechSynthesis' in window ? ' and can be read aloud' : ''}.</li>
      <li>Press the red button to record; press again to stop. ${steps.some((s) => s.part === 2) ? 'Part 2 gives you 1 minute to prepare and up to 2 minutes to speak.' : ''}</li>
      <li>Recordings are uploaded and transcribed with Whisper on your computer; a live browser transcript is captured too.</li>
    </ul>`;
  const go = h('button', { class: 'btn primary lg', type: 'button', html: `${icon('mic')} Start` });
  intro.append(go);
  left.append(intro);
  go.addEventListener('click', async () => {
    go.disabled = true;
    try { await ensureStream(); } catch (e) { toast(`Microphone permission is needed: ${e.message}`, 'error'); go.disabled = false; return; }
    try { await ensureSession(); } catch (e) { toast(`Could not create session: ${e.message}`, 'error'); go.disabled = false; return; }
    showStep();
  });
  drawProgress();
  nav.guard = async () => {
    if (!S.sessionId || !S.uploads.length) return true;
    const ok = await confirmDialog('Leave speaking practice?', 'Answers recorded so far are saved in this session.', 'Leave');
    return ok;
  };
  return cleanup;
}

// ------------------------------------------------------------------ session
async function renderSession(root, id) {
  setTitle(`Speaking session #${id}`);
  let pollT = 0;
  const load = async () => {
    const s = await api.get(`/api/speaking/sessions/${id}`);
    draw(s);
    const pending = asList(s.responses).some((r) => r.transcribe_status === 'pending' || r.transcribe_status === 'running');
    clearTimeout(pollT);
    if (pending && root.isConnected) pollT = setTimeout(() => load().catch(() => {}), 4000);
  };
  let respBox = null;
  function draw(s) {
    const responses = asList(s.responses);
    if (!respBox) {
      root.replaceChildren(h('div', { class: 'page-head' },
        h('div', null,
          h('div', { class: 'small' }, h('a', { href: s.mock_id ? `#/mock/${s.mock_id}` : '#/speaking' }, s.mock_id ? '← Mock exam' : '← Speaking')),
          h('h1', null, `Speaking session · ${modeLabel(s.mode)}`),
          h('p', null, `${fmtDate(s.created_at)} · ${responses.length} answer${responses.length === 1 ? '' : 's'}`)),
        h('div', { class: 'page-actions' }, h('a', { class: 'btn', href: '#/speaking', html: `${icon('mic')} New practice` }))));
      respBox = h('div', { class: 'stack', style: { marginBottom: '22px' } });
      root.append(respBox);
      root.append(analysisPanel({
        target_type: 'speaking_session', target_id: id, title: 'Analyse with AI',
        subtitle: 'Band estimate for Fluency & Coherence, Lexical Resource, Grammar and Pronunciation (from transcript + metrics).',
      }));
    }
    if (!responses.length && s.teacher_band != null) {
      respBox.replaceChildren(h('div', { class: 'card', html: `<p><b>Teacher-assessed band ${esc(fmtBand(s.teacher_band))}</b> — ${esc(s.notes || '')}</p>
        <p class="muted">Imported from your records (no recordings). Practise these questions again here to get recordings, transcripts and AI feedback.</p>` }));
      return;
    }
    if (!responses.length) { respBox.replaceChildren(emptyState('No answers recorded in this session')); return; }
    const open = new Set([...respBox.querySelectorAll('details[open]')].map((d) => d.dataset.id));
    respBox.replaceChildren(...responses.map((r, i) => responseCard(r, i, open)));
  }
  function responseCard(r, i, open) {
    const m = parseMaybeJSON(r.metrics, null) || {};
    const st = r.transcribe_status;
    const card = h('div', { class: 'card response-item' });
    const whisperDone = st === 'done';
    card.innerHTML = `<div class="row between"><div><span class="badge accent">Part ${esc(r.part)}</span> <b style="margin-left:6px">${i + 1}. ${esc(r.question_text || '')}</b></div>
      <span class="badge ${st === 'done' ? 'good' : st === 'error' ? 'bad' : st === 'unavailable' ? '' : 'warn'}">${st === 'done' ? 'Whisper transcript' : st === 'error' ? 'Transcription failed' : st === 'unavailable' ? 'Browser transcript' : 'Transcribing…'}</span></div>`;
    if (r.audio_url || r.audio_path) card.append(h('audio', { controls: true, preload: 'none', src: r.audio_url || uploadUrl(r.audio_path) }));
    const metrics = h('div', { class: 'metrics' });
    const add = (label, v) => { if (v !== null && v !== undefined && v !== '') metrics.append(h('span', { class: 'metric' }, `${label} `, h('b', null, String(v)))); };
    add('Duration', r.duration_sec ? fmtClock(r.duration_sec) : null);
    add('WPM', m.wpm != null ? Math.round(m.wpm) : null);
    add('Pauses', m.pause_count);
    add('Long pauses', m.long_pauses);
    add('Fillers', m.filler_count);
    if (m.fillers && typeof m.fillers === 'object') {
      const top = Object.entries(m.fillers).filter(([, n]) => n).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([w, n]) => `${w}×${n}`).join(', ');
      add('', top || null);
    }
    if (metrics.childNodes.length) card.append(metrics);
    const transcript = r.transcript || r.browser_transcript || '';
    const low = new Set(asList(m.low_confidence_words).map((w) => String(typeof w === 'object' ? w.word : w).toLowerCase().replace(/[^a-z']/g, '')));
    const tDiv = h('div', { style: { marginTop: '10px', lineHeight: '1.65' } });
    if (transcript) {
      tDiv.innerHTML = esc(transcript).split(/(\s+)/).map((w) => low.has(w.toLowerCase().replace(/[^a-z']/g, '')) && w.trim() ? `<span class="lowconf" title="Low confidence — check pronunciation">${w}</span>` : w).join('');
    } else tDiv.innerHTML = `<span class="muted">${st === 'pending' ? 'Transcript is being generated…' : 'No transcript.'}</span>`;
    card.append(tDiv);
    const extra = h('div', { class: 'row', style: { marginTop: '8px' } });
    if (whisperDone && r.browser_transcript && r.browser_transcript !== r.transcript) {
      const d = h('details', { dataset: { id: `b${r.id}` } }, h('summary', { class: 'small', style: { cursor: 'pointer', color: 'var(--accent)' } }, 'Browser transcript'), h('div', { class: 'small muted' }, r.browser_transcript));
      if (open.has(`b${r.id}`)) d.open = true;
      extra.append(d);
    }
    if (low.size) extra.append(h('span', { class: 'small muted' }, `${low.size} low-confidence word${low.size > 1 ? 's' : ''} highlighted`));
    if (r.audio_url || r.audio_path) {
      extra.append(h('span', { class: 'spacer' }), h('button', { class: 'btn sm ghost', type: 'button', html: `${icon('refresh')} Re-transcribe`, onclick: async () => {
        try { await api.post(`/api/speaking/responses/${r.id}/retranscribe`); toast('Re-transcribing…'); load(); } catch (e) { toast(e.message, 'error'); }
      } }));
    }
    if (r.transcribe_error) extra.append(h('div', { class: 'small', style: { color: 'var(--bad)', width: '100%' } }, r.transcribe_error));
    card.append(extra);
    return card;
  }
  await load();
  return () => clearTimeout(pollT);
}

// ------------------------------------------------------------------ bank
async function renderBank(root) {
  setTitle('Speaking question bank');
  const f = store.get('speakBank', { part: 1, topic: '', q: '' });
  root.replaceChildren(h('div', { class: 'page-head' },
    h('div', null, h('div', { class: 'small' }, h('a', { href: '#/speaking' }, '← Speaking')), h('h1', null, 'Question bank'), h('p', null, 'Recent exam questions by part and topic, with model answers where available.'))));
  const tabs = h('div', { class: 'tabs', role: 'tablist' });
  const toolbar = h('div', { class: 'toolbar' });
  const list = h('div');
  root.append(tabs, toolbar, list);
  const search = h('div', { class: 'search' }, h('span', { html: icon('search') }), h('input', { class: 'input', type: 'search', placeholder: 'Search questions…', value: f.q, 'aria-label': 'Search questions' }));
  const topicSel = h('select', { class: 'select', 'aria-label': 'Topic' });
  toolbar.append(search, topicSel);
  const drawTabs = () => tabs.replaceChildren(...[1, 2, 3].map((p) => h('button', { type: 'button', role: 'tab', 'aria-selected': String(f.part === p), onclick: () => { f.part = p; f.topic = ''; drawTabs(); loadTopics(); load(); } }, `Part ${p}`)));
  drawTabs();
  async function loadTopics() {
    topicSel.replaceChildren(h('option', { value: '' }, 'All topics'));
    try {
      const t = asList(await api.get('/api/speaking/topics', { part: f.part }));
      topicSel.append(...t.map((x) => h('option', { value: x.topic, selected: x.topic === f.topic }, `${x.topic} (${x.questions})`)));
    } catch { /* ignore */ }
  }
  const load = () => {
    store.set('speakBank', f);
    withStates(list, () => api.get('/api/speaking/questions', { part: f.part, topic: f.topic, q: f.q }), (data) => {
      const qs = asList(data, 'questions');
      if (!qs.length) { list.append(emptyState('No questions found', 'Try another topic or search.', 'speaking')); return; }
      const byTopic = new Map();
      for (const q of qs) { const k = q.topic || 'Other'; if (!byTopic.has(k)) byTopic.set(k, []); byTopic.get(k).push(q); }
      list.append(h('div', { class: 'small muted', style: { marginBottom: '10px' } }, `${qs.length} questions in ${byTopic.size} topics`));
      for (const [topic, items] of byTopic) {
        const card = h('div', { class: 'card card-pad', style: { marginBottom: '12px' } });
        card.append(h('div', { class: 'row between' }, h('h3', { style: { margin: 0 } }, topic), items[0].season ? h('span', { class: 'badge' }, items[0].season) : null));
        for (const q of items) {
          const row = h('div', { style: { padding: '8px 0', borderBottom: '1px solid var(--border)' } });
          row.append(h('div', { class: 'row between' }, h('div', null, q.question), h('div', { class: 'row' },
            q.answered ? h('span', { class: 'badge good' }, `answered ${q.answered}×`) : null,
            'speechSynthesis' in window ? h('button', { class: 'btn sm ghost', type: 'button', title: 'Read aloud', 'aria-label': 'Read aloud', html: icon('speaker'), onclick: () => { const u = new SpeechSynthesisUtterance(q.question); u.lang = 'en-GB'; speechSynthesis.cancel(); speechSynthesis.speak(u); } }) : null)));
          const cues = asList(q.cue_points);
          if (cues.length) row.append(h('ul', { class: 'small muted', style: { margin: '4px 0 0', paddingLeft: '1.2em' } }, ...cues.map((c) => h('li', null, c))));
          if (q.model_answer) row.append(h('details', { style: { marginTop: '6px' } }, h('summary', { class: 'small', style: { cursor: 'pointer', color: 'var(--accent)' } }, 'Model answer'), h('div', { style: { whiteSpace: 'pre-wrap', marginTop: '4px', background: 'var(--surface-2)', padding: '10px 12px', borderRadius: '8px' } }, q.model_answer)));
          card.append(row);
        }
        list.append(card);
      }
    });
  };
  search.querySelector('input').addEventListener('input', debounce((e) => { f.q = e.target.value; load(); }, 250));
  topicSel.addEventListener('change', () => { f.topic = topicSel.value; load(); });
  loadTopics();
  load();
}
