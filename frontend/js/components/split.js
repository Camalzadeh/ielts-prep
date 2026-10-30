// Resizable two-pane layout. Drag the bar (or focus it and use the arrow keys; double-click resets) to share
// the space. Side by side when there is room, stacked when the layout is narrower than `stackBelow` px.
// The share is remembered per `key` (separately for the side-by-side and the stacked arrangement).
//
// page: true -> the panes are part of the page scroll (no fixed height): the first pane sticks to the top
//              while the second scrolls past it, and the stacked arrangement has no bar.
import { h, store } from '../ui.js';

export function splitPane(first, second, { key, initial = 50, min = 22, max = 78, stackBelow = 760, page = false, label = 'Resize panes' } = {}) {
  const bar = h('div', {
    class: 'divider', role: 'separator', tabindex: '0', 'aria-label': label,
    title: 'Drag to resize · double-click to reset', 'aria-valuemin': String(min), 'aria-valuemax': String(max),
  });
  first.classList.add('split-a');
  second.classList.add('split-b');
  const el = h('div', { class: `split${page ? ' split-page' : ''}` }, first, bar, second);

  let stacked = false;
  const storeKey = () => `split.${key}${stacked ? '.stacked' : ''}`;
  let pct = initial;
  const apply = () => {
    el.style.setProperty('--split', `${pct}%`);
    bar.setAttribute('aria-valuenow', String(Math.round(pct)));
  };
  const set = (v, save = true) => {
    pct = Math.max(min, Math.min(max, v));
    apply();
    if (save && key) store.set(storeKey(), Math.round(pct * 10) / 10);
  };
  const arrange = () => {
    const now = el.clientWidth > 0 && el.clientWidth < stackBelow;
    if (now === stacked && el.dataset.ready) return;
    stacked = now;
    el.dataset.ready = '1';
    el.classList.toggle('stacked', stacked);
    bar.setAttribute('aria-orientation', stacked ? 'horizontal' : 'vertical');
    set(key ? store.get(storeKey(), initial) : initial, false);
  };
  apply();
  new ResizeObserver(arrange).observe(el);

  let drag = null;
  bar.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    drag = { id: e.pointerId };
    bar.classList.add('drag');
    bar.setPointerCapture(e.pointerId);
    document.body.classList.add(stacked ? 'resizing-row' : 'resizing-col');
    e.preventDefault();
  });
  bar.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const r = el.getBoundingClientRect();
    set(stacked ? ((e.clientY - r.top) / r.height) * 100 : ((e.clientX - r.left) / r.width) * 100);
  });
  const end = () => {
    if (!drag) return;
    drag = null;
    bar.classList.remove('drag');
    document.body.classList.remove('resizing-row', 'resizing-col');
  };
  bar.addEventListener('pointerup', end);
  bar.addEventListener('pointercancel', end);
  bar.addEventListener('keydown', (e) => {
    const step = e.shiftKey ? 10 : 3;
    const back = stacked ? 'ArrowUp' : 'ArrowLeft', fwd = stacked ? 'ArrowDown' : 'ArrowRight';
    if (e.key === back) { e.preventDefault(); set(pct - step); }
    else if (e.key === fwd) { e.preventDefault(); set(pct + step); }
    else if (e.key === 'Home') { e.preventDefault(); set(min); }
    else if (e.key === 'End') { e.preventDefault(); set(max); }
  });
  bar.addEventListener('dblclick', () => set(initial));
  return el;
}
