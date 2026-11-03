"""GPU names and driver details from WMI (read once at startup)."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _date(raw: str | None) -> str | None:
    # WMI CIM_DATETIME: "20230823000000.000000-000" -> "8/23/2023"
    if not raw or len(raw) < 8 or not raw[:8].isdigit():
        return None
    return f"{int(raw[4:6])}/{int(raw[6:8])}/{raw[:4]}"


def video_controllers() -> list[dict]:
    try:
        import wmi

        return [{"name": v.Name, "driver_version": v.DriverVersion, "driver_date": _date(v.DriverDate)}
                for v in wmi.WMI().Win32_VideoController()]
    except Exception as exc:  # COM errors surface as many types
        log.warning("WMI video controller query failed: %s", exc)
        return []
