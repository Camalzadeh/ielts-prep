// Settings: AI provider + availability, CLI overrides, content reimport, theme.
import { api } from '../api.js';
import { h, esc, icon, toast, asList } from '../ui.js';
import { state, setProvider, onStateChange, setTheme, themePref } from '../state.js';
import { setTitle } from '../app.js';

export async function render(root) {
  setTitle('Settings');
  root.replaceChildren(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Settings'), h('p', null, 'AI tutor, content and appearance.'))));
  const col = h('div', { class: 'stack', style: { maxWidth: '900px' } });
  root.append(col);

  // ------------------------------------------------ profile
  const nameInput = h('input', { class: 'input', type: 'text', id: 'user_name', placeholder: 'e.g. Aysel' });
  api.get('/api/settings').then((s) => { nameInput.value = s.user_name || ''; }).catch(() => {});
  col.append(h('section', { class: 'card card-pad' },
    h('h2', { style: { margin: 0 } }, 'Your name'),
    h('p', { class: 'small muted' }, 'Shown on the dashboard. If you imported a course chat archive, it also marks which results in it are yours (comma-separate several spellings).'),
    h('div', { class: 'row', style: { gap: '10px', marginTop: '8px' } }, nameInput,
      h('button', { class: 'btn sm', type: 'button', onclick: async () => {
        try { await api.put('/api/settings', { user_name: nameInput.value.trim() }); toast('Name saved.', 'good'); }
        catch (e) { toast(e.message, 'error'); }
      } }, 'Save'))));

  // ------------------------------------------------ AI provider
  const aiCard = h('section', { class: 'card card-pad' });
  col.append(aiCard);
  let providers = state.providers;
  const drawAi = () => {
    aiCard.replaceChildren(
      h('div', { class: 'row between' }, h('div', null, h('h2', { style: { margin: 0 } }, 'AI provider'),
        h('p', { class: 'small muted', style: { margin: '2px 0 0' } }, 'Used for every “Analyse with AI” request. Also switchable from the header.')),
        h('button', { class: 'btn sm', type: 'button', html: `${icon('refresh')} Re-check`, onclick: refresh })),
    );
    const grid = h('div', { class: 'grid grid-2', style: { marginTop: '14px' }, role: 'radiogroup', 'aria-label': 'Default AI provider' });
    for (const p of providers) {
      const sel = state.provider === p.id;
      const card = h('label', { class: 'card card-pad', style: { cursor: 'pointer', borderColor: sel ? 'var(--accent)' : '', boxShadow: sel ? 'var(--focus)' : '' } });
      card.innerHTML = `<div class="row between"><div class="row"><input type="radio" name="prov" value="${esc(p.id)}" ${sel ? 'checked' : ''}>
          <b>${esc(p.name || p.id)}</b></div>
          ${p.available === true ? '<span class="badge good">Available</span>' : p.available === false ? '<span class="badge bad">Not found</span>' : '<span class="badge">Unknown</span>'}</div>
        <div class="small muted" style="margin-top:8px">${p.version ? `Version: <span class="mono">${esc(p.version)}</span><br>` : ''}${p.path ? `Path: <span class="mono" style="word-break:break-all">${esc(p.path)}</span>` : 'Executable not found on PATH.'}</div>
        ${p.error ? `<div class="small" style="color:var(--bad);margin-top:6px;white-space:pre-wrap">${esc(p.error)}</div>` : ''}`;
      card.querySelector('input').addEventListener('change', () => { setProvider(p.id); });
      grid.append(card);
    }
    aiCard.append(grid);
  };
  async function refresh() {
    try {
      providers = asList(await api.get('/api/ai/providers', { refresh: 'true' }));
      state.providers = providers;
      drawAi();
      toast('Provider availability refreshed.');
    } catch (e) { toast(e.message, 'error'); }
  }
  drawAi();
  const unsub = onStateChange(() => { if (aiCard.isConnected) { providers = state.providers; drawAi(); } });

  // ------------------------------------------------ CLI overrides
  const cliCard = h('section', { class: 'card card-pad' });
  col.append(cliCard);
  try {
    const s = await api.get('/api/settings');
    cliCard.append(h('h2', null, 'Advanced: CLI overrides'),
      h('p', { class: 'small muted' }, 'Optional. Executable path and command template (JSON list of arguments; use {exe} and {instruction} placeholders) for each provider. Leave empty to use the defaults. Permission-bypassing flags are rejected by the server.'));
    for (const p of state.providers) {
      const exeKey = `ai_exe_${p.id}`, cmdKey = `ai_cmd_${p.id}`;
      const exe = h('input', { class: 'input mono', type: 'text', value: s[exeKey] || '', placeholder: p.path || 'auto-detect', id: exeKey });
      const cmd = h('input', { class: 'input mono', type: 'text', value: s[cmdKey] || '', placeholder: 'empty = built-in default', id: cmdKey });
      const save = h('button', { class: 'btn sm', type: 'button', onclick: async () => {
        const body = { [exeKey]: exe.value.trim() || null, [cmdKey]: cmd.value.trim() || null };
        try { await api.put('/api/settings', body); toast(`${p.name || p.id} settings saved.`, 'good'); refresh(); }
        catch (e) { toast(e.message, 'error'); }
      } }, 'Save');
      cliCard.append(h('div', { class: 'card card-pad', style: { background: 'var(--surface-2)', marginTop: '10px' } },
        h('b', null, p.name || p.id),
        h('div', { class: 'grid grid-2', style: { marginTop: '8px', gap: '10px' } },
          h('div', { class: 'field' }, h('label', { for: exeKey }, 'Executable'), exe),
          h('div', { class: 'field' }, h('label', { for: cmdKey }, 'Command (JSON list)'), cmd)),
        h('div', { class: 'row', style: { marginTop: '10px' } }, save)));
    }
  } catch (e) {
    cliCard.append(h('h2', null, 'Advanced: CLI overrides'), h('p', { class: 'small muted' }, `Settings unavailable: ${e.message}`));
  }

  // ------------------------------------------------ content
  const contentCard = h('section', { class: 'card card-pad' });
  col.append(contentCard);
  const statusBox = h('div', { class: 'small muted', style: { marginTop: '10px' } });
  const reBtn = h('button', { class: 'btn primary', type: 'button', html: `${icon('refresh')} Reimport content` });
  contentCard.append(h('h2', null, 'Content'),
    h('p', { class: 'small muted' }, 'Re-reads content/tests, knowledge/data and knowledge/kb into the database. Your attempts and history are kept.'),
    reBtn, statusBox);
  let pollT = 0;
  const loadStatus = async () => {
    try {
      const st = await api.get('/api/admin/status');
      const c = st.counts || {};
      const imp = st.import || {};
      statusBox.innerHTML = `
        <div class="grid grid-4" style="gap:8px;margin-bottom:10px">${Object.entries(c).map(([k, v]) => `<div style="background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:6px 10px"><div class="small muted">${esc(k.replace(/_/g, ' '))}</div><b>${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</b></div>`).join('')}</div>
        ${imp.running ? '<span class="badge warn">Import running…</span>' : imp.finished_at ? `Last import: ${esc(imp.finished_at)}` : ''}
        ${imp.error ? `<div style="color:var(--bad)">${esc(imp.error)}</div>` : ''}
        ${st.transcriber ? `<div style="margin-top:6px">Transcriber: <span class="mono">${esc(typeof st.transcriber === 'object' ? JSON.stringify(st.transcriber) : st.transcriber)}</span></div>` : ''}
        ${st.db_path ? `<div>Database: <span class="mono">${esc(st.db_path)}</span></div>` : ''}`;
      clearTimeout(pollT);
      if (imp.running && statusBox.isConnected) pollT = setTimeout(loadStatus, 1500);
      reBtn.disabled = !!imp.running;
    } catch (e) {
      statusBox.textContent = `Status unavailable: ${e.message}`;
    }
  };
  reBtn.addEventListener('click', async () => {
    reBtn.disabled = true;
    try { await api.post('/api/admin/reimport'); toast('Reimport started.'); setTimeout(loadStatus, 400); }
    catch (e) { toast(e.message, 'error'); reBtn.disabled = false; }
  });
  loadStatus();

  // ------------------------------------------------ appearance
  const themeCard = h('section', { class: 'card card-pad' });
  const cur = themePref();
  const seg = h('div', { class: 'provider-switch', role: 'group', 'aria-label': 'Theme' });
  const drawSeg = (val) => seg.replaceChildren(...[['light', 'Light'], ['dark', 'Dark'], ['system', 'System']].map(([k, l]) =>
    h('button', { type: 'button', 'aria-pressed': String(val === k), onclick: () => { setTheme(k); drawSeg(k); } }, l)));
  drawSeg(cur);
  themeCard.append(h('h2', null, 'Appearance'), h('div', { class: 'row' }, h('span', { class: 'small muted' }, 'Theme'), seg));
  col.append(themeCard);

  return () => { unsub(); clearTimeout(pollT); };
}
