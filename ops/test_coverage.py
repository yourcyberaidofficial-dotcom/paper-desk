"""Twelve-pair coverage. No network."""

from ops.bars import make_bar
from ops.feeds import aggregate_spot_samples, xaus_spot_bars
from ops.terminal_route import handle_signal
from ops.terminal_signal import decide
from ops.worker import COVERAGE


def test_coverage_is_twelve_distinct_pairs():
    assert len(COVERAGE) == 12
    assert len(set(COVERAGE)) == 12
    for symbol in ("BTCUSDT", "ETHUSDT", "XAUUSD"):
        for interval in ("1m", "3m", "15m", "1h"):
            assert (symbol, interval) in COVERAGE


def test_a_sparse_sample_does_not_become_a_15m_bar():
    now = 1_700_003_600_000
    bucket = now - (now % 900_000) - 900_000
    points = [
        {"t": bucket // 1000, "p": 2000},
        {"t": bucket // 1000 + 300, "p": 2004},
        {"t": bucket // 1000 + 600, "p": 2001},
        {"t": bucket // 1000 + 900, "p": 9},
    ]
    bars = aggregate_spot_samples(points, "15m", now)
    assert len(bars) == 1
    assert bars[0]["interval"] == "15m"
    assert bars[0]["open"] == 2000
    assert bars[0]["high"] == 2004
    assert bars[0]["close"] == 2001
    assert bars[0]["quote_semantics"] == "spot_sample_not_bid_ask"
    assert xaus_spot_bars("1m", now_ms=now)["reason"] == "sample_is_5m"
    assert xaus_spot_bars("3m", now_ms=now)["bars"] == []


def test_gold_minute_is_not_invented_and_a_1m_crypto_plan_stays_on_1m():
    def boom(*args, **kwargs):
        raise AssertionError("gold loader should not run")
    status, body = handle_signal("user-a", {"symbol": "XAUUSD", "interval": "1m", "strategy": "auto"}, 1_700_000_000_000, ohlc_loader=boom)
    assert status == 200
    assert body["blocked"] == "sample_is_5m"
    assert body["reference_price"] is None
    assert body["order"] is False
    start = 1_700_000_000_000 - (1_700_000_000_000 % 60_000)
    bars = []
    for index in range(80):
        close = 200 - index * 0.15
        open_time = start + index * 60_000
        bars.append(make_bar(
            symbol="BTCUSDT", interval="1m", open_time_ms=open_time, close_time_ms=open_time + 59_999,
            open=close, high=close + 0.3, low=close - 0.3, close=close, volume=1, complete=True, fresh=True,
            provider="fixture", source_type="fixture", quote_semantics="last_trade",
        ))
    last = bars[-1]["close"]
    bars[-1] = make_bar(
        symbol="BTCUSDT", interval="1m", open_time_ms=bars[-1]["open_time_ms"], close_time_ms=bars[-1]["close_time_ms"],
        open=last, high=last + 2, low=last - 0.4, close=last - 0.05, volume=1, complete=True, fresh=True,
        provider="fixture", source_type="fixture", quote_semantics="last_trade",
    )
    now = bars[-1]["close_time_ms"] + 1000
    result = decide("BTCUSDT", "1m", "auto", bars, now, {"profile": {"signal_style": "apex_momentum", "capital": 10000, "currency": "USD"}, "plan": {"risk_per_trade_percent": 2.5}})
    assert result["interval"] == "1m"
    assert "1m" in result["reason"]
    assert result["decision"] == "SELL"
    assert result["stop"] > result["entry"] > result["target"]
    assert result["approved"] is False
