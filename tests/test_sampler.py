import sqlite3

import pytest

from thermo.alerts import DEFAULT_THRESHOLDS, AlertEngine
from thermo.buffers import UsageBuffers
from thermo.cooling import MODES, Cooling, SmartCooling, SmartRules
from thermo.fake import FakePowerApi, FakeSources
from thermo.model import Reading
from thermo.sampler import Sampler
from thermo.store import Store


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, title, body):
        self.calls.append(title)


def make(sources=None, store=None):
    store = store or Store(":memory:")
    api = FakePowerApi(MODES["balanced"])
    cooling = Cooling(api, store)
    sampler = Sampler(sources or FakeSources(), store, AlertEngine(list(DEFAULT_THRESHOLDS), FakeNotifier(), store),
                      cooling, SmartCooling(cooling, SmartRules()), UsageBuffers())
    return sampler, store, api


def finite_temps(readings):
    return sum(1 for r in readings if r.kind == "temperature" and r.value is not None)


def test_tick_builds_snapshot():
    sampler, _, _ = make()
    snap = sampler.tick(1000.0)
    assert set(snap.headline) == {"cpu", "gpu0", "gpu1", "ssd"}
    assert {"cpu", "memory", "disk0", "wifi", "gpu0", "gpu1", "fans"} <= set(snap.usage)
    assert snap.cooling_mode == "balanced"
    assert sampler.latest is snap


def test_persist_every_second_tick():
    sampler, store, _ = make()
    snaps = [sampler.tick(1000.0 + i) for i in range(4)]
    assert store.sample_count() == 2 * finite_temps(snaps[0].readings)


def test_paused_skips_store_only():
    sampler, store, _ = make()
    sampler.paused = True
    q = sampler.subscribe()
    sampler.tick(1000.0)
    assert store.sample_count() == 0
    assert q.get_nowait().ts == 1000.0


def test_sleeping_gpu_no_crash_no_row():
    sampler, store, _ = make()
    for i in range(2):
        snap = sampler.tick(1000.0 + i)
    assert snap.headline["gpu1"] is None
    assert store.series(["/gpu-nvidia/0/temperature/0"], since=0)["/gpu-nvidia/0/temperature/0"] == []


def test_slow_subscriber_never_blocks():
    sampler, _, _ = make()
    q = sampler.subscribe()
    for i in range(20):
        sampler.tick(1000.0 + i)
    items = [q.get_nowait() for _ in range(q.qsize())]
    assert [s.ts for s in items] == [1015.0, 1016.0, 1017.0, 1018.0, 1019.0]


def test_unsubscribe():
    sampler, _, _ = make()
    q = sampler.subscribe()
    sampler.unsubscribe(q)
    sampler.tick(1000.0)
    assert q.empty()


class SeqSource:
    lhm_error = None

    def __init__(self, values):
        self._values = iter(values)

    def read(self):
        return [Reading("t1", "HW", "Temp", "temperature", next(self._values))], {}


def test_minmax_since_start():
    sampler, _, _ = make(SeqSource([50.0, 70.0, None, 60.0]))
    for i in range(4):
        sampler.tick(1000.0 + i)
    assert sampler.minmax["t1"] == (50.0, 70.0)


class BrokenStore(Store):
    def __init__(self):
        super().__init__(":memory:")
        self.fail = True

    def add_temps(self, ts, readings):
        if self.fail:
            raise sqlite3.OperationalError("disk I/O error")
        return super().add_temps(ts, readings)


def test_store_error_flagged():
    store = BrokenStore()
    sampler, _, _ = make(store=store)
    snap = sampler.tick(1000.0)
    assert sampler.store_error == "disk I/O error"
    assert snap.to_json()["store_error"] == "disk I/O error"
    store.fail = False
    sampler.tick(1001.0)
    sampler.tick(1002.0)
    assert sampler.store_error is None


class FlakySource:
    lhm_error = None

    def __init__(self):
        self.calls = 0

    def read(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("sensor bus hiccup")
        return FakeSources().read()


def test_source_exception_is_contained():
    sampler, _, _ = make(FlakySource())
    snap = sampler.tick(1000.0)
    assert snap.readings == []
    assert sampler.tick(1001.0).readings


def test_external_mode_change_pauses_smart():
    sampler, store, api = make()
    sampler.smart.set_rules(SmartRules(enabled=True))
    sampler.tick(1000.0)
    api.guid = MODES["quiet"]
    sampler.tick(1001.0)
    assert store.cooling_events(0)[-1]["source"] == "external"
    assert sampler.smart._paused_until == pytest.approx(1601.0)
