// Renders test question groups (listening/reading) per ARCHITECTURE.md §1, in test or review mode.
import { mediaUrl } from '../api.js';
import { esc, h, sanitizeContent, qtypeLabel, icon } from '../ui.js';

const RADIO_TYPES = new Set(['mcq', 'tfng', 'ynng']);
const TFNG = [{ key: 'TRUE', text: 'TRUE' }, { key: 'FALSE', text: 'FALSE' }, { key: 'NOT GIVEN', text: 'NOT GIVEN' }];
const YNNG = [{ key: 'YES', text: 'YES' }, { key: 'NO', text: 'NO' }, { key: 'NOT GIVEN', text: 'NOT GIVEN' }];

export function groupRange(g) {
  if (Array.isArray(g.range) && g.range.length) return [g.range[0], g.range[g.range.length - 1]];
  const nums = (g.questions || []).map((q) => q.number);
  return nums.length ? [Math.min(...nums), Math.max(...nums)] : [0, 0];
}

export function partQuestionNumbers(part) {
  const out = [];
  for (const g of part.groups || []) for (const q of g.questions || []) out.push(q.number);
  return out.sort((a, b) => a - b);
}

/** Normalise options (accept strings or {key,text}). */
function normOptions(opts) {
  if (!Array.isArray(opts)) return [];
  return opts.map((o, i) => {
    if (o === null || o === undefined) return null;
    if (typeof o === 'string') {
      const m = o.match(/^\s*([A-Z]|[ivxlc]+)[.)\s]\s*(.*)$/i);
      return m ? { key: m[1], text: m[2] } : { key: String.fromCharCode(65 + i), text: o };
    }
    return { key: String(o.key ?? o.letter ?? o.value ?? String.fromCharCode(65 + i)), text: o.text ?? o.label ?? '' };
  }).filter(Boolean);
}

function stripTags(s) {
  const d = document.createElement('div');
  d.innerHTML = s || '';
  return d.textContent.trim();
}

function normalise(s) {
  return String(s ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
}

/**
 * ctx = {
 *   mode: 'test' | 'review',
 *   getAnswer(num) -> string,
 *   setAnswer(num, value),          // test mode
 *   detail(num) -> {user_answer, correct_answers, is_correct, explanation_html} | undefined  (review)
 *   toast(msg)
 * }
 */
export function renderGroup(group, ctx) {
  const [from, to] = groupRange(group);
  const type = group.type || '';
  const groupOpts = normOptions(group.options);
  const questions = (group.questions || []).slice().sort((a, b) => a.number - b.number);
  const sec = h('section', { class: `q-group t-${type}`, dataset: { from, to } });

  sec.append(h('h3', { class: 'q-range' }, from === to ? `Question ${from}` : `Questions ${from}–${to}`));
  if (group.instructions_html) sec.append(h('div', { class: 'q-instr', html: sanitizeContent(group.instructions_html) }));
  if (group.image) {
    sec.append(h('figure', { class: 'q-image' }, h('img', { src: group.image_url || mediaUrl(group.image), alt: `Image for questions ${from}–${to}`, loading: 'lazy' })));
  }

  const content = group.content_html || '';
  const hasGaps = /\{\{\s*\d+\s*\}\}/.test(content);
  const isMulti = type === 'multi_select';
  const isRadio = RADIO_TYPES.has(type);
  // Option box for shared options (matching / headings / word lists) — not for MCQ/multi where options render as choices.
  if (groupOpts.length && !isMulti && !(isRadio && !hasGaps) && groupOpts.some((o) => stripTags(o.text) && stripTags(o.text) !== o.key)) {
    const box = h('div', { class: `opt-box${type === 'matching_headings' ? ' headings' : ''}` });
    const title = type === 'matching_headings' ? 'List of Headings' : (type === 'matching_features' ? 'List' : 'Options');
    box.append(h('div', { class: 'opt-box-title' }, title));
    const dl = h('div', { class: 'opt-list' });
    for (const o of groupOpts) dl.append(h('div', { class: 'opt-row' }, h('b', null, o.key), h('span', { html: sanitizeContent(o.text) })));
    box.append(dl);
    sec.append(box);
  }

  if (hasGaps) {
    sec.append(renderContentWithGaps(content, group, groupOpts, ctx));
    // questions that also have prompts but no gap in content
    const inContent = new Set([...content.matchAll(/\{\{\s*(\d+)\s*\}\}/g)].map((m) => Number(m[1])));
    for (const q of questions) {
      if (!inContent.has(q.number)) sec.append(renderQuestion(q, group, groupOpts, ctx));
    }
  } else if (isMulti) {
    sec.append(renderMultiSelect(group, questions, groupOpts, ctx));
  } else {
    if (content) sec.append(h('div', { class: `q-content${/<(table|img)/i.test(content) ? '' : ' plain'}`, html: sanitizeContent(content) }));
    const list = h('div', { class: 'q-list' });
    for (const q of questions) list.append(renderQuestion(q, group, groupOpts, ctx));
    sec.append(list);
  }

  if (ctx.mode === 'review') sec.append(renderGroupReview(group, questions, ctx));
  return sec;
}

function numBadge(n) {
  return h('span', { class: 'qnum', 'aria-hidden': 'true' }, String(n));
}

function reviewMark(n, ctx) {
  const d = ctx.detail(n);
  if (!d) return null;
  const ok = !!d.is_correct;
  return h('span', { class: `ans-mark ${ok ? 'ok' : 'bad'}`, title: ok ? 'Correct' : 'Incorrect', html: icon(ok ? 'check' : 'x') });
}

function correctText(d) {
  const c = d?.correct_answers;
  if (Array.isArray(c)) return c.join(' / ');
  return c ?? '';
}

function inlineCorrect(n, ctx) {
  const d = ctx.detail(n);
  if (!d || d.is_correct) return null;
  return h('span', { class: 'correct-ans', title: 'Correct answer' }, correctText(d) || '—');
}

function textInput(n, ctx, { inline = false } = {}) {
  const val = ctx.getAnswer(n) || '';
  const wrap = h('span', { class: `gap${inline ? ' inline' : ''}`, id: `q-${n}`, dataset: { q: n } });
  const input = h('input', {
    type: 'text', class: 'gap-input', value: val, autocomplete: 'off', spellcheck: 'false',
    'aria-label': `Question ${n}`, dataset: { q: n }, placeholder: String(n),
  });
  input.value = val;
  if (ctx.mode === 'review') {
    input.disabled = true;
    const d = ctx.detail(n);
    if (d) wrap.classList.add(d.is_correct ? 'is-ok' : 'is-bad');
  } else {
    const size = () => { input.style.width = `${Math.min(28, Math.max(9, input.value.length + 3))}ch`; };
    input.addEventListener('input', () => { size(); ctx.setAnswer(n, input.value); });
    size();
  }
  if (ctx.mode === 'review') {
    input.style.width = `${Math.min(28, Math.max(9, (input.value || '').length + 3))}ch`;
  }
  wrap.append(input);
  if (ctx.mode === 'review') wrap.append(...[reviewMark(n, ctx), inlineCorrect(n, ctx)].filter(Boolean));
  return wrap;
}

function selectInput(n, opts, ctx, { inline = false } = {}) {
  const val = ctx.getAnswer(n) || '';
  const wrap = h('span', { class: `gap sel${inline ? ' inline' : ''}`, id: `q-${n}`, dataset: { q: n } });
  const sel = h('select', { class: 'gap-select', 'aria-label': `Question ${n}`, dataset: { q: n } });
  sel.append(h('option', { value: '' }, inline ? String(n) : 'Select…'));
  for (const o of opts) {
    const txt = stripTags(o.text);
    const label = inline || !txt ? o.key : `${o.key}  ${txt.length > 70 ? txt.slice(0, 68) + '…' : txt}`;
    sel.append(h('option', { value: o.key }, label));
  }
  sel.value = opts.some((o) => o.key === val) ? val : (val ? matchKey(val, opts) : '');
  if (ctx.mode === 'review') {
    sel.disabled = true;
    const d = ctx.detail(n);
    if (d) wrap.classList.add(d.is_correct ? 'is-ok' : 'is-bad');
  } else {
    sel.addEventListener('change', () => ctx.setAnswer(n, sel.value));
  }
  wrap.append(sel);
  if (ctx.mode === 'review') wrap.append(...[reviewMark(n, ctx), inlineCorrect(n, ctx)].filter(Boolean));
  return wrap;
}

function matchKey(val, opts) {
  const v = normalise(val);
  const o = opts.find((x) => normalise(x.key) === v);
  return o ? o.key : '';
}

function renderContentWithGaps(content, group, opts, ctx) {
  const marked = content.replace(/\{\{\s*(\d+)\s*\}\}/g, (_, n) => `<span data-gap-slot="${n}"></span>`);
  const div = h('div', { class: `q-content with-gaps t-${group.type}` });
  div.innerHTML = sanitizeContent(marked);
  // DOMPurify keeps data-* attributes by default.
  div.querySelectorAll('[data-gap-slot]').forEach((slot) => {
    const n = Number(slot.getAttribute('data-gap-slot'));
    const el = opts.length ? selectInput(n, opts, ctx, { inline: true }) : textInput(n, ctx, { inline: true });
    el.prepend(numBadge(n));
    slot.replaceWith(el);
  });
  return div;
}

function choiceList(n, options, ctx, kind = 'radio') {
  const val = ctx.getAnswer(n) || '';
  const d = ctx.mode === 'review' ? ctx.detail(n) : null;
  const correct = new Set((d?.correct_answers || []).map(normalise));
  const ul = h('div', { class: 'choices', role: 'radiogroup', 'aria-label': `Question ${n}` });
  for (const o of options) {
    const id = `q${n}-${o.key.replace(/\s+/g, '_')}`;
    const input = h('input', { type: kind, name: `q${n}`, id, value: o.key, dataset: { q: n } });
    input.checked = normalise(val) === normalise(o.key);
    const label = h('label', { class: 'choice', for: id },
      input,
      h('span', { class: 'choice-key' }, o.key.length <= 3 ? o.key : ''),
      h('span', { class: 'choice-text', html: sanitizeContent(o.text && o.text !== o.key ? o.text : o.key) }));
    if (ctx.mode === 'review') {
      input.disabled = true;
      if (correct.has(normalise(o.key))) label.classList.add('is-correct');
      else if (input.checked) label.classList.add('is-wrong');
    } else {
      input.addEventListener('change', () => { if (input.checked) ctx.setAnswer(n, o.key); });
    }
    ul.append(label);
  }
  return ul;
}

function renderQuestion(q, group, groupOpts, ctx) {
  const n = q.number;
  const type = group.type || '';
  const block = h('div', { class: 'q-item', id: `q-${n}`, dataset: { q: n } });
  const prompt = q.prompt_html || '';
  const qOpts = normOptions(q.options);

  if (RADIO_TYPES.has(type) || (qOpts.length && !groupOpts.length)) {
    let opts = qOpts.length ? qOpts : groupOpts;
    if (!opts.length) opts = type === 'ynng' ? YNNG : TFNG;
    const head = h('div', { class: 'q-prompt' }, numBadge(n), h('div', { class: 'q-text', html: sanitizeContent(prompt) }));
    if (ctx.mode === 'review') head.append(reviewMark(n, ctx) || '');
    block.append(head, choiceList(n, opts, ctx));
    return block;
  }

  if (/\{\{\s*\d+\s*\}\}/.test(prompt)) {
    // Inline gap inside the prompt (sentence completion etc.)
    const div = h('div', { class: 'q-prompt inline-gaps' });
    div.innerHTML = sanitizeContent(prompt.replace(/\{\{\s*(\d+)\s*\}\}/g, (_, x) => `<span data-gap-slot="${x}"></span>`));
    div.querySelectorAll('[data-gap-slot]').forEach((slot) => {
      const k = Number(slot.getAttribute('data-gap-slot'));
      const el = groupOpts.length ? selectInput(k, groupOpts, ctx, { inline: true }) : textInput(k, ctx, { inline: true });
      el.prepend(numBadge(k));
      slot.replaceWith(el);
    });
    block.removeAttribute('id');
    block.append(div);
    return block;
  }

  // prompt followed by a select (matching) or text input
  block.classList.add('q-row');
  const control = groupOpts.length ? selectInput(n, groupOpts, ctx) : textInput(n, ctx);
  control.removeAttribute('id');
  block.append(
    numBadge(n),
    h('div', { class: 'q-text', html: sanitizeContent(prompt) || `<span class="muted">Question ${n}</span>` }),
    control,
  );
  return block;
}

function renderMultiSelect(group, questions, opts, ctx) {
  const nums = questions.map((q) => q.number);
  const limit = nums.length || 2;
  const wrap = h('div', { class: 'q-item multi', id: `q-${nums[0]}`, dataset: { q: nums[0] } });
  // anchors for the other numbers so palette jumps work
  for (const n of nums.slice(1)) wrap.append(h('span', { id: `q-${n}`, class: 'anchor', dataset: { q: n } }));
  const prompts = questions.map((q) => q.prompt_html).filter(Boolean);
  const instrText = stripTags(group.instructions_html).replace(/\s+/g, ' ');
  const uniq = [...new Set(prompts)].filter((p) => stripTags(p).replace(/\s+/g, ' ') !== instrText);
  const head = h('div', { class: 'q-prompt' }, h('span', { class: 'qnum wide' }, `${nums[0]}–${nums[nums.length - 1]}`),
    h('div', { class: 'q-text', html: sanitizeContent(uniq.join('<br>')) || `<span class="muted">Choose <b>${limit}</b> answers.</span>` }));
  wrap.append(head);
  let options = opts;
  if (!options.length) options = normOptions(questions[0]?.options);
  const selected = new Set(nums.map((n) => ctx.getAnswer(n)).filter(Boolean).map(String));
  const correct = new Set();
  if (ctx.mode === 'review') {
    for (const n of nums) for (const c of ctx.detail(n)?.correct_answers || []) correct.add(normalise(c));
  }
  const box = h('div', { class: 'choices' });
  const inputs = [];
  for (const o of options) {
    const id = `q${nums[0]}m-${o.key}`;
    const input = h('input', { type: 'checkbox', id, value: o.key, dataset: { q: nums[0] } });
    input.checked = selected.has(o.key);
    inputs.push(input);
    const label = h('label', { class: 'choice', for: id }, input, h('span', { class: 'choice-key' }, o.key), h('span', { class: 'choice-text', html: sanitizeContent(o.text) }));
    if (ctx.mode === 'review') {
      input.disabled = true;
      if (correct.has(normalise(o.key))) label.classList.add('is-correct');
      else if (input.checked) label.classList.add('is-wrong');
    } else {
      input.addEventListener('change', () => {
        const checked = inputs.filter((i) => i.checked);
        if (checked.length > limit) {
          input.checked = false;
          ctx.toast?.(`Choose no more than ${limit} options.`);
          return;
        }
        const letters = checked.map((i) => i.value).sort();
        nums.forEach((n, i) => ctx.setAnswer(n, letters[i] || ''));
      });
    }
    box.append(label);
  }
  wrap.append(h('div', { class: 'multi-hint muted small' }, `Select ${limit} options`), box);
  return wrap;
}

function renderGroupReview(group, questions, ctx) {
  const box = h('div', { class: 'review-list' });
  for (const q of questions) {
    const d = ctx.detail(q.number) || {};
    const ok = !!d.is_correct;
    const user = d.user_answer ?? ctx.getAnswer(q.number) ?? '';
    const expl = d.explanation_html || q.explanation_html;
    const row = h('div', { class: `rv-row ${ok ? 'ok' : 'bad'}` },
      h('span', { class: 'rv-num' }, String(q.number)),
      h('span', { class: `ans-mark ${ok ? 'ok' : 'bad'}`, html: icon(ok ? 'check' : 'x') }),
      h('span', { class: 'rv-user' }, h('span', { class: 'muted small' }, 'Your answer: '), user ? h('b', null, user) : h('i', { class: 'muted' }, 'no answer')),
      h('span', { class: 'rv-correct' }, h('span', { class: 'muted small' }, 'Correct: '), h('b', null, correctText(d) || (Array.isArray(q.answer) ? q.answer.join(' / ') : q.answer || '—'))),
    );
    box.append(row);
    if (expl) {
      const det = h('details', { class: 'rv-expl' }, h('summary', null, 'Explanation'), h('div', { html: sanitizeContent(expl) }));
      box.append(det);
    }
  }
  return box;
}

export function partTitle(part, type) {
  const label = type === 'reading' ? 'Passage' : 'Part';
  const n = part.number;
  if (!part.title || new RegExp(`^${label}\\s*${n}$`, 'i').test(part.title.trim())) return `${label} ${n}`;
  return `${label} ${n}`;
}

export { qtypeLabel };
