"""Regression tests for the G1-H4 correction."""

from desk.h4 import simulate_h4, trailing_vol


def _bars(closes):
    return [
        {"open": c, "close": c, "open_time_ms": 1_000 * i}
        for i, c in enumerate(closes)
    ]


def test_no_future_vol():
    closes = [100, 101, 102, 103, 104, 200]
    vol = trailing_vol(closes, 5, 4)
    assert vol is not None
    assert vol < 0.02


def test_zero_vol_skips():
    bars = _bars([100] * 30)
    trades = simulate_h4(bars, 10, 10, 1)
    assert trades == []


def test_cost_monotonic():
    closes = [100 + (i % 7) - 3 + i * 0.1 for i in range(80)]
    bars = _bars(closes)
    opt = simulate_h4(bars, 10, 7.5, 1)
    base = simulate_h4(bars, 10, 10, 1)
    stress = simulate_h4(bars, 10, 10, 5)
    assert len(opt) == len(base) == len(stress)
    for a, b, c in zip(opt, base, stress):
        assert a["entry_t"] == b["entry_t"] == c["entry_t"]
        assert a["pnl"] >= b["pnl"] >= c["pnl"]


def test_vol_recorded():
    closes = [100 + i * 0.2 + (i % 5) for i in range(40)]
    trades = simulate_h4(_bars(closes), 10, 10, 1)
    assert trades
    assert all(t["vol"] > 0 and t["size"] > 0 for t in trades)
