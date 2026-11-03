from pathlib import Path

from thermo.sources.wifi import WifiInfo, parse_netsh

FIX = Path(__file__).parent / "fixtures"
CONNECTED = (FIX / "netsh_connected.txt").read_text(encoding="utf-8")
DISCONNECTED = (FIX / "netsh_disconnected.txt").read_text(encoding="utf-8")


def test_parse_connected():
    assert parse_netsh(CONNECTED) == {"connected": True, "ssid": "TestNet", "signal_pct": 100}


def test_parse_disconnected():
    assert parse_netsh(DISCONNECTED) == {"connected": False, "ssid": None, "signal_pct": None}


def test_parse_locale_tolerant():
    german = (CONNECTED.replace("State", "Status").replace("connected", "Verbunden")
              .replace("Signal ", "Signalstärke ").replace("Name ", "Name ").replace("Channel", "Kanal"))
    out = parse_netsh(german)
    assert out["ssid"] == "TestNet"
    assert out["signal_pct"] == 100
    assert out["connected"] is True


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_wifi_cache_ttl():
    calls = []
    clock = Clock()
    info = WifiInfo(ttl_s=10, run=lambda: calls.append(1) or CONNECTED, clock=clock)
    info.get()
    clock.t = 5
    info.get()
    assert len(calls) == 1
    clock.t = 11
    info.get()
    assert len(calls) == 2


def test_wifi_run_error():
    def boom():
        raise OSError("netsh missing")

    assert WifiInfo(run=boom).get()["connected"] is False
