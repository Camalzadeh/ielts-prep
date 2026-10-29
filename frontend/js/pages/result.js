// Results + review page for a submitted listening/reading attempt.
import { api, mediaUrl } from '../api.js';
import { h, esc, icon, fmtBand, fmtDuration, fmtDate, sanitizeContent, qtypeLabel, emptyState, parseMaybeJSON } from '../ui.js';
import { renderGroup, partQuestionNumbers } from '../components/questions.js';
import { analysisPanel } from '../components/analysis.js';
import { mistakesByQuestion, questionNote } from '../components/inline-fix.js';
import { applyHighlights } from '../components/highlight.js';
import { setTitle } from '../app.js';

export function bandRing(band, size = 120, label = 'Band') {
  const r = (size / 2) - 8, c = 2 * Math.PI * r;
  const pct = band ? Math.max(0, Math.min(1, Number(band) / 9)) : 0;
  return `<div class="band-ring" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--surface-3)" stroke-width="9"/>
      ${pct > 0 ? `<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--accent)" stroke-width="9" stroke-linecap="round"
        stroke-dasharray="${c * pct} ${c}"/>` : ''}
    </svg>
    <div class="val"><b>${fmtBand(band)}</b><span>${esc(label)}</span></div></div>`;
}

// Band-only result imported from the learner's own records: there are no answers to review.
function renderImported(root, attempt, testId) {
  const type = attempt.type || 'reading';
  const title = attempt.title || attempt.test_title || testId;
  setTitle(`Results — ${title}`);
  const hero = h('div', { class: 'card result-hero' });
  hero.innerHTML = `${bandRing(attempt.band)}
    <div>
      <p><b>Imported result</b> — taken when the teacher assigned this test (${esc(fmtDate(attempt.finished_at))}).</p>
      <p class="muted">Only the band was recorded, so there are no individual answers to review or explain.
        Retake the test here to get a question-by-question AI analysis.</p>
    </div>`;
  root.replaceChildren(
    h('div', { class: 'page-head' },
      h('div', null,
        h('div', { class: 'small muted' }, h('a', { href: `#/${type}` }, `← ${type === 'listening' ? 'Listening' : 'Reading'} library`)),
        h('h1', null, title),
        h('p', null, `${type === 'listening' ? 'Listening' : 'Reading'} · Imported · ${fmtDate(attempt.finished_at)}`)),
      h('div', { class: 'page-actions' },
        h('a', { class: 'btn primary', href: `#/test/${encodeURIComponent(testId)}`, html: `${icon('refresh')} Retake` }))),
    hero);
}

export async function render(root, params) {
  const id = Number(params[0]);
  const attempt = await api.get(`/api/attempts/${id}`);
  if (attempt.status && attempt.status !== 'submitted') {
    root.replaceChildren(emptyState('This attempt is still in progress', '', 'clock',
      `<a class="btn primary" href="#/test/${encodeURIComponent(attempt.test_id)}/${id}">Resume test</a>`));
    return;
  }
  const testId = attempt.test_id || attempt.test?.id;
  if (attempt.mode === 'imported') return renderImported(root, attempt, testId);
  let test = null, testErr = null;
  try { test = await api.get(`/api/tests/${encodeURIComponent(testId)}/review`); } catch (e) { testErr = e; }
  const type = attempt.type || test?.type || 'reading';
  const title = attempt.title || attempt.test_title || attempt.test?.title || test?.title || testId;
  setTitle(`Results — ${title}`);

  const details = Array.isArray(attempt.details) ? attempt.details : [];
  const byNum = new Map(details.map((d) => [Number(d.number ?? d.question_number), normaliseDetail(d)]));
  const raw = attempt.raw_score ?? details.filter((d) => d.is_correct).length;
  const total = attempt.total ?? (details.length || 40);
  const highlights = parseMaybeJSON(attempt.highlights_json, null) || attempt.highlights || {};

  root.replaceChildren();
  // ------------------------------------------------ header
  const backHref = attempt.mock_id ? `#/mock/${attempt.mock_id}` : `#/${type}`;
  root.append(h('div', { class: 'page-head' },
    h('div', null,
      h('div', { class: 'small muted' }, h('a', { href: backHref }, attempt.mock_id ? '← Mock exam' : `← ${type === 'listening' ? 'Listening' : 'Reading'} library`)),
      h('h1', null, title),
      h('p', null, `${type === 'listening' ? 'Listening' : 'Reading'} · ${attempt.mode === 'mock' ? 'Mock exam' : 'Practice'} · ${fmtDate(attempt.finished_at || attempt.started_at)}`)),
    h('div', { class: 'page-actions' },
      h('a', { class: 'btn', href: '#ai', onclick: (e) => { e.preventDefault(); document.getElementById('ai')?.scrollIntoView({ behavior: 'smooth' }); }, html: `${icon('sparkles')} Explain my mistakes with AI` }),
      h('a', { class: 'btn primary', href: `#/test/${encodeURIComponent(testId)}`, html: `${icon('refresh')} Retake` }))));

  // ------------------------------------------------ summary
  const parts = (test?.parts || []).slice().sort((a, b) => a.number - b.number);
  const partStats = parts.map((p) => {
    const nums = partQuestionNumbers(p);
    return { p, n: nums.length, ok: nums.filter((n) => byNum.get(n)?.is_correct).length };
  });
  if (!partStats.length && details.length) {
    const m = new Map();
    for (const d of details) {
      const k = d.part || 1;
      if (!m.has(k)) m.set(k, { p: { number: k }, n: 0, ok: 0 });
      m.get(k).n++; if (d.is_correct) m.get(k).ok++;
    }
    partStats.push(...[...m.values()].sort((a, b) => a.p.number - b.p.number));
  }
  const pct = total ? Math.round((raw / total) * 100) : 0;
  const hero = h('div', { class: 'card result-hero' });
  hero.innerHTML = `${bandRing(attempt.band)}
    <div>
      <div class="result-facts">
        <div><b>${raw} / ${total}</b><span>Correct answers</span></div>
        <div><b>${pct}%</b><span>Accuracy</span></div>
        <div><b>${fmtDuration(attempt.duration_sec)}</b><span>Time taken</span></div>
        <div><b>${total - raw}</b><span>Mistakes</span></div>
      </div>
      <div class="part-score" style="margin-top:16px">
        ${partStats.map((s) => `<div class="ps"><div class="small muted">${type === 'reading' ? 'Passage' : 'Part'} ${s.p.number}</div><b>${s.ok}/${s.n}</b>
          <div class="bar-track" style="margin-top:6px"><div class="bar-fill ${cls(s.ok / (s.n || 1))}" style="width:${(s.ok / (s.n || 1)) * 100}%"></div></div></div>`).join('')}
      </div>
    </div>`;

  // accuracy by type
  const typeMap = new Map();
  for (const d of byNum.values()) {
    const t = d.type || 'other';
    if (!typeMap.has(t)) typeMap.set(t, { t, ok: 0, n: 0 });
    typeMap.get(t).n++; if (d.is_correct) typeMap.get(t).ok++;
  }
  const types = [...typeMap.values()].sort((a, b) => a.ok / a.n - b.ok / b.n);
  const typeCard = h('div', { class: 'card' },
    h('div', { class: 'card-head' }, h('h3', null, 'Accuracy by question type')),
    h('div', { class: 'card-body' }, ...(types.length ? types.map((x) => {
      const r = x.ok / x.n;
      return frag2(`<div class="qtype-row" style="grid-template-columns:minmax(120px,1.4fr) 1.4fr 48px">
        <span>${esc(qtypeLabel(x.t))}</span>
        <div class="bar-track"><div class="bar-fill ${cls(r)}" style="width:${r * 100}%"></div></div>
        <span class="num small">${x.ok}/${x.n}</span></div>`);
    }) : [h('p', { class: 'muted' }, 'No details.')])));
  root.append(h('div', { class: 'grid', style: { gridTemplateColumns: 'minmax(0,1.5fr) minmax(0,1fr)', marginBottom: '22px' } }, hero, typeCard));

  // ------------------------------------------------ review
  // AI notes go under each wrong question of the review (filled when an analysis is on screen).
  let aiByQ = new Map();
  const paintAi = () => root.querySelectorAll('[data-aiq]').forEach((slot) => {
    const list = aiByQ.get(Number(slot.dataset.aiq));
    slot.replaceChildren(...(list ? [questionNote(list)] : []));
  });
  root.append(h('h2', { style: { marginTop: '8px' } }, 'Answer review'));
  if (!test) {
    root.append(h('div', { class: 'error-box' }, `Could not load the test for review: ${testErr?.message || 'unknown error'}`));
    root.append(detailsTable(details));
  } else {
    root.append(reviewView(test, type, byNum, highlights, paintAi));
  }

  // ------------------------------------------------ AI
  const ai = analysisPanel({
    target_type: 'attempt', target_id: id, title: 'Explain my mistakes with AI',
    subtitle: 'Why each answer was wrong, what the evidence was, and what to practise next.',
    buttonLabel: 'Explain my mistakes',
    onResult: (j) => { aiByQ = mistakesByQuestion(j); paintAi(); },
  });
  ai.id = 'ai';
  ai.style.marginTop = '26px';
  root.append(ai);
}

function normaliseDetail(d) {
  let c = d.correct_answers;
  if (typeof c === 'string') c = parseMaybeJSON(c, [c]);
  return { ...d, correct_answers: Array.isArray(c) ? c : (c ? [c] : []), is_correct: !!Number(d.is_correct) || d.is_correct === true, type: d.type || d.question_type };
}

function cls(r) { return r >= 0.75 ? 'high' : r >= 0.5 ? 'mid' : 'low'; }
function frag2(s) { const t = document.createElement('template'); t.innerHTML = s.trim(); return t.content.firstElementChild; }

function reviewView(test, type, byNum, highlights, afterShow = () => {}) {
  const parts = (test.parts || []).slice().sort((a, b) => a.number - b.number);
  const wrap = h('div');
  const tabs = h('div', { class: 'tabs', role: 'tablist' });
  const content = h('div');
  wrap.append(tabs, content);
  const ctx = {
    mode: 'review',
    getAnswer: (n) => byNum.get(n)?.user_answer ?? '',
    setAnswer: () => {},
    detail: (n) => byNum.get(n),
  };
  let audioEl = null;
  const show = (i) => {
    if (audioEl) audioEl.pause();
    tabs.querySelectorAll('button').forEach((b, k) => b.setAttribute('aria-selected', String(k === i)));
    const part = parts[i];
    const nums = partQuestionNumbers(part);
    const ok = nums.filter((n) => byNum.get(n)?.is_correct).length;
    const qPane = h('div', { class: 'pane questions' });
    qPane.append(h('div', { class: 'part-banner', html: `<b>${type === 'reading' ? 'Passage' : 'Part'} ${part.number}</b> · ${ok}/${nums.length} correct` }));
    for (const g of part.groups || []) qPane.append(renderGroup(g, ctx));
    if (type === 'reading') {
      const pPane = h('div', { class: 'pane passage' });
      if (part.title && !/^passage\s*\d+$/i.test(part.title)) pPane.append(h('div', { class: 'passage-title' }, part.title));
      const pb = h('div', { class: 'passage-body', html: sanitizeContent(part.passage_html || '') });
      pPane.append(pb);
      try { applyHighlights(pb, highlights[part.number] || highlights[String(part.number)] || []); } catch { /* ignore */ }
      content.replaceChildren(h('div', { class: 'review-layout' }, pPane, qPane));
    } else {
      const top = h('div', { class: 'card card-pad', style: { marginBottom: '14px' } });
      const src = part.audio_url || (part.audio ? mediaUrl(part.audio) : (part.audio_remote || ''));
      if (src) {
        audioEl = h('audio', { controls: true, preload: 'none', src, style: { width: '100%' } });
        if (part.audio && part.audio_remote) audioEl.addEventListener('error', () => { if (audioEl.src !== part.audio_remote) audioEl.src = part.audio_remote; }, { once: true });
        top.append(h('div', { class: 'small muted', style: { marginBottom: '6px' } }, `Part ${part.number} recording`), audioEl);
      }
      const tBtn = h('button', { class: 'btn sm', type: 'button', html: `${icon('doc')} Show transcript`, disabled: !part.transcript_html });
      const tBox = h('div', { class: 'transcript hidden', html: sanitizeContent(part.transcript_html || '') });
      tBtn.addEventListener('click', () => {
        tBox.classList.toggle('hidden');
        tBtn.innerHTML = `${icon('doc')} ${tBox.classList.contains('hidden') ? 'Show' : 'Hide'} transcript`;
      });
      top.append(h('div', { class: 'row', style: { marginTop: src ? '10px' : '0' } }, tBtn, part.transcript_html ? null : h('span', { class: 'small muted' }, 'No transcript available')));
      content.replaceChildren(top, tBox, h('div', { class: 'review-layout single' }, qPane));
    }
    afterShow();
  };
  parts.forEach((p, i) => {
    const nums = partQuestionNumbers(p);
    const ok = nums.filter((n) => byNum.get(n)?.is_correct).length;
    tabs.append(h('button', { type: 'button', role: 'tab', onclick: () => show(i) }, `${type === 'reading' ? 'Passage' : 'Part'} ${p.number} · ${ok}/${nums.length}`));
  });
  if (parts.length) show(0);
  else content.append(emptyState('No parts in this test'));
  return wrap;
}

function detailsTable(details) {
  const t = h('div', { class: 'card table-wrap', style: { marginTop: '12px' } });
  t.innerHTML = `<table class="table"><thead><tr><th>#</th><th>Type</th><th>Your answer</th><th>Correct</th><th></th></tr></thead><tbody>
    ${details.map((d) => {
      const n = normaliseDetail(d);
      return `<tr><td>${esc(d.number)}</td><td>${esc(qtypeLabel(n.type))}</td><td>${esc(d.user_answer || '—')}</td><td>${esc(n.correct_answers.join(' / '))}</td>
      <td>${n.is_correct ? '<span class="badge good">Correct</span>' : '<span class="badge bad">Wrong</span>'}</td></tr>`;
    }).join('')}</tbody></table>`;
  return t;
}
