# Thermo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web app (`http://127.0.0.1:8000`) for the user's Lenovo IdeaPad 5 Pro 16ARH7 that shows live temperatures, Task Manager-style usage, 24 h temperature history, overheat alerts, fan speeds and a cooling-mode control.

**Architecture:** One Python process. A sampler thread reads LibreHardwareMonitor (via pythonnet), psutil, `netsh` and WMI once per second and builds a `Snapshot`; downstream modules (ring buffers, SQLite store, alerts, cooling) only ever see `Snapshot`s, so they're tested without hardware. FastAPI serves a vanilla-JS single-page app, REST endpoints and an SSE stream.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, pythonnet, psutil, winotify, wmi, SQLite (stdlib), pytest, httpx; vanilla JS + Chart.js 4.4.x (vendored); Plus Jakarta Sans (vendored).

**Spec:** `temp-monitor/docs/superpowers/specs/2026-11-03-temp-monitor-design.md`. Where module names differ from spec section 5 (`history.py` → `store.py`, which also holds the alert log and cooling events; new `mapping.py` and `fake.py`), this plan wins. Mockups: `temp-monitor/docs/mockups/` (`dashboard.html`, `perf.html`, `fans.html`, `style.css`, and their PNGs).

## Global Constraints

- Windows 11 only; Python 3.11; project root is `temp-monitor/`. All paths below are relative to it.
- Server binds `127.0.0.1` only; default port `8000`, overridable with `--port` and the `port` setting.
- Sample loop: 1 s. Temperatures persisted every 2 s. Rows older than 24 h pruned every 10 min.
- Alerts: defaults CPU 90 °C, GPU 0 85 °C, GPU 1 85 °C, SSD 70 °C; hysteresis 3 °C; at most one toast per sensor per 300 s.
- Smart Cooling: off by default; defaults up 85 °C for 30 s, down 70 °C for 120 s; manual change pauses it for 600 s.
- Cooling overlay GUIDs: quiet `961cc777-2547-4f9d-8174-7d86181b8a7a`, balanced `00000000-0000-0000-0000-000000000000`, performance `ded574b5-45a0-4f42-8737-46345c09c238`.
- No direct fan RPM writes or EC access, ever.
- Mutating endpoints require header `X-Thermo-Token` matching the per-process token injected into `index.html`.
- UI: brand orange, tokens copied from `docs/mockups/style.css` (muted light `#6b645e`, dark `#a6a19c`); smallest text 12 px; status chips stay green / yellow / red in both themes.
- No CDN or network access at runtime: Chart.js and fonts are vendored in `static/vendor/`.
- Downloads (LHM NuGet package, Chart.js, font files) and `pip install` need the user's OK at the moment they happen.
- Cooling-mode switching on the real laptop is only exercised with the user present.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A sensor returns `None`/NaN** (RTX 3050 asleep, SSD briefly unreadable): nothing crashes, nothing is written to SQLite, the UI shows "Sleeping" / "—". → tests in Task 3 (mapping), Task 6 (store), Task 10 (sampler).
2. **Laptop sleeps and resumes** (a multi-minute gap between ticks): Smart Cooling must not treat the gap as "sustained" heat, and alerts must not double-fire. → tests in Task 8 (gap > 5 s resets timers) and Task 7.
3. **Several browser tabs, or a tab closed mid-stream:** a slow or dead SSE client never blocks the sampler. → test in Task 10 (full subscriber queue drops oldest).
4. **`settings.json` missing, empty or hand-edited into invalid JSON:** app starts with defaults and rewrites the file. → test in Task 9.
5. **Bad values sent to PUT endpoints** (threshold `-5`, `"abc"`, `500`; unknown cooling mode): rejected with 422, nothing saved. → tests in Task 11.

---

## File Structure

```
temp-monitor/
  .gitignore                data/, lib/*.dll, __pycache__/, .pytest_cache/
  requirements.txt          runtime deps, pinned
  requirements-dev.txt      pytest, httpx
  pyproject.toml            pytest config (testpaths = tests)
  start.bat                 elevate + run + open browser
  tools/
    fetch_vendor.ps1        downloads LHM NuGet → lib/, Chart.js + fonts → static/vendor/
    discover_sensors.py     dumps every LHM sensor to tests/fixtures/lhm_dump.json
  thermo/
    __init__.py
    __main__.py             CLI entry; wiring
    model.py                Reading, Snapshot
    mapping.py              raw readings → headline temps, GPU / disk / fan views
    sources/__init__.py     Sources (real) — bundles all OS readers
    sources/lhm.py          LhmSource
    sources/system.py       psutil readers + rate counters
    sources/wifi.py         netsh parser + cached reader
    sources/gpuinfo.py      WMI video controllers
    fake.py                 FakeSources (mockup values) for --fake and tests
    buffers.py              RingBuffer, downsample
    store.py                SQLite: samples, alert_log, cooling_events
    alerts.py               AlertEngine, notifiers
    cooling.py              PowerApi, Cooling, SmartCooling
    settings.py             Settings load/save
    sampler.py              Sampler loop + pub/sub
    server.py               create_app()
  static/
    index.html              shell, {{TOKEN}} placeholder
    css/tokens.css  css/app.css
    js/app.js  js/api.js  js/charts.js
    js/pages/{dashboard,performance,fans,sensors,history,alerts,settings}.js
    vendor/chart.umd.min.js  vendor/fonts/*.woff2
  tests/
    fixtures/lhm_dump.json  fixtures/netsh_*.txt
    test_*.py               one per thermo module
```

---

### Task 1: Project skeleton, model, git

**Files:**
- Create: `.gitignore`, `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `thermo/__init__.py`, `thermo/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class Reading:
      id: str; hardware: str; name: str; kind: str; value: float | None
  # kind ∈ {"temperature","load","clock","fan","power","data","smalldata","throughput"}

  @dataclass
  class Snapshot:
      ts: float
      readings: list[Reading]
      usage: dict[str, dict]            # keys: cpu, memory, disk0, wifi, gpu0, gpu1
      headline: dict[str, float | None] # keys: cpu, gpu0, gpu1, ssd
      cooling_mode: str                 # quiet | balanced | performance | unknown
      def to_json(self) -> dict: ...    # NaN → None; readings as list of dicts
  ```

- [ ] **Step 1:** `git init` in `temp-monitor/`, add `.gitignore` (contents above).
- [ ] **Step 2:** Write `requirements.txt` pinning `fastapi`, `uvicorn`, `pythonnet`, `psutil`, `winotify`, `wmi` to current releases; `requirements-dev.txt` with `pytest`, `httpx`. Ask the user before running `pip install -r requirements.txt -r requirements-dev.txt`.
- [ ] **Step 3: Write failing test** `test_snapshot_to_json_replaces_nan_with_none`: a `Snapshot` with one `Reading(value=float("nan"))` and `headline={"gpu1": float("nan")}` → `to_json()["readings"][0]["value"] is None` and `to_json()["headline"]["gpu1"] is None`; the result passes `json.dumps(..., allow_nan=False)`.
- [ ] **Step 4:** Run `pytest tests/test_model.py -v` → FAIL (ImportError).
- [ ] **Step 5:** Implement `thermo/model.py`.
- [ ] **Step 6:** Run `pytest tests/test_model.py -v` → PASS.
- [ ] **Step 7:** Commit `chore: project skeleton and data model`. Also commit the `docs/` folder (spec, plan, mockups).

---

### Task 2: LibreHardwareMonitor source + sensor discovery

**Files:**
- Create: `tools/fetch_vendor.ps1`, `thermo/sources/lhm.py`, `tools/discover_sensors.py`
- Create (generated): `tests/fixtures/lhm_dump.json`

**Interfaces:**
- Produces:
  ```python
  class LhmUnavailable(Exception): ...
  class LhmSource:
      def __init__(self, dll_dir: Path): ...   # raises LhmUnavailable with a readable message
      def read(self) -> list[Reading]: ...     # calls Update() on every hardware + subhardware
      def close(self) -> None: ...
  ```
  `Reading.id` = LHM `Identifier.ToString()`; `kind` = `SensorType` lower-cased; `hardware` = hardware `Name`.

- [ ] **Step 1:** Write `tools/fetch_vendor.ps1`: downloads the `LibreHardwareMonitorLib` NuGet package (pin a specific release; record it in the script), extracts the `net472` DLLs (`LibreHardwareMonitorLib.dll`, `HidSharp.dll`) into `lib/`; downloads `chart.umd.min.js` 4.4.x into `static/vendor/` and Plus Jakarta Sans 400/500/600/700 woff2 into `static/vendor/fonts/`. Show the user the URLs and sizes and get their OK before running it.
- [ ] **Step 2:** Implement `LhmSource`: `pythonnet.load("netfx")`, `clr.AddReference(str(dll_dir / "LibreHardwareMonitorLib"))`, `Computer(IsCpuEnabled=True, IsGpuEnabled=True, IsStorageEnabled=True, IsMotherboardEnabled=True, IsControllerEnabled=True, IsBatteryEnabled=True, IsNetworkEnabled=False, IsMemoryEnabled=True)`, `Open()`. Wrap any load/open exception in `LhmUnavailable`.
- [ ] **Step 3:** Write `tools/discover_sensors.py`: opens `LhmSource(Path("lib"))`, reads three times 1 s apart, and writes the last read as a JSON list of `Reading` dicts to `tests/fixtures/lhm_dump.json`. It also prints a table (hardware, name, kind, value).
- [ ] **Step 4:** Ask the user to run, from an **admin** terminal: `python tools/discover_sensors.py`. Then ask them to compare the printed table with LibreHardwareMonitor's app or HWiNFO. Record in the commit message: whether any `fan` sensors exist, and the exact names for CPU package temp, both GPU temps / loads / D3D memory, SSD temp / activity.
- [ ] **Step 5:** Commit `feat: LibreHardwareMonitor source and sensor discovery` (the fixture included; `lib/` ignored).

No automated test: this is the only module that needs real hardware, and `discover_sensors.py` is its check.

---

### Task 3: Sensor mapping

**Files:**
- Create: `thermo/mapping.py`
- Test: `tests/test_mapping.py` (uses `tests/fixtures/lhm_dump.json`)

**Interfaces:**
- Consumes: `Reading` (Task 1).
- Produces:
  ```python
  def find(readings: list[Reading], hardware: str, name: str, kind: str) -> Reading | None
      # hardware: case-insensitive substring match; name, kind: exact
  def headline_temps(readings) -> dict[str, float | None]   # keys cpu, gpu0, gpu1, ssd
  def gpu_view(readings, which: Literal["gpu0","gpu1"]) -> dict
      # {name, load_pct, temp_c, dedicated_used_gb, dedicated_total_gb, shared_used_gb, shared_total_gb, fan_rpm, power_w, sleeping: bool}
  def cpu_clock_ghz(readings) -> float | None        # mean of "Core #n" clock sensors / 1000
  def disk_view(readings) -> dict                    # {temp_c, active_pct}
  def fans(readings) -> list[dict]                   # [{id, name, rpm}] for every kind=="fan"
  ```
  `gpu0` = the AMD hardware, `gpu1` = the NVIDIA hardware (spec 5.2). Use the sensor names recorded in Task 2.

- [ ] **Step 1: Write failing tests:**
  - `test_headline_from_fixture`: every key present; `cpu`, `gpu0`, `ssd` are floats between 20 and 110.
  - `test_gpu1_sleeping_when_temp_missing`: the fixture with the NVIDIA temperature reading's value set to `None` → `headline_temps(...)["gpu1"] is None` and `gpu_view(..., "gpu1")["sleeping"] is True`.
  - `test_nan_treated_as_missing`: same as above, with `float("nan")`.
  - `test_fans_empty_when_no_fan_sensors`: readings filtered to non-fan kinds → `fans(...) == []`.
  - `test_cpu_clock_mean`: two fake `Core #1/#2` clock readings, 3000 and 3300 → `3.15`.
- [ ] **Step 2:** Run `pytest tests/test_mapping.py -v` → FAIL.
- [ ] **Step 3:** Implement `thermo/mapping.py`.
- [ ] **Step 4:** Run `pytest tests/test_mapping.py -v` → PASS.
- [ ] **Step 5:** Commit `feat: map raw sensors to headline values`.

---

### Task 4: System, Wi-Fi and GPU-info sources; Sources bundle; FakeSources

**Files:**
- Create: `thermo/sources/system.py`, `thermo/sources/wifi.py`, `thermo/sources/gpuinfo.py`, `thermo/sources/__init__.py`, `thermo/fake.py`
- Create: `tests/fixtures/netsh_connected.txt`, `tests/fixtures/netsh_disconnected.txt`
- Test: `tests/test_system.py`, `tests/test_wifi.py`, `tests/test_fake.py`

**Interfaces:**
- Consumes: `Reading`, `mapping.*`.
- Produces:
  ```python
  # system.py
  def cpu_usage() -> dict            # {percent, processes, threads, uptime_s}
  def memory() -> dict               # {used_gb, total_gb, available_gb, percent, pagefile_used_gb}
  class RateCounter:                 # generic bytes→rate
      def __init__(self, read_totals: Callable[[], tuple[int, int]], clock=time.monotonic): ...
      def sample(self) -> tuple[float, float]   # bytes/s for (a, b); (0.0, 0.0) on first call
  def disk_rate() -> RateCounter     # psutil.disk_io_counters(perdisk=True)["PhysicalDrive0"] read/write
  def net_rate(nic: str) -> RateCounter   # psutil.net_io_counters(pernic=True)[nic] sent/recv
  def wifi_nic_name() -> str | None  # first psutil interface whose name starts with "Wi-Fi"
  def ipv4(nic: str) -> str | None
  # wifi.py
  def parse_netsh(text: str) -> dict # {connected: bool, ssid: str | None, signal_pct: int | None}
  class WifiInfo:
      def __init__(self, ttl_s: float = 10, run: Callable[[], str] = _run_netsh, clock=time.monotonic): ...
      def get(self) -> dict          # cached parse_netsh result; on run() error → {connected: False, ...}
  # gpuinfo.py
  def video_controllers() -> list[dict]   # [{name, driver_version, driver_date: "M/D/YYYY"}], read once
  # sources/__init__.py
  class Sources:
      def __init__(self, lib_dir: Path): ...   # LhmSource failure is kept, not raised
      lhm_error: str | None
      def read(self) -> tuple[list[Reading], dict[str, dict]]   # (readings, usage)
  # fake.py
  class FakeSources:                 # same interface; values from the mockups, gently varying, seeded
      def __init__(self, no_fans: bool = False, seed: int = 1): ...
      lhm_error: str | None = None
      def read(self) -> tuple[list[Reading], dict[str, dict]]
  ```
  `usage` field names (used by Tasks 10, 13–15):
  - `cpu`: `{percent, ghz, processes, threads, uptime_s, temp_c}`
  - `memory`: as `memory()`
  - `disk0`: `{active_pct, read_mbs, write_mbs, temp_c, label: "SSD (NVMe)"}`
  - `wifi`: `{connected, ssid, signal_pct, ipv4, send_kbps, recv_kbps}`
  - `gpu0` / `gpu1`: `gpu_view(...)` plus `driver_version`, `driver_date`
  - top-level extra `usage["fans"] = fans(readings)`

- [ ] **Step 1:** Save sample `netsh wlan show interfaces` output (from the user's machine, with SSID and BSSID replaced by `TestNet` / zeros) as `netsh_connected.txt`; a disconnected sample as `netsh_disconnected.txt`.
- [ ] **Step 2: Write failing tests:**
  - `test_parse_connected`: → `{"connected": True, "ssid": "TestNet", "signal_pct": <value in fixture>}`.
  - `test_parse_disconnected`: → `connected False`, `ssid None`, `signal_pct None`.
  - `test_parse_locale_tolerant`: the connected text with every label except `SSID` translated to German → `signal_pct` is still found (the value of a key/value line ending in `%`).
  - `test_wifi_cache_ttl`: a fake `run` counter called once across two `get()` calls within 10 s, and twice after the fake clock advances 11 s.
  - `test_wifi_run_error`: `run` raises `OSError` → `get()["connected"] is False`.
  - `test_rate_counter`: totals (0,0) then (2_000_000, 1_000_000) after 2 fake seconds → `(1_000_000.0, 500_000.0)`.
  - `test_rate_counter_counter_reset`: totals go down → `(0.0, 0.0)`, not negative.
  - `test_fake_sources_shape`: `FakeSources().read()` usage has keys `cpu, memory, disk0, wifi, gpu0, gpu1, fans` with the field names above, and `gpu1["sleeping"] is True`.
- [ ] **Step 3:** Run `pytest tests/test_wifi.py tests/test_system.py tests/test_fake.py -v` → FAIL.
- [ ] **Step 4:** Implement the five modules. `Sources.read()` builds `usage` from `mapping` + `system` + `WifiInfo` + `video_controllers()` (matched by name contains "AMD" / "NVIDIA").
- [ ] **Step 5:** Run the same tests → PASS.
- [ ] **Step 6:** Commit `feat: system, wifi and gpu info sources`.

---

### Task 5: Ring buffers

**Files:**
- Create: `thermo/buffers.py`
- Test: `tests/test_buffers.py`

**Interfaces:**
- Produces:
  ```python
  def downsample(points: list[tuple[float, float]], max_points: int) -> list[tuple[float, float]]
      # equal-width buckets by index; each bucket → (mean ts, mean value); unchanged if len <= max_points
  class RingBuffer:
      def __init__(self, capacity: int = 3600): ...
      def append(self, ts: float, value: float | None) -> None   # None stored as gap, skipped on read
      def since(self, ts: float) -> list[tuple[float, float]]
  class UsageBuffers:
      def add(self, snap: Snapshot) -> None    # one RingBuffer per series key below
      def series(self, device: str, range_s: int, now: float, max_points: int = 300) -> dict[str, list]
  ```
  Series keys per device: `cpu: percent`; `memory: percent`; `disk0: active_pct, read_mbs, write_mbs`; `wifi: send_kbps, recv_kbps`; `gpu0/gpu1: load_pct, dedicated_used_gb, shared_used_gb`; `fans: <fan id>` rpm; `temps: cpu` (for the Fans chart).

- [ ] **Step 1: Write failing tests:** `test_ring_wraps` (capacity 3, 5 appends → last 3); `test_since_filters`; `test_none_skipped`; `test_downsample_300` (3600 points → exactly 300, first/last ts preserved within one bucket); `test_usage_series_range` (feed 120 snapshots 1 s apart, `series("cpu", 60, now)` → 60 points).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: in-memory usage ring buffers`.

---

### Task 6: SQLite store

**Files:**
- Create: `thermo/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Reading`.
- Produces:
  ```python
  class Store:
      def __init__(self, path: Path | str): ...      # ":memory:" allowed; creates the 3 tables from spec 5.4; WAL mode
      def add_temps(self, ts: float, readings: list[Reading]) -> int   # kind=="temperature" and finite value only; returns rows written
      def prune(self, now: float, keep_s: int = 86_400) -> int
      def series(self, sensor_ids: list[str], since: float, max_points: int = 500) -> dict[str, list[tuple[float, float]]]
      def hourly(self, sensor_id: str, hours: int, now: float) -> list[dict]   # [{hour_ts, avg}] oldest first, missing hours omitted
      def export_csv(self, since: float) -> str      # header "timestamp,sensor_id,value_c"; ISO-8601 local time
      def sample_count(self) -> int
      def alert_start(self, sensor_id: str, ts: float, value: float) -> int
      def alert_update(self, alert_id: int, value: float) -> None   # raises peak
      def alert_end(self, alert_id: int, ts: float) -> None
      def alerts(self, limit: int = 10) -> list[dict]   # newest first: {id, sensor_id, started, ended, peak}
      def log_cooling(self, ts: float, mode: str, source: str) -> None
      def cooling_events(self, since: float) -> list[dict]
  ```
  The store is shared across threads: open with `check_same_thread=False` and guard every call with one `threading.Lock`.

- [ ] **Step 1: Write failing tests:** `test_only_finite_temperatures_saved` (temperature 50, temperature `None`, temperature NaN, load 30 → 1 row); `test_prune_24h`; `test_series_downsampled` (1000 rows → ≤ 500); `test_hourly_averages` (two hours of data → 2 entries, correct means); `test_csv_header_and_rows`; `test_alert_lifecycle` (start 91 → update 93 → end; `alerts()[0]["peak"] == 93` and `ended` set); `test_cooling_events_since`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: sqlite store for history, alerts and cooling events`.

---

### Task 7: Alerts

**Files:**
- Create: `thermo/alerts.py`
- Test: `tests/test_alerts.py`

**Interfaces:**
- Consumes: `Store` (Task 6).
- Produces:
  ```python
  @dataclass
  class Threshold:
      key: str; enabled: bool; limit_c: float     # key ∈ headline keys or any temperature Reading.id
  DEFAULT_THRESHOLDS = [Threshold("cpu", True, 90), Threshold("gpu0", True, 85),
                        Threshold("gpu1", True, 85), Threshold("ssd", True, 70)]
  class Notifier(Protocol):
      def notify(self, title: str, body: str) -> None
  class WinotifyNotifier: ...     # app_id "Thermo"; failures logged, never raised
  class AlertEngine:
      HYSTERESIS_C = 3.0; COOLDOWN_S = 300
      def __init__(self, thresholds: list[Threshold], notifier: Notifier, store: Store): ...
      def set_thresholds(self, thresholds: list[Threshold]) -> None
      def check(self, values: dict[str, float | None], now: float) -> list[str]   # keys that started an alert this call
  ```
  Toast copy: title `"{label} is {value:.0f} °C"`, body `"Above your {limit:.0f} °C alert limit."`, with labels CPU / GPU 0 (Radeon) / GPU 1 (RTX 3050) / SSD.

- [ ] **Step 1: Write failing tests** (fake notifier records calls; `Store(":memory:")`):
  - `test_starts_at_threshold`: cpu 90 → one toast, one alert row.
  - `test_hysteresis`: 91, 88, 91 → still one alert (88 > 87); 86.9 → alert ended.
  - `test_cooldown_300s`: start, end, restart at +100 s → a second alert row but no second toast; restart at +301 s → toast.
  - `test_none_value_ignored`: `{"gpu1": None}` → no alert; an open gpu1 alert stays open.
  - `test_disabled_threshold`.
  - `test_resume_gap_does_not_double_fire`: alert open at t=0; next check at t=+900 s still above → no new toast, same alert row.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: temperature alerts with hysteresis and cooldown`.

---

### Task 8: Cooling mode + Smart Cooling

**Files:**
- Create: `thermo/cooling.py`
- Test: `tests/test_cooling.py`

**Interfaces:**
- Consumes: `Store`.
- Produces:
  ```python
  MODES: dict[str, str]   # name → overlay GUID (Global Constraints)
  class PowerApi(Protocol):
      def get_overlay(self) -> str            # GUID string, lower-case
      def set_overlay(self, guid: str) -> None   # raises OSError(winerror) on failure
      def balanced_plan_active(self) -> bool
  class WinPowerApi: ...   # ctypes powrprof: PowerGetEffectiveOverlayScheme, PowerSetActiveOverlayScheme, PowerGetActiveScheme vs 381b4222-f694-41f0-9685-ff5bb260df2e
  class Cooling:
      def __init__(self, api: PowerApi, store: Store): ...
      def mode(self) -> str                   # quiet | balanced | performance | unknown
      def available(self) -> bool             # == api.balanced_plan_active()
      def set_mode(self, mode: str, source: str, now: float) -> None   # source app | smart; logs event
      def poll(self, now: float) -> str       # reads mode; logs source "external" if it changed since last poll/set
  @dataclass
  class SmartRules:
      enabled: bool = False; up_c: float = 85; up_s: float = 30; down_c: float = 70; down_s: float = 120
  class SmartCooling:
      MANUAL_PAUSE_S = 600; MAX_GAP_S = 5
      def __init__(self, cooling: Cooling, rules: SmartRules): ...
      def set_rules(self, rules: SmartRules) -> None
      def on_manual_change(self, now: float) -> None
      def step(self, cpu_c: float | None, now: float) -> str | None   # returns new mode if it switched
  ```
  Smart Cooling state machine: remembers the mode it switched away from and restores that mode on the way down. A gap of more than `MAX_GAP_S` between steps, or `cpu_c is None`, resets the "sustained since" timers. An `external` mode change counts as manual too (`Cooling.poll` → sampler calls `on_manual_change`).

Also add `class FakePowerApi` (implements `PowerApi`; settable `guid`, `balanced=True`, optional `fail_with: OSError | None`) to `thermo/fake.py`. It's used by these tests, by Tasks 10–11, and by `--fake`.

- [ ] **Step 1: Write failing tests** (`FakePowerApi`; `Store(":memory:")`):
  - `test_set_mode_sets_guid_and_logs`: `set_mode("performance","app",0)` → api GUID `ded574b5-…`, one `cooling_events` row with source `app`.
  - `test_poll_detects_external`: the fake api's GUID changed behind the app's back → `poll()` returns `"quiet"` and logs source `external`.
  - `test_unknown_guid`: → `mode() == "unknown"`.
  - `test_smart_up_after_30s`: from balanced, cpu 86 every 1 s; at t=29 still balanced, at t=30 → performance.
  - `test_smart_restores_previous_mode`: start quiet → up → cpu 69 for 120 s → back to quiet (not balanced).
  - `test_smart_gap_resets`: cpu 86 at t=0..20, then next step at t=200 (gap) → no switch at t=200; switches only after another 30 s.
  - `test_manual_pauses_600s`: `on_manual_change(0)`, cpu 95 from t=0 → no switch before t=600; switches at t≥630.
  - `test_disabled_does_nothing`.
  - `test_set_mode_failure_raises`: fake `set_overlay` raises `OSError(5)` → `set_mode` raises, mode unchanged, nothing logged.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: cooling mode control and smart cooling`.

---

### Task 9: Settings

**Files:**
- Create: `thermo/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `Threshold`, `DEFAULT_THRESHOLDS`, `SmartRules`.
- Produces:
  ```python
  @dataclass
  class Settings:
      theme: str = "system"            # system | light | dark
      cpu_limit_c: float = 90          # headroom gauge
      port: int = 8000
      thresholds: list[Threshold] = field(default_factory=lambda: list(DEFAULT_THRESHOLDS))
      smart: SmartRules = field(default_factory=SmartRules)
  def load(path: Path) -> Settings     # missing / empty / invalid JSON / wrong types → defaults, then save()
  def save(path: Path, s: Settings) -> None   # atomic: write tmp + os.replace
  ```

- [ ] **Step 1: Write failing tests:** `test_missing_file_gives_defaults_and_creates_it`; `test_roundtrip`; `test_corrupt_json_gives_defaults` (`"{not json"`); `test_partial_file_fills_defaults` (`{"theme":"dark"}` → theme dark, everything else default); `test_wrong_type_field_reset` (`{"port":"abc"}` → 8000).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: settings file`.

---

### Task 10: Sampler

**Files:**
- Create: `thermo/sampler.py`
- Test: `tests/test_sampler.py`

**Interfaces:**
- Consumes: `Sources`/`FakeSources`, `mapping.headline_temps`, `UsageBuffers`, `Store`, `AlertEngine`, `Cooling`, `SmartCooling`.
- Produces:
  ```python
  class Sampler:
      PERSIST_EVERY = 2; PRUNE_EVERY_S = 600
      def __init__(self, sources, store, alerts, cooling, smart, buffers, interval_s: float = 1.0): ...
      paused: bool
      started_at: float
      latest: Snapshot | None
      minmax: dict[str, tuple[float, float]]   # Reading.id → (min, max) of finite values since start
      store_error: str | None                  # last SQLite error; cleared after the next successful write
      def tick(self, now: float) -> Snapshot   # one full cycle; never raises (errors logged, partial snapshot returned)
      def start(self) -> None; def stop(self) -> None   # daemon thread calling tick() every interval_s
      def subscribe(self) -> queue.Queue[Snapshot]       # maxsize 5
      def unsubscribe(self, q) -> None
  ```
  Order inside `tick`: `sources.read()` → headline → `cooling.poll()` (an external change calls `smart.on_manual_change`) → `smart.step(headline["cpu"])` → `buffers.add` → if not paused and tick count is even, `store.add_temps` → `alerts.check(headline + every temperature Reading.id)` → prune if due → publish to every subscriber (when a queue is full, drop its oldest item, then put).

- [ ] **Step 1: Write failing tests** (`FakeSources`, `Store(":memory:")`, fake notifier, `FakePowerApi`):
  - `test_tick_builds_snapshot`: headline keys and `usage` keys present; `cooling_mode` set.
  - `test_persist_every_second_tick`: 4 ticks → `store.sample_count()` equals 2 × the number of finite temperature readings.
  - `test_paused_skips_store_only`: `paused=True` → no rows, but subscribers still get snapshots.
  - `test_sleeping_gpu_no_crash_no_row`: FakeSources with gpu1 temperature `None` → tick ok; no rows for that sensor id.
  - `test_slow_subscriber_never_blocks`: subscribe and never read; 20 ticks finish; the queue holds the 5 newest snapshots.
  - `test_minmax_since_start`: values 50, 70, 60 for one id across three ticks → `minmax[id] == (50, 70)`; `None` values ignored.
  - `test_store_error_flagged`: a store whose `add_temps` raises `sqlite3.OperationalError` → tick ok, `store_error` set; next successful write clears it.
  - `test_source_exception_is_contained`: sources.read raises once → `tick` returns a snapshot with empty readings and doesn't raise.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: sampler loop with pub/sub`.

---

### Task 11: HTTP API + SSE

**Files:**
- Create: `thermo/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  ```python
  @dataclass
  class AppState:
      sampler: Sampler; store: Store; buffers: UsageBuffers; cooling: Cooling; smart: SmartCooling
      alerts: AlertEngine; settings: Settings; settings_path: Path; token: str
      is_admin: bool; lhm_error: str | None; machine: dict   # {host, model, cpu, gpu}
      request_quit: Callable[[], None]
  def create_app(state: AppState) -> FastAPI
  ```
  Routes (spec 5.3 plus the cooling routes): `GET /` (serves `static/index.html` with `{{TOKEN}}` replaced), static mount `/static`, `GET /api/stream` (SSE: `event: snapshot\ndata: <json>\n\n`; heartbeat comment every 15 s; unsubscribe on disconnect), `GET /api/usage?device&range∈{60,300,3600}`, `GET /api/history?range∈{1h,6h,24h}&sensors=a,b`, `GET /api/history/hourly?sensor&hours`, `GET /api/history.csv`, `GET/PUT /api/settings`, `GET/PUT /api/alerts/thresholds`, `GET /api/alerts/log?limit=10`, `GET /api/sensors` → latest readings each with `min`/`max` from `sampler.minmax`, `GET /api/status` → `{is_admin, lhm_error, store_error, sensor_count, uptime_s, samples_saved, paused, machine, cooling_available}`, `POST /api/monitor/pause|resume`, `POST /api/quit`, `GET/PUT /api/cooling/mode`, `GET/PUT /api/cooling/smart`, `GET /api/cooling/events?since`.
  Validation (pydantic): `limit_c` 30–110; smart `up_c`/`down_c` 30–110 with `down_c < up_c`; `up_s`/`down_s` 5–3600; mode ∈ MODES; theme ∈ {system, light, dark}; port 1024–65535. PUT/POST without a valid `X-Thermo-Token` → 403. Mode PUT when `cooling.available()` is false → 409; `OSError` → 502 with `{"error": "Windows error <code>"}`. A mode PUT calls `smart.on_manual_change`. Settings/threshold/smart PUTs save `settings.json` and push the change into the live objects.

- [ ] **Step 1: Write failing tests** (TestClient over an `AppState` built from fakes; `sampler.tick()` called a few times by hand, thread not started):
  - `test_index_injects_token`; `test_status_fields`; `test_sensors_have_minmax`; `test_usage_60`; `test_history_csv_header`.
  - `test_put_requires_token` (403 without it, 200 with it).
  - `test_threshold_validation`: `limit_c` −5, `"abc"`, 500 → 422; settings file unchanged.
  - `test_cooling_mode_put`: `"performance"` → 200 and the fake api GUID changes; `"turbo"` → 422; cooling unavailable → 409; api raising `OSError(5)` → 502.
  - `test_smart_put_validation`: `down_c` ≥ `up_c` → 422.
  - `test_stream_sends_snapshot`: open `/api/stream`, call `sampler.tick()`, read one event, parse its JSON, check the `headline` key.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: http api and sse stream`.

---

### Task 12: Entry point and launcher

**Files:**
- Create: `thermo/__main__.py`, `start.bat`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `create_app`, `AppState`, all components.
- Produces: `python -m thermo [--port N] [--fake] [--no-browser] [--data DIR]`. `--fake` uses `FakeSources(no_fans=os.environ.get("THERMO_FAKE_NO_FANS") == "1")` and `FakePowerApi()` (for UI work and screenshots without admin). Port precedence: `--port`, then `settings.port`. Real mode: `Sources(Path("lib"))`, `WinPowerApi`, `WinotifyNotifier`, `data/thermo.db`, `data/settings.json`, rotating log `data/thermo.log` (1 MB × 3). `is_admin` = `ctypes.windll.shell32.IsUserAnAdmin()`. uvicorn `Server` on `127.0.0.1`; `request_quit` sets `server.should_exit = True`. Opens the browser 1 s after startup unless `--no-browser`. Port in use → print `Port 8000 is already in use. Start with --port 8001 or change it in Settings.` and exit 1.
  `start.bat`: if not elevated, re-launch itself via `powershell Start-Process -Verb RunAs`; then `cd /d %~dp0` and `python -m thermo`.

- [ ] **Step 1: Write failing tests:** `test_build_state_fake` (`build_state(args_fake)` returns an `AppState` whose sampler ticks cleanly); `test_port_in_use_message` (bind a socket to a free port, then call `main(["--fake","--no-browser","--port",str(port)])` → `SystemExit(1)`, message on stderr).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `build_state(args) -> AppState` and `main(argv) -> None`. **Step 4:** Run → PASS.
- [ ] **Step 5:** Manual: `python -m thermo --fake` → `curl http://127.0.0.1:8000/api/status` returns JSON.
- [ ] **Step 6:** Commit `feat: entry point and admin launcher`.

---

### Task 13: Front-end shell, theme and Dashboard page

**Files:**
- Create: `static/index.html`, `static/css/tokens.css`, `static/css/app.css`, `static/js/app.js`, `static/js/api.js`, `static/js/charts.js`, `static/js/pages/dashboard.js`

**Interfaces:**
- Consumes: the HTTP API (Task 11) and `Snapshot.to_json()` shape (Task 1 / Task 4 field names).
- Produces:
  - `api.js`: `get(path)`, `put(path, body)`, `post(path)` (add the token from `<meta name="thermo-token">`); `stream(onSnapshot, onState)`, which uses `EventSource` and reports `"live"` / `"reconnecting"`.
  - `app.js`: hash router `#/dashboard` (default), `#/performance[?device=gpu0]`, `#/fans`, `#/sensors[?q=]`, `#/history`, `#/alerts`, `#/settings`. Each page module exports `mount(root, ctx)` / `unmount()` / `onSnapshot(snap)`; `ctx = {api, status, settings}`.
  - `charts.js`: `areaChart(canvas, opts)`, `sparkline(canvas)`, `pillChart(el, hourly, bands)`, `gauge(svg, value, max)`, all built on Chart.js except the pill chart and gauge, which are DOM/SVG as in the mockup.
  - Theme: `<html data-theme>`. On first load it follows `prefers-color-scheme` when the setting is `system`; the toggle writes `localStorage["thermo-theme"]` and PUTs `/api/settings`.
  - Shell: sidebar (Dashboard, Performance, Sensors + live count badge, History, Alerts, Fans · Settings, Quit monitor), top bar (search → `#/sensors?q=`, Light/Dark toggle, bell dropdown of `/api/alerts/log?limit=10`, machine name + model), admin card / "Restart as admin" warning card, red banner when `!is_admin || lhm_error`, amber banner "History is paused: <store_error>" when `store_error`, "● Live" dot that goes grey while reconnecting.
  - Dashboard: exactly `docs/mockups/dashboard.html`, wired up to live data, with the spec 3 changes (subtitle "updated every second", "+ Set Alert" → `#/alerts`, ↗ → `#/performance?device=…`, "Cooling mode" button → `#/fans`). Pill chart from `/api/history/hourly?sensor=cpu&hours=7` with bands <60 striped, 60–74, 75–84, 85+. Headroom = `settings.cpu_limit_c − cpu`. Pause / Stop on the timer card → `/api/monitor/pause|resume` and the quit confirmation.

- [ ] **Step 1:** Copy the tokens from `docs/mockups/style.css` into `tokens.css`; move the layout rules into `app.css`, raising every font size below 12 px to 12 px. `@font-face` uses `static/vendor/fonts`.
- [ ] **Step 2:** Implement the shell, `api.js`, `charts.js` and `dashboard.js`.
- [ ] **Step 3: Verify:** run `python -m thermo --fake --no-browser`, then use Playwright at 1440×900 to screenshot `#/dashboard` in light and dark. Compare side by side with `docs/mockups/dashboard-light.png` / `dashboard-dark.png`; layout, colours and card order should match. Check the browser console has no errors, the toggle switches theme without reload, and reloading keeps the theme.
- [ ] **Step 4:** Commit `feat: app shell, theme toggle and dashboard`.

---

### Task 14: Performance page

**Files:**
- Create: `static/js/pages/performance.js`
- Modify: `static/css/app.css` (performance rules from `docs/mockups/perf.html`)

**Interfaces:**
- Consumes: `usage.*` field names (Task 4), `/api/usage` (Task 11), `charts.js` (Task 13).
- Produces: the page in `docs/mockups/perf.html`: device list (CPU, Memory, Disk 0 (C:), Wi-Fi, GPU 0, GPU 1) with sparklines fed from a 60-point client buffer; selected device highlighted; detail panel per the spec 4 table; range 60 s (client buffer) / 5 min / 1 hr (`/api/usage`). Wi-Fi chart has two lines (send, receive). GPU 1 shows "Sleeping" when `sleeping`. `?device=` preselects a device.

- [ ] **Step 1:** Implement.
- [ ] **Step 2: Verify:** with `--fake`, take Playwright screenshots of each of the six devices in light mode, plus GPU 0 in dark mode. Compare GPU 0 with `performance-light.png` / `performance-dark.png`. Switching ranges re-renders without console errors, and the charts move every second.
- [ ] **Step 3:** Commit `feat: performance page`.

---

### Task 15: Fans page

**Files:**
- Create: `static/js/pages/fans.js`
- Modify: `static/css/app.css` (rules from `docs/mockups/fans.html`)

**Interfaces:**
- Consumes: `snapshot.cooling_mode`, `usage.fans`, `usage.gpu1.sleeping`, `/api/cooling/*`, `/api/usage?device=fans|temps&range=300`, `status.cooling_available`.
- Produces: the page in `docs/mockups/fans.html`. Clicking a mode PUTs it right away and highlights it; on error the highlight snaps back and an in-page toast shows the error text. Smart Cooling switch plus four editable numbers (saved on blur, with the 422 message shown inline). A fan card per `usage.fans` entry (bar against the max RPM seen this session); "This laptop doesn't report fan speed" when the list is empty. RTX 3050 card shows "Sleeping". The temperature-vs-fan chart has dashed vertical markers from `/api/cooling/events`. When `cooling_available` is false, the mode buttons are disabled with the note "Cooling modes need the Balanced power plan."

- [ ] **Step 1:** Implement.
- [ ] **Step 2: Verify:** with `--fake`, screenshot light and dark and compare with `fans-light.png` / `fans-dark.png`. Clicking each mode updates the fake mode (check via `GET /api/cooling/mode`). Entering `down_c` 90 shows the inline error. Run once with FakeSources fans emptied (`--fake` accepts env `THERMO_FAKE_NO_FANS=1`) and check the "doesn't report fan speed" state.
- [ ] **Step 3:** Commit `feat: fans and cooling page`.

---

### Task 16: Sensors, History, Alerts, Settings pages

**Files:**
- Create: `static/js/pages/sensors.js`, `history.js`, `alerts.js`, `settings.js`
- Modify: `static/css/app.css`

**Interfaces:**
- Consumes: `snapshot.readings`, `/api/sensors`, `/api/history`, `/api/alerts/*`, `/api/settings`, `/api/quit`.
- Produces (spec 4, items 3, 4, 6, 7):
  - Sensors: a table from `/api/sensors`, refreshed from each snapshot (hardware, name, type, current, min, max since the app started), a text filter (from `?q=`), and a type filter.
  - History: a line chart of cpu / gpu0 / gpu1 / ssd with 1 h / 6 h / 24 h, per-sensor toggles, and an Export CSV button.
  - Alerts: a threshold row per temperature sensor (enable + °C) and a log table (time, sensor, peak, duration).
  - Settings: theme select, CPU limit, retention (read-only "24 hours"), port ("takes effect on next start").
  - Quit confirmation → `POST /api/quit` → a "Monitor stopped" screen.
  Every page uses the same card, typography and token styles as the mockups.

- [ ] **Step 1:** Implement.
- [ ] **Step 2: Verify:** with `--fake`, screenshot each page in both themes. Check that the filter narrows the table, an invalid threshold shows the 422 message inline, Export CSV downloads a file whose first line is `timestamp,sensor_id,value_c`, and Quit stops the server.
- [ ] **Step 3:** Commit `feat: sensors, history, alerts and settings pages`.

---

### Task 17: On-laptop acceptance (user present)

**Files:** none (fixes found here go back to the owning task's files with a test where possible).

- [ ] **Step 1:** User runs `tools/fetch_vendor.ps1` (if not yet run) and `start.bat`. Check: UAC prompt, browser opens in under 10 s, no red banner (criterion 1).
- [ ] **Step 2:** With LibreHardwareMonitor's app open side by side, CPU package / GPU 0 / GPU 1 / SSD are within ±2 °C (criterion 2).
- [ ] **Step 3:** With Task Manager open side by side, the CPU / memory / disk / Wi-Fi / GPU numbers move together (criterion 3).
- [ ] **Step 4:** Light and dark both match the mockups; the toggle is remembered across restarts (criterion 4).
- [ ] **Step 5:** User temporarily sets the CPU threshold to 60 °C and runs a CPU load. Expect exactly one toast, and none again within 5 minutes; then restore 90 (criterion 5).
- [ ] **Step 6:** Quit and restart. History charts still show the earlier data (criterion 6).
- [ ] **Step 7:** Cooling: user picks each mode in the app and checks Windows Settings → Power mode matches; presses Fn + Q and checks the app follows within 2 s; runs a load in Quiet, then Performance, and notes whether fan noise / RPM changes (criterion 7). If the Lenovo profile doesn't follow, apply the spec 6 fallback: relabel the card "Windows power mode".
- [ ] **Step 8:** Record the results in `docs/acceptance-2026-11-xx.md` and commit `docs: on-laptop acceptance results`.
