import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thermo import settings as settings_mod
from thermo.alerts import AlertEngine
from thermo.buffers import UsageBuffers
from thermo.cooling import MODES, Cooling, SmartCooling
from thermo.fake import FakePowerApi, FakeSources
from thermo.sampler import Sampler
from thermo.server import AppState, create_app
from thermo.store import Store

TOKEN = "t0ken"


class Notifier:
    def notify(self, title, body):
        pass


@pytest.fixture
def env(tmp_path: Path):
    store = Store(":memory:")
    api = FakePowerApi(MODES["balanced"])
    cooling = Cooling(api, store)
    s = settings_mod.load(tmp_path / "settings.json")
    alerts = AlertEngine(s.thresholds, Notifier(), store)
    smart = SmartCooling(cooling, s.smart)
    buffers = UsageBuffers()
    sampler = Sampler(FakeSources(), store, alerts, cooling, smart, buffers)
    quit_calls = []
    state = AppState(sampler=sampler, store=store, buffers=buffers, cooling=cooling, smart=smart, alerts=alerts,
                     settings=s, settings_path=tmp_path / "settings.json", token=TOKEN, is_admin=True,
                     lhm_error=None, machine={"host": "TEST", "model": "IdeaPad", "cpu": "Ryzen", "gpu": "RTX"},
                     request_quit=lambda: quit_calls.append(1))
    for i in range(3):
        sampler.tick(1000.0 + i)
    client = TestClient(create_app(state, allowed_hosts=["testserver"]))
    return client, state, api, quit_calls


H = {"X-Thermo-Token": TOKEN}


def test_index_injects_token(env):
    client, *_ = env
    r = client.get("/")
    assert r.status_code == 200
    assert f'content="{TOKEN}"' in r.text and "{{TOKEN}}" not in r.text


def test_unknown_host_rejected(env):
    client, *_ = env
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 400


def test_status_fields(env):
    client, *_ = env
    body = client.get("/api/status").json()
    assert set(body) == {"is_admin", "lhm_error", "store_error", "sensor_count", "uptime_s", "samples_saved",
                         "paused", "machine", "cooling_available"}
    assert body["sensor_count"] > 0 and body["cooling_available"] is True


def test_sensors_have_minmax(env):
    client, *_ = env
    rows = client.get("/api/sensors").json()
    cpu = next(r for r in rows if r["name"] == "Core (Tctl/Tdie)")
    assert cpu["min"] <= cpu["value"] <= cpu["max"]


def test_usage_60(env):
    client, *_ = env
    body = client.get("/api/usage", params={"device": "cpu", "range": 60}).json()
    assert len(body["percent"]) == 3
    assert client.get("/api/usage", params={"device": "cpu", "range": 61}).status_code == 422


def test_history_and_hourly(env):
    client, *_ = env
    hist = client.get("/api/history", params={"range": "1h", "sensors": "cpu,gpu0"}).json()
    assert set(hist) == {"cpu", "gpu0"}
    assert client.get("/api/history", params={"range": "2h"}).status_code == 422
    hourly = client.get("/api/history/hourly", params={"sensor": "cpu", "hours": 7}).json()
    assert isinstance(hourly, list)


def test_history_csv_header(env):
    client, *_ = env
    r = client.get("/api/history.csv")
    assert r.text.splitlines()[0] == "timestamp,sensor_id,value_c"
    assert "attachment" in r.headers["content-disposition"]


def test_put_requires_token(env):
    client, *_ = env
    assert client.put("/api/settings", json={"theme": "dark"}).status_code == 403
    assert client.put("/api/settings", json={"theme": "dark"}, headers={"X-Thermo-Token": "nope"}).status_code == 403
    r = client.put("/api/settings", json={"theme": "dark"}, headers=H)
    assert r.status_code == 200 and r.json()["theme"] == "dark"


def test_settings_persisted(env):
    client, state, *_ = env
    client.put("/api/settings", json={"cpu_limit_c": 95}, headers=H)
    assert json.loads(state.settings_path.read_text())["cpu_limit_c"] == 95


@pytest.mark.parametrize("bad", [-5, "abc", 500])
def test_threshold_validation(env, bad):
    client, state, *_ = env
    before = state.settings_path.read_text()
    r = client.put("/api/alerts/thresholds", json=[{"key": "cpu", "enabled": True, "limit_c": bad}], headers=H)
    assert r.status_code == 422
    assert state.settings_path.read_text() == before


def test_threshold_put_applies(env):
    client, state, *_ = env
    r = client.put("/api/alerts/thresholds", json=[{"key": "cpu", "enabled": True, "limit_c": 60}], headers=H)
    assert r.status_code == 200
    assert [(t.key, t.limit_c) for t in state.alerts.thresholds] == [("cpu", 60)]
    assert client.get("/api/alerts/thresholds").json() == [{"key": "cpu", "enabled": True, "limit_c": 60}]


def test_alert_log(env):
    client, state, *_ = env
    state.store.alert_start("cpu", 1.0, 91.0)
    assert client.get("/api/alerts/log", params={"limit": 10}).json()[0]["sensor_id"] == "cpu"


def test_cooling_mode_put(env):
    client, state, api, _ = env
    r = client.put("/api/cooling/mode", json={"mode": "performance"}, headers=H)
    assert r.status_code == 200 and api.guid == MODES["performance"]
    assert client.get("/api/cooling/mode").json() == {"mode": "performance", "available": True}
    assert state.smart._paused_until > 0
    assert client.put("/api/cooling/mode", json={"mode": "turbo"}, headers=H).status_code == 422
    api.fail_with = OSError(5, "Access is denied")
    r = client.put("/api/cooling/mode", json={"mode": "quiet"}, headers=H)
    assert r.status_code == 502 and r.json()["error"] == "Windows error 5"
    api.balanced = False
    assert client.put("/api/cooling/mode", json={"mode": "quiet"}, headers=H).status_code == 409


def test_smart_put_validation(env):
    client, state, *_ = env
    bad = {"enabled": True, "up_c": 80, "up_s": 30, "down_c": 90, "down_s": 120}
    assert client.put("/api/cooling/smart", json=bad, headers=H).status_code == 422
    good = {**bad, "down_c": 70}
    assert client.put("/api/cooling/smart", json=good, headers=H).status_code == 200
    assert state.smart.rules.enabled is True
    assert json.loads(state.settings_path.read_text())["smart"]["enabled"] is True


def test_cooling_events(env):
    client, *_ = env
    client.put("/api/cooling/mode", json={"mode": "quiet"}, headers=H)
    assert client.get("/api/cooling/events", params={"since": 0}).json()[-1]["mode"] == "quiet"


def test_pause_resume_quit(env):
    client, state, _, quit_calls = env
    assert client.post("/api/monitor/pause", headers=H).status_code == 200 and state.sampler.paused
    assert client.post("/api/monitor/resume", headers=H).status_code == 200 and not state.sampler.paused
    assert client.post("/api/quit").status_code == 403
    assert client.post("/api/quit", headers=H).status_code == 200 and quit_calls == [1]


def test_stream_sends_snapshot(env):
    client, state, *_ = env
    with client.stream("GET", "/api/stream") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                snap = json.loads(line[6:])
                break
    assert "headline" in snap and snap["cooling_mode"] == "balanced"


def test_stream_ends_when_stopping(env):
    import threading

    client, state, *_ = env
    state.stopping.set()
    done = threading.Event()

    def read_all():
        with client.stream("GET", "/api/stream") as r:
            for _ in r.iter_lines():
                pass
        done.set()

    threading.Thread(target=read_all, daemon=True).start()
    assert done.wait(5), "SSE stream kept running after quit"


def test_quit_sets_stopping(env):
    client, state, *_ = env
    client.post("/api/quit", headers=H)
    assert state.stopping.is_set()
