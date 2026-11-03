import json

from thermo import settings
from thermo.alerts import Threshold
from thermo.cooling import SmartRules


def test_missing_file_gives_defaults_and_creates_it(tmp_path):
    p = tmp_path / "data" / "settings.json"
    s = settings.load(p)
    assert s == settings.Settings()
    assert p.exists()
    assert json.loads(p.read_text())["port"] == 8000


def test_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    s = settings.Settings(theme="dark", cpu_limit_c=95, port=8123,
                          thresholds=[Threshold("cpu", False, 80)], smart=SmartRules(enabled=True, up_c=88))
    settings.save(p, s)
    assert settings.load(p) == s


def test_corrupt_json_gives_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{not json")
    assert settings.load(p) == settings.Settings()
    assert json.loads(p.read_text())["theme"] == "system"


def test_empty_file_gives_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("")
    assert settings.load(p) == settings.Settings()


def test_partial_file_fills_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"theme": "dark"}')
    s = settings.load(p)
    assert s.theme == "dark"
    assert s.port == 8000 and s.smart == SmartRules() and len(s.thresholds) == 4


def test_wrong_type_field_reset(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"port": "abc", "theme": "purple", "thresholds": [{"key": "cpu"}], "smart": 5}')
    s = settings.load(p)
    assert s.port == 8000 and s.theme == "system"
    assert len(s.thresholds) == 4 and s.smart == SmartRules()
