# Thermo — PC Temperature & Performance Monitor — Design

**Date:** 2026-11-03
**Status:** Awaiting review
**Mockups:** `../../mockups/` — `dashboard-*.png`, `performance-*.png`, `fans-*.png` in light and dark (static HTML sources alongside)
**Machine:** Lenovo IdeaPad 5 Pro 16ARH7 (model 82SN, BIOS J4CN36WW)

## 1. Goal

A local web dashboard for one Windows 11 laptop (Ryzen 7 6800HS, Radeon 680M iGPU, RTX 3050 Laptop GPU, NVMe SSD) that shows:

- live temperatures for CPU, both GPUs, SSD, battery and other exposed sensors
- Task Manager-style usage for CPU, Memory, Disk 0, Wi-Fi, GPU 0 and GPU 1
- 24 hours of temperature history
- Windows notifications when a temperature crosses a threshold
- fan speeds (where the laptop exposes them) and a cooling-mode control: Quiet / Balanced / Performance, plus an optional automatic switch based on CPU temperature

It runs only on this machine, opens at `http://127.0.0.1:8000`, and is started with administrator rights.

**Success criteria**

1. Running `start.bat` shows a UAC prompt, starts the server, and opens the dashboard in the default browser within 10 seconds.
2. CPU package, GPU 0, GPU 1 and SSD temperatures are within ±2 °C of what LibreHardwareMonitor's own app shows.
3. CPU, memory, disk, Wi-Fi and GPU usage values track Task Manager (same direction, within a few percent).
4. The UI matches the approved mockups in both light and dark themes, and the theme toggle switches instantly and is remembered.
5. Crossing a threshold produces exactly one Windows notification per sensor per 5 minutes.
6. Restarting the app keeps the last 24 h of temperature history.
7. Picking a cooling mode in the app changes the Windows power mode within 1 s, and a change made elsewhere (Fn + Q, Windows Settings, Lenovo Vantage) shows up in the app within 2 s.

## 2. Non-goals

- Setting fan RPM directly or custom fan curves. This IdeaPad's fans are driven by the laptop's embedded controller; Lenovo only exposes them through its cooling modes. Writing to the controller directly is undocumented for this model and could leave the laptop overheating, so the app controls fans only through the cooling mode (section 4, Fans).
- Remote access, multiple machines, user accounts.
- Packaging as an installer/.exe (a `.bat` launcher is enough).
- Auto-start on Windows login (can be a later add-on).
- Mobile layout. The page targets a desktop browser window ≥ 1280 px wide; narrower windows stack cards into fewer columns but are not specifically designed.

## 3. Changes from the mockups

The mockups contain a few placeholders that this spec resolves:

| Mockup element | Decision |
|---|---|
| Sidebar "Help" | Removed. "Fans" stays and opens the Fans page. |
| "+ Fan Curve" button on Dashboard | Becomes "Cooling mode" and opens the Fans page. |
| Search box | Filters the Sensors page by name; pressing Enter on any page jumps there. |
| Bell icon | Opens a dropdown of the 10 most recent alerts. |
| "Monitoring For" pause / stop | Pause = stop writing history (live view continues). Stop = same as "Quit monitor". |
| GPU "DirectX version" / "Physical location" | Dropped. Driver version and date are kept. |
| Dashboard subtitle "updated every 2 seconds" | Reads "updated every second"; the whole app runs on one 1 s sample loop. |
| "+ Set Alert" button | Opens the Alerts page. |
| ↗ on each temperature card | Opens the Performance page with that device selected (SSD → Disk 0). |
| "14" sensor badge, "All 14 sensors are readable" | Live sensor count from `/api/status`. |
| Top-bar machine subtitle | Shows the laptop model (IdeaPad 5 Pro 16ARH7), as in the Fans mockup. |

## 4. Pages

All pages share the sidebar, top bar (search, theme toggle, bell, machine name + CPU/GPU model).

1. **Dashboard** — exactly the dashboard mockup: four temperature cards (CPU package highlighted), CPU temperature pill chart (hourly average, last 7 h; striped = below 60 °C, light orange 60–74, orange 75–84, dark 85+), Last Alert card, All Sensors list (top 5), Fans & Load card, Thermal Headroom gauge (CPU limit minus current CPU temp), Monitoring For timer. "Export CSV" downloads the last 24 h of history.
2. **Performance** — the performance mockup. Left: six device cards with 60-point sparklines. Right: detail panel for the selected device. Range switch: 60 s / 5 min / 1 hr. Per-device detail:

   | Device | Main chart | Extra charts | Stat tiles |
   |---|---|---|---|
   | CPU | Total usage % | — | Usage, speed (avg core clock), processes, threads, uptime, package temp |
   | Memory | Used % | — | In use, available, total, page file used |
   | Disk 0 (C:) | Active time % | Read / write MB/s | Active %, read, write, temp |
   | Wi-Fi | Send + receive Kbps (two lines) | — | Send, receive, SSID, signal %, IPv4 |
   | GPU 0 / GPU 1 | 3D / core load % | Dedicated memory, shared memory | Usage, GPU memory, dedicated, shared, temp; GPU 1 also fan RPM and power W; driver version + date |

3. **Sensors** — table of every sensor LibreHardwareMonitor reports: hardware, name, type (temperature / load / clock / fan / power / data), current, min, max since start. Filterable by search box and type.
4. **History** — one line chart of the four headline temperatures with 1 h / 6 h / 24 h range, plus per-sensor toggles.
5. **Fans** — the fans mockup.
   - **Cooling Mode:** three choices, Quiet / Balanced / Performance, mapped to the Windows power modes Best power efficiency / Balanced / Best performance. On this laptop, the Lenovo Intelligent Thermal Solution service (`LITSSVC`) is expected to follow the Windows power mode, which is the same mode Fn + Q cycles. The selected mode is highlighted; changes made outside the app are picked up within 2 s.
   - **Smart Cooling** (off by default): when on, switch to Performance once CPU ≥ *X* °C for *N* s (defaults 85 °C, 30 s), and back to the mode you had before once CPU < *Y* °C for *M* s (defaults 70 °C, 120 s). All four numbers are editable. A manual mode change pauses Smart Cooling for 10 minutes, so it never fights you.
   - **Fan cards:** one per fan sensor found, with RPM, a bar against the highest RPM seen, and the matching temperature. The RTX 3050 card shows "Sleeping" when the GPU is powered down. If no fan RPM sensor is found, the cards are replaced by "This laptop doesn't report fan speed", and the mode controls still work.
   - **Temperature vs Fan Speed:** CPU temp and fan RPM over the last 5 min, with dashed markers where the cooling mode changed.
6. **Alerts** — threshold editor (one row per temperature sensor, enable + °C value) and the alert log (time, sensor, peak value, duration).
7. **Settings** — theme (System / Light / Dark), CPU limit used by the headroom gauge, history retention (fixed 24 h, shown read-only), port number (takes effect on next start).

"Quit monitor" asks for confirmation, then shuts the server down and shows a "Monitor stopped" page.

## 5. Architecture

Single Python 3.11 process. A background sampler thread reads all sources once per second and publishes a snapshot; the FastAPI app serves the UI, REST endpoints and a Server-Sent Events stream.

```
temp-monitor/
  start.bat                 elevate via UAC, run `python -m thermo`, open browser
  requirements.txt
  thermo/
    __main__.py             parse args, start sampler + uvicorn on 127.0.0.1:8000
    sources/
      lhm.py                LibreHardwareMonitor via pythonnet → list[Reading]
      system.py             psutil: CPU %, processes, threads, uptime, memory, disk IO, net IO
      wifi.py               `netsh wlan show interfaces` → SSID, signal (cached 10 s)
      gpuinfo.py            WMI Win32_VideoController → name, driver version/date (read once)
    model.py                Reading, Snapshot, DeviceUsage dataclasses
    sampler.py              1 s loop: gather sources → Snapshot; feed buffers, history, alerts
    buffers.py              in-memory ring buffers for usage series (3600 points × series)
    history.py              SQLite temperature history (writes every 2 s, prunes > 24 h)
    alerts.py               threshold check, hysteresis, cooldown, toast, alert log
    cooling.py              read/set Windows power mode (powrprof overlay API) + Smart Cooling rules
    settings.py             JSON settings file load/save with defaults
    server.py               FastAPI routes + SSE
  static/
    index.html              app shell; hash routes #/dashboard, #/performance, …
    css/tokens.css          light/dark tokens (from mockup style.css)
    css/app.css
    js/app.js               router, SSE client, theme toggle
    js/pages/*.js           one module per page
    vendor/chart.umd.min.js Chart.js 4.4.x, vendored (works offline)
    vendor/fonts/           Plus Jakarta Sans woff2, vendored
  lib/LibreHardwareMonitorLib.dll  (+ HidSharp.dll dependency)
  data/                     thermo.db, settings.json (created at runtime, git-ignored)
  tests/
```

Each module has one job and is testable without hardware: `sources/*` are the only code that touches the OS; everything downstream takes `Snapshot` objects.

### 5.1 Data model

```python
@dataclass
class Reading:
    id: str          # stable LHM identifier, e.g. "/amdcpu/0/temperature/2"
    hardware: str    # "AMD Ryzen 7 6800HS"
    name: str        # "Core (Tctl/Tdie)"
    kind: str        # temperature | load | clock | fan | power | data | throughput
    value: float | None

@dataclass
class Snapshot:
    ts: float
    readings: list[Reading]
    usage: dict[str, dict]   # "cpu", "memory", "disk0", "wifi", "gpu0", "gpu1" → device fields
```

### 5.2 Headline sensor mapping

The first implementation step is a discovery script that dumps every LHM sensor on this laptop, so the exact names below are confirmed before they're hard-coded. Expected:

| Card | LHM hardware / sensor |
|---|---|
| CPU Package | AMD CPU / `Core (Tctl/Tdie)` temperature |
| CPU speed | AMD CPU / average of `Core #n` clocks (psutil's `cpu_freq` reports a fixed base clock on Windows) |
| GPU 0 (Radeon) | AMD GPU / `GPU Core` temp, `D3D 3D` load, `D3D Dedicated/Shared Memory Used` |
| GPU 1 (RTX 3050) | NVIDIA GPU / `GPU Core` temp, `GPU Core` load, `D3D Dedicated/Shared Memory Used`, fan, power |
| NVMe SSD | Storage / `Composite Temperature`, `Total Activity` load |
| Battery | Battery sensors if LHM exposes them; card hidden otherwise |
| Fans | Any LHM `fan` sensor (EC, motherboard or GPU). Checked in the discovery step; Win32_Fan on this laptop reports no speed, so it isn't used. |

GPU 0 / GPU 1 numbering follows Task Manager: the Radeon is GPU 0, the RTX 3050 is GPU 1. When the RTX 3050 is idle in hybrid mode, it may report no temperature; its card then shows "Sleeping" instead of a value.

### 5.3 Live updates

- `GET /api/stream` — SSE, one `snapshot` event per second containing current readings and usage. The browser keeps its own 60-point rolling buffer from this stream for the 60 s view.
- `GET /api/usage?device=gpu0&range=300|3600` — usage series from ring buffers for the 5 min / 1 hr views (downsampled to ≤ 300 points).
- `GET /api/history?range=1h|6h|24h&sensors=…` — temperature series from SQLite (downsampled to ≤ 500 points per sensor).
- `GET /api/history/hourly?sensor=cpu&hours=7` — hourly averages for the pill chart.
- `GET /api/history.csv` — 24 h export.
- `GET/PUT /api/settings`, `GET/PUT /api/alerts/thresholds`, `GET /api/alerts/log`.
- `GET /api/status` — admin yes/no, LHM loaded yes/no, sensor count, uptime, samples saved, paused flag.
- `POST /api/monitor/pause`, `POST /api/monitor/resume`, `POST /api/quit`.
- `GET/PUT /api/cooling/mode` (`quiet` | `balanced` | `performance`), `GET/PUT /api/cooling/smart` (enabled + four rule numbers), `GET /api/cooling/events` (mode changes for the chart markers). The current mode is also included in every SSE snapshot.

### 5.3a Cooling mode

`cooling.py` calls `PowerGetEffectiveOverlayScheme` / `PowerSetActiveOverlayScheme` from `powrprof.dll` via `ctypes`. Overlay GUIDs: Best power efficiency `961cc777-2547-4f9d-8174-7d86181b8a7a` (confirmed as the current mode on this laptop), Balanced `00000000-0000-0000-0000-000000000000`, Best performance `ded574b5-45a0-4f42-8737-46345c09c238`. These modes apply while the Balanced power plan is active (it is); if another plan is active, the control is disabled with a note explaining why.

Smart Cooling runs inside the sampler loop, using the same CPU package reading as the Dashboard. Every mode change, from the app, Smart Cooling or outside, is recorded in a `cooling_events` table (`ts`, `mode`, `source`).

Mutating endpoints require a per-session token embedded in the served HTML, so other sites in the browser can't trigger them.

### 5.4 Storage

SQLite `data/thermo.db`:

```sql
CREATE TABLE samples (ts INTEGER NOT NULL, sensor_id TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX samples_sensor_ts ON samples(sensor_id, ts);
CREATE TABLE alert_log (id INTEGER PRIMARY KEY, sensor_id TEXT, started INTEGER, ended INTEGER, peak REAL);
CREATE TABLE cooling_events (ts INTEGER NOT NULL, mode TEXT NOT NULL, source TEXT NOT NULL);  -- source: app | smart | external
```

Only temperature readings are persisted, every 2 s. Pruning of rows older than 24 h runs every 10 min. Expected size: ~15 sensors × 43,200 rows ≈ 650 k rows, ≈ 30 MB. Usage series stay in memory only (lost on restart, by design).

### 5.5 Alerts

- Defaults: CPU 90 °C, GPU 0 85 °C, GPU 1 85 °C, SSD 70 °C; others off.
- An alert starts when value ≥ threshold, and ends when value < threshold − 3 °C (hysteresis).
- A Windows toast (`winotify`) fires when an alert starts, at most once per sensor per 5 min.
- Each alert is written to `alert_log` with its peak value and duration; the Dashboard's Last Alert card and the bell dropdown read from it.

### 5.6 Theme

CSS tokens on `:root` (light) and `[data-theme="dark"]`, taken from the mockup's `style.css`. Secondary text uses the `--muted` tokens, adjusted for WCAG AA contrast (light `#6b645e`, dark `#a6a19c`). The real build uses 12 px as the smallest text size; the mockups' 10–11 px labels are bumped up. On first load the theme follows Windows (`prefers-color-scheme`); clicking the toggle stores the choice in `localStorage` and in `settings.json`. Semantic status colours stay green / yellow / red in both themes; brand colour is orange.

## 6. Error handling

| Situation | Behaviour |
|---|---|
| Not running as admin | Red banner: "Run start.bat as administrator to read CPU temperatures." psutil usage and NVIDIA data still work; cards without data show "—". The sidebar admin card turns into a "Restart as admin" warning. |
| `LibreHardwareMonitorLib.dll` missing or fails to load | Same banner with the specific error; app keeps running with psutil data only. |
| A sensor disappears (e.g. dGPU sleeps) | Card shows "Sleeping" / "—"; no crash; history simply has a gap. |
| `netsh` fails / no Wi-Fi | Wi-Fi card shows "Not connected". |
| SSE connection drops | Browser auto-reconnects; the "● Live" indicator turns grey until it's back. |
| Port 8000 in use | Start fails with a clear message; port is configurable in settings or via `--port`. |
| Setting the cooling mode fails | The selection snaps back to the real current mode and a toast in the page shows the Windows error code. |
| Laptop doesn't follow the Windows power mode | Found during manual testing (section 7). If it doesn't, the Cooling Mode card is relabelled "Windows power mode", and the risk in section 9 applies. |
| SQLite write error | Logged; live view continues; banner says history is paused. |

Errors are logged to `data/thermo.log` (rotating, 1 MB × 3).

## 7. Testing

- **Unit (pytest, no hardware, no admin):** `history` (insert, prune, downsample, hourly averages), `alerts` (threshold, hysteresis, cooldown — with a fake clock and fake notifier), `buffers` (ring wrap, downsample), `settings` (defaults, round-trip), `wifi` (parse sample `netsh` output, including non-English-safe fallbacks), sensor mapping (from a recorded LHM dump fixture), `cooling` Smart Cooling rules (enter / exit timing, restore previous mode, 10 min pause after a manual change — fake clock and fake power API).
- **API (FastAPI TestClient):** every endpoint with a fake sampler feeding canned snapshots; token check on mutating routes.
- **Manual on the laptop:** compare against LibreHardwareMonitor and Task Manager side by side (success criteria 2–3); run a stress load to trigger an alert (criterion 5); restart and confirm history (criterion 6); screenshot both themes against the mockups (criterion 4); switch each cooling mode in the app and confirm Windows Settings → Power mode matches, press Fn + Q and confirm the app follows, and listen for / watch the fan RPM change under load in Quiet vs Performance (criterion 7). Mode switching is only tested with you present.

## 8. Dependencies and downloads

These need your OK when implementation starts:

- **Download:** `LibreHardwareMonitorLib` (and its `HidSharp` dependency) from the official NuGet package, pinned to a specific release, placed in `lib/`.
- **Download:** Chart.js 4.4.x UMD build and Plus Jakarta Sans font files, vendored into `static/vendor/`.
- **pip install:** `fastapi`, `uvicorn`, `pythonnet`, `psutil`, `winotify`, `wmi`; dev: `pytest`, `httpx`.

## 9. Open risks

- **pythonnet + LHM on .NET Framework:** expected to work on Windows 11 (built-in .NET Framework 4.8). If it doesn't, the fallback is to run LibreHardwareMonitor's own app and read its JSON web server instead; only `sources/lhm.py` changes.
- **Fan RPM on this IdeaPad:** LibreHardwareMonitor often can't read fan speed on IdeaPad embedded controllers, and Windows' own `Win32_Fan` reports none here. The discovery step will show whether any fan sensor exists. If not, the fan cards show "This laptop doesn't report fan speed", and the Dashboard's Fans & Load card shows only power and load. Reading the embedded controller directly is out of scope for the same safety reason as fan control.
- **Cooling modes on this IdeaPad:** the assumption is that Lenovo's thermal service follows the Windows power mode, as it does on many recent IdeaPads. If testing shows it doesn't, the control still changes the Windows power mode (which affects CPU speed and heat), but not the Lenovo fan profile directly.
- **Antivirus:** LHM loads a kernel driver for sensor access; some antivirus tools flag it. If that happens, you'll need to allow it.
