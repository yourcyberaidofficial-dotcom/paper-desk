"""Gate 4 data and research tests. No network and no Telegram."""

import json
import lzma
import struct
from datetime import datetime, timezone

from ops.bars import aggregate, make_bar
from ops.engine_eval import PRODUCTION
from ops.feeds import decode_dukascopy_m1
from ops.gate4_hypotheses import CRYPTO, GOLD, SETUP as GATE4_SETUP, fail_break_setup
from ops.gate4_research import score_symbol, split_bars
from ops.hypotheses import FAMILIES, GOLD_COST
from ops.research_select import judge, select_candidate
from ops.routing import dispatch
from ops.simulate import simulate
from ops.xau_bars import hours_from_minutes

HOUR = 60 * 60 * 1000
START = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)


def _minute(hour, offset, bid, ask):
    stamp = hour + offset * 60 * 1000
    return (
        {"time_ms": stamp, "open": bid, "high": bid + 0.4, "low": bid - 0.2, "close": bid + 0.1, "volume": 1},
        {"time_ms": stamp, "open": ask, "high": ask + 0.4, "low": ask - 0.2, "close": ask + 0.1, "volume": 1},
    )


def _hour_minutes(hour, bid=2000.0, ask=2000.4):
    bids, asks = [], []
    for offset in range(60):
        left, right = _minute(hour, offset, bid, ask)
        bids.append(left)
        asks.append(right)
    return bids, asks


def test_m1_keeps_bid_and_ask_and_real_open():
    day = int(datetime(2024, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
    bid_raw = struct.pack(">IIIIIf", 0, 2_635_595, 2_635_495, 2_635_255, 2_635_725, 0.02)
    ask_raw = struct.pack(">IIIIIf", 0, 2_635_985, 2_635_905, 2_635_632, 2_636_155, 0.05)
    bid = decode_dukascopy_m1(lzma.compress(bid_raw), day)
    ask = decode_dukascopy_m1(lzma.compress(ask_raw), day)
    assert bid[0]["open"] == 2635.595
    assert bid[0]["open"] != bid[0]["close"]
    assert bid[0]["high"] == 2635.725 and bid[0]["low"] == 2635.255
    assert ask[0]["open"] == 2635.985
    assert ask[0]["open"] > bid[0]["open"]
    built = hours_from_minutes(bid, ask)
    assert built["bars"] == []
    assert built["skipped_hours"] == 1


def test_full_hour_preserves_both_sides_without_copying_close():
    bids, asks = _hour_minutes(START)
    built = hours_from_minutes(bids, asks)
    assert len(built["bars"]) == 1
    bar = built["bars"][0]
    assert bar["open"] == bar["bid_open"] == 2000.0
    assert bar["close"] == bar["bid_close"] == 2000.1
    assert bar["open"] != bar["close"]
    assert bar["ask_open"] == 2000.4
    assert bar["ask_close"] != bar["bid_close"]
    assert bar["quote_semantics"] == "dukascopy_xauusd_bid_ask"


def test_gap_duplicate_empty_and_crossed_do_not_invent_a_bar():
    assert hours_from_minutes([], [])["bars"] == []
    bids, asks = _hour_minutes(START)
    assert hours_from_minutes(bids[:-1], asks)["bars"] == []
    dup = list(bids)
    dup.append(dict(bids[0]))
    built = hours_from_minutes(dup, asks)
    assert built["bars"] == []
    assert built["duplicate_minutes"] == 1
    crossed_asks = [dict(row, open=row["open"] - 10, close=row["close"] - 10) for row in asks]
    assert hours_from_minutes(bids, crossed_asks)["bars"] == []
    bad = lzma.compress(b"not-a-record")
    try:
        decode_dukascopy_m1(bad, START)
        raised = False
    except ValueError:
        raised = True
    assert raised is True
    assert decode_dukascopy_m1(lzma.compress(b""), START) == []


def test_aggregate_keeps_separate_sides():
    first = hours_from_minutes(*_hour_minutes(START, 2000, 2001))["bars"][0]
    second = hours_from_minutes(*_hour_minutes(START + HOUR, 2010, 2011))["bars"][0]
    third = hours_from_minutes(*_hour_minutes(START + 2 * HOUR, 2005, 2006))["bars"][0]
    fourth = hours_from_minutes(*_hour_minutes(START + 3 * HOUR, 2008, 2009))["bars"][0]
    higher = aggregate([first, second, third, fourth], "1h", "4h")
    assert len(higher) == 1
    assert higher[0]["bid_open"] == 2000
    assert higher[0]["ask_open"] == 2001
    assert higher[0]["bid_close"] == 2008.1
    assert higher[0]["open"] != higher[0]["ask_open"]


def test_side_aware_long_pays_ask_and_stop_wins():
    bars = []
    for index in range(40):
        open_time = START + index * HOUR
        bars.append(make_bar(
            symbol="XAUUSD", instrument="XAUUSD_DUKASCOPY", interval="1h",
            open_time_ms=open_time, close_time_ms=open_time + HOUR - 1,
            open=100, high=101, low=99, close=100,
            bid_open=100, bid_high=101, bid_low=99, bid_close=100,
            ask_open=100.5, ask_high=101.5, ask_low=99.5, ask_close=100.5,
            provider="fixture", source_type="fixture", quote_semantics="dukascopy_xauusd_bid_ask",
            retrieved_at_ms=open_time, complete=True, fresh=False,
        ))
    def always_long(rows, index, higher, symbol):
        del rows, higher, symbol
        if index != 30:
            return None
        return {"strategy": "fixture", "direction": "LONG", "stop_price": 99.2, "reward_risk": 2, "hold_bars": 4, "target_mode": "rr"}
    trades = simulate("XAUUSD", bars, [], "fixture", execution="bid_ask", slippage_usd=0.10, setup_map={"fixture": always_long})
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry"] == 100.5
    assert trade["reason"] == "stop"
    assert trade["exit"] == 99.2
    gross = (99.2 - 100.5) / 100.5
    assert abs(trade["gross"] - gross) < 1e-12
    assert abs(trade["net"] - (gross - 0.20 / 100.5)) < 1e-12
    assert trade["execution"] == "bid_ask"


def test_fail_break_ignores_the_future_and_is_deterministic():
    bars = []
    for index in range(40):
        open_time = START + index * 15 * 60 * 1000
        bars.append(make_bar(
            symbol="BTCUSDT", instrument="BTCUSDT", interval="15m",
            open_time_ms=open_time, close_time_ms=open_time + 15 * 60 * 1000 - 1,
            open=100, high=100.4, low=99.6, close=100, volume=1,
            provider="fixture", source_type="fixture", quote_semantics="last_trade",
            retrieved_at_ms=open_time, complete=True, fresh=True,
        ))
    probe = dict(bars[30])
    probe.update(open=100, high=102, low=99.5, close=100.2)
    bars[30] = probe
    # Failed downside break: low under the prior 20-bar low, close back inside and above open.
    prior_low = min(bar["low"] for bar in bars[10:30])
    probe["low"] = prior_low - 1
    probe["close"] = 100.2
    probe["open"] = 100.0
    probe["high"] = 100.4
    bars[30] = probe
    first = fail_break_setup(bars, 30, [], "BTCUSDT")
    assert first["direction"] == "LONG"
    future = dict(bars[31], close=50, low=40, high=60, open=55)
    changed = list(bars)
    changed[31] = future
    assert fail_break_setup(changed, 30, [], "BTCUSDT")["stop_price"] == first["stop_price"]
    assert simulate("BTCUSDT", bars, [], "fail-break-20261028", setup_map=GATE4_SETUP) == simulate("BTCUSDT", bars, [], "fail-break-20261028", setup_map=GATE4_SETUP)


def test_splits_do_not_open_holdout_for_a_failed_rule(monkeypatch):
    bars = []
    for index in range(100):
        open_time = START + index * HOUR
        bars.append(make_bar(
            symbol="BTCUSDT", instrument="BTCUSDT", interval="1h",
            open_time_ms=open_time, close_time_ms=open_time + HOUR - 1,
            open=100, high=101, low=99, close=100, volume=1,
            provider="fixture", source_type="fixture", quote_semantics="last_trade",
            retrieved_at_ms=open_time, complete=True, fresh=True,
        ))
    dev, val, hold = split_bars(bars)
    assert dev[-1]["open_time_ms"] < val[0]["open_time_ms"] < hold[0]["open_time_ms"]
    assert len(dev) == 60 and len(val) == 20 and len(hold) == 20
    rows, selection = score_symbol("BTCUSDT", bars, bars, ["fail-break-20261028"], "last_trade", False)
    assert selection["holdout"] == "NOT_OPENED"
    assert all(row["split"] != "holdout" for row in rows)
    assert set(FAMILIES).isdisjoint(CRYPTO)
    assert set(FAMILIES).isdisjoint(GOLD)
    assert GOLD_COST["measured_bid_ask"] is False
    assert PRODUCTION == "WAIT_DEFAULT"


def test_pass_opens_holdout_and_failure_does_not(monkeypatch):
    bars = []
    for index in range(100):
        open_time = START + index * HOUR
        bars.append({"open_time_ms": open_time, "close_time_ms": open_time + HOUR - 1, "interval": "1h"})
    dev, val, hold = split_bars(bars)

    def fake(symbol, source, higher, strategy, stress=False, execution="last_trade", slippage_usd=0.0, setup_map=None):
        del symbol, higher, strategy, stress, execution, slippage_usd, setup_map
        end = source[-1]["open_time_ms"]
        window_start = hold[0]["open_time_ms"] if end >= hold[0]["open_time_ms"] else val[0]["open_time_ms"]
        out = []
        for offset in range(40):
            stamp = window_start + offset * 1000
            out.append({
                "strategy": "fail-break-20261028",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "signal_open_time_ms": stamp,
                "entry_open_time_ms": stamp,
                "net": 0.01,
            })
        return out

    monkeypatch.setattr("ops.gate4_research.simulate", fake)
    rows, selection = score_symbol("BTCUSDT", bars, [], ["fail-break-20261028"], "last_trade", None)
    assert selection["holdout"] == "SCORED"
    assert any(row["split"] == "holdout" and row["judgment"] == "PASS" for row in rows)

    def lose(symbol, source, higher, strategy, stress=False, execution="last_trade", slippage_usd=0.0, setup_map=None):
        made = fake(symbol, source, higher, strategy, stress, execution, slippage_usd, setup_map)
        for trade in made:
            trade["net"] = -0.01
        return made

    monkeypatch.setattr("ops.gate4_research.simulate", lose)
    rows, selection = score_symbol("BTCUSDT", bars, [], ["fail-break-20261028"], "last_trade", None)
    assert selection["holdout"] == "NOT_OPENED"
    assert all(row["split"] != "holdout" for row in rows)
    summary = {"trades": 40, "base_mean": 0.01, "stress_mean": 0.01, "normal_95_lower": 0.001, "equity": 1.2, "max_drawdown": 0.01, "worst_loss_streak": 1}
    halves = {"first": {"trades": 20, "base_mean": 0.01}, "second": {"trades": 20, "base_mean": 0.01}}
    assert judge(summary, halves, "BTCUSDT", measured_bid_ask=True)[0] == "PASS"
    assert "no_measured_bid_ask" in judge(summary, halves, "XAUUSD", measured_bid_ask=False)[2]
    assert select_candidate([{"symbol": "BTCUSDT", "strategy": "old", "split": "holdout", "judgment": "PASS", "base_mean": 1}]) == {}


def test_unapproved_event_still_does_not_send():
    calls = []
    event = {"state": "PAPER_CANDIDATE", "event_id": "gate4", "expires_at_ms": 10}
    profile = {"experimental_alerts": True, "telegram": {"verified": True, "chat_id": "1"}}
    result = dispatch(event, profile, lambda *args, **kwargs: calls.append(args))
    assert result["send"] is False
    assert calls == []
    assert "token" not in json.dumps(result)
