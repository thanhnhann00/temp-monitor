// Fans & Cooling: cooling mode (Windows power mode), Smart Cooling rules, fan speeds, temp-vs-fan chart.
import { areaChart } from '../charts.js';
import { duration, esc, isNum, num, temp } from '../fmt.js';

const MODES = [
  ['quiet', '🌙', 'Quiet', 'Fans stay low and quiet.<br>CPU and GPU run slower and cooler.'],
  ['balanced', '⚖', 'Balanced', 'Fans speed up only when needed.<br>Good for everyday use.'],
  ['performance', '🚀', 'Performance', 'Fans spin up sooner and faster.<br>Best for games and renders.'],
];
const MODE_NAME = Object.fromEntries(MODES.map(([k, , n]) => [k, n]));

let root; let ctx; let chart; let timers = [];
let mode = null; let pending = null; let lastEvent = null;
let maxRpm = {};
let fanIds = '';
let gen = 0;

export async function mount(el, c) {
  const my = ++gen;
  root = el; ctx = c;
  root.classList.add('fans');
  root.innerHTML = `
    <div class="head"><div><h1>Fans &amp; Cooling</h1><p>Choose how hard the fans work. Same modes as Fn + Q.</p></div></div>
    <div class="card modes span2">
      <h3>Cooling Mode</h3>
      <div class="seg" role="radiogroup" aria-label="Cooling mode">${MODES.map(([k, em, name, desc]) => `
        <button type="button" class="mode" role="radio" aria-checked="false" data-mode="${k}"><div class="em" aria-hidden="true">${em}</div><b>${name}</b><small>${desc}</small></button>`).join('')}
      </div>
      <p class="note" id="mode-note">&nbsp;</p>
    </div>
    <div class="card auto" id="smart">
      <h3>Smart Cooling</h3><button type="button" class="switch" role="switch" aria-checked="false" aria-label="Smart Cooling" id="smart-switch"></button>
      <div class="rule">Switch to <b>Performance</b> when CPU stays at or above <input type="number" data-k="up_c" aria-label="Switch up temperature"> °C for <input type="number" data-k="up_s" aria-label="Switch up seconds"> s.</div>
      <div class="rule">Go back to your previous mode when CPU stays below <input type="number" data-k="down_c" aria-label="Switch back temperature"> °C for <input type="number" data-k="down_s" aria-label="Switch back seconds"> s.</div>
      <p class="err" id="smart-err" role="alert"></p>
    </div>
    <div class="full" id="fan-cards" style="display:contents"></div>
    <div class="card full">
      <h3>Temperature vs Fan Speed · last 5 min</h3>
      <div class="keyline" style="position:absolute;right:18px;top:18px"><span style="--c:var(--chart-a)">CPU temp</span><span style="--c:var(--chart-b)">CPU fan</span><span style="--c:var(--stripe)">Mode change</span></div>
      <div class="chartbox big" style="margin-top:14px"><canvas id="tf"></canvas></div>
    </div>`;

  root.querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => choose(b.dataset.mode)));
  root.querySelector('#smart-switch').addEventListener('click', toggleSmart);
  root.querySelectorAll('#smart input').forEach((i) => i.addEventListener('change', saveSmart));

  chart = areaChart(root.querySelector('#tf'), {
    series: [{ label: 'CPU temp', unit: ' °C' }, { label: 'CPU fan', color: '--chart-b', fill: false, axis: 'y2', unit: ' RPM' }],
    yMax: 110, xRange: 300,
  });
  await Promise.all([loadSmart(), loadMode(), loadChart()]);
  if (my !== gen) return;
  timers.push(setInterval(loadChart, 5000));
  onStatus(ctx.status);
}

export function unmount() {
  gen++;
  timers.forEach(clearInterval);
  timers = [];
  chart?.destroy();
  chart = null; root = null; fanIds = '';
}

// ---- cooling mode ------------------------------------------------------------
async function loadMode() {
  const r = await ctx.api.get('/api/cooling/mode');
  mode = r.mode;
  if (root) renderModes();
}

function renderModes() {
  const shown = pending ?? mode;
  root.querySelectorAll('[data-mode]').forEach((b) => {
    const on = b.dataset.mode === shown;
    b.classList.toggle('on', on);
    b.setAttribute('aria-checked', String(on));
  });
}

async function choose(next) {
  if (next === mode || pending) return;
  pending = next;
  renderModes();
  try {
    await ctx.api.put('/api/cooling/mode', { mode: next });
    mode = next;
    lastEvent = { ts: Date.now() / 1000, mode: next, source: 'app' };
    renderNote();
  } catch (e) {
    ctx.toast(`Couldn't change the cooling mode: ${e.message}`);
  } finally {
    pending = null;
    renderModes();
  }
}

function renderNote() {
  const note = root?.querySelector('#mode-note');
  if (!note) return;
  if (ctx.status && !ctx.status.cooling_available) {
    note.textContent = 'Cooling modes need the Balanced power plan. Switch to it in Windows power settings to use these.';
    return;
  }
  let text = 'Changes the Windows power mode, which your Lenovo cooling service follows.';
  if (lastEvent) {
    const ago = duration(Date.now() / 1000 - lastEvent.ts);
    const by = { app: '', smart: ' by Smart Cooling', external: ' outside Thermo' }[lastEvent.source] ?? '';
    text += ` Switched to ${MODE_NAME[lastEvent.mode] ?? lastEvent.mode}${by} ${ago} ago.`;
  }
  note.textContent = text;
}

export function onStatus(status) {
  if (!root || !status) return;
  root.querySelectorAll('[data-mode]').forEach((b) => { b.disabled = !status.cooling_available; });
  renderNote();
}

// ---- smart cooling -----------------------------------------------------------
let smart = null;
async function loadSmart() {
  smart = await ctx.api.get('/api/cooling/smart');
  if (root) renderSmart();
}

function renderSmart() {
  root.querySelector('#smart-switch').setAttribute('aria-checked', String(smart.enabled));
  root.querySelectorAll('#smart input').forEach((i) => { i.value = smart[i.dataset.k]; });
}

async function toggleSmart() {
  await saveSmart(null, !smart.enabled);
}

async function saveSmart(_event, enabled = smart.enabled) {
  const body = { enabled };
  root.querySelectorAll('#smart input').forEach((i) => { body[i.dataset.k] = Number(i.value); });
  const err = root.querySelector('#smart-err');
  try {
    smart = await ctx.api.put('/api/cooling/smart', body);
    err.textContent = '';
    renderSmart();
  } catch (e) {
    err.textContent = e.message;
  }
}

// ---- fan cards ---------------------------------------------------------------
function renderFans(snap) {
  const fans = snap.usage.fans ?? [];
  const gpu1 = snap.usage.gpu1 ?? {};
  const ids = fans.map((f) => f.id).join(',') || 'none';
  const box = root.querySelector('#fan-cards');
  if (ids !== fanIds) {
    fanIds = ids;
    box.innerHTML = (fans.length ? fans.map((f) => `
      <div class="card rpm" data-fan="${esc(f.id)}"><h3>${esc(f.name)}</h3><div class="spin" aria-hidden="true">✲</div>
        <div class="v" data-v>—</div><div class="meter"><i data-bar style="width:0"></i></div><div class="f"><span data-pct>&nbsp;</span><span data-t>&nbsp;</span></div></div>`).join('')
      : `<div class="card span2 nofan"><div class="big" aria-hidden="true">≋</div><div><h3>This laptop doesn't report fan speed</h3>
          <p class="note">Lenovo doesn't expose fan RPM on this model. The cooling modes above still control how hard the fans run.</p></div></div>`)
      + `<div class="card rpm" id="rtx"><h3>RTX 3050</h3><div class="spin" aria-hidden="true" data-icon>☾</div>
          <div class="v" data-v>—</div><div class="meter"><i data-bar style="width:0"></i></div><div class="f"><span data-pct>&nbsp;</span><span data-t>&nbsp;</span></div></div>`;
  }
  for (const f of fans) {
    const card = box.querySelector(`[data-fan="${CSS.escape(f.id)}"]`);
    if (!card) continue;
    if (isNum(f.rpm)) maxRpm[f.id] = Math.max(maxRpm[f.id] ?? 0, f.rpm);
    const share = isNum(f.rpm) && maxRpm[f.id] ? Math.round((f.rpm / maxRpm[f.id]) * 100) : 0;
    const t = /gpu/i.test(f.name) ? ['GPU', snap.headline.gpu0] : ['CPU', snap.headline.cpu];
    card.querySelector('[data-v]').innerHTML = isNum(f.rpm) ? `${num(f.rpm)}<span> RPM</span>` : '—';
    card.querySelector('[data-bar]').style.width = `${share}%`;
    card.querySelector('[data-pct]').textContent = isNum(f.rpm) ? `${share}% of highest seen` : 'No reading';
    card.querySelector('[data-t]').textContent = `${t[0]} ${temp(t[1])} °C`;
  }
  const rtx = box.querySelector('#rtx');
  const v = rtx.querySelector('[data-v]');
  v.className = gpu1.sleeping ? 'v sleep' : 'v';
  rtx.querySelector('[data-icon]').className = gpu1.sleeping ? 'spin off' : 'spin';
  rtx.querySelector('[data-icon]').textContent = gpu1.sleeping ? '☾' : '✲';
  if (gpu1.sleeping) {
    v.textContent = 'Sleeping';
    rtx.querySelector('[data-bar]').style.width = '0';
    rtx.querySelector('[data-pct]').textContent = 'GPU is idle and powered down';
    rtx.querySelector('[data-t]').textContent = '—';
  } else {
    v.innerHTML = isNum(gpu1.fan_rpm) ? `${num(gpu1.fan_rpm)}<span> RPM</span>` : `${temp(gpu1.temp_c)}<span> °C</span>`;
    rtx.querySelector('[data-bar]').style.width = `${Math.min(100, Math.max(0, gpu1.load_pct ?? 0))}%`;
    rtx.querySelector('[data-pct]').textContent = `${num(gpu1.load_pct)}% load`;
    rtx.querySelector('[data-t]').textContent = isNum(gpu1.power_w) ? `${num(gpu1.power_w, 1)} W` : '';
  }
}

// ---- chart -------------------------------------------------------------------
async function loadChart() {
  const now = ctx.snapshot?.ts ?? Date.now() / 1000;
  const [temps, fans, events] = await Promise.all([
    ctx.api.get('/api/usage?device=temps&range=300').catch(() => ({})),
    ctx.api.get('/api/usage?device=fans&range=300').catch(() => ({})),
    ctx.api.get(`/api/cooling/events?since=${now - 3600}`).catch(() => []),
  ]);
  if (!chart) return;
  const named = ctx.snapshot?.usage?.fans ?? [];
  const cpuId = (named.find((f) => !/gpu/i.test(f.name)) ?? named[0])?.id;
  const cpuFan = (cpuId && fans[cpuId]) || Object.values(fans)[0] || [];
  chart.set([temps.cpu ?? [], cpuFan], now);
  chart.setMarkers(events.filter((e) => e.ts >= now - 300).map((e) => ({ x: e.ts, label: `→ ${MODE_NAME[e.mode] ?? e.mode}` })));
  if (events.length) { lastEvent = events[events.length - 1]; renderNote(); }
}

export function onSnapshot(snap) {
  if (!root) return;
  if (!pending && snap.cooling_mode && snap.cooling_mode !== 'unknown' && snap.cooling_mode !== mode) {
    mode = snap.cooling_mode;
    renderModes();
  }
  renderFans(snap);
}
