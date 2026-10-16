from ops.e1 import e1_side


def test_wait_inside_range():
    bars = [{"high": 10, "low": 9, "close": 9.5} for _ in range(21)]
    assert e1_side(bars) == "WAIT"


def test_long_and_short():
    bars = [{"high": 10, "low": 9, "close": 9.5} for _ in range(20)]
    bars.append({"high": 12, "low": 11, "close": 11})
    assert e1_side(bars) == "LONG_BIAS"
    bars[-1] = {"high": 8, "low": 7, "close": 7}
    assert e1_side(bars) == "SHORT_BIAS"


def test_no_future():
    bars = [{"high": 10 + i, "low": 9 + i, "close": 9.5 + i} for i in range(21)]
    assert e1_side(bars) in {"WAIT", "LONG_BIAS", "SHORT_BIAS"}
