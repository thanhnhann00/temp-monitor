// History: headline temperatures over 1 h / 6 h / 24 h from the SQLite store.
import { areaChart } from '../charts.js';
import { sensorLabel } from '../fmt.js';

const SENSORS = [['cpu', '--chart-a'], ['gpu0', '--chart-b'], ['gpu1', '--chart-c'], ['ssd', '--chart-d']];
const RANGES = [['1h', '1 hr', 3600], ['6h', '6 hr', 6 * 3600], ['24h', '24 hr', 24 * 3600]];

let root; let ctx; let chart; let timer = null;
let range = '1h';
let gen = 0;
const visible = new Set(SENSORS.map(([k]) => k));

export async function mount(el, c) {
  const my = ++gen;
  root = el; ctx = c;
  root.classList.add('cols1');
  root.innerHTML = `
    <div class="head">
      <div><h1>History</h1><p>Temperatures saved every 2 seconds, kept for 24 hours.</p></div>
      <div class="acts"><div class="range" role="group" aria-label="Time range">${RANGES.map(([k, l]) => `<button type="button" data-range="${k}">${l}</button>`).join('')}</div>
      <a class="btn" href="/api/history.csv" download>Export CSV</a></div>
    </div>
    <div class="card">
      <div class="chips" id="toggles">${SENSORS.map(([k, color]) => `<button type="button" class="chipbtn" data-s="${k}" aria-pressed="true" style="--c:var(${color})"><i></i>${sensorLabel(k)}</button>`).join('')}</div>
      <div class="chartbox big" style="height:380px;margin-top:14px"><canvas id="hist"></canvas></div>
    </div>`;
  root.querySelectorAll('[data-range]').forEach((b) => b.addEventListener('click', () => { range = b.dataset.range; load(); }));
  root.querySelectorAll('[data-s]').forEach((b) => b.addEventListener('click', () => {
    const k = b.dataset.s;
    if (visible.has(k)) visible.delete(k); else visible.add(k);
    b.setAttribute('aria-pressed', String(visible.has(k)));
    draw();
  }));
  await load();
  if (my !== gen) return;
  timer = setInterval(load, 30_000);
}

export function unmount() { gen++; clearInterval(timer); chart?.destroy(); chart = null; root = null; }

let data = {};
async function load() {
  root.querySelectorAll('[data-range]').forEach((b) => b.classList.toggle('on', b.dataset.range === range));
  data = await ctx.api.get(`/api/history?range=${range}&sensors=${SENSORS.map(([k]) => k).join(',')}`);
  if (!root) return;
  chart?.destroy();
  chart = areaChart(root.querySelector('#hist'), {
    series: SENSORS.map(([k, color]) => ({ label: sensorLabel(k), color, fill: false })),
    yMin: 20, yMax: 110, yUnit: ' °C', xRange: RANGES.find((r) => r[0] === range)[2],
  });
  draw();
}

function draw() {
  if (!chart) return;
  const now = ctx.snapshot?.ts ?? Date.now() / 1000;
  chart.set(SENSORS.map(([k]) => (visible.has(k) ? data[k] ?? [] : [])), now);
}
