"""Temperature alerts: threshold, hysteresis, toast cooldown, alert log."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol

from thermo.model import finite
from thermo.store import Store

log = logging.getLogger(__name__)

LABELS = {"cpu": "CPU", "gpu0": "GPU 0 (Radeon)", "gpu1": "GPU 1 (RTX 3050)", "ssd": "SSD"}


@dataclass
class Threshold:
    key: str
    enabled: bool
    limit_c: float


DEFAULT_THRESHOLDS = [Threshold("cpu", True, 90), Threshold("gpu0", True, 85),
                      Threshold("gpu1", True, 85), Threshold("ssd", True, 70)]


class Notifier(Protocol):
    def notify(self, title: str, body: str) -> None: ...


class WinotifyNotifier:
    def notify(self, title: str, body: str) -> None:
        try:
            from winotify import Notification

            Notification(app_id="Thermo", title=title, msg=body).show()
        except Exception as exc:  # toast failures must never stop monitoring
            log.warning("Toast failed: %s", exc)


class AlertEngine:
    HYSTERESIS_C = 3.0
    COOLDOWN_S = 300

    def __init__(self, thresholds: list[Threshold], notifier: Notifier, store: Store, now: float | None = None):
        self._notifier = notifier
        self._store = store
        self._open: dict[str, int] = {}          # key -> alert_log id
        self._last_toast: dict[str, float] = {}  # key -> ts
        self._thresholds: dict[str, Threshold] = {}
        # Rows left open by a previous run (crash, power loss) can never end on their own.
        store.close_open_alerts(time.time() if now is None else now)
        self.set_thresholds(thresholds, now)

    def set_thresholds(self, thresholds: list[Threshold], now: float | None = None) -> None:
        self._thresholds = {t.key: t for t in thresholds}
        for key in list(self._open):
            t = self._thresholds.get(key)
            if t is None or not t.enabled:
                self._end(key, time.time() if now is None else now)

    def _end(self, key: str, now: float) -> None:
        self._store.alert_end(self._open.pop(key), now)

    @property
    def thresholds(self) -> list[Threshold]:
        return list(self._thresholds.values())

    def check(self, values: dict[str, float | None], now: float) -> list[str]:
        started = []
        for key, t in self._thresholds.items():
            value = finite(values.get(key))
            alert_id = self._open.get(key)
            if value is None:
                if alert_id is not None:  # sensor went away (e.g. the dGPU fell asleep)
                    self._end(key, now)
                continue
            if alert_id is not None:
                if not t.enabled or value < t.limit_c - self.HYSTERESIS_C:
                    self._end(key, now)
                else:
                    self._store.alert_update(alert_id, value)
            elif t.enabled and value >= t.limit_c:
                self._open[key] = self._store.alert_start(key, now, value)
                started.append(key)
                if now - self._last_toast.get(key, float("-inf")) >= self.COOLDOWN_S:
                    self._last_toast[key] = now
                    self._notifier.notify(f"{LABELS.get(key, key)} is {value:.0f} °C",
                                          f"Above your {t.limit_c:.0f} °C alert limit.")
        return started
