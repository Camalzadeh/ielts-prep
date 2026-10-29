// Global app state: AI provider (persisted via /api/settings), provider availability, theme.
import { api } from './api.js';
import { store, toast } from './ui.js';

const listeners = new Set();

export const state = {
  provider: store.get('provider', 'claude'),
  providers: [
    { id: 'claude', name: 'Claude', available: null },
    { id: 'antigravity', name: 'Antigravity', available: null },
  ],
  settings: {},
};

export function onStateChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
function emit() { listeners.forEach((fn) => { try { fn(state); } catch (e) { console.warn(e); } }); }

export async function loadSettings() {
  try {
    const s = await api.get('/api/settings');
    state.settings = s || {};
    if (s && s.ai_provider) { state.provider = s.ai_provider; store.set('provider', s.ai_provider); }
  } catch (e) { console.warn('settings', e); }
  emit();
  try {
    const p = await api.get('/api/ai/providers');
    const list = Array.isArray(p) ? p : (p?.providers || []);
    if (list.length) state.providers = list;
  } catch (e) { console.warn('providers', e); }
  emit();
}

export async function setProvider(id) {
  if (state.provider === id) return;
  state.provider = id;
  store.set('provider', id);
  emit();
  try {
    await api.put('/api/settings', { ai_provider: id });
    state.settings.ai_provider = id;
  } catch (e) {
    toast(`Could not save provider: ${e.message}`, 'error');
  }
}

export function providerName(id) {
  const p = state.providers.find((x) => x.id === id);
  if (p) return p.name || id;
  return id === 'antigravity' ? 'Antigravity' : id === 'claude' ? 'Claude' : (id || '?');
}

// ---------------------------------------------------------------- theme
export function currentTheme() {
  const t = document.documentElement.getAttribute('data-theme');
  if (t) return t;
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
export function setTheme(t) {
  if (t === 'system') {
    document.documentElement.removeAttribute('data-theme');
    try { localStorage.removeItem('ielts.theme'); } catch { /* ignore */ }
  } else {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('ielts.theme', t); } catch { /* ignore */ }
  }
  emit();
  window.dispatchEvent(new CustomEvent('themechange'));
}
export function themePref() {
  try { return localStorage.getItem('ielts.theme') || 'system'; } catch { return 'system'; }
}
