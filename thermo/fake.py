"""Stand-ins for hardware, used by `--fake` and by tests. Values follow the mockups."""
from __future__ import annotations

import random

from thermo.model import Reading
from thermo.sources import build_usage

_GPUS = [
    {"name": "AMD Radeon(TM) Graphics", "driver_version": "31.0.21024.2004", "driver_date": "8/23/2023"},
    {"name": "NVIDIA GeForce RTX 3050 Laptop GPU", "driver_version": "32.0.15.6094", "driver_date": "8/14/2024"},
]


class FakeSources:
    lhm_error: str | None = None

    def __init__(self, no_fans: bool = False, seed: int = 1):
        self._rng = random.Random(seed)
        self._no_fans = no_fans
        self._state = {"cpu_t": 67.0, "cpu_load": 19.0, "gpu0_t": 54.0, "gpu0_load": 10.0, "ssd_t": 44.0}

    def _walk(self, key: str, step: float, lo: float, hi: float) -> float:
        v = min(hi, max(lo, self._state[key] + self._rng.uniform(-step, step)))
        self._state[key] = v
        return round(v, 1)

    def read(self) -> tuple[list[Reading], dict]:
        cpu_t = self._walk("cpu_t", 1.5, 55, 92)
        cpu_load = self._walk("cpu_load", 6, 3, 95)
        gpu0_t = self._walk("gpu0_t", 1.0, 45, 75)
        gpu0_load = self._walk("gpu0_load", 4, 0, 60)
        ssd_t = self._walk("ssd_t", 0.3, 40, 52)
        cpu, amd, nv = "AMD Ryzen 7 6800HS Creator Edition", "AMD Radeon(TM) Graphics", "NVIDIA GeForce RTX 3050 Laptop GPU"
        readings = [
            Reading("/amdcpu/0/temperature/2", cpu, "Core (Tctl/Tdie)", "temperature", cpu_t),
            Reading("/amdcpu/0/load/0", cpu, "CPU Total", "load", cpu_load),
            *[Reading(f"/amdcpu/0/clock/{i}", cpu, f"Core #{i}", "clock", 3150.0 + self._rng.uniform(-80, 80))
              for i in range(1, 9)],
            Reading("/amdcpu/0/power/0", cpu, "Package", "power", 28.0),
            Reading("/d3dkmt/1/temperature", amd, "GPU Temperature", "temperature", gpu0_t),
            Reading("/gpu-amd/0/load/0", amd, "D3D 3D", "load", gpu0_load),
            Reading("/gpu-amd/0/smalldata/0", amd, "D3D Dedicated Memory Used", "smalldata", 1331.0),
            Reading("/gpu-amd/0/smalldata/1", amd, "D3D Dedicated Memory Total", "smalldata", 2048.0),
            Reading("/gpu-amd/0/smalldata/2", amd, "D3D Shared Memory Used", "smalldata", 717.0),
            Reading("/gpu-amd/0/smalldata/3", amd, "D3D Shared Memory Total", "smalldata", 6963.0),
            Reading("/gpu-nvidia/0/temperature/0", nv, "GPU Core", "temperature", None),  # asleep
            Reading("/gpu-nvidia/0/load/0", nv, "GPU Core", "load", 0.0),
            Reading("/gpu-nvidia/0/smalldata/0", nv, "D3D Dedicated Memory Used", "smalldata", 0.0),
            Reading("/gpu-nvidia/0/smalldata/1", nv, "GPU Memory Total", "smalldata", 4096.0),
            Reading("/gpu-nvidia/0/smalldata/2", nv, "D3D Shared Memory Used", "smalldata", 0.2),
            Reading("/gpu-nvidia/0/power/0", nv, "GPU Package", "power", 0.0),
            Reading("/nvme/0/temperature/0", "SSD 1TB", "Composite Temperature", "temperature", ssd_t),
            Reading("/nvme/0/load/0", "SSD 1TB", "Total Activity", "load", round(self._rng.uniform(0, 4), 1)),
            Reading("/battery/0/level/0", "AP16L5J", "Charge Level", "level", 82.0),
        ]
        if not self._no_fans:
            readings += [
                Reading("/lpc/0/fan/0", "Lenovo EC", "CPU Fan", "fan", round(1800 + cpu_t * 20)),
                Reading("/lpc/0/fan/1", "Lenovo EC", "GPU Fan", "fan", round(1700 + gpu0_t * 22)),
            ]
        cpu_info = {"percent": cpu_load, "processes": 287, "threads": 3912, "uptime_s": 5048.0}
        memory = {"used_gb": 11.9, "total_gb": 13.7, "available_gb": 1.8, "percent": 87.0, "pagefile_used_gb": 10.6}
        wifi = {"connected": True, "ssid": "HomeNet", "signal_pct": 92, "ipv4": "192.168.1.24"}
        disk_bps = (self._rng.uniform(0, 3e6), self._rng.uniform(0, 1.5e6))
        net_bps = (self._rng.uniform(5e3, 12e3), self._rng.uniform(0.5e3, 2e3))
        return readings, build_usage(readings, cpu_info, memory, disk_bps, wifi, net_bps, _GPUS)
