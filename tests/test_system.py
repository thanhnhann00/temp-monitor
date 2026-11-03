from thermo.sources.system import RateCounter, cpu_usage, memory


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_rate_counter():
    totals = iter([(0, 0), (2_000_000, 1_000_000)])
    clock = Clock()
    rc = RateCounter(lambda: next(totals), clock=clock)
    assert rc.sample() == (0.0, 0.0)
    clock.t = 2
    assert rc.sample() == (1_000_000.0, 500_000.0)


def test_rate_counter_counter_reset():
    totals = iter([(5_000, 5_000), (1_000, 1_000)])
    clock = Clock()
    rc = RateCounter(lambda: next(totals), clock=clock)
    rc.sample()
    clock.t = 1
    assert rc.sample() == (0.0, 0.0)


def test_cpu_usage_fields():
    u = cpu_usage()
    assert set(u) == {"percent", "processes", "threads", "uptime_s"}
    assert u["processes"] > 0 and u["threads"] >= u["processes"]


def test_memory_fields():
    m = memory()
    assert set(m) == {"used_gb", "total_gb", "available_gb", "percent", "pagefile_used_gb"}
    assert 0 < m["used_gb"] < m["total_gb"]
