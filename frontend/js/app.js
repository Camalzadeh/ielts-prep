// App shell + hash router.
import { icon, esc, h, errorState, loading } from './ui.js';
import { state, loadSettings, setProvider, onStateChange, currentTheme, setTheme } from './state.js';
import { assistButton, installSelectionTranslator, loadAssistSettings, clearAssistContext } from './components/assist.js';

const NAV = [
  { section: 'Overview' },
  { href: '#/', key: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
  { section: 'Practice' },
  { href: '#/listening', key: 'listening', label: 'Listening', icon: 'listening' },
  { href: '#/reading', key: 'reading', label: 'Reading', icon: 'reading' },
  { href: '#/writing', key: 'writing', label: 'Writing', icon: 'writing' },
  { href: '#/speaking', key: 'speaking', label: 'Speaking', icon: 'speaking' },
  { href: '#/mock', key: 'mock', label: 'Mock Exam', icon: 'mock' },
  { section: 'Study' },
  { href: '#/learn', key: 'learn', label: 'Learn', icon: 'learn' },
  { href: '#/history', key: 'history', label: 'History', icon: 'history' },
  { href: '#/settings', key: 'settings', label: 'Settings', icon: 'settings' },
];

// [pattern, module, nav key, title, fullscreen]
const ROUTES = [
  [/^\/?$/, 'dashboard', 'dashboard', 'Dashboard'],
  [/^\/(listening|reading)$/, 'library', null, null],
  [/^\/test\/([^/]+)\/(\d+)$/, 'player', null, 'Test', true],
  [/^\/test\/([^/]+)$/, 'player', null, 'Test', true],
  [/^\/result\/(\d+)$/, 'result', null, 'Results'],
  [/^\/writing$/, 'writing', 'writing', 'Writing'],
  [/^\/writing\/(write)\/(\d+)$/, 'writing', 'writing', 'Writing', true],
  [/^\/writing\/(submission)\/(\d+)$/, 'writing', 'writing', 'Writing submission'],
  [/^\/writing\/(submissions)$/, 'writing', 'writing', 'Writing'],
  [/^\/speaking$/, 'speaking', 'speaking', 'Speaking'],
  [/^\/speaking\/(practice)\/(\w+)$/, 'speaking', 'speaking', 'Speaking practice'],
  [/^\/speaking\/(session)\/(\d+)$/, 'speaking', 'speaking', 'Speaking session'],
  [/^\/speaking\/(bank)$/, 'speaking', 'speaking', 'Question bank'],
  [/^\/speaking\/(sessions)$/, 'speaking', 'speaking', 'Speaking'],
  [/^\/mock$/, 'mock', 'mock', 'Mock Exam'],
  [/^\/mock\/(\d+)$/, 'mock', 'mock', 'Mock Exam'],
  [/^\/mock\/(\d+)\/(writing)$/, 'mock', 'mock', 'Mock Exam — Writing', true],
  [/^\/mock\/(\d+)\/(speaking)$/, 'mock', 'mock', 'Mock Exam — Speaking'],
  [/^\/learn$/, 'learn', 'learn', 'Learn'],
  [/^\/learn\/(kb)\/(.+)$/, 'learn', 'learn', 'Learn'],
  [/^\/learn\/(vocab)$/, 'learn', 'learn', 'Vocabulary'],
  [/^\/history$/, 'history', 'history', 'History'],
  [/^\/settings$/, 'settings', 'settings', 'Settings'],
];

let cleanup = null;
let renderSeq = 0;
/** Pages can set a leave guard: () => boolean|Promise<boolean> (true = allow leaving). */
export const nav = { guard: null, lastHash: location.hash || '#/' };

export function navigate(hash, { replace = false } = {}) {
  if (replace) { history.replaceState(null, '', hash); route(); }
  else if (location.hash === hash) route();
  else location.hash = hash;
}

function renderSidebar(activeKey) {
  const sb = document.getElementById('sidebar');
  if (!sb.dataset.built) {
    sb.innerHTML = `
      <a class="brand" href="#/"><div class="brand-mark">IE</div><div><div class="brand-name">IELTS Prep</div><div class="brand-sub">Local study studio</div></div></a>
      <nav class="nav">${NAV.map((n) => n.section
        ? `<div class="nav-section">${esc(n.section)}</div>`
        : `<a href="${n.href}" data-key="${n.key}" title="${esc(n.label)}">${icon(n.icon)}<span>${esc(n.label)}</span></a>`).join('')}</nav>
      <div class="sidebar-foot">Runs locally · data in <span class="mono">data/ielts.db</span></div>`;
    sb.dataset.built = '1';
  }
  sb.querySelectorAll('.nav a').forEach((a) => {
    const on = a.dataset.key === activeKey;
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
}

export function providerSwitch() {
  const wrap = h('div', { class: 'row', style: { gap: '8px' } });
  const label = h('span', { class: 'provider-label' }, 'AI');
  const sw = h('div', { class: 'provider-switch', role: 'group', 'aria-label': 'AI provider' });
  const draw = () => {
    sw.replaceChildren(...state.providers.map((p) => {
      const avail = p.available === true ? 'on' : p.available === false ? 'off' : '';
      const title = p.available === false ? `${p.name || p.id} — not available on this machine` : `${p.name || p.id}${p.version ? ' ' + p.version : ''}`;
      const short = p.id === 'claude' ? 'Claude' : p.id === 'antigravity' ? 'Antigravity' : (p.name || p.id);
      return h('button', {
        type: 'button', 'aria-pressed': String(state.provider === p.id), title,
        onclick: () => setProvider(p.id),
      }, h('span', { class: `dot ${avail}` }), short);
    }));
  };
  draw();
  onStateChange(draw);
  wrap.append(label, sw);
  return wrap;
}

function renderTopbar(title) {
  const tb = document.getElementById('topbar');
  if (!tb.dataset.built) {
    const themeBtn = h('button', { class: 'icon-btn', id: 'theme-toggle', type: 'button' });
    const drawTheme = () => {
      const dark = currentTheme() === 'dark';
      themeBtn.innerHTML = icon(dark ? 'sun' : 'moon');
      themeBtn.title = dark ? 'Switch to light mode' : 'Switch to dark mode';
      themeBtn.setAttribute('aria-label', themeBtn.title);
    };
    themeBtn.addEventListener('click', () => setTheme(currentTheme() === 'dark' ? 'light' : 'dark'));
    onStateChange(drawTheme);
    drawTheme();
    tb.append(
      h('div', { class: 'crumb', id: 'crumb' }),
      h('div', { class: 'topbar-right' }, assistButton(), providerSwitch(), themeBtn),
    );
    tb.dataset.built = '1';
  }
  document.getElementById('crumb').textContent = title || '';
}

export function setTitle(t) {
  const c = document.getElementById('crumb');
  if (c) c.textContent = t;
  document.title = t ? `${t} · IELTS Prep` : 'IELTS Prep';
}

async function route() {
  const hash = location.hash || '#/';
  const path = decodeURIComponent(hash.replace(/^#/, '').split('?')[0]) || '/';
  const query = Object.fromEntries(new URLSearchParams(hash.split('?')[1] || ''));

  if (nav.guard && hash !== nav.lastHash) {
    const ok = await nav.guard();
    if (!ok) { history.replaceState(null, '', nav.lastHash); return; }
  }
  nav.guard = null;
  nav.lastHash = hash;
  clearAssistContext();

  let match = null, def = null;
  for (const r of ROUTES) {
    const m = path.match(r[0]);
    if (m) { match = m; def = r; break; }
  }
  if (typeof cleanup === 'function') { try { cleanup(); } catch (e) { console.warn(e); } }
  cleanup = null;
  const seq = ++renderSeq;

  const main = document.getElementById('main');
  const fs = document.getElementById('fullscreen-root');
  if (!def) {
    renderSidebar(null); renderTopbar('Not found');
    document.body.classList.remove('player-open'); fs.replaceChildren();
    main.innerHTML = `<div class="empty"><h3>Page not found</h3><p><a href="#/">Back to dashboard</a></p></div>`;
    return;
  }
  const [, mod, navKey, title, fullscreen] = def;
  const params = match.slice(1);
  const key = navKey || params[0];
  renderSidebar(key);
  const t = title || (params[0] ? params[0][0].toUpperCase() + params[0].slice(1) : '');
  renderTopbar(t);
  document.title = `${t} · IELTS Prep`;

  let target;
  if (fullscreen) {
    document.body.classList.add('player-open');
    target = h('div', { class: 'fs-page' });
    fs.replaceChildren(target);
  } else {
    document.body.classList.remove('player-open');
    fs.replaceChildren();
    target = main;
    window.scrollTo(0, 0);
  }
  target.replaceChildren(loading());
  try {
    const m = await import(`./pages/${mod}.js`);
    if (seq !== renderSeq) return;
    const ret = await m.render(target, params, query);
    if (seq !== renderSeq) { if (typeof ret === 'function') ret(); return; }
    cleanup = ret;
    if (!fullscreen) main.focus({ preventScroll: true });
  } catch (e) {
    console.error(e);
    if (seq === renderSeq) target.replaceChildren(errorState(e, () => route()));
  }
}

window.addEventListener('hashchange', route);
window.addEventListener('beforeunload', (e) => {
  if (nav.beforeUnload && nav.beforeUnload()) { e.preventDefault(); e.returnValue = ''; }
});

loadSettings();
loadAssistSettings();
installSelectionTranslator();
route();
