// Performance: Task Manager-style usage per device, with 60 s / 5 min / 1 hr ranges.
import { areaChart } from '../charts.js';
import { duration, esc, gb, isNum, kbps, num, pct, temp } from '../fmt.js';

const DEVICES = ['cpu', 'memory', 'disk0', 'wifi', 'gpu0', 'gpu1'];
const TITLES = { cpu: 'CPU', memory: 'Memory', disk0: 'Disk 0 (C:)', wifi: 'Wi-Fi', gpu0: 'GPU 0', gpu1: 'GPU 1' };
const SPARK_KEY = { cpu: 'percent', memory: 'percent', disk0: 'active_pct', wifi: 'recv_kbps', gpu0: 'load_pct', gpu1: 'load_pct' };
const RANGES = [[60, '60 s'], [300, '5 min'], [3600, '1 hr']];
const BUFFER_S = 60;

let root; let ctx; let device = 'cpu'; let range = 60;
let sparks = {}; let charts = []; let serverSeries = null; let pollTimer = null;
const buf = {}; // device -> key -> [[ts, v]]
let latest = null;

export async function mount(el, c, params) {
  root = el; ctx = c;
  device = DEVICES.includes(params.get('device')) ? params.get('device') : 'cpu';
  root.classList.add('perf');
  root.innerHTML = `
    <div class="head">
      <div><h1>Performance</h1><p>Usage for every device, like Task Manager. Updates every second.</p></div>
      <div class="range" role="group" aria-label="Time range">${RANGES.map(([r, l]) => `<button type="button" data-range="${r}" class="${r === range ? 'on' : ''}">${l}</button>`).join('')}</div>
    </div>
    <div class="devs">${DEVICES.map((d) => `
      <button type="button" class="dev" data-dev="${d}"><div class="spark"><canvas></canvas></div><div><b>${TITLES[d]}</b><small data-sub>&nbsp;</small></div></button>`).join('')}
    </div>
    <div class="detail" id="detail"></div>`;
  root.querySelectorAll('[data-dev]').forEach((b) => b.addEventListener('click', () => select(b.dataset.dev)));
  root.querySelectorAll('[data-range]').forEach((b) => b.addEventListener('click', () => setRange(Number(b.dataset.range))));
  for (const d of DEVICES) {
    sparks[d] = areaChart(root.querySelector(`[data-dev="${d}"] canvas`), { series: [{ label: TITLES[d] }], spark: true, yMax: d === 'wifi' ? null : 100 });
  }
  await prefill();
  select(device);
}

export function unmount() {
  Object.values(sparks).forEach((s) => s.destroy());
  charts.forEach((c) => c.destroy());
  sparks = {}; charts = [];
  clearInterval(pollTimer);
  root = null;
}

async function prefill() {
  // Fill the 60 s buffers from the server so charts aren't empty on arrival.
  await Promise.all(DEVICES.map(async (d) => {
    const s = await ctx.api.get(`/api/usage?device=${d}&range=60`).catch(() => ({}));
    buf[d] = Object.fromEntries(Object.entries(s).map(([k, pts]) => [k, pts.slice()]));
  }));
}

function select(d) {
  device = d;
  history.replaceState(null, '', `#/performance?device=${d}`);
  root.querySelectorAll('[data-dev]').forEach((b) => {
    const on = b.dataset.dev === d;
    b.classList.toggle('on', on);
    sparks[b.dataset.dev].setOnHero(on);
  });
  buildDetail();
  setRange(range);
}

async function setRange(r) {
  range = r;
  root.querySelectorAll('[data-range]').forEach((b) => b.classList.toggle('on', Number(b.dataset.range) === r));
  clearInterval(pollTimer);
  serverSeries = null;
  if (r > BUFFER_S) {
    const load = async () => {
      serverSeries = await ctx.api.get(`/api/usage?device=${device}&range=${r}`).catch(() => null);
      drawDetail();
    };
    await load();
    pollTimer = setInterval(load, 5000);
  }
  drawDetail();
}

// ---- detail layout per device -------------------------------------------------
function spec(d) {
  if (d === 'wifi') return { main: ['send_kbps', 'recv_kbps'], mainLabel: 'Throughput', yMax: null, unit: ' Kbps', extra: [] };
  if (d === 'disk0') return { main: ['active_pct'], mainLabel: 'Active time', yMax: 100, unit: '%', extra: [['read_mbs', 'Read speed', ' MB/s'], ['write_mbs', 'Write speed', ' MB/s']] };
  if (d === 'gpu0' || d === 'gpu1') return { main: ['load_pct'], mainLabel: d === 'gpu0' ? 'Utilization · 3D engine' : 'Utilization · GPU core', yMax: 100, unit: '%', extra: [['dedicated_used_gb', 'Dedicated GPU memory', ' GB', 'dedicated_total_gb'], ['shared_used_gb', 'Shared GPU memory', ' GB', 'shared_total_gb']] };
  return { main: ['percent'], mainLabel: d === 'cpu' ? 'Utilization' : 'Memory usage', yMax: 100, unit: '%', extra: [] };
}

function buildDetail() {
  charts.forEach((c) => c.destroy());
  charts = [];
  const s = spec(device);
  const u = latest?.usage?.[device] ?? {};
  const name = device === 'gpu0' || device === 'gpu1' ? (u.name ?? '') : device === 'cpu' ? 'AMD Ryzen 7 6800HS' : device === 'disk0' ? 'SSD (NVMe)' : device === 'wifi' ? 'Wireless network' : '';
  const box = root.querySelector('#detail');
  box.innerHTML = `
    <div class="dhead"><h2>${TITLES[device]}</h2><span>${esc(name)}</span></div>
    <div>
      <div class="chartlbl"><span><b>${s.mainLabel}</b></span>${device === 'wifi'
        ? '<span class="keyline"><span style="--c:var(--chart-a)">Send</span><span style="--c:var(--chart-b)">Receive</span></span>'
        : `<span>${s.yMax ? '100%' : ''}</span>`}</div>
      <div class="chartbox big"><canvas id="main-chart"></canvas></div>
      <div class="chartlbl" style="margin-top:4px"><span data-span>${RANGES.find((x) => x[0] === range)[1]}</span><span>0</span></div>
    </div>
    ${s.extra.length ? `<div class="two">${s.extra.map(([k, label], i) => `
      <div><div class="chartlbl"><b>${label}</b><span data-total="${i}"></span></div><div class="chartbox small"><canvas data-extra="${i}"></canvas></div></div>`).join('')}</div>` : ''}
    <div class="tiles" id="tiles"></div>
    <dl class="meta" id="meta"></dl>`;
  charts.push(areaChart(box.querySelector('#main-chart'), {
    series: s.main.map((k, i) => ({ label: k === 'recv_kbps' ? 'Receive' : k === 'send_kbps' ? 'Send' : s.mainLabel, color: i ? '--chart-b' : '--chart-a', fill: i === 0 })),
    yMax: s.yMax, yUnit: s.unit, xRange: range,
  }));
  s.extra.forEach(([k, label, unit, totalKey], i) => {
    charts.push(areaChart(box.querySelector(`[data-extra="${i}"]`), {
      series: [{ label }], yMax: u[totalKey] ?? null, yUnit: unit, xRange: range,
    }));
  });
  renderTiles();
}

function seriesFor(key) {
  if (range > BUFFER_S) return serverSeries?.[key] ?? [];
  return buf[device]?.[key] ?? [];
}

function drawDetail() {
  if (!root || !charts.length) return;
  const s = spec(device);
  const now = latest?.ts ?? (Date.now() / 1000);
  charts[0].chart.options.scales.x.min = now - range;
  charts[0].set(s.main.map(seriesFor), now);
  s.extra.forEach(([k, , , totalKey], i) => {
    const c = charts[i + 1];
    const total = latest?.usage?.[device]?.[totalKey];
    if (isNum(total)) c.chart.options.scales.y.max = total;
    root.querySelector(`[data-total="${i}"]`).textContent = isNum(total) ? `${gb(total)} GB` : '';
    c.set([seriesFor(k)], now);
  });
  root.querySelector('[data-span]').textContent = RANGES.find((x) => x[0] === range)[1];
}

function tile(label, value, hot = false) {
  return `<div class="tile${hot ? ' hot' : ''}"><small>${label}</small><b title="${esc(value)}">${esc(value)}</b></div>`;
}

function renderTiles() {
  const u = latest?.usage?.[device];
  const tiles = root?.querySelector('#tiles');
  if (!tiles) return;
  const meta = root.querySelector('#meta');
  if (!u) { tiles.innerHTML = ''; meta.innerHTML = ''; return; }
  let html = ''; let metaHtml = '';
  const t = (v) => (isNum(v) ? `${temp(v)} °C` : '—');
  if (device === 'cpu') {
    html = tile('Utilization', pct(u.percent)) + tile('Speed', isNum(u.ghz) ? `${u.ghz.toFixed(2)} GHz` : '—')
      + tile('Processes', num(u.processes)) + tile('Threads', num(u.threads)) + tile('Up time', duration(u.uptime_s)) + tile('Temperature', t(u.temp_c), true);
  } else if (device === 'memory') {
    html = tile('In use', `${gb(u.used_gb)} GB`) + tile('Available', `${gb(u.available_gb)} GB`) + tile('Total', `${gb(u.total_gb)} GB`)
      + tile('Page file used', `${gb(u.pagefile_used_gb)} GB`) + tile('Usage', pct(u.percent), true);
  } else if (device === 'disk0') {
    html = tile('Active time', pct(u.active_pct)) + tile('Read speed', `${num(u.read_mbs, 1)} MB/s`) + tile('Write speed', `${num(u.write_mbs, 1)} MB/s`)
      + tile('Temperature', t(u.temp_c), true);
  } else if (device === 'wifi') {
    html = tile('Send', kbps(u.send_kbps)) + tile('Receive', kbps(u.recv_kbps)) + tile('Network', u.connected ? (u.ssid ?? '—') : 'Not connected')
      + tile('Signal', pct(u.signal_pct)) + tile('IPv4 address', u.ipv4 ?? '—');
  } else {
    const used = (u.dedicated_used_gb ?? 0) + (u.shared_used_gb ?? 0);
    const total = (u.dedicated_total_gb ?? 0) + (u.shared_total_gb ?? 0);
    html = tile('Utilization', pct(u.load_pct)) + tile('GPU memory', `${gb(used)} / ${gb(total)} GB`)
      + tile('Dedicated', `${gb(u.dedicated_used_gb)} / ${gb(u.dedicated_total_gb)} GB`) + tile('Shared', `${gb(u.shared_used_gb)} / ${gb(u.shared_total_gb)} GB`);
    if (device === 'gpu1') html += tile('Fan', isNum(u.fan_rpm) ? `${num(u.fan_rpm)} RPM` : '—') + tile('Power', isNum(u.power_w) ? `${num(u.power_w, 1)} W` : '—');
    html += tile('Temperature', u.sleeping ? 'Sleeping' : t(u.temp_c), true);
    metaHtml = `<dt>Driver version</dt><dd>${esc(u.driver_version ?? '—')}</dd><dt>Driver date</dt><dd>${esc(u.driver_date ?? '—')}</dd>`;
  }
  tiles.innerHTML = html;
  meta.innerHTML = metaHtml;
}

function subtitle(d, u) {
  if (!u) return '&nbsp;';
  const t = (v) => (isNum(v) ? ` · ${temp(v)} °C` : '');
  switch (d) {
    case 'cpu': return `${pct(u.percent)}${isNum(u.ghz) ? ` · ${u.ghz.toFixed(2)} GHz` : ''}${t(u.temp_c)}`;
    case 'memory': return `${gb(u.used_gb)} / ${gb(u.total_gb)} GB (${pct(u.percent)})`;
    case 'disk0': return `SSD (NVMe) · ${pct(u.active_pct)}${t(u.temp_c)}`;
    case 'wifi': return u.connected ? `Send ${kbps(u.send_kbps)} · Receive ${kbps(u.recv_kbps)}` : 'Not connected';
    default: return `${esc((u.name ?? '').replace('(TM) Graphics', ' Graphics').replace(' Laptop GPU', ''))}<br>${u.sleeping ? 'Sleeping' : `${pct(u.load_pct)}${t(u.temp_c)}`}`;
  }
}

export function onSnapshot(snap) {
  if (!root) return;
  const first = !latest;
  latest = snap;
  for (const d of DEVICES) {
    const u = snap.usage[d];
    if (!u) continue;
    const b = (buf[d] ??= {});
    for (const [k, v] of Object.entries(u)) {
      if (!isNum(v)) continue;
      const list = (b[k] ??= []);
      if (!list.length || list[list.length - 1][0] < snap.ts) list.push([snap.ts, v]);
      while (list.length && list[0][0] <= snap.ts - BUFFER_S) list.shift();
    }
    root.querySelector(`[data-dev="${d}"] [data-sub]`).innerHTML = subtitle(d, u);
    sparks[d].set([b[SPARK_KEY[d]] ?? []], snap.ts);
  }
  if (first) buildDetail();
  renderTiles();
  drawDetail();
}
