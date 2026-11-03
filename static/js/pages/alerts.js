// Alerts: per-sensor temperature limits and the alert log.
import { esc, isNum, sensorLabel, temp, when } from '../fmt.js';

let root; let ctx; let thresholds = []; let names = {};

export async function mount(el, c) {
  root = el; ctx = c;
  root.classList.add('cols1');
  root.innerHTML = `
    <div class="head"><div><h1>Alerts</h1><p>Get a Windows notification when a temperature reaches its limit. At most one per sensor every 5 minutes.</p></div></div>
    <div class="card">
      <h3>Alert limits</h3>
      <div class="scroll"><table style="margin-top:10px"><thead><tr><th>Sensor</th><th>On</th><th class="num">Limit</th><th></th></tr></thead><tbody id="th-rows"></tbody></table></div>
      <div class="filters" style="margin-top:14px">
        <select class="field" id="add-sensor" aria-label="Add an alert for another sensor"></select>
        <button type="button" class="mini" id="add">＋ Add sensor</button>
        <span class="sp" style="flex:1"></span>
        <span class="err" id="th-err" role="alert"></span>
        <button type="button" class="btn pri" id="save">Save limits</button>
      </div>
    </div>
    <div class="card">
      <h3>Alert log</h3>
      <div class="scroll"><table style="margin-top:10px"><thead><tr><th>When</th><th>Sensor</th><th class="num">Peak</th><th class="num">Lasted</th></tr></thead><tbody id="log-rows"></tbody></table></div>
    </div>`;
  root.querySelector('#save').addEventListener('click', save);
  root.querySelector('#add').addEventListener('click', add);
  const [th, sensors] = await Promise.all([ctx.api.get('/api/alerts/thresholds'), ctx.api.get('/api/sensors')]);
  thresholds = th;
  names = Object.fromEntries(sensors.filter((s) => s.kind === 'temperature').map((s) => [s.id, `${s.name} · ${s.hardware}`]));
  renderThresholds();
  await loadLog();
}

export function unmount() { root = null; }

const label = (key) => names[key] ?? sensorLabel(key);

function renderThresholds() {
  root.querySelector('#th-rows').innerHTML = thresholds.map((t, i) => `
    <tr><td><b>${esc(label(t.key))}</b></td>
      <td><input type="checkbox" data-i="${i}" data-f="enabled" ${t.enabled ? 'checked' : ''} aria-label="Alert on for ${esc(label(t.key))}"></td>
      <td class="num"><input class="field" type="number" data-i="${i}" data-f="limit_c" value="${t.limit_c}" aria-label="Limit for ${esc(label(t.key))}"> °C</td>
      <td class="num">${['cpu', 'gpu0', 'gpu1', 'ssd'].includes(t.key) ? '' : `<button type="button" class="mini" data-rm="${i}">Remove</button>`}</td></tr>`).join('');
  root.querySelectorAll('#th-rows input').forEach((inp) => inp.addEventListener('change', () => {
    const t = thresholds[Number(inp.dataset.i)];
    t[inp.dataset.f] = inp.type === 'checkbox' ? inp.checked : Number(inp.value);
  }));
  root.querySelectorAll('[data-rm]').forEach((b) => b.addEventListener('click', () => {
    thresholds.splice(Number(b.dataset.rm), 1);
    renderThresholds();
  }));
  const used = new Set(thresholds.map((t) => t.key));
  const options = Object.entries(names).filter(([id]) => !used.has(id));
  root.querySelector('#add-sensor').innerHTML = options.length
    ? options.map(([id, n]) => `<option value="${esc(id)}">${esc(n)}</option>`).join('')
    : '<option value="">No other temperature sensors</option>';
}

function add() {
  const key = root.querySelector('#add-sensor').value;
  if (!key) return;
  thresholds.push({ key, enabled: true, limit_c: 85 });
  renderThresholds();
}

async function save() {
  const err = root.querySelector('#th-err');
  try {
    thresholds = await ctx.api.put('/api/alerts/thresholds', thresholds);
    err.textContent = '';
    renderThresholds();
    ctx.toast('Alert limits saved.');
  } catch (e) {
    err.textContent = /limit_c|greater|less/.test(e.message) ? 'Limits must be between 30 and 110 °C.' : e.message;
  }
}

async function loadLog() {
  const log = await ctx.api.get('/api/alerts/log?limit=50');
  root.querySelector('#log-rows').innerHTML = log.length ? log.map((a) => `
    <tr><td>${esc(when(a.started))}</td><td>${esc(label(a.sensor_id))}</td><td class="num">${temp(a.peak)} °C</td>
      <td class="num">${isNum(a.ended) ? `${Math.max(1, Math.round(a.ended - a.started))} s` : 'ongoing'}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">No alerts yet.</td></tr>';
}
