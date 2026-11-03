import pytest

from thermo.cooling import MODES, Cooling, SmartCooling, SmartRules
from thermo.fake import FakePowerApi
from thermo.store import Store


@pytest.fixture
def env():
    api = FakePowerApi(MODES["balanced"])
    store = Store(":memory:")
    return api, store, Cooling(api, store)


def run(smart, temps, start=0):
    """Feed one reading per second; return {t: switched_mode} for every switch."""
    switches = {}
    for i, c in enumerate(temps):
        if (m := smart.step(c, start + i)) is not None:
            switches[start + i] = m
    return switches


def test_set_mode_sets_guid_and_logs(env):
    api, store, cooling = env
    cooling.set_mode("performance", "app", 0)
    assert api.guid == "ded574b5-45a0-4f42-8737-46345c09c238"
    assert store.cooling_events(0) == [{"ts": 0, "mode": "performance", "source": "app"}]


def test_poll_detects_external(env):
    api, store, cooling = env
    cooling.poll(0)
    api.guid = MODES["quiet"]
    assert cooling.poll(1) == "quiet"
    assert store.cooling_events(0)[-1] == {"ts": 1, "mode": "quiet", "source": "external"}
    assert cooling.poll(2) == "quiet"
    assert len(store.cooling_events(0)) == 1


def test_unknown_guid(env):
    api, store, cooling = env
    api.guid = "11111111-2222-3333-4444-555555555555"
    assert cooling.mode() == "unknown"


def test_available_follows_balanced_plan(env):
    api, store, cooling = env
    api.balanced = False
    assert cooling.available() is False


def test_smart_up_after_30s(env):
    api, store, cooling = env
    smart = SmartCooling(cooling, SmartRules(enabled=True))
    assert run(smart, [86.0] * 31) == {30: "performance"}


def test_smart_restores_previous_mode(env):
    api, store, cooling = env
    cooling.set_mode("quiet", "app", -1000)
    smart = SmartCooling(cooling, SmartRules(enabled=True))
    run(smart, [86.0] * 31)
    assert cooling.mode() == "performance"
    switches = run(smart, [69.0] * 121, start=31)
    assert switches == {151: "quiet"}
    assert cooling.mode() == "quiet"
    assert store.cooling_events(0)[-1]["source"] == "smart"


def test_smart_gap_resets(env):
    api, store, cooling = env
    smart = SmartCooling(cooling, SmartRules(enabled=True))
    assert run(smart, [86.0] * 21) == {}
    assert run(smart, [86.0] * 31, start=200) == {230: "performance"}


def test_smart_none_resets(env):
    api, store, cooling = env
    smart = SmartCooling(cooling, SmartRules(enabled=True))
    assert run(smart, [86.0] * 20 + [None] + [86.0] * 20) == {}


def test_manual_pauses_600s(env):
    api, store, cooling = env
    smart = SmartCooling(cooling, SmartRules(enabled=True))
    smart.on_manual_change(0)
    assert run(smart, [95.0] * 631) == {630: "performance"}


def test_disabled_does_nothing(env):
    api, store, cooling = env
    smart = SmartCooling(cooling, SmartRules(enabled=False))
    assert run(smart, [99.0] * 100) == {}


def test_already_performance_no_switch(env):
    api, store, cooling = env
    cooling.set_mode("performance", "app", -1)
    smart = SmartCooling(cooling, SmartRules(enabled=True))
    assert run(smart, [99.0] * 100) == {}


def test_set_mode_failure_raises(env):
    api, store, cooling = env
    api.fail_with = OSError(5, "Access is denied")
    with pytest.raises(OSError):
        cooling.set_mode("quiet", "app", 0)
    assert cooling.mode() == "balanced"
    assert store.cooling_events(0) == []


def test_poll_does_not_report_app_change_as_external(env):
    import threading
    import time

    api, store, cooling = env
    cooling.poll(0)
    real_get = api.get_overlay
    started = threading.Event()

    def slow_get():
        guid = real_get()
        if not started.is_set():
            started.set()
            threading.Thread(target=lambda: cooling.set_mode("performance", "app", 1)).start()
            time.sleep(0.2)
        return guid

    api.get_overlay = slow_get
    cooling.poll(1)
    time.sleep(0.3)
    api.get_overlay = real_get
    cooling.poll(2)
    assert [e["source"] for e in store.cooling_events(0)] == ["app"]
