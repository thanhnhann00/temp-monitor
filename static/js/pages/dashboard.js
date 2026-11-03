// Dashboard: headline temperatures, 7-hour CPU pill chart, alerts, sensors, fans, headroom, uptime.
import { gauge, pillChart } from '../charts.js';
import { clock, esc, isNum, num, sensorLabel, status, temp, when } from '../fmt.js';

const CARDS = [
  ['cpu', 'CPU Package', 'cpu', true],
  ['gpu1', 'RTX 3050 GPU', 'gpu1', false],
  ['gpu0', 'Radeon iGPU', 'gpu0', false],
  ['ssd', 'NVMe SSD', 'disk0', false],
];
const SHORT_KEYS = new Set(['cpu', 'gpu0', 'gpu1', 'ssd']);

let root; let ctx; let timers = [];
let max24 = {};
const recent = {}; // key -> [[ts, v]] for the last ~60 s (trend arrows)

export async function mount(el, c) {
  root = el; ctx = c;
  root.classList.add('dash');
  root.innerHTML = `
    <div class="head">
      <div><h1>Dashboard</h1><p>Live temperatures for your laptop, updated every second.</p></div>
      <div class="acts"><a class="btn pri" href="#/alerts">＋ Set Alert</a><a class="btn" href="/api/history.csv" download>Export CSV</a></div>
    </div>
    ${CARDS.map(([key, title, dev, hero]) => `
      <a class="card stat${hero ? ' hero' : ''}" href="#/performance?device=${dev}" data-key="${key}">
        <h3>${title}</h3><span class="arrow" aria-hidden="true">↗</span>
        <div class="v" data-v>—</div><div class="f" data-f>&nbsp;</div></a>`).join('')}
    <div class="card span2 pills-card">
      <h3>CPU Temperature · last 7 hours</h3>
      <div class="legend" aria-hidden="true"><span style="--c:var(--pill-hot)">Hot</span><span style="--c:var(--o500)">Warm</span><span style="--c:var(--stripe)">Cool</span></div>
      <div class="bars" id="pills"></div>
    </div>
    <div class="card alertcard" id="last-alert"><h3>Last Alert</h3><h2>&nbsp;</h2><p>&nbsp;</p></div>
    <div class="card" id="top-sensors"><h3>All Sensors</h3><a class="mini tr" href="#/sensors">View all</a><div class="list"></div></div>
    <div class="card span2" id="fans-load"><h3>Fans &amp; Load</h3><a class="mini tr" href="#/fans">Cooling mode</a><div class="list"></div></div>
    <div class="card" id="headroom">
      <h3>Thermal Headroom</h3>
      <div class="gauge"><svg width="210" height="120" viewBox="0 0 210 120" aria-hidden="true"></svg><div class="n">—</div><div class="l">&nbsp;</div></div>
      <div class="glegend" aria-hidden="true"><span style="--c:var(--o500)">Used</span><span style="--c:var(--stripe)">Headroom</span></div>
    </div>
    <div class="card timer" id="timer">
      <h3>Monitoring For</h3><div class="clock">00:00:00</div><small data-samples>&nbsp;</small>
      <div class="ctl"><button type="button" data-pause aria-label="Pause history">❚❚</button><button type="button" class="stop" data-stop aria-label="Quit monitor">■</button></div>
    </div>`;

  root.querySelector('[data-pause]').addEventListener('click', togglePause);
  root.querySelector('[data-stop]').addEventListener('click', () => ctx.confirmQuit());
  await Promise.all([loadPills(), loadMax(), loadAlert()]);
  timers.push(setInterval(loadPills, 5 * 60_000), setInterval(loadAlert, 15_000), setInterval(loadMax, 5 * 60_000));
  renderTimer();
}

export function unmount() {
  timers.forEach(clearInterval);
  timers = [];
}

async function loadPills() {
  pillChart(root.querySelector('#pills'), await ctx.api.get('/api/history/hourly?sensor=cpu&hours=7'));
}

async function loadMax() {
  const hist = await ctx.api.get('/api/history?range=24h&sensors=cpu,gpu0,gpu1,ssd');
  max24 = Object.fromEntries(Object.entries(hist).map(([k, pts]) => [k, pts.length ? Math.max(...pts.map((p) => p[1])) : null]));
}

async function loadAlert() {
  const [a] = await ctx.api.get('/api/alerts/log?limit=1');
  const card = root.querySelector('#last-alert');
  if (!a) {
    card.innerHTML = `<h3>Last Alert</h3><h2>No alerts yet</h2><p>Everything has stayed below your limits.</p><a class="btn pri" href="#/alerts">⚙ Edit Thresholds</a>`;
    return;
  }
  const lasted = a.ended ? `lasted ${Math.max(1, Math.round(a.ended - a.started))} s` : 'still above the limit';
  card.innerHTML = `<h3>Last Alert</h3><h2>${esc(sensorLabel(a.sensor_id))} reached<br>${temp(a.peak)} °C</h2>
    <p>${esc(when(a.started))} · ${lasted}</p><a class="btn pri" href="#/alerts">⚙ Edit Thresholds</a>`;
}

async function togglePause() {
  const paused = ctx.status?.paused;
  try {
    await ctx.api.post(paused ? '/api/monitor/resume' : '/api/monitor/pause');
    await ctx.refreshStatus();
    ctx.toast(paused ? 'History recording resumed.' : 'History paused. The live view keeps updating.');
  } catch (e) { ctx.toast(e.message); }
}

export function onStatus() { renderTimer(); }

function renderTimer() {
  const s = ctx.status;
  if (!s || !root) return;
  root.querySelector('#timer .clock').textContent = clock(s.uptime_s);
  root.querySelector('[data-samples]').textContent = s.paused ? 'History paused' : `${num(s.samples_saved)} samples saved`;
  const btn = root.querySelector('[data-pause]');
  btn.textContent = s.paused ? '▶' : '❚❚';
  btn.setAttribute('aria-label', s.paused ? 'Resume history' : 'Pause history');
}

function trend(key, v, ts) {
  const list = (recent[key] ??= []);
  if (isNum(v)) list.push([ts, v]);
  while (list.length && list[0][0] < ts - 60) list.shift();
  if (!isNum(v) || list.length < 2) return '';
  const d = Math.round(v - list[0][1]);
  return d === 0 ? '' : `<i>${d > 0 ? '▲' : '▼'}${Math.abs(d)}</i>`;
}

export function onSnapshot(snap) {
  if (!root) return;
  for (const [key] of CARDS) {
    const card = root.querySelector(`[data-key="${key}"]`);
    const v = snap.headline[key];
    const vEl = card.querySelector('[data-v]');
    const sleeping = key === 'gpu1' && snap.usage.gpu1?.sleeping;
    vEl.className = sleeping ? 'v sleep' : 'v';
    vEl.innerHTML = sleeping ? 'Sleeping' : `${temp(v)}<span>°C</span>`;
    const max = Math.max(...[max24[key], v].filter(isNum));
    const foot = sleeping ? 'GPU is idle and powered down'
      : !isNum(v) && (key === 'cpu' || key === 'ssd') && !ctx.status?.is_admin ? 'Needs administrator'
        : isNum(max) ? `Max ${Math.round(max)} °C · 24 h` : '&nbsp;';
    card.querySelector('[data-f]').innerHTML = `${trend(key, v, snap.ts)}${foot}`;
  }

  // five hottest temperature sensors
  const temps = snap.readings.filter((r) => r.kind === 'temperature' && isNum(r.value) && r.value > 0 && !SHORT_KEYS.has(r.id))
    .sort((a, b) => b.value - a.value).slice(0, 5);
  root.querySelector('#top-sensors .list').innerHTML = temps.length ? temps.map((r) => `
    <div class="row"><div class="ico" aria-hidden="true">▣</div><div><b>${esc(r.name)}</b><small>${esc(r.hardware)}</small></div><span class="t">${temp(r.value)}°</span></div>`).join('')
    : '<p class="empty">No temperature sensors yet.</p>';

  renderFans(snap);

  const limit = ctx.settings?.cpu_limit_c ?? 90;
  const cpu = snap.headline.cpu;
  const box = root.querySelector('#headroom');
  gauge(box.querySelector('svg'), cpu, limit);
  box.querySelector('.n').textContent = isNum(cpu) ? `${Math.round(limit - cpu)}°` : '—';
  box.querySelector('.l').textContent = isNum(cpu)
    ? (cpu >= limit ? `above CPU limit (${limit} °C)` : `below CPU limit (${limit} °C)`)
    : 'CPU temperature needs administrator';

  if (ctx.status) {
    ctx.status.uptime_s += 1; // ticks between /api/status refreshes
    renderTimer();
  }
}

function renderFans(snap) {
  const u = snap.usage;
  const rows = [];
  for (const fan of u.fans ?? []) {
    const isGpu = /gpu/i.test(fan.name);
    const t = isGpu ? snap.headline.gpu0 : snap.headline.cpu;
    const load = isGpu ? `GPU load ${num(u.gpu0?.load_pct)}%` : `CPU load ${num(u.cpu?.percent)}%`;
    rows.push(['≋', fan.name, `Spinning at <em>${num(fan.rpm)} RPM</em> · ${load}`, status(t)]);
  }
  if (!rows.length) {
    rows.push(['▣', 'CPU Load', `<em>${num(u.cpu?.percent)}%</em> · ${isNum(u.cpu?.ghz) ? `${u.cpu.ghz.toFixed(2)} GHz` : 'clock needs administrator'}`, status(snap.headline.cpu)]);
    rows.push(['◧', 'GPU 0 Load', `<em>${num(u.gpu0?.load_pct)}%</em> · Radeon`, status(snap.headline.gpu0)]);
  }
  const cpuPower = snap.readings.find((r) => r.kind === 'power' && r.name === 'Package' && /ryzen/i.test(r.hardware));
  if (cpuPower && isNum(cpuPower.value)) rows.push(['⚡', 'CPU Power', `Package draw <em>${num(cpuPower.value)} W</em>`, status(snap.headline.cpu)]);
  if (u.gpu1) {
    rows.push(['⚡', 'GPU Power', u.gpu1.sleeping ? 'RTX 3050 is sleeping' : `Board draw <em>${num(u.gpu1.power_w, 1)} W</em>`,
      u.gpu1.sleeping ? null : status(snap.headline.gpu1)]);
  }
  root.querySelector('#fans-load .list').innerHTML = rows.map(([ic, name, sub, st]) => `
    <div class="row"><div class="ico" aria-hidden="true">${ic}</div><div><b>${esc(name)}</b><small>${sub}</small></div>${st ? `<span class="chip ${st[0]}">${st[1]}</span>` : ''}</div>`).join('');
}
