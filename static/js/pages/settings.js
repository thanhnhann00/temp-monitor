// Settings: theme, CPU limit for the headroom gauge, port, and how to run as administrator.
import { esc } from '../fmt.js';

let root; let ctx;

export async function mount(el, c) {
  root = el; ctx = c;
  root.classList.add('cols2');
  const s = ctx.settings;
  root.innerHTML = `
    <div class="head"><div><h1>Settings</h1><p>Changes save as soon as you make them.</p></div></div>
    <div class="card">
      <h3>General</h3>
      <div class="form">
        <label class="line"><span><b>Theme</b><small>System follows your Windows setting.</small></span>
          <select class="field" id="theme"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label>
        <label class="line"><span><b>CPU limit</b><small>Used by the Thermal Headroom gauge.</small></span>
          <span><input class="field" type="number" id="cpu_limit_c" min="30" max="110" value="${esc(s.cpu_limit_c)}"> °C</span></label>
        <label class="line"><span><b>History kept for</b><small>Older temperatures are deleted automatically.</small></span><span>24 hours</span></label>
        <label class="line"><span><b>Port</b><small>Takes effect next time Thermo starts.</small></span>
          <input class="field" type="number" id="port" min="1024" max="65535" value="${esc(s.port)}"></label>
        <p class="err" id="err" role="alert"></p>
      </div>
    </div>
    <div class="card">
      <h3>Administrator mode</h3>
      <p class="muted" style="margin-top:8px;font-size:13px" id="admin-state"></p>
      <ol class="steps">
        <li>Quit Thermo (button below).</li>
        <li>Open the <b>temp-monitor</b> folder and double-click <b>start.bat</b>.</li>
        <li>Click <b>Yes</b> when Windows asks to allow changes.</li>
      </ol>
      <p class="muted" style="margin-top:10px;font-size:13px">Administrator rights let Thermo read CPU and SSD temperatures. Thermo only reads sensors and changes the Windows power mode; it never writes to the fan controller.</p>
      <button type="button" class="btn" id="quit" style="margin-top:16px">⏻ Quit monitor</button>
    </div>`;
  root.querySelector('#theme').value = s.theme;
  root.querySelector('#theme').addEventListener('change', (e) => ctx.setTheme(e.target.value).catch(showErr));
  for (const id of ['cpu_limit_c', 'port']) {
    root.querySelector(`#${id}`).addEventListener('change', async (e) => {
      try {
        ctx.settings = await ctx.api.put('/api/settings', { [id]: Number(e.target.value) });
        root.querySelector('#err').textContent = '';
      } catch (err) { showErr(err); }
    });
  }
  root.querySelector('#quit').addEventListener('click', () => ctx.confirmQuit());
  onStatus(ctx.status);
}

function showErr(e) {
  const msg = /cpu_limit_c|30|110/.test(e.message) ? 'CPU limit must be between 30 and 110 °C.'
    : /port|1024|65535/.test(e.message) ? 'Port must be between 1024 and 65535.' : e.message;
  root.querySelector('#err').textContent = msg;
}

export function onStatus(status) {
  if (!root || !status) return;
  root.querySelector('#admin-state').textContent = status.is_admin
    ? '✓ Thermo is running as administrator.'
    : 'Thermo is not running as administrator, so CPU and SSD temperatures are hidden.';
}

export function unmount() { root = null; }
