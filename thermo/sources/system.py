"""CPU, memory, disk and network usage from psutil."""
from __future__ import annotations

import socket
import time
from typing import Callable

import psutil

GB = 1024 ** 3
_PROC_CACHE_S = 5.0
_proc_cache: tuple[float, int, int] | None = None


def _process_counts() -> tuple[int, int]:
    global _proc_cache
    now = time.monotonic()
    if _proc_cache is None or now - _proc_cache[0] > _PROC_CACHE_S:
        procs = threads = 0
        for p in psutil.process_iter(["num_threads"]):
            procs += 1
            threads += p.info.get("num_threads") or 0
        _proc_cache = (now, procs, threads)
    return _proc_cache[1], _proc_cache[2]


def cpu_usage() -> dict:
    procs, threads = _process_counts()
    return {
        "percent": psutil.cpu_percent(interval=None),
        "processes": procs,
        "threads": threads,
        "uptime_s": time.time() - psutil.boot_time(),
    }


def memory() -> dict:
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    return {
        "used_gb": (vm.total - vm.available) / GB,
        "total_gb": vm.total / GB,
        "available_gb": vm.available / GB,
        "percent": vm.percent,
        "pagefile_used_gb": sw.used / GB,
    }


class RateCounter:
    """Turns two monotonically increasing byte totals into bytes/second."""

    def __init__(self, read_totals: Callable[[], tuple[int, int]], clock=time.monotonic):
        self._read = read_totals
        self._clock = clock
        self._last: tuple[float, int, int] | None = None

    def sample(self) -> tuple[float, float]:
        try:
            a, b = self._read()
        except (KeyError, OSError, AttributeError):
            self._last = None
            return 0.0, 0.0
        now = self._clock()
        last, self._last = self._last, (now, a, b)
        if last is None or now <= last[0]:
            return 0.0, 0.0
        dt = now - last[0]
        return max(0.0, (a - last[1]) / dt), max(0.0, (b - last[2]) / dt)


def disk_rate(disk: str = "PhysicalDrive0") -> RateCounter:
    def totals():
        c = psutil.disk_io_counters(perdisk=True)[disk]
        return c.read_bytes, c.write_bytes
    return RateCounter(totals)


def net_rate(nic: str) -> RateCounter:
    def totals():
        c = psutil.net_io_counters(pernic=True)[nic]
        return c.bytes_sent, c.bytes_recv
    return RateCounter(totals)


def wifi_nic_name() -> str | None:
    return next((n for n in psutil.net_if_addrs() if n.lower().startswith("wi-fi")), None)


def ipv4(nic: str) -> str | None:
    for addr in psutil.net_if_addrs().get(nic, []):
        if addr.family == socket.AF_INET:
            return addr.address
    return None
