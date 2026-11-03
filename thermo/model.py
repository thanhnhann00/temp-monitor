"""Core data types shared by every module."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Reading:
    id: str
    hardware: str
    name: str
    kind: str  # temperature | load | clock | fan | power | data | smalldata | throughput
    value: float | None


@dataclass
class Snapshot:
    ts: float
    readings: list[Reading]
    usage: dict[str, Any]
    headline: dict[str, float | None]
    cooling_mode: str = "unknown"  # quiet | balanced | performance | unknown
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        return _clean({
            "ts": self.ts,
            "readings": [asdict(r) for r in self.readings],
            "usage": self.usage,
            "headline": self.headline,
            "cooling_mode": self.cooling_mode,
            **self.extra,
        })


def finite(value: float | None) -> float | None:
    """Return value if it is a real number, else None."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _clean(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj
