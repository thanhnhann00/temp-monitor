import json
from dataclasses import replace
from pathlib import Path

import pytest

from thermo import mapping
from thermo.model import Reading

FIXTURE = Path(__file__).parent / "fixtures" / "lhm_dump.json"


@pytest.fixture
def readings() -> list[Reading]:
    raw = [Reading(**r) for r in json.loads(FIXTURE.read_text(encoding="utf-8"))]
    # What the D3DKMT source adds on this laptop (LHM has no Radeon temperature).
    raw.append(Reading("/d3dkmt/1/temperature", "AMD Radeon(TM) Graphics", "GPU Temperature", "temperature", 47.0))
    return raw


def _set(readings, hardware, name, kind, value):
    return [replace(r, value=value) if hardware in r.hardware and r.name == name and r.kind == kind else r
            for r in readings]


def test_headline_from_fixture(readings):
    h = mapping.headline_temps(readings)
    assert set(h) == {"cpu", "gpu0", "gpu1", "ssd"}
    assert 20 <= h["gpu0"] <= 110
    assert 20 <= h["gpu1"] <= 110
    # cpu and ssd need admin; the provisional fixture was recorded without it
    for key in ("cpu", "ssd"):
        assert h[key] is None or 20 <= h[key] <= 110


def test_zero_temperature_is_missing(readings):
    rs = _set(readings, "AMD Ryzen", "Core (Tctl/Tdie)", "temperature", 0.0)
    assert mapping.headline_temps(rs)["cpu"] is None


def test_cpu_temperature_when_admin(readings):
    rs = _set(readings, "AMD Ryzen", "Core (Tctl/Tdie)", "temperature", 67.5)
    assert mapping.headline_temps(rs)["cpu"] == 67.5


def test_gpu1_sleeping_when_temp_missing(readings):
    rs = _set(readings, "NVIDIA", "GPU Core", "temperature", None)
    assert mapping.headline_temps(rs)["gpu1"] is None
    assert mapping.gpu_view(rs, "gpu1")["sleeping"] is True


def test_nan_treated_as_missing(readings):
    rs = _set(readings, "NVIDIA", "GPU Core", "temperature", float("nan"))
    assert mapping.headline_temps(rs)["gpu1"] is None
    assert mapping.gpu_view(rs, "gpu1")["sleeping"] is True


def test_gpu0_view_fields(readings):
    v = mapping.gpu_view(readings, "gpu0")
    assert v["name"] == "AMD Radeon(TM) Graphics"
    assert v["temp_c"] == 47.0
    assert v["sleeping"] is False
    assert 0 <= v["load_pct"] <= 100
    assert v["dedicated_total_gb"] == pytest.approx(2021.8 / 1024, abs=0.2)
    assert v["shared_total_gb"] == pytest.approx(7010.5 / 1024, abs=0.5)


def test_gpu1_shared_total_falls_back_to_system_value(readings):
    v = mapping.gpu_view(readings, "gpu1")
    assert v["dedicated_total_gb"] == pytest.approx(4.0, abs=0.01)
    assert v["shared_total_gb"] == pytest.approx(7010.5 / 1024, abs=0.5)
    assert v["power_w"] is not None


def test_fans_empty_when_no_fan_sensors(readings):
    assert mapping.fans([r for r in readings if r.kind != "fan"]) == []


def test_fans_listed():
    rs = [Reading("/lpc/0/fan/0", "EC", "Fan #1", "fan", 3200.0), Reading("/lpc/0/fan/1", "EC", "Fan #2", "fan", None)]
    assert mapping.fans(rs) == [{"id": "/lpc/0/fan/0", "name": "Fan #1", "rpm": 3200.0},
                                {"id": "/lpc/0/fan/1", "name": "Fan #2", "rpm": None}]


def test_cpu_clock_mean():
    rs = [Reading("/amdcpu/0/clock/1", "AMD Ryzen", "Core #1", "clock", 3000.0),
          Reading("/amdcpu/0/clock/2", "AMD Ryzen", "Core #2", "clock", 3300.0),
          Reading("/amdcpu/0/clock/3", "AMD Ryzen", "Core #3", "clock", float("nan"))]
    assert mapping.cpu_clock_ghz(rs) == pytest.approx(3.15)


def test_disk_view_by_id_prefix():
    rs = [Reading("/nvme/0/temperature/0", "SAMSUNG MZ", "Composite Temperature", "temperature", 44.0),
          Reading("/nvme/0/load/0", "SAMSUNG MZ", "Total Activity", "load", 1.5)]
    assert mapping.disk_view(rs) == {"temp_c": 44.0, "active_pct": 1.5}
    assert mapping.headline_temps(rs)["ssd"] == 44.0
