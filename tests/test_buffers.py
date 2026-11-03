from thermo.buffers import RingBuffer, UsageBuffers, downsample
from thermo.fake import FakeSources
from thermo.model import Snapshot


def test_ring_wraps():
    rb = RingBuffer(capacity=3)
    for i in range(5):
        rb.append(float(i), float(i * 10))
    assert rb.since(0) == [(2.0, 20.0), (3.0, 30.0), (4.0, 40.0)]


def test_since_filters():
    rb = RingBuffer()
    for i in range(10):
        rb.append(float(i), 1.0)
    assert [t for t, _ in rb.since(7)] == [7.0, 8.0, 9.0]


def test_none_skipped():
    rb = RingBuffer()
    rb.append(1.0, None)
    rb.append(2.0, 5.0)
    assert rb.since(0) == [(2.0, 5.0)]


def test_downsample_300():
    pts = [(float(i), float(i % 7)) for i in range(3600)]
    out = downsample(pts, 300)
    assert len(out) == 300
    assert out[0][0] < 12 and out[-1][0] > 3600 - 13


def test_downsample_small_unchanged():
    pts = [(1.0, 2.0), (2.0, 3.0)]
    assert downsample(pts, 300) == pts


def _snapshots(n: int) -> list[Snapshot]:
    fake = FakeSources()
    out = []
    for i in range(n):
        readings, usage = fake.read()
        out.append(Snapshot(ts=1000.0 + i, readings=readings, usage=usage, headline={"cpu": 60.0}))
    return out


def test_usage_series_range():
    ub = UsageBuffers()
    snaps = _snapshots(120)
    for s in snaps:
        ub.add(s)
    now = snaps[-1].ts
    series = ub.series("cpu", 60, now)
    assert set(series) == {"percent"}
    assert len(series["percent"]) == 60


def test_usage_series_fans_and_temps():
    ub = UsageBuffers()
    for s in _snapshots(5):
        ub.add(s)
    assert set(ub.series("fans", 60, 1004.0)) == {"/lpc/0/fan/0", "/lpc/0/fan/1"}
    assert len(ub.series("temps", 60, 1004.0)["cpu"]) == 5
    assert set(ub.series("gpu0", 60, 1004.0)) == {"load_pct", "dedicated_used_gb", "shared_used_gb"}
