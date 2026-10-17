from ops.history import coverage_status


def test_more_than_20000_is_not_failed():
    bars = [{"open_time_ms": i, "close_time_ms": i + 1} for i in range(25000)]
    assert coverage_status(bars, bars[-1]["close_time_ms"] + 1000, "15m") == "COMPLETE"


def test_old_end_is_partial():
    bars = [{"open_time_ms": 1, "close_time_ms": 2}]
    assert coverage_status(bars, 10_000_000_000, "15m") == "PARTIAL"
