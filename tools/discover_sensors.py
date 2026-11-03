"""Dump every LibreHardwareMonitor sensor on this machine.

Run from the temp-monitor folder in an administrator terminal:
    python tools\\discover_sensors.py
Writes tests/fixtures/lhm_dump.json and prints a table.
"""
from __future__ import annotations

import ctypes
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from thermo.sources.lhm import LhmSource  # noqa: E402


def main() -> None:
    if not ctypes.windll.shell32.IsUserAnAdmin():
        print("Warning: not running as administrator; CPU and some other sensors will be missing.\n")
    src = LhmSource(ROOT / "lib")
    readings = []
    for _ in range(3):
        readings = src.read()
        time.sleep(1)
    src.close()

    out = ROOT / "tests" / "fixtures" / "lhm_dump.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(r) for r in readings], indent=1), encoding="utf-8")

    print(f"{'HARDWARE':<34} {'NAME':<34} {'KIND':<12} VALUE")
    for r in readings:
        value = "—" if r.value is None else f"{r.value:.1f}"
        print(f"{r.hardware[:33]:<34} {r.name[:33]:<34} {r.kind:<12} {value}")
    print(f"\n{len(readings)} sensors written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
