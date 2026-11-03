"""The 1-second loop: read sources, update buffers/history/alerts/cooling, publish snapshots."""
from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time

from thermo import mapping
from thermo.alerts import AlertEngine
from thermo.buffers import UsageBuffers
from thermo.cooling import Cooling, SmartCooling
from thermo.model import Reading, Snapshot, finite
from thermo.store import Store

log = logging.getLogger(__name__)


class Sampler:
    PERSIST_EVERY = 2
    PRUNE_EVERY_S = 600
    QUEUE_SIZE = 5

    def __init__(self, sources, store: Store, alerts: AlertEngine, cooling: Cooling, smart: SmartCooling,
                 buffers: UsageBuffers, interval_s: float = 1.0):
        self.sources = sources
        self.store = store
        self.alerts = alerts
        self.cooling = cooling
        self.smart = smart
        self.buffers = buffers
        self.interval_s = interval_s
        self.paused = False
        self.started_at = time.time()
        self.latest: Snapshot | None = None
        self.minmax: dict[str, tuple[float, float]] = {}
        self.store_error: str | None = None
        self._ticks = 0
        self._last_prune = float("-inf")
        self._subs: list[queue.Queue] = []
        self._subs_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- pub/sub ------------------------------------------------------------
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self.QUEUE_SIZE)
        with self._subs_lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._subs_lock:
            if q in self._subs:
                self._subs.remove(q)

    def _publish(self, snap: Snapshot) -> None:
        with self._subs_lock:
            subs = list(self._subs)
        for q in subs:
            while True:
                try:
                    q.put_nowait(snap)
                    break
                except queue.Full:
                    try:
                        q.get_nowait()  # drop the oldest so a slow client never blocks us
                    except queue.Empty:
                        pass

    # --- loop ---------------------------------------------------------------
    def _guard(self, what: str, fn, default=None):
        try:
            return fn()
        except Exception:
            log.exception("%s failed", what)
            return default

    def tick(self, now: float) -> Snapshot:
        readings, usage = self._guard("reading sensors", self.sources.read, ([], {}))
        headline = mapping.headline_temps(readings)

        mode = self._guard("reading cooling mode", lambda: self.cooling.poll(now), "unknown")
        if self.cooling.changed_externally:
            self.smart.on_manual_change(now)
        if self._guard("smart cooling", lambda: self.smart.step(headline["cpu"], now)):
            mode = self.cooling.mode()

        for r in readings:
            v = finite(r.value)
            if v is not None:
                lo, hi = self.minmax.get(r.id, (v, v))
                self.minmax[r.id] = (min(lo, v), max(hi, v))

        if not self.paused and self._ticks % self.PERSIST_EVERY == 0:
            try:
                # Headline values are also saved under their short keys (cpu, gpu0, ...) for charts.
                short = [Reading(key, "", key, "temperature", v) for key, v in headline.items()]
                self.store.add_temps(now, readings + short)
                self.store_error = None
            except sqlite3.Error as exc:
                self.store_error = str(exc)
                log.error("History write failed: %s", exc)
        self._ticks += 1

        temps = {r.id: r.value for r in readings if r.kind == "temperature"}
        self._guard("alerts", lambda: self.alerts.check({**temps, **headline}, now))

        if now - self._last_prune >= self.PRUNE_EVERY_S:
            self._last_prune = now
            self._guard("pruning history", lambda: self.store.prune(now))

        snap = Snapshot(ts=now, readings=readings, usage=usage, headline=headline, cooling_mode=mode,
                        extra={"paused": self.paused, "store_error": self.store_error})
        self._guard("usage buffers", lambda: self.buffers.add(snap))
        self.latest = snap
        self._publish(snap)
        return snap

    def _run(self) -> None:
        next_at = time.monotonic()
        while not self._stop.is_set():
            self.tick(time.time())
            next_at += self.interval_s
            delay = next_at - time.monotonic()
            if delay < 0:  # fell behind (e.g. after sleep); don't try to catch up
                next_at, delay = time.monotonic(), 0
            self._stop.wait(delay)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="thermo-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
