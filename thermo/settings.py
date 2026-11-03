"""User settings stored in data/settings.json. Anything unreadable falls back to defaults."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from thermo.alerts import DEFAULT_THRESHOLDS, Threshold
from thermo.cooling import SmartRules

log = logging.getLogger(__name__)
THEMES = ("system", "light", "dark")


@dataclass
class Settings:
    theme: str = "system"
    cpu_limit_c: float = 90
    port: int = 8000
    thresholds: list[Threshold] = field(default_factory=lambda: [Threshold(**asdict(t)) for t in DEFAULT_THRESHOLDS])
    smart: SmartRules = field(default_factory=SmartRules)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _thresholds(raw) -> list[Threshold] | None:
    if not isinstance(raw, list):
        return None
    out = []
    for t in raw:
        if not (isinstance(t, dict) and isinstance(t.get("key"), str) and isinstance(t.get("enabled"), bool)
                and _num(t.get("limit_c"))):
            return None
        out.append(Threshold(t["key"], t["enabled"], float(t["limit_c"])))
    return out


def _smart(raw) -> SmartRules | None:
    if not isinstance(raw, dict):
        return None
    base = asdict(SmartRules())
    for f in fields(SmartRules):
        if f.name in raw:
            v = raw[f.name]
            if (f.name == "enabled" and not isinstance(v, bool)) or (f.name != "enabled" and not _num(v)):
                return None
            base[f.name] = v
    return SmartRules(**base)


def _from_dict(raw: dict) -> Settings:
    s = Settings()
    if raw.get("theme") in THEMES:
        s.theme = raw["theme"]
    if _num(raw.get("cpu_limit_c")):
        s.cpu_limit_c = float(raw["cpu_limit_c"])
    if isinstance(raw.get("port"), int) and not isinstance(raw.get("port"), bool) and 1024 <= raw["port"] <= 65535:
        s.port = raw["port"]
    if (t := _thresholds(raw.get("thresholds"))) is not None:
        s.thresholds = t
    if (sm := _smart(raw.get("smart"))) is not None:
        s.smart = sm
    return s


def load(path: Path) -> Settings:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("settings root is not an object")
        s = _from_dict(raw)
    except (OSError, ValueError) as exc:
        if path.exists():
            log.warning("Ignoring unreadable %s: %s", path, exc)
        s = Settings()
    save(path, s)
    return s


def save(path: Path, s: Settings) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
    os.replace(tmp, path)
