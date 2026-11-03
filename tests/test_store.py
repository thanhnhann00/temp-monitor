import pytest

from thermo.model import Reading
from thermo.store import Store

HOUR = 3600


@pytest.fixture
def store():
    return Store(":memory:")


def _t(id_, value, kind="temperature"):
    return Reading(id_, "HW", "Name", kind, value)


def test_only_finite_temperatures_saved(store):
    n = store.add_temps(100.0, [_t("a", 50.0), _t("b", None), _t("c", float("nan")), _t("d", 30.0, "load")])
    assert n == 1
    assert store.sample_count() == 1


def test_prune_24h(store):
    store.add_temps(0.0, [_t("a", 50.0)])
    store.add_temps(90_000.0, [_t("a", 51.0)])
    assert store.prune(now=90_000.0) == 1
    assert store.sample_count() == 1


def test_series_downsampled(store):
    for i in range(1000):
        store.add_temps(float(i), [_t("cpu", 40.0 + i % 10)])
    out = store.series(["cpu", "missing"], since=0.0, max_points=500)
    assert 0 < len(out["cpu"]) <= 500
    assert out["missing"] == []


def test_hourly_averages(store):
    base = 10 * HOUR
    for i in range(0, HOUR, 60):
        store.add_temps(base + i, [_t("cpu", 60.0)])
        store.add_temps(base + HOUR + i, [_t("cpu", 80.0)])
    out = store.hourly("cpu", hours=7, now=base + 2 * HOUR - 1)
    assert [round(h["avg"]) for h in out] == [60, 80]
    assert out[0]["hour_ts"] == base


def test_csv_header_and_rows(store):
    store.add_temps(1_700_000_000.0, [_t("cpu", 61.5)])
    lines = store.export_csv(since=0.0).strip().splitlines()
    assert lines[0] == "timestamp,sensor_id,value_c"
    assert lines[1].endswith(",cpu,61.5")
    assert lines[1][:4] == "2023"


def test_alert_lifecycle(store):
    aid = store.alert_start("cpu", 10.0, 91.0)
    store.alert_update(aid, 93.0)
    store.alert_update(aid, 92.0)
    store.alert_end(aid, 50.0)
    a = store.alerts()[0]
    assert a["peak"] == 93.0 and a["ended"] == 50.0 and a["sensor_id"] == "cpu"


def test_cooling_events_since(store):
    store.log_cooling(1.0, "quiet", "app")
    store.log_cooling(5.0, "performance", "smart")
    assert store.cooling_events(since=2.0) == [{"ts": 5.0, "mode": "performance", "source": "smart"}]
