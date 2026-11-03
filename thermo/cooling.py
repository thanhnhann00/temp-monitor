"""Cooling mode via the Windows power mode, which Lenovo's thermal service follows."""
from __future__ import annotations

import ctypes
import threading
import uuid
from dataclasses import dataclass
from typing import Protocol

from thermo.store import Store

MODES = {
    "quiet": "961cc777-2547-4f9d-8174-7d86181b8a7a",        # Best power efficiency
    "balanced": "00000000-0000-0000-0000-000000000000",     # Balanced
    "performance": "ded574b5-45a0-4f42-8737-46345c09c238",  # Best performance
}
BALANCED_PLAN = "381b4222-f694-41f0-9685-ff5bb260df2e"
_BY_GUID = {g: m for m, g in MODES.items()}


class PowerApi(Protocol):
    def get_overlay(self) -> str: ...
    def set_overlay(self, guid: str) -> None: ...
    def balanced_plan_active(self) -> bool: ...


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_str(cls, s: str) -> "_GUID":
        return cls.from_buffer_copy(uuid.UUID(s).bytes_le)

    def __str__(self) -> str:
        return str(uuid.UUID(bytes_le=bytes(self)))


class WinPowerApi:
    def __init__(self):
        self._p = ctypes.WinDLL("powrprof")
        self._k = ctypes.WinDLL("kernel32")

    def get_overlay(self) -> str:
        g = _GUID()
        rc = self._p.PowerGetEffectiveOverlayScheme(ctypes.byref(g))
        if rc != 0:
            raise OSError(rc, "PowerGetEffectiveOverlayScheme failed")
        return str(g)

    def set_overlay(self, guid: str) -> None:
        rc = self._p.PowerSetActiveOverlayScheme(_GUID.from_str(guid))
        if rc != 0:
            raise OSError(rc, "PowerSetActiveOverlayScheme failed")

    def balanced_plan_active(self) -> bool:
        ptr = ctypes.POINTER(_GUID)()
        if self._p.PowerGetActiveScheme(None, ctypes.byref(ptr)) != 0:
            return False
        try:
            return str(ptr.contents) == BALANCED_PLAN
        finally:
            self._k.LocalFree(ptr)


class Cooling:
    def __init__(self, api: PowerApi, store: Store):
        self._api = api
        self._store = store
        self._lock = threading.Lock()
        self._last: str | None = None

    def mode(self) -> str:
        try:
            return _BY_GUID.get(self._api.get_overlay().lower(), "unknown")
        except OSError:
            return "unknown"

    def available(self) -> bool:
        return self._api.balanced_plan_active()

    def set_mode(self, mode: str, source: str, now: float) -> None:
        with self._lock:
            self._api.set_overlay(MODES[mode])  # raises OSError; nothing logged on failure
            self._last = mode
            self._store.log_cooling(now, mode, source)

    def poll(self, now: float) -> str:
        """Current mode; logs an 'external' event when it changed outside the app."""
        mode = self.mode()
        with self._lock:
            if self._last is not None and mode != self._last and mode != "unknown":
                self._store.log_cooling(now, mode, "external")
            self._last = mode
        return mode


@dataclass
class SmartRules:
    enabled: bool = False
    up_c: float = 85
    up_s: float = 30
    down_c: float = 70
    down_s: float = 120


class SmartCooling:
    MANUAL_PAUSE_S = 600
    MAX_GAP_S = 5

    def __init__(self, cooling: Cooling, rules: SmartRules):
        self._cooling = cooling
        self.rules = rules
        self._paused_until = float("-inf")
        self._last_step: float | None = None
        self._since: float | None = None      # start of the current sustained hot/cool stretch
        self._restore_to: str | None = None   # set while Smart Cooling holds Performance

    def set_rules(self, rules: SmartRules) -> None:
        self.rules = rules
        self._since = None

    def on_manual_change(self, now: float) -> None:
        self._paused_until = now + self.MANUAL_PAUSE_S
        self._restore_to = None
        self._since = None

    def step(self, cpu_c: float | None, now: float) -> str | None:
        gap = self._last_step is not None and now - self._last_step > self.MAX_GAP_S
        self._last_step = now
        if gap:
            self._since = None  # a long gap (e.g. sleep) is not "sustained"; restart the clock here
        if not self.rules.enabled or now < self._paused_until or cpu_c is None:
            self._since = None
            return None

        if self._restore_to is None:
            hot = cpu_c >= self.rules.up_c and self._cooling.mode() not in ("performance", "unknown")
            if not hot:
                self._since = None
                return None
            self._since = now if self._since is None else self._since
            if now - self._since >= self.rules.up_s:
                self._restore_to = self._cooling.mode()
                return self._switch("performance", now)
            return None

        if cpu_c >= self.rules.down_c:
            self._since = None
            return None
        self._since = now if self._since is None else self._since
        if now - self._since >= self.rules.down_s:
            target, self._restore_to = self._restore_to, None
            return self._switch(target, now)
        return None

    def _switch(self, mode: str, now: float) -> str | None:
        self._since = None
        try:
            self._cooling.set_mode(mode, "smart", now)
        except OSError:
            return None
        return mode
