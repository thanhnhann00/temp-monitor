// Thin client for the Thermo HTTP API and live stream.
const TOKEN = document.querySelector('meta[name="thermo-token"]')?.content ?? '';

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (method !== 'GET') opts.headers['X-Thermo-Token'] = TOKEN;
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : await res.text();
  if (res.status === 403 && method !== 'GET') {
    // Thermo was restarted and issued a new token; reload to pick it up.
    location.reload();
  }
  if (!res.ok) {
    const err = new Error(errorText(data, res.status));
    err.status = res.status;
    throw err;
  }
  return data;
}

function errorText(data, status) {
  if (data && typeof data === 'object') {
    if (data.error) return data.error;
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail) && data.detail.length) {
      const d = data.detail[0];
      return (d.msg || 'Invalid value').replace(/^Value error, /, '');
    }
  }
  return `Request failed (${status})`;
}

export const get = (path) => request('GET', path);
export const put = (path, body) => request('PUT', path, body);
export const post = (path) => request('POST', path);

// Calls onSnapshot(json) for every snapshot and onState('live' | 'reconnecting').
export function stream(onSnapshot, onState) {
  const es = new EventSource('/api/stream');
  es.addEventListener('snapshot', (e) => {
    onState('live');
    onSnapshot(JSON.parse(e.data));
  });
  es.onerror = () => onState('reconnecting'); // EventSource retries by itself
  return () => es.close();
}
