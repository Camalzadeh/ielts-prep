// Listening review for one part, laid out like Engnovate: the recording on top, the transcript on the left with
// every question's evidence marked (green = you got it, red = you missed it), and the answer sheet on the right:
// your answer vs the correct one, "Locate" (jumps to the evidence), the explanation and the AI note.
import { mediaUrl } from '../api.js';
import { h, icon, sanitizeContent, store } from '../ui.js';
import { partQuestionNumbers } from './questions.js';
import { markExcerpt, flash } from './transcript.js';
import { splitPane } from './split.js';

/**
 * `questionPaper()` renders the part's questions in review mode (the "Question paper" view);
 * `onDraw()` runs after the right pane changes (the page fills the AI notes into `[data-aiq]` slots).
 */
export function listeningPartReview(part, byNum, { questionPaper, onDraw = () => {} }) {
  const nums = partQuestionNumbers(part);
  const wrap = h('div', { class: 'lr' });

  // ---- recording
  const src = part.audio_url || (part.audio ? mediaUrl(part.audio) : (part.audio_remote || ''));
  const audio = src ? h('audio', { controls: true, preload: 'metadata', src }) : null;
  if (audio && part.audio && part.audio_remote) {
    audio.addEventListener('error', () => { if (audio.src !== part.audio_remote) audio.src = part.audio_remote; }, { once: true });
  }
  wrap.append(h('div', { class: 'lr-audio' },
    h('span', { class: 'lr-audio-label', html: `${icon('listening')} Part ${part.number} recording` }),
    audio || h('span', { class: 'small muted' }, 'No recording for this part')));

  // ---- transcript with the evidence marked
  const text = h('div', { class: 'lr-text', html: sanitizeContent(part.transcript_html || '<p class="muted">No transcript for this part.</p>') });
  const marks = new Map();
  for (const n of nums) {
    const d = byNum.get(n);
    if (!d?.excerpt) continue;
    const tone = d.is_correct ? 'ok' : 'bad';
    const found = markExcerpt(text, d.excerpt, () => h('mark', { class: `ev ${tone}`, dataset: { q: n } }));
    if (!found.length) continue;
    found[0].before(h('span', { class: `ev-num ${tone}`, dataset: { q: n }, title: `Question ${n}` }, String(n)));
    marks.set(n, found);
  }
  const tPane = h('div', { class: 'pane passage lr-tpane' },
    h('div', { class: 'transcript-title' }, `Part ${part.number} transcript`), text);

  // ---- answer sheet
  const rows = new Map();
  const select = (n, from) => {
    wrap.querySelectorAll('.ev.active, .lr-row.active').forEach((e) => e.classList.remove('active'));
    (marks.get(n) || []).forEach((m) => m.classList.add('active'));
    rows.get(n)?.classList.add('active');
    if (from !== 'transcript') flash(marks.get(n)?.[0]);
    if (from !== 'sheet') flash(rows.get(n));
  };
  const sheet = h('div', { class: 'lr-sheet' }, ...nums.map((n) => {
    const d = byNum.get(n) || {};
    const ok = !!d.is_correct;
    const correct = (d.correct_answers || []).join(' / ');
    const row = h('div', { class: `lr-row ${ok ? 'ok' : 'bad'}`, id: `lr-${n}` },
      h('div', { class: 'lr-head' },
        h('span', { class: 'qnum' }, String(n)),
        h('span', { class: `ans-mark ${ok ? 'ok' : 'bad'}`, html: icon(ok ? 'check' : 'x') }),
        h('div', { class: 'lr-ans' },
          ok ? h('b', { class: 'lr-good' }, d.user_answer || correct)
            : [h('span', { class: 'lr-yours' }, d.user_answer || 'no answer'), h('span', { class: 'lr-arrow' }, '→'), h('b', { class: 'lr-good' }, correct)]),
        h('button', { class: 'btn sm ghost', type: 'button', disabled: !marks.has(n), title: marks.has(n) ? 'Show the evidence in the transcript' : 'Not found in the transcript',
          html: `${icon('target')} Locate`, onclick: () => select(n, 'sheet') })),
      d.question_text ? h('div', { class: 'lr-q' }, d.question_text) : '',
      d.explanation_html ? h('details', { class: 'lr-expl' }, h('summary', null, 'Explanation'),
        h('div', { html: sanitizeContent(d.explanation_html) })) : '',
      h('div', { class: 'ai-slot', dataset: { aiq: n } }));
    rows.set(n, row);
    return row;
  }));
  text.addEventListener('click', (e) => {
    const m = e.target.closest('[data-q]');
    if (m) select(Number(m.dataset.q), 'transcript');
  });

  // ---- right pane: Answers / Question paper, All / Mistakes only (remembered)
  const pref = store.get('review.listening', { view: 'answers', filter: 'all' });
  const right = h('div', { class: 'pane questions lr-right' });
  const bar = h('div', { class: 'lr-bar' });
  const body = h('div');
  let paper = null;
  const seg = (label, opts, key) => h('div', { class: 'view-toggle', role: 'group', 'aria-label': label }, ...opts.map(([v, l]) =>
    h('button', { type: 'button', 'aria-pressed': String(pref[key] === v), onclick: () => { pref[key] = v; store.set('review.listening', pref); draw(); } }, l)));
  const wrong = nums.filter((n) => !byNum.get(n)?.is_correct).length;
  function draw() {
    bar.replaceChildren(
      seg('Review view', [['answers', 'Answer sheet'], ['paper', 'Question paper']], 'view'),
      pref.view === 'answers' ? seg('Show', [['all', `All ${nums.length}`], ['wrong', `Mistakes ${wrong}`]], 'filter') : '');
    if (pref.view === 'paper') {
      paper = paper || questionPaper();
      body.replaceChildren(paper);
    } else {
      sheet.classList.toggle('only-wrong', pref.filter === 'wrong');
      body.replaceChildren(sheet, pref.filter === 'wrong' && !wrong ? h('p', { class: 'muted' }, 'No mistakes in this part.') : '');
    }
    onDraw();
  }
  draw();
  right.append(bar, body);

  wrap.append(h('div', { class: 'review-layout' }, splitPane(tPane, right, { key: 'transcript', initial: 50, label: 'Resize transcript and answers' })));
  return { el: wrap, stop: () => audio?.pause() };
}
