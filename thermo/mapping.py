"""Turn raw sensor readings into the values the UI shows."""
from __future__ import annotations

from statistics import mean
from typing import Literal

from thermo.model import Reading, finite

GPU_HARDWARE = {"gpu0": "AMD Radeon", "gpu1": "NVIDIA"}
STORAGE_PREFIXES = ("/nvme/", "/ssd/", "/hdd/", "/storage/")
MB_PER_GB = 1024


def find(readings: list[Reading], hardware: str, name: str, kind: str) -> Reading | None:
    hw = hardware.lower()
    for r in readings:
        if r.kind == kind and r.name == name and hw in r.hardware.lower():
            return r
    return None


def _value(readings, hardware, name, kind) -> float | None:
    r = find(readings, hardware, name, kind)
    return finite(r.value) if r else None


def _temp(value: float | None) -> float | None:
    # LHM reports 0 °C for sensors it cannot read (e.g. CPU without admin rights).
    return value if value is not None and value > 0 else None


def _gb(mb: float | None) -> float | None:
    return None if mb is None else mb / MB_PER_GB


def cpu_temp(readings) -> float | None:
    return _temp(_value(readings, "AMD Ryzen", "Core (Tctl/Tdie)", "temperature"))


def gpu_temp(readings, which: Literal["gpu0", "gpu1"]) -> float | None:
    hw = GPU_HARDWARE[which]
    return _temp(_value(readings, hw, "GPU Core", "temperature")) or _temp(
        _value(readings, hw, "GPU Temperature", "temperature"))


def _storage(readings) -> list[Reading]:
    return [r for r in readings if r.id.startswith(STORAGE_PREFIXES)]


def disk_view(readings) -> dict:
    temp = active = None
    for r in _storage(readings):
        if r.kind == "temperature" and temp is None and r.name in ("Composite Temperature", "Temperature"):
            temp = _temp(finite(r.value))
        elif r.kind == "load" and r.name == "Total Activity" and active is None:
            active = finite(r.value)
    return {"temp_c": temp, "active_pct": active}


def headline_temps(readings) -> dict[str, float | None]:
    return {
        "cpu": cpu_temp(readings),
        "gpu0": gpu_temp(readings, "gpu0"),
        "gpu1": gpu_temp(readings, "gpu1"),
        "ssd": disk_view(readings)["temp_c"],
    }


def _system_shared_total(readings) -> float | None:
    for r in readings:
        if r.name == "D3D Shared Memory Total" and finite(r.value):
            return finite(r.value)
    return None


def gpu_view(readings, which: Literal["gpu0", "gpu1"]) -> dict:
    hw = GPU_HARDWARE[which]
    hw_reading = next((r for r in readings if hw.lower() in r.hardware.lower()), None)
    load = _value(readings, hw, "D3D 3D", "load") if which == "gpu0" else _value(readings, hw, "GPU Core", "load")
    dedicated_total = (_value(readings, hw, "D3D Dedicated Memory Total", "smalldata")
                       or _value(readings, hw, "GPU Memory Total", "smalldata"))
    shared_total = _value(readings, hw, "D3D Shared Memory Total", "smalldata") or _system_shared_total(readings)
    fan = next((finite(r.value) for r in readings if r.kind == "fan" and hw.lower() in r.hardware.lower()), None)
    temp = gpu_temp(readings, which)
    return {
        "name": hw_reading.hardware if hw_reading else None,
        "load_pct": load,
        "temp_c": temp,
        "dedicated_used_gb": _gb(_value(readings, hw, "D3D Dedicated Memory Used", "smalldata")),
        "dedicated_total_gb": _gb(dedicated_total),
        "shared_used_gb": _gb(_value(readings, hw, "D3D Shared Memory Used", "smalldata")),
        "shared_total_gb": _gb(shared_total),
        "fan_rpm": fan,
        "power_w": _value(readings, hw, "GPU Package", "power"),
        "sleeping": temp is None,
    }


def cpu_clock_ghz(readings) -> float | None:
    clocks = [finite(r.value) for r in readings
              if r.kind == "clock" and r.name.startswith("Core #") and "AMD Ryzen" in r.hardware]
    clocks = [c for c in clocks if c]
    return round(mean(clocks) / 1000, 3) if clocks else None


def fans(readings) -> list[dict]:
    return [{"id": r.id, "name": r.name, "rpm": finite(r.value)} for r in readings if r.kind == "fan"]
