"""CPU, memory, disk and network usage from psutil."""
from __future__ import annotations

import ctypes
import socket
import time
from ctypes import wintypes as w
from typing import Callable

import psutil

GB = 1024 ** 3
_PROC_CACHE_S = 5.0
_proc_cache: tuple[float, int, int] | None = None


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", w.LONG), ("dwFlags", w.DWORD),
                ("szExeFile", w.WCHAR * 260)]


_TH32CS_SNAPPROCESS = 0x2
_INVALID_HANDLE = w.HANDLE(-1).value


def _count_processes() -> tuple[int, int]:
    """Process and thread totals from one Toolhelp32 snapshot (~15 ms).

    psutil's per-process num_threads opens every process and cost ~8 s of CPU per scan here.
    """
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    snap = k.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == _INVALID_HANDLE:
        return len(psutil.pids()), 0
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        procs = threads = 0
        ok = k.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            procs += 1
            threads += entry.cntThreads
            ok = k.Process32NextW(snap, ctypes.byref(entry))
        return procs, threads
    finally:
        k.CloseHandle(snap)


def _process_counts() -> tuple[int, int]:
    global _proc_cache
    now = time.monotonic()
    if _proc_cache is None or now - _proc_cache[0] > _PROC_CACHE_S:
        _proc_cache = (now, *_count_processes())
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
