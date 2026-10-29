// Small fetch helper for the FastAPI backend (same origin).

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request(method, url, body, opts = {}) {
  const init = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  if (opts.keepalive) init.keepalive = true;
  let res;
  try {
    res = await fetch(url, init);
  } catch (e) {
    throw new ApiError('Cannot reach the local server. Is it running?', 0, null);
  }
  const ct = res.headers.get('content-type') || '';
  let data = null;
  if (res.status !== 204) {
    data = ct.includes('application/json') ? await res.json().catch(() => null) : await res.text().catch(() => null);
  }
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    if (data && typeof data === 'object' && data.detail) {
      msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
    } else if (typeof data === 'string' && data.length < 300 && data) {
      msg = data;
    }
    throw new ApiError(msg, res.status, data);
  }
  return data;
}

function qs(params) {
  if (!params) return '';
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    p.set(k, v);
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

export const api = {
  get: (url, params) => request('GET', url + qs(params)),
  post: (url, body) => request('POST', url, body === undefined ? {} : body),
  put: (url, body, opts) => request('PUT', url, body, opts),
  del: (url) => request('DELETE', url),
  upload: (url, formData) => request('POST', url, formData),
};

/** Resolve a content-relative media path (e.g. "media/listening/x/part1.mp3") to a URL. */
export function mediaUrl(path) {
  if (!path) return '';
  if (/^(https?:|data:|blob:)/.test(path)) return path;
  if (path.startsWith('/media/')) return path;
  let p = path.replace(/^\/+/, '');
  if (p.startsWith('content/')) p = p.slice(8);
  return '/media/content/' + p.split('/').map(encodeURIComponent).join('/');
}

/** Resolve a path under data/uploads. */
export function uploadUrl(path) {
  if (!path) return '';
  if (/^(https?:|\/)/.test(path)) return path;
  let p = path.replace(/\\/g, '/');
  if (p.startsWith('data/uploads/')) p = p.slice('data/uploads/'.length);
  return '/media/uploads/' + p;
}
