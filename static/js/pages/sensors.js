// Sensors: every reading LibreHardwareMonitor and Windows report, with min/max since the app started.
import { esc, isNum } from '../fmt.js';

const UNITS = { temperature: ' °C', load: '%', clock: ' MHz', fan: ' RPM', power: ' W', voltage: ' V', data: ' GB', smalldata: ' MB', throughput: ' B/s', level: '%', energy: ' mWh', current: ' A', factor: '' };
const SHORT_KEYS = new Set(['cpu', 'gpu0', 'gpu1', 'ssd']);

let root; let ctx; let rows = []; let timer = null;
let query = ''; let kind = '';
let gen = 0;

export async function mount(el, c, params) {
  const my = ++gen;
  root = el; ctx = c;
  query = params.get('q') ?? '';
  document.getElementById('search').value = query;
  root.classList.add('cols1');
  root.innerHTML = `
    <div class="head"><div><h1>Sensors</h1><p>Every sensor on this laptop. Min and max are since Thermo started.</p></div></div>
    <div class="card">
      <div class="filters">
        <input class="field" id="q" type="search" placeholder="Filter by name or hardware" aria-label="Filter sensors" value="${esc(query)}">
        <select class="field" id="kind" aria-label="Sensor type"><option value="">All types</option></select>
        <span class="muted" id="count"></span>
      </div>
      <div class="scroll"><table><thead><tr><th>Hardware</th><th>Name</th><th>Type</th><th class="num">Current</th><th class="num">Min</th><th class="num">Max</th></tr></thead><tbody id="rows"></tbody></table></div>
    </div>`;
  root.querySelector('#q').addEventListener('input', (e) => { query = e.target.value.trim(); render(); });
  root.querySelector('#kind').addEventListener('change', (e) => { kind = e.target.value; render(); });
  await load();
  if (my !== gen) return;
  timer = setInterval(load, 2000);
}

export function unmount() { gen++; clearInterval(timer); root = null; }

export function onSearch(q) {
  query = q;
  if (root) { root.querySelector('#q').value = q; render(); }
}

async function load() {
  rows = (await ctx.api.get('/api/sensors')).filter((r) => !SHORT_KEYS.has(r.id));
  if (!root) return;
  const select = root.querySelector('#kind');
  const kinds = [...new Set(rows.map((r) => r.kind))].sort();
  if (select.options.length !== kinds.length + 1) {
    select.innerHTML = `<option value="">All types</option>${kinds.map((k) => `<option value="${esc(k)}">${esc(k)}</option>`).join('')}`;
    select.value = kind;
  }
  render();
}

function fmt(v, k) {
  if (!isNum(v)) return '—';
  const digits = k === 'temperature' || k === 'load' || k === 'level' ? 1 : k === 'fan' || k === 'clock' ? 0 : 2;
  return `${v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}${UNITS[k] ?? ''}`;
}

function render() {
  const q = query.toLowerCase();
  const shown = rows.filter((r) => (!kind || r.kind === kind) && (!q || `${r.name} ${r.hardware}`.toLowerCase().includes(q)));
  root.querySelector('#count').textContent = `${shown.length} of ${rows.length}`;
  root.querySelector('#rows').innerHTML = shown.length ? shown.map((r) => `
    <tr><td>${esc(r.hardware)}</td><td><b>${esc(r.name)}</b></td><td><span class="tag">${esc(r.kind)}</span></td>
      <td class="num">${fmt(r.value, r.kind)}</td><td class="num">${fmt(r.min, r.kind)}</td><td class="num">${fmt(r.max, r.kind)}</td></tr>`).join('')
    : '<tr><td colspan="6" class="empty">No sensors match.</td></tr>';
}
