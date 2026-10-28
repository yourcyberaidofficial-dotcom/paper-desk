"""Frozen leader rules and the stored Binance history."""

from ops.bars import make_bar
from ops.history_store import ROOT, load_csv, validate_bars
from ops.leaders import choose_leader, sweep_reclaim


def _bar(index, low, close, high=None):
    step = 14_400_000
    start = 1_672_531_200_000
    open_time = start + index * step
    high = high if high is not None else max(close, low) + 1
    return make_bar(
        symbol="BTCUSDT", interval="4h", open_time_ms=open_time, close_time_ms=open_time + step - 1,
        open=close, high=high, low=low, close=close, volume=1, complete=True, fresh=True,
        provider="fixture", source_type="fixture", quote_semantics="last_trade",
    )


def test_sweep_uses_only_the_signal_bar_and_prior_day():
    bars = [_bar(i, 100, 101) for i in range(8)]
    bars[6] = _bar(6, 90, 95)
    bars[7] = _bar(7, 89, 96)
    signal = sweep_reclaim(bars, 7, [], "BTCUSDT")
    assert signal["direction"] == "LONG"
    assert signal["stop_price"] == 89
    future = [dict(bar) for bar in bars]
    future.append(_bar(8, 1, 1, 2))
    assert sweep_reclaim(bars, 7, [], "BTCUSDT")["target_price"] == sweep_reclaim(future, 7, [], "BTCUSDT")["target_price"]
    assert sweep_reclaim(bars, 7, [], "XAUUSD") is None


def test_a_failed_rank_is_not_approval():
    rows = [
        {"strategy": "a", "judgment": "FAIL", "blocked": [], "folds": [{"trades": 12, "base_mean": -0.01}, {"trades": 12, "base_mean": -0.002}, {"trades": 12, "base_mean": -0.02}]},
        {"strategy": "b", "judgment": "FAIL", "blocked": [], "folds": [{"trades": 12, "base_mean": -0.05}, {"trades": 12, "base_mean": -0.04}, {"trades": 12, "base_mean": -0.03}]},
    ]
    chosen = choose_leader(rows)
    assert chosen["strategy"] == "a"
    assert chosen["approved"] is False
    assert chosen["status"] == "research_leader_failed"
    blocked = choose_leader([{"strategy": "a", "judgment": "BLOCKED", "blocked": ["sample"], "folds": [{"trades": 1, "base_mean": 1}, {"trades": 1, "base_mean": 1}, {"trades": 1, "base_mean": 1}]}])
    assert blocked["approved"] is False
    assert blocked["strategy"] is None


def test_stored_bars_reject_a_gap_and_a_forming_candle():
    step = 14_400_000
    start = 1_672_531_200_000
    bars = []
    for index in (0, 1, 3):
        open_time = start + index * step
        bars.append({"symbol": "BTCUSDT", "interval": "4h", "open_time_ms": open_time, "close_time_ms": open_time + step - 1, "open": 1, "high": 2, "low": 1, "close": 1.5, "complete": True})
    report = validate_bars(bars, "4h")
    assert report["gaps"] == 1
    assert report["ok"] is False
    bars[0]["complete"] = False
    assert validate_bars(bars[:1], "4h")["forming"] == 1


def test_saved_binance_history_has_no_gaps():
    for symbol in ("BTCUSDT", "ETHUSDT"):
        bars = load_csv(ROOT / f"{symbol}-4h.csv", symbol, "4h", "binance-public", "last_trade")
        report = validate_bars(bars, "4h")
        assert report["ok"] is True
        assert report["bars"] > 5000
        assert bars[0]["open_time_ms"] == 1672531200000
        assert bars[0]["quote_semantics"] == "last_trade"
