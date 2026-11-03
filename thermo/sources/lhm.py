"""LibreHardwareMonitor reader (via pythonnet on .NET Framework)."""
from __future__ import annotations

import threading
from pathlib import Path

from thermo.model import Reading, finite


class LhmUnavailable(Exception):
    pass


class LhmSource:
    def __init__(self, dll_dir: Path):
        dll = Path(dll_dir) / "LibreHardwareMonitorLib.dll"
        if not dll.exists():
            raise LhmUnavailable(f"{dll} is missing. Run tools\\fetch_vendor.ps1 first.")
        try:
            import pythonnet

            try:
                pythonnet.load("netfx")
            except RuntimeError:
                pass  # runtime already loaded
            import clr  # noqa: F401  (provided by pythonnet)

            clr.AddReference(str(dll.with_suffix("")))
            from LibreHardwareMonitor.Hardware import Computer  # type: ignore

            computer = Computer()
            computer.IsCpuEnabled = True
            computer.IsGpuEnabled = True
            computer.IsStorageEnabled = True
            computer.IsMotherboardEnabled = True
            computer.IsControllerEnabled = True
            computer.IsBatteryEnabled = True
            computer.IsMemoryEnabled = True
            computer.IsNetworkEnabled = False
            computer.Open()
        except LhmUnavailable:
            raise
        except Exception as exc:  # pythonnet raises a variety of .NET exception types
            raise LhmUnavailable(f"Could not load LibreHardwareMonitor: {exc}") from exc
        self._computer = computer
        self._lock = threading.Lock()

    def read(self) -> list[Reading]:
        out: list[Reading] = []
        with self._lock:
            for hw in self._computer.Hardware:
                self._collect(hw, str(hw.Name).strip("\x00 "), out)
        return out

    def _collect(self, hw, hw_name: str, out: list[Reading]) -> None:
        hw.Update()
        for sensor in hw.Sensors:
            value = sensor.Value
            out.append(Reading(
                id=str(sensor.Identifier),
                hardware=hw_name,
                name=str(sensor.Name),
                kind=str(sensor.SensorType).lower(),
                value=finite(float(value)) if value is not None else None,
            ))
        for sub in hw.SubHardware:
            self._collect(sub, hw_name, out)

    def close(self) -> None:
        with self._lock:
            self._computer.Close()
