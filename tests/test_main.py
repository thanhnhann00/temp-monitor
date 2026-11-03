import socket

import pytest

from thermo.__main__ import build_state, main, parse_args
from thermo.fake import FakePowerApi, FakeSources


def test_build_state_fake(tmp_path):
    state = build_state(parse_args(["--fake", "--no-browser", "--data", str(tmp_path)]))
    assert isinstance(state.sampler.sources, FakeSources)
    assert isinstance(state.cooling._api, FakePowerApi)
    snap = state.sampler.tick(1_000_000.0)
    assert snap.headline["cpu"] is not None
    assert state.store.hourly("cpu", 7, 1_000_000.0), "fake mode seeds 7 h of history"
    assert len(state.token) >= 32
    assert state.machine["model"] == "IdeaPad 5 Pro 16ARH7"


def test_fake_no_fans_env(tmp_path, monkeypatch):
    monkeypatch.setenv("THERMO_FAKE_NO_FANS", "1")
    state = build_state(parse_args(["--fake", "--data", str(tmp_path)]))
    assert state.sampler.tick(1.0).usage["fans"] == []


def test_port_in_use_message(tmp_path, capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        with pytest.raises(SystemExit) as exc:
            main(["--fake", "--no-browser", "--data", str(tmp_path), "--port", str(port)])
    assert exc.value.code == 1
    assert f"Port {port} is already in use. Start with --port {port + 1} or change it in Settings." in capsys.readouterr().err
