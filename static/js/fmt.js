// Formatting helpers. Every function accepts null and returns "—" for it.
export const DASH = '—';

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
export const temp = (v) => (isNum(v) ? Math.round(v).toString() : DASH);
export const num = (v, digits = 0) => (isNum(v) ? v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits }) : DASH);
export const pct = (v) => (isNum(v) ? `${Math.round(v)}%` : DASH);
export const gb = (v) => (isNum(v) ? v.toFixed(1) : DASH);

export function kbps(v) {
  if (!isNum(v)) return DASH;
  return v >= 1000 ? `${(v / 1000).toFixed(1)} Mbps` : `${v.toFixed(v < 10 ? 1 : 0)} Kbps`;
}

export function clock(seconds) {
  if (!isNum(seconds)) return DASH;
  const s = Math.max(0, Math.floor(seconds));
  const p = (n) => String(n).padStart(2, '0');
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

export function duration(seconds) {
  if (!isNum(seconds)) return DASH;
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return d ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
}

export function when(ts) {
  if (!isNum(ts)) return DASH;
  const d = new Date(ts * 1000);
  const today = new Date();
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if (d.toDateString() === today.toDateString()) return `Today · ${time}`;
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} · ${time}`;
}

export function hourLabel(ts) {
  const h = new Date(ts * 1000).getHours();
  return `${h % 12 || 12}${h < 12 ? 'a' : 'p'}`;
}

// Temperature status used by chips: Normal / Warm / High.
export function status(v, warmAt = 75, hotAt = 85) {
  if (!isNum(v)) return null;
  if (v >= hotAt) return ['hot', 'High'];
  if (v >= warmAt) return ['warm', 'Warm'];
  return ['ok', 'Normal'];
}

export const LABELS = { cpu: 'CPU', gpu0: 'GPU 0 (Radeon)', gpu1: 'GPU 1 (RTX 3050)', ssd: 'SSD' };
export const sensorLabel = (key) => LABELS[key] ?? key;
