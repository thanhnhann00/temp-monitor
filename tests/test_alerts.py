import pytest

from thermo.alerts import DEFAULT_THRESHOLDS, AlertEngine, Threshold
from thermo.store import Store


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, title, body):
        self.calls.append((title, body))


@pytest.fixture
def env():
    store = Store(":memory:")
    notifier = FakeNotifier()
    engine = AlertEngine(list(DEFAULT_THRESHOLDS), notifier, store)
    return engine, notifier, store


def test_defaults():
    assert [(t.key, t.limit_c) for t in DEFAULT_THRESHOLDS] == [("cpu", 90), ("gpu0", 85), ("gpu1", 85), ("ssd", 70)]


def test_starts_at_threshold(env):
    engine, notifier, store = env
    assert engine.check({"cpu": 90.0}, now=0) == ["cpu"]
    assert notifier.calls == [("CPU is 90 °C", "Above your 90 °C alert limit.")]
    assert len(store.alerts()) == 1


def test_hysteresis(env):
    engine, notifier, store = env
    for t, v in enumerate([91.0, 88.0, 91.0]):
        engine.check({"cpu": v}, now=t)
    assert len(store.alerts()) == 1 and store.alerts()[0]["ended"] is None
    engine.check({"cpu": 86.9}, now=10)
    assert store.alerts()[0]["ended"] == 10
    assert store.alerts()[0]["peak"] == 91.0


def test_cooldown_300s(env):
    engine, notifier, store = env
    engine.check({"cpu": 92.0}, now=0)
    engine.check({"cpu": 80.0}, now=10)
    engine.check({"cpu": 92.0}, now=100)
    assert len(store.alerts()) == 2
    assert len(notifier.calls) == 1
    engine.check({"cpu": 80.0}, now=200)
    engine.check({"cpu": 92.0}, now=301)
    assert len(notifier.calls) == 2


def test_none_value_ignored(env):
    engine, notifier, store = env
    assert engine.check({"gpu1": None}, now=0) == []
    engine.check({"gpu1": 90.0}, now=1)
    engine.check({"gpu1": None}, now=2)
    assert store.alerts()[0]["ended"] is None


def test_disabled_threshold(env):
    engine, notifier, store = env
    engine.set_thresholds([Threshold("cpu", False, 90)])
    assert engine.check({"cpu": 99.0}, now=0) == []
    assert notifier.calls == []


def test_resume_gap_does_not_double_fire(env):
    engine, notifier, store = env
    engine.check({"cpu": 95.0}, now=0)
    engine.check({"cpu": 95.0}, now=900)
    assert len(notifier.calls) == 1
    assert len(store.alerts()) == 1


def test_label_for_reading_id(env):
    engine, notifier, store = env
    engine.set_thresholds([Threshold("/gpu-nvidia/0/temperature/2", True, 80)])
    engine.check({"/gpu-nvidia/0/temperature/2": 81.0}, now=0)
    assert notifier.calls[0][0] == "/gpu-nvidia/0/temperature/2 is 81 °C"
