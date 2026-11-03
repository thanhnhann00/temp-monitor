import json

from thermo.model import Reading, Snapshot


def test_snapshot_to_json_replaces_nan_with_none():
    snap = Snapshot(
        ts=1.0,
        readings=[Reading("/x/0/temperature/0", "X", "Core", "temperature", float("nan"))],
        usage={"cpu": {"percent": float("nan")}},
        headline={"gpu1": float("nan")},
        cooling_mode="balanced",
    )
    out = snap.to_json()
    assert out["readings"][0]["value"] is None
    assert out["headline"]["gpu1"] is None
    assert out["usage"]["cpu"]["percent"] is None
    json.dumps(out, allow_nan=False)
