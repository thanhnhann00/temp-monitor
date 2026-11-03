"""In-memory rolling series for the Performance and Fans charts (lost on restart, by design)."""
from __future__ import annotations

import threading
from bisect import bisect_left
from collections import deque

from thermo.model import Snapshot, finite

SERIES = {
    "cpu": ("percent",),
    "memory": ("percent",),
    "disk0": ("active_pct", "read_mbs", "write_mbs"),
    "wifi": ("send_kbps", "recv_kbps"),
    "gpu0": ("load_pct", "dedicated_used_gb", "shared_used_gb"),
    "gpu1": ("load_pct", "dedicated_used_gb", "shared_used_gb"),
}


def downsample(points: list[tuple[float, float]], max_points: int) -> list[tuple[float, float]]:
    n = len(points)
    if n <= max_points:
        return points
    out = []
    for b in range(max_points):
        chunk = points[b * n // max_points:(b + 1) * n // max_points]
        out.append((sum(p[0] for p in chunk) / len(chunk), sum(p[1] for p in chunk) / len(chunk)))
    return out


class RingBuffer:
    def __init__(self, capacity: int = 3600):
        self._items: deque[tuple[float, float]] = deque(maxlen=capacity)

    def append(self, ts: float, value: float | None) -> None:
        v = finite(value)
        if v is not None:
            self._items.append((ts, v))

    def since(self, ts: float) -> list[tuple[float, float]]:
        items = list(self._items)
        return items[bisect_left(items, (ts, float("-inf"))):]


class UsageBuffers:
    def __init__(self, capacity: int = 3600):
        self._capacity = capacity
        self._buffers: dict[str, dict[str, RingBuffer]] = {}
        self._lock = threading.Lock()

    def _buf(self, device: str, key: str) -> RingBuffer:
        return self._buffers.setdefault(device, {}).setdefault(key, RingBuffer(self._capacity))

    def add(self, snap: Snapshot) -> None:
        with self._lock:
            for device, keys in SERIES.items():
                values = snap.usage.get(device, {})
                for key in keys:
                    self._buf(device, key).append(snap.ts, values.get(key))
            for fan in snap.usage.get("fans", []):
                self._buf("fans", fan["id"]).append(snap.ts, fan["rpm"])
            self._buf("temps", "cpu").append(snap.ts, snap.headline.get("cpu"))

    def series(self, device: str, range_s: int, now: float, max_points: int = 300) -> dict[str, list]:
        # Points strictly newer than now - range_s, so a 60 s range holds 60 one-second samples.
        start = now - range_s + 1e-6
        with self._lock:
            return {key: downsample(buf.since(start), max_points)
                    for key, buf in self._buffers.get(device, {}).items()}
