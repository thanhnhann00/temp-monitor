"""Wi-Fi name and signal strength from `netsh wlan show interfaces`."""
from __future__ import annotations

import re
import subprocess
import time
from typing import Callable

_PCT = re.compile(r"^(\d{1,3})\s*%$")


def _run_netsh() -> str:
    out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, timeout=5,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out.stdout.decode("utf-8", errors="replace")


def parse_netsh(text: str) -> dict:
    """Locale-tolerant: relies only on the literal 'SSID' key and a value ending in '%'."""
    ssid = signal = None
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "SSID" and ssid is None:
            ssid = value or None
        elif signal is None and (m := _PCT.match(value)):
            signal = int(m.group(1))
    connected = ssid is not None
    return {"connected": connected, "ssid": ssid, "signal_pct": signal if connected else None}


class WifiInfo:
    def __init__(self, ttl_s: float = 10, run: Callable[[], str] = _run_netsh, clock=time.monotonic):
        self._ttl = ttl_s
        self._run = run
        self._clock = clock
        self._at: float | None = None
        self._cached = {"connected": False, "ssid": None, "signal_pct": None}

    def get(self) -> dict:
        now = self._clock()
        if self._at is None or now - self._at >= self._ttl:
            self._at = now
            try:
                self._cached = parse_netsh(self._run())
            except (OSError, subprocess.SubprocessError):
                self._cached = {"connected": False, "ssid": None, "signal_pct": None}
        return dict(self._cached)
