// Deleting a result — a listening/reading attempt, an essay or a speaking session — always after a confirmation.
// Items imported from the course chat or My Results.docx cannot be deleted (the next import would restore them).
import { api } from '../api.js';
import { h, esc, icon, toast, confirmDialog, store, fmtBand } from '../ui.js';

const KINDS = {
  attempt: {
    url: (id) => `/api/attempts/${id}`,
    what: (x) => (x.status && x.status !== 'submitted' ? 'this unfinished attempt' : 'this result'),
    lost: 'Your answers and any AI analyses of it are',
    can: (x) => x.mode !== 'imported',
    after: (x) => store.remove(`attempt.${x.id}`),   // the player's local copy of an unfinished attempt
  },
  writing: {
    url: (id) => `/api/writing/submissions/${id}`,
    what: () => 'this essay',
    lost: 'The essay and its AI analyses are',
    can: (x) => x.origin !== 'telegram_import',
  },
  speaking: {
    url: (id) => `/api/speaking/sessions/${id}`,
    what: () => 'this speaking session',
    lost: 'Its recordings, transcripts and AI analyses are',
    can: (x) => x.mode !== 'imported',
  },
};

/** Whether `item` of `kind` ('attempt' | 'writing' | 'speaking') can be deleted in the app. */
export const canDelete = (kind, item) => !!item && KINDS[kind].can(item);

/** Ask, then delete; resolves true when deleted. `item`: { id, title?, band?, mock_id?, ... }. */
export async function confirmDelete(kind, item) {
  const k = KINDS[kind];
  const ok = await confirmDialog(`Delete ${k.what(item)}?`,
    `${item.title ? `<p>${esc(item.title)}${item.band != null ? ` — band ${esc(fmtBand(item.band))}` : ''}</p>` : ''}
     <p>${k.lost} removed for good.${item.mock_id ? ' Its mock exam loses this section.' : ''} This cannot be undone.</p>`,
    'Delete', 'danger');
  if (!ok) return false;
  try {
    await api.del(k.url(item.id));
  } catch (e) { toast(`Could not delete: ${e.message}`, 'error'); return false; }
  k.after?.(item);
  toast('Deleted.', 'good');
  return true;
}

/** "Delete" button for a detail page; `done()` runs after a successful delete (e.g. go back to the list). */
export function deleteButton(kind, item, done) {
  if (!canDelete(kind, item)) return null;
  return h('button', { class: 'btn danger', type: 'button', html: `${icon('trash')} Delete`,
    onclick: async () => { if (await confirmDelete(kind, item)) done(); } });
}

/** Small trash button for a table row (handled by `onRowDelete`). */
export function rowDeleteHtml(kind, id) {
  return `<button class="icon-btn sm-del" type="button" data-del-kind="${kind}" data-del="${esc(id)}" title="Delete" aria-label="Delete">${icon('trash')}</button>`;
}

/**
 * One click handler for a table of rows with `rowDeleteHtml` buttons. `find(kind, id)` returns the item;
 * `removed(kind, id)` runs after it was deleted.
 */
export function onRowDelete(table, find, removed) {
  table.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-del]');
    if (!b) return;
    e.preventDefault();
    e.stopPropagation();
    const kind = b.dataset.delKind, item = find(kind, b.dataset.del);
    if (item && await confirmDelete(kind, item)) removed(kind, b.dataset.del);
  });
}
