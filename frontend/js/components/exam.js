// Exam day: countdown, readiness per skill against the target band, and a day-by-day plan to the exam.
// Settings keys: exam_date (YYYY-MM-DD), exam_date_kind (exact | predicted), target_band.
import { api } from '../api.js';
import { h, esc, icon, toast, modal, fmtBand, qtypeLabel, asList } from '../ui.js';
import { state } from '../state.js';

const SKILLS = [['listening', 'Listening'], ['reading', 'Reading'], ['writing', 'Writing'], ['speaking', 'Speaking']];
const BANDS = ['5', '5.5', '6', '6.5', '7', '7.5', '8', '8.5', '9'];

/** Pop-up to set the exam date, whether it is booked or predicted, and the target band. Resolves true if saved. */
export async function editExam() {
  const s = await api.get('/api/settings').catch(() => ({}));
  const body = h('div', { class: 'stack' });
  const dateIn = h('input', { class: 'input', type: 'date', value: s.exam_date || '' });
  const kind = h('div', { class: 'chips', role: 'radiogroup', 'aria-label': 'Exam date type' });
  let kindVal = s.exam_date_kind || 'exact';
  const drawKind = () => kind.replaceChildren(...[['exact', 'Booked (exact date)'], ['predicted', 'Predicted / planned']].map(([k, l]) =>
    h('button', { class: 'chip', type: 'button', role: 'radio', 'aria-checked': String(kindVal === k), 'aria-pressed': String(kindVal === k), onclick: () => { kindVal = k; drawKind(); } }, l)));
  drawKind();
  const target = h('select', { class: 'select' }, ...BANDS.map((b) => h('option', { value: b, selected: String(Number(s.target_band || 7)) === String(Number(b)) }, b)));
  body.append(
    h('label', { class: 'field' }, h('span', { class: 'small muted' }, 'Exam date'), dateIn),
    h('div', { class: 'field' }, h('span', { class: 'small muted' }, 'Is this date booked or predicted?'), kind),
    h('label', { class: 'field' }, h('span', { class: 'small muted' }, 'Target overall band'), target));
  const v = await modal({
    title: 'My IELTS exam', body,
    actions: [{ label: 'Clear date', value: 'clear' }, { label: 'Cancel', value: null }, { label: 'Save', kind: 'primary', value: 'save' }],
  });
  if (!v) return false;
  const payload = v === 'clear' ? { exam_date: '' } : { exam_date: dateIn.value || '', exam_date_kind: kindVal, target_band: target.value };
  try {
    const saved = await api.put('/api/settings', payload);
    Object.assign(state.settings, saved || payload);
    toast(v === 'clear' ? 'Exam date cleared.' : 'Exam saved.', 'good');
    return true;
  } catch (e) { toast(e.message, 'error'); return false; }
}

const fmtDay = (iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, opts);
const addDays = (iso, n) => { const d = new Date(`${iso}T12:00:00`); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };

/**
 * Dashboard card. exam = stats.exam ({date, kind, days_left, target}); est = {skill: band|null};
 * weakTypes = [{type, skill, rate}]; prios = examiner speaking priorities; onChange() re-renders the dashboard.
 */
export function examCard({ exam, est, overall, weakTypes, prios, onChange }) {
  const card = h('section', { class: 'card exam-card', 'aria-label': 'My exam' });
  const edit = h('button', { class: 'btn sm', type: 'button', html: `${icon('clock')} ${exam?.date ? 'Change' : 'Set exam date'}`,
    onclick: async () => { if (await editExam()) onChange?.(); } });
  if (!exam?.date) {
    card.append(h('div', { class: 'exam-empty' },
      h('div', { class: 'exam-icon', html: icon('target') }),
      h('div', { style: { flex: '1' } }, h('h2', { style: { margin: 0 } }, 'When is your exam?'),
        h('p', { class: 'muted small', style: { margin: '4px 0 0' } }, 'Set the date (booked or predicted) to get a countdown, your readiness per skill and a plan for the days left.')),
      edit));
    return card;
  }
  const target = Number(exam.target || 7);
  const left = Number(exam.days_left);
  // ------------------------------------------------ countdown
  const big = left > 1 ? `${left} days` : left === 1 ? '1 day' : left === 0 ? 'Today' : 'Passed';
  const count = h('div', { class: `exam-count${left <= 3 && left >= 0 ? ' soon' : ''}` },
    h('div', { class: 'small muted' }, left >= 0 ? 'Exam in' : 'Exam date'),
    h('div', { class: 'exam-days' }, big),
    h('div', { class: 'exam-date' }, fmtDay(exam.date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })),
    h('div', { class: 'row', style: { gap: '6px', marginTop: '8px', flexWrap: 'wrap' } },
      h('span', { class: `badge ${exam.kind === 'exact' ? 'good' : 'warn'}` }, exam.kind === 'exact' ? 'Booked' : 'Predicted'),
      h('span', { class: 'badge accent' }, `Target ${fmtBand(target)}`)),
    h('div', { style: { marginTop: '12px' } }, edit));

  // ------------------------------------------------ readiness
  const ready = h('div', { class: 'exam-ready' }, h('h3', null, 'Readiness'));
  const lo = 4, hi = 9, pos = (b) => `${((Math.min(hi, Math.max(lo, b)) - lo) / (hi - lo)) * 100}%`;
  for (const [k, label] of [...SKILLS, ['overall', 'Overall']]) {
    const b = k === 'overall' ? overall : est[k];
    const gap = b == null ? null : target - b;
    const tone = b == null ? 'none' : gap <= 0 ? 'high' : gap <= 0.5 ? 'mid' : 'low';
    const row = h('div', { class: `ready-row${k === 'overall' ? ' overall' : ''}` });
    row.innerHTML = `<span class="small">${esc(label)}</span>
      <div class="ready-track" role="img" aria-label="${esc(label)}: ${b == null ? 'no estimate' : fmtBand(b)} of target ${fmtBand(target)}">
        ${b == null ? '' : `<div class="bar-fill ${tone}" style="width:${pos(b)}"></div>`}
        <div class="ready-target" style="left:${pos(target)}" title="Target ${fmtBand(target)}"></div></div>
      <span class="small num">${b == null ? '–' : fmtBand(b)}</span>
      <span class="small ready-gap ${tone}">${gap == null ? 'no data' : gap <= 0 ? '✓ on target' : `+${gap.toFixed(1)} to go`}</span>`;
    ready.append(row);
  }
  ready.append(h('div', { class: 'small muted', style: { marginTop: '6px' } }, 'Estimate = average of your last 3 scores per skill. The line marks your target.'));

  // ------------------------------------------------ plan
  const plan = h('div', { class: 'exam-plan' }, h('h3', null, left > 7 ? 'Focus until the exam' : left >= 0 ? 'Your plan to exam day' : 'Next step'));
  for (const item of buildPlan({ exam, est, target, weakTypes, prios })) {
    plan.append(h('div', { class: `plan-item${item.exam ? ' exam-day' : ''}` },
      h('div', { class: 'plan-when' }, item.when),
      h('div', null, ...item.tasks.map((t) => h('div', { class: 'plan-task' }, h('span', { html: icon(t.icon || 'check') }), h('span', { html: t.html }))))));
  }
  card.append(h('div', { class: 'exam-grid' }, count, ready, plan));
  return card;
}

/** A simple, rule-based plan from the days left, the biggest gaps, weak question types and speaking priorities. */
export function buildPlan({ exam, est, target, weakTypes, prios }) {
  const left = Number(exam.days_left);
  const gaps = SKILLS.map(([k, l]) => ({ k, l, gap: est[k] == null ? 1 : target - est[k] }))
    .sort((a, b) => b.gap - a.gap);
  const weakest = gaps[0];
  const weak = asList(weakTypes).slice(0, 3).map((x) => `${qtypeLabel(x.type)} (${Math.round(x.rate * 100)}%)`);
  const prio = asList(prios)[0];
  const T = {
    lr: { icon: 'mock', html: '<b>Timed Listening + Reading</b> — a mock with Writing and Speaking switched off, then review every mistake' },
    weak: weak.length ? { icon: 'target', html: `<b>Drill your weakest question types:</b> ${esc(weak.join(', '))}` } : null,
    write: { icon: 'writing', html: '<b>Writing:</b> one Task 1 (20 min) + one Task 2 (40 min) under time, then AI feedback — Task 2 counts double' },
    speak: { icon: 'speaking', html: `<b>Speaking:</b> one full test (Parts 1–3)${prio ? ` — work on: ${esc(prio)}` : ''}` },
    light: { icon: 'learn', html: '<b>Light day:</b> vocabulary flashcards, one Part 2 cue card aloud, re-read your common mistakes. Prepare your ID, sleep early' },
  };
  const bySkill = { listening: T.lr, reading: T.lr, writing: T.write, speaking: T.speak };
  if (left < 0) return [{ when: 'Exam passed', tasks: [{ icon: 'target', html: 'Set your next exam date (or a predicted one) to plan again.' }] }];
  if (left === 0) {
    return [{ when: 'Today', exam: true, tasks: [
      { icon: 'clock', html: 'Arrive early with your ID. Eat and drink water before.' },
      { icon: 'listening', html: 'Listening: read the next questions while the recording pauses; spelling and plurals count.' },
      { icon: 'reading', html: 'Reading: about 20 minutes per passage — don’t get stuck on one question.' },
      { icon: 'writing', html: 'Writing: plan Task 2 for 5 minutes; Task 2 is worth twice Task 1.' },
    ] }];
  }
  if (left <= 7) {
    const days = [];
    // the biggest gaps first, then the other skills; the day before the exam is always light
    const order = [...new Set([bySkill[weakest.k], T.lr, T.write, T.speak, bySkill[gaps[1].k]])];
    for (let i = 0; i < left; i++) {
      const day = addDays(new Date().toISOString().slice(0, 10), i);
      const when = i === 0 ? 'Today' : i === 1 ? 'Tomorrow' : fmtDay(day);
      if (i === left - 1 && left > 1) { days.push({ when, tasks: [T.light] }); continue; }
      const main = order[i % order.length];
      const tasks = [main];
      if (main === T.lr && T.weak) tasks.push(T.weak);
      else if (main !== T.speak && left <= 3) tasks.push(T.speak);   // keep speaking warm every day near the exam
      days.push({ when, tasks });
    }
    days.push({ when: fmtDay(exam.date), exam: true, tasks: [{ icon: 'target', html: `<b>Exam day</b> — target ${fmtBand(target)}. Good luck!` }] });
    return days;
  }
  const weeks = Math.ceil(left / 7);
  return [
    { when: `Next ${weeks} week${weeks > 1 ? 's' : ''}`, tasks: [
      { icon: 'target', html: `<b>Main focus:</b> ${esc(weakest.l)}${weakest.gap > 0 ? ` (+${weakest.gap.toFixed(1)} to target)` : ''}, then ${esc(gaps[1].l)}` },
      ...(T.weak ? [T.weak] : []),
      { icon: 'mock', html: '<b>One full mock every week</b>, reviewed the next day' },
      { icon: 'writing', html: '<b>Writing:</b> 2–3 essays a week with AI feedback' },
      { icon: 'speaking', html: `<b>Speaking:</b> 3 short sessions a week${prio ? ` — ${esc(prio)}` : ''}` },
    ] },
    { when: 'Last week', tasks: [{ icon: 'mock', html: 'Two full mocks under exam timing, then light review in the last 2 days' }] },
  ];
}
