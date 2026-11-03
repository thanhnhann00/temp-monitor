from thermo.fake import FakeSources

USAGE_FIELDS = {
    "cpu": {"percent", "ghz", "processes", "threads", "uptime_s", "temp_c"},
    "memory": {"used_gb", "total_gb", "available_gb", "percent", "pagefile_used_gb"},
    "disk0": {"active_pct", "read_mbs", "write_mbs", "temp_c", "label"},
    "wifi": {"connected", "ssid", "signal_pct", "ipv4", "send_kbps", "recv_kbps"},
    "gpu0": {"name", "load_pct", "temp_c", "dedicated_used_gb", "dedicated_total_gb", "shared_used_gb",
             "shared_total_gb", "fan_rpm", "power_w", "sleeping", "driver_version", "driver_date"},
}
USAGE_FIELDS["gpu1"] = USAGE_FIELDS["gpu0"]


def test_fake_sources_shape():
    readings, usage = FakeSources().read()
    assert readings
    assert set(usage) == set(USAGE_FIELDS) | {"fans"}
    for key, fields in USAGE_FIELDS.items():
        assert set(usage[key]) == fields, key
    assert usage["gpu1"]["sleeping"] is True
    assert len(usage["fans"]) == 2


def test_fake_no_fans():
    _, usage = FakeSources(no_fans=True).read()
    assert usage["fans"] == []


def test_fake_is_deterministic():
    a = FakeSources(seed=3)
    b = FakeSources(seed=3)
    for _ in range(3):
        assert a.read()[1]["cpu"]["percent"] == b.read()[1]["cpu"]["percent"]
