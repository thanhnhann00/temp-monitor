"""Bundle every OS reader behind one `read()` call."""
from __future__ import annotations

import logging
from pathlib import Path

from thermo import mapping
from thermo.model import Reading, finite

log = logging.getLogger(__name__)

BYTES_PER_MB = 1024 * 1024


def build_usage(readings: list[Reading], cpu: dict, memory: dict, disk_bps: tuple[float, float],
                wifi: dict, net_bps: tuple[float, float], gpus: list[dict]) -> dict:
    """Assemble the per-device usage dict. Shared by Sources and FakeSources so shapes always match."""
    lhm_total = mapping.find(readings, "AMD Ryzen", "CPU Total", "load")
    disk = mapping.disk_view(readings)
    usage = {
        "cpu": {
            "percent": finite(lhm_total.value) if lhm_total and finite(lhm_total.value) is not None else cpu["percent"],
            "ghz": mapping.cpu_clock_ghz(readings),
            "processes": cpu["processes"],
            "threads": cpu["threads"],
            "uptime_s": cpu["uptime_s"],
            "temp_c": mapping.cpu_temp(readings),
        },
        "memory": memory,
        "disk0": {
            "active_pct": disk["active_pct"],
            "read_mbs": disk_bps[0] / BYTES_PER_MB,
            "write_mbs": disk_bps[1] / BYTES_PER_MB,
            "temp_c": disk["temp_c"],
            "label": "SSD (NVMe)",
        },
        "wifi": {**wifi, "send_kbps": net_bps[0] * 8 / 1000, "recv_kbps": net_bps[1] * 8 / 1000},
        "fans": mapping.fans(readings),
    }
    for key, vendor in (("gpu0", "AMD"), ("gpu1", "NVIDIA")):
        info = next((g for g in gpus if vendor.lower() in (g.get("name") or "").lower()), {})
        usage[key] = {**mapping.gpu_view(readings, key),
                      "driver_version": info.get("driver_version"), "driver_date": info.get("driver_date")}
    return usage


class Sources:
    def __init__(self, lib_dir: Path):
        from thermo.sources import d3dkmt, gpuinfo, system, wifi
        from thermo.sources.lhm import LhmSource, LhmUnavailable

        self._system = system
        self.lhm_error: str | None = None
        self._lhm = None
        try:
            self._lhm = LhmSource(lib_dir)
        except LhmUnavailable as exc:
            self.lhm_error = str(exc)
            log.warning("%s", exc)
        try:
            self._d3d = d3dkmt.D3dkmtTemps()
        except OSError as exc:
            log.warning("D3DKMT unavailable: %s", exc)
            self._d3d = None
        self._gpus = gpuinfo.video_controllers()
        self._wifi = wifi.WifiInfo()
        self._nic = system.wifi_nic_name()
        self._disk = system.disk_rate()
        self._net = system.net_rate(self._nic) if self._nic else None

    def read(self) -> tuple[list[Reading], dict]:
        readings: list[Reading] = []
        if self._lhm:
            readings += self._lhm.read()
        if self._d3d:
            readings += self._d3d.read()
        wifi = {**self._wifi.get(), "ipv4": self._system.ipv4(self._nic) if self._nic else None}
        usage = build_usage(
            readings, self._system.cpu_usage(), self._system.memory(), self._disk.sample(),
            wifi, self._net.sample() if self._net else (0.0, 0.0), self._gpus)
        return readings, usage
