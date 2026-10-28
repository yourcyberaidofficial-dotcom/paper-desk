"""Daily rules stay unapproved, and a gold snapshot is not a candle."""

from ops.bars import make_bar
from ops.daily_rules import dip_in_trend
from ops.gold_live import parse_swissquote
from ops.terminal_signal import auto_strategy, decide


def _day(index, close, low=None):
    start = 1_672_531_200_000
    step = 86_400_000
    open_time = start + index * step
    low = close - 1 if low is None else low
    return make_bar(
        symbol="BTCUSDT", interval="1d", open_time_ms=open_time, close_time_ms=open_time + step - 1,
        open=close, high=close + 1, low=low, close=close, volume=1, complete=True, fresh=True,
        provider="fixture", source_type="fixture", quote_semantics="last_trade",
    )


def test_a_two_percent_dip_above_the_average_is_the_only_entry():
    bars = [_day(i, 100 + i * 0.1) for i in range(101)]
    assert dip_in_trend(bars, 100, [], "BTCUSDT") is None
    bars[-1] = _day(100, bars[-2]["close"] * 0.97, low=bars[-2]["close"] * 0.96)
    signal = dip_in_trend(bars, 100, [], "BTCUSDT")
    assert signal["direction"] == "LONG"
    assert signal["strategy"] == "dip-in-trend-1d-20261028"
    below = [_day(i, 50) for i in range(101)]
    below[-1] = _day(100, below[-2]["close"] * 0.97)
    assert dip_in_trend(below, 100, [], "BTCUSDT") is None


def test_auto_keeps_the_less_bad_failed_rule():
    assert auto_strategy("BTCUSDT") == "compress-break-4h-20261028"
    assert auto_strategy("ETHUSDT") == "sweep-reclaim-4h-20261028"
    assert auto_strategy("XAUUSD") == "london-reclaim-1h-20261028"


def test_a_bid_ask_snapshot_cannot_become_a_buy():
    quote = parse_swissquote(
        [{"topo": {"platform": "SwissquoteLtd"}, "ts": 1_000_000, "spreadProfilePrices": [{"spreadProfile": "premium", "bid": 100.0, "ask": 100.4}]}],
        1_000_000,
    )
    assert quote["fresh"] is True
    skewed = parse_swissquote(
        [{"topo": {"platform": "SwissquoteLtd"}, "ts": 1_001_000, "spreadProfilePrices": [{"spreadProfile": "premium", "bid": 100.0, "ask": 100.4}]}],
        1_000_000,
    )
    assert skewed["fresh"] is True
    future = parse_swissquote(
        [{"topo": {"platform": "SwissquoteLtd"}, "ts": 1_120_000, "spreadProfilePrices": [{"spreadProfile": "premium", "bid": 100.0, "ask": 100.4}]}],
        1_000_000,
    )
    assert future["fresh"] is False
    assert quote["not_a_candle"] is True
    result = decide("XAUUSD", "1h", "auto", [], 1_000_000, {}, live_quote=quote)
    assert result["decision"] == "WAIT"
    assert result["blocked"] == "snapshot_not_candle"
    assert result["reference_price"] is None
    assert result["approved"] is False
    assert result["validation_status"] == "BLOCKED"
    assert "100.4" in result["reason"]
    assert parse_swissquote([{"ts": 1, "spreadProfilePrices": [{"bid": 10, "ask": 9}]}], 1)["ok"] is False
