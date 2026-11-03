// App shell: sidebar, top bar, theme, banners, router and the live stream.
import * as api from './api.js';
import { esc, sensorLabel, temp, when } from './fmt.js';

const PAGES = {
  dashboard: () => import('./pages/dashboard.js'),
  performance: () => import('./pages/performance.js'),
  sensors: () => import('./pages/sensors.js'),
  history: () => import('./pages/history.js'),
  alerts: () => import('./pages/alerts.js'),
  fans: () => import('./pages/fans.js'),
  settings: () => import('./pages/settings.js'),
};
const NAV = [
  ['dashboard', '▦', 'Dashboard'], ['performance', '∿', 'Performance'], ['sensors', '◎', 'Sensors'],
  ['history', '◷', 'History'], ['alerts', '⚠', 'Alerts'], ['fans', '≋', 'Fans'],
];

const ctx = { api, status: null, settings: null, snapshot: null, toast, confirmQuit, refreshStatus };
let page = null;
let pageName = null;

// ---------- theme ----------
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}
function resolveTheme(setting) {
  let stored = null;
  try { stored = localStorage.getItem('thermo-theme'); } catch { /* storage blocked */ }
  if (setting === 'light' || setting === 'dark') return setting;
  if (stored === 'light' || stored === 'dark') return stored;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
export async function setTheme(theme) {
  // theme: 'system' | 'light' | 'dark'
  try {
    if (theme === 'system') localStorage.removeItem('thermo-theme');
    else localStorage.setItem('thermo-theme', theme);
  } catch { /* storage blocked */ }
  applyTheme(resolveTheme(theme));
  ctx.settings = await api.put('/api/settings', { theme });
}
ctx.setTheme = setTheme;
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (ctx.settings?.theme === 'system') applyTheme(resolveTheme('system'));
});

// ---------- shell ----------
function renderShell() {
  document.getElementById('app').innerHTML = `
  <div class="app">
    <aside>
      <a class="logo" href="#/dashboard"><span class="mark" aria-hidden="true">🌡</span>Thermo</a>
      <div class="sec">Menu</div>
      <nav id="nav-main">${NAV.map(([k, ic, label]) => `<a href="#/${k}" data-page="${k}"><span class="ic" aria-hidden="true">${ic}</span>${label}${k === 'sensors' ? '<span class="badge" id="sensor-count">0</span>' : ''}</a>`).join('')}</nav>
      <div class="sec">General</div>
      <nav>
        <a href="#/settings" data-page="settings"><span class="ic" aria-hidden="true">⚙</span>Settings</a>
        <button type="button" id="quit-nav"><span class="ic" aria-hidden="true">⏻</span>Quit monitor</button>
      </nav>
      <div class="promo" id="promo"></div>
    </aside>
    <div class="main">
      <div class="top">
        <label class="search"><span aria-hidden="true">⌕</span><input id="search" type="search" placeholder="Search sensor" aria-label="Search sensors"><kbd>Ctrl F</kbd></label>
        <span class="live" id="live">Connecting</span>
        <div class="sp"></div>
        <button class="toggle" id="theme-toggle" type="button" aria-label="Switch light or dark theme"><span class="l">☀ Light</span><span class="d">☾ Dark</span></button>
        <div class="bellwrap"><button class="iconbtn" id="bell" type="button" aria-label="Recent alerts" aria-expanded="false">🔔</button><div id="bell-menu"></div></div>
        <div class="who"><div class="av" aria-hidden="true">💻</div><div><b id="host">—</b><small id="model"></small></div></div>
      </div>
      <div id="banners"></div>
      <main id="page" class="board"></main>
    </div>
  </div>`;

  document.getElementById('theme-toggle').addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark').catch((e) => toast(e.message));
  });
  document.getElementById('quit-nav').addEventListener('click', confirmQuit);
  const search = document.getElementById('search');
  search.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') location.hash = `#/sensors?q=${encodeURIComponent(search.value.trim())}`;
  });
  search.addEventListener('input', () => {
    if (pageName === 'sensors') page?.onSearch?.(search.value.trim());
  });
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key.toLowerCase() === 'f') { e.preventDefault(); search.focus(); search.select(); }
  });
  document.getElementById('bell').addEventListener('click', toggleBell);
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.bellwrap')) closeBell();
  });
}

async function toggleBell() {
  const menu = document.getElementById('bell-menu');
  const btn = document.getElementById('bell');
  if (menu.innerHTML) { closeBell(); return; }
  btn.setAttribute('aria-expanded', 'true');
  const alerts = await api.get('/api/alerts/log?limit=10').catch(() => []);
  menu.innerHTML = `<div class="dropdown" role="dialog" aria-label="Recent alerts"><h4>Recent alerts</h4>${
    alerts.length ? alerts.map((a) => `<div class="item">${esc(sensorLabel(a.sensor_id))} reached ${temp(a.peak)} °C
      <small>${esc(when(a.started))}${a.ended ? ` · lasted ${Math.max(1, Math.round(a.ended - a.started))} s` : ' · still above the limit'}</small></div>`).join('')
      : '<div class="item muted">No alerts yet.</div>'}
    <div class="item"><a class="mini" href="#/alerts">Manage alerts</a></div></div>`;
}
function closeBell() {
  document.getElementById('bell-menu').innerHTML = '';
  document.getElementById('bell').setAttribute('aria-expanded', 'false');
}

function renderStatus() {
  const s = ctx.status;
  if (!s) return;
  document.getElementById('host').textContent = s.machine.host;
  document.getElementById('model').textContent = s.machine.model;
  document.getElementById('sensor-count').textContent = s.sensor_count;
  const promo = document.getElementById('promo');
  if (s.is_admin && !s.lhm_error) {
    promo.className = 'promo';
    promo.innerHTML = `<div aria-hidden="true">🛡</div><h4>Running as<br>Administrator</h4><p>All ${s.sensor_count} sensors are readable</p><a class="btn-w" href="#/sensors">Open Sensor List</a>`;
  } else {
    promo.className = 'promo warn';
    promo.innerHTML = `<div aria-hidden="true">⚠</div><h4>Restart as<br>Administrator</h4><p>CPU and SSD temperatures are hidden</p><a class="btn-w" href="#/settings">How to fix</a>`;
  }
  const banners = [];
  if (s.lhm_error) banners.push(['red', `Sensor library failed to load: ${s.lhm_error}`]);
  else if (!s.is_admin) banners.push(['red', 'Run start.bat as administrator to read CPU temperatures.']);
  if (s.store_error) banners.push(['amber', `History is paused: ${s.store_error}`]);
  document.getElementById('banners').innerHTML = banners.map(([c, t]) => `<div class="banner ${c}" role="status">${esc(t)}</div>`).join('');
  document.getElementById('banners').style.display = banners.length ? 'flex' : 'none';
  document.getElementById('banners').style.flexDirection = 'column';
  document.getElementById('banners').style.gap = '8px';
}

async function refreshStatus() {
  try {
    ctx.status = await api.get('/api/status');
    renderStatus();
    page?.onStatus?.(ctx.status);
  } catch { /* server gone; the live dot shows it */ }
}

// ---------- router ----------
async function route() {
  const [name, query] = (location.hash.replace(/^#\/?/, '') || 'dashboard').split('?');
  const key = PAGES[name] ? name : 'dashboard';
  page?.unmount?.();
  page = null;
  pageName = key;
  document.querySelectorAll('nav a').forEach((a) => a.classList.toggle('on', a.dataset.page === key));
  const root = document.getElementById('page');
  root.className = 'board';
  root.innerHTML = '';
  const mod = await PAGES[key]();
  if (pageName !== key) return; // user navigated again while loading
  page = mod;
  await mod.mount(root, ctx, new URLSearchParams(query ?? ''));
  if (ctx.snapshot) mod.onSnapshot?.(ctx.snapshot);
  const search = document.getElementById('search');
  if (key !== 'sensors') search.value = '';
}

// ---------- dialogs ----------
function toast(message) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

function confirmQuit() {
  const bg = document.createElement('div');
  bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="quit-title">
    <h3 id="quit-title">Stop monitoring?</h3>
    <p>Thermo will stop recording temperatures and sending alerts until you start it again with start.bat.</p>
    <div class="acts"><button class="btn" id="quit-cancel" type="button">Cancel</button><button class="btn pri" id="quit-ok" type="button">Quit monitor</button></div></div>`;
  document.body.appendChild(bg);
  const close = () => bg.remove();
  bg.addEventListener('click', (e) => { if (e.target === bg) close(); });
  bg.querySelector('#quit-cancel').addEventListener('click', close);
  bg.querySelector('#quit-ok').addEventListener('click', async () => {
    try {
      await api.post('/api/quit');
    } catch (e) { toast(e.message); return; }
    stopStream?.();
    document.body.innerHTML = '<div class="stopped"><div><h1>Monitor stopped</h1><p class="muted">Start it again with start.bat. You can close this tab.</p></div></div>';
  });
  bg.querySelector('#quit-ok').focus();
}

// ---------- boot ----------
let stopStream = null;
async function boot() {
  renderShell();
  [ctx.settings, ctx.status] = await Promise.all([api.get('/api/settings'), api.get('/api/status')]);
  applyTheme(resolveTheme(ctx.settings.theme));
  renderStatus();
  window.addEventListener('hashchange', route);
  await route();
  const live = document.getElementById('live');
  stopStream = api.stream((snap) => {
    ctx.snapshot = snap;
    page?.onSnapshot?.(snap);
  }, (state) => {
    live.className = state === 'live' ? 'live on' : 'live';
    live.textContent = state === 'live' ? 'Live' : 'Reconnecting';
  });
  setInterval(refreshStatus, 10_000);
}

boot().catch((e) => {
  document.getElementById('app').innerHTML = `<div class="stopped"><div><h1>Thermo isn't responding</h1><p class="muted">${esc(e.message)}</p></div></div>`;
});
