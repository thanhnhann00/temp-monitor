# On-laptop acceptance — 2026-11-03

Machine: Lenovo IdeaPad 5 Pro 16ARH7 (82SN), Ryzen 7 6800HS, Radeon 680M, RTX 3050 Laptop, Samsung MZVL2512HCJQ NVMe.
Started with `start.bat` (elevated). Build: branch `build/thermo`.

| # | Criterion | Result |
|---|-----------|--------|
| 1 | start.bat elevates, server starts, no banner | Pass — `is_admin: true`, `lhm_error: null`, 133 sensors |
| 2 | Temperatures match LibreHardwareMonitor | Pass (spot check) — CPU Tctl 65 °C, NVMe 44 °C, RTX 3050 46 °C, Radeon 56 °C (D3DKMT, same source as Task Manager) |
| 3 | Usage tracks Task Manager | Pass (spot check) — CPU 29 % @ 2.30 GHz, disk active 3.6 %, memory and Wi-Fi live |
| 4 | Light/dark match mockups, toggle remembered | Pass — verified with Playwright screenshots in fake mode; same UI in real mode |
| 5 | One toast per alert per 5 min | Covered by automated tests; not triggered on hardware |
| 6 | History survives restart | Not yet exercised on hardware (covered by SQLite store tests) |
| 7 | Cooling modes | Pass — app switched balanced → performance → quiet (logged as `app`); the user heard the fans ramp up in Performance and quiet down in Quiet. Fn + Q → app sync not yet tried. |

Findings:
- LibreHardwareMonitor exposes **no fan sensors** on this model, even elevated; Windows `Win32_Fan` and D3DKMT report no RPM either. The Fans page shows the "doesn't report fan speed" state; mode control works.
- The user's own `tools/discover_sensors.py` run appears to have been non-elevated (CPU 0 °C, no NVMe); the admin sensor list was taken from the running app instead and saved as `tests/fixtures/lhm_dump.json`.
