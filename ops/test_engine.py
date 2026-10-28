"""Gate 3 engine tests. No network and no Telegram."""

import lzma
import struct
from datetime import datetime, timezone

from ops.bars import aggregate, make_bar, to_chart_candles, validate_series
from ops.engine_eval import evaluate_snapshot
from ops.experimental import present_book
from ops.feeds import decode_dukascopy_bi5, xaus_chart
from ops.hypotheses import e1_observation, vol_break_setup
from ops.research_select import select_candidate
from ops.routing import decide_route, dispatch, style_risk
from ops.sessions import expected_gold_gap, gold_market_open, gold_signal_session
from ops.simulate import _exit, simulate


STEP = 15 * 60 * 1000
HOUR = 60 * 60 * 1000
START = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)


def _bars(count, step, start, price=100.0, symbol="BTCUSDT", interval="15m", widen=None):
    rows = []
    for index in range(count):
        open_time = start + index * step
        close = price if widen is None or index != widen else price + 5
        high = close + 0.4
        low = close - 0.4
        rows.append(make_bar(
            symbol=symbol,
            instrument="XAUUSD_SPOT" if symbol == "XAUUSD" else symbol,
            interval=interval,
            open_time_ms=open_time,
            close_time_ms=open_time + step - 1,
            open=price,
            high=high,
            low=low,
            close=close,
            volume=1,
            provider="fixture",
            source_type="fixture",
            quote_semantics="last_trade",
            retrieved_at_ms=open_time + step,
            complete=True,
            fresh=True,
        ))
    return rows


def _hours(count, start, price=100.0):
    return _bars(count, HOUR, start, price=price, interval="1h")


def test_chart_keeps_the_real_open():
    bar = _bars(1, HOUR, START, price=100, symbol="XAUUSD", interval="1h")[0]
    bar["close"] = 110
    bar["high"] = 111
    points = to_chart_candles([bar])
    assert points[0]["o"] == 100
    assert points[0]["o"] != points[0]["c"]
    bar["high"] = bar["low"] - 1
    assert to_chart_candles([bar]) == []


def _bid_ask(bars):
    for bar in bars:
        bar["quote_semantics"] = "dukascopy_xauusd_bid_ask"
        bar["ask_open"] = bar["open"] + 0.3
        bar["bid_open"] = bar["open"]
    return bars


def test_closed_gold_market_waits():
    bars = _bid_ask(_bars(80, HOUR, START, price=2000, symbol="XAUUSD", interval="1h"))
    saturday = int(datetime(2026, 1, 10, 15, tzinfo=timezone.utc).timestamp() * 1000)
    rows = evaluate_snapshot("XAUUSD", bars, [], saturday, "1h")
    assert rows[0]["state"] == "WAIT"
    assert rows[0]["reason"] == "MARKET_CLOSED"
    assert rows[0]["approved"] is False


def test_gold_cash_session_is_required():
    end_open = int(datetime(2026, 1, 15, 12, tzinfo=timezone.utc).timestamp() * 1000)
    bars = _bid_ask(_bars(80, HOUR, end_open - 79 * HOUR, price=2000, symbol="XAUUSD", interval="1h"))
    higher = _bid_ask(_bars(30, 4 * HOUR, end_open - 40 * 4 * HOUR, price=2000, symbol="XAUUSD", interval="4h"))
    now = bars[-1]["close_time_ms"] + 1000
    rows = evaluate_snapshot("XAUUSD", bars, higher, now, "1h")
    session = next(row for row in rows if row["strategy"] == "xau-session-20261027")
    assert session["state"] == "WAIT"
    assert session["reason"] == "OUTSIDE_SESSION"
    assert all(row["approved"] is False for row in rows)


def test_ohlc_not_bid_ask_does_not_run_gold_rules(monkeypatch):
    import ops.engine_eval as engine
    called = []
    monkeypatch.setattr(engine, "SETUP", {name: (lambda *args, _name=name, **kwargs: called.append(_name)) for name in engine.SETUP})
    monkeypatch.setattr(engine, "e1_observation", lambda *args, **kwargs: called.append("e1"))
    bars = _bars(80, HOUR, START, price=2000, symbol="XAUUSD", interval="1h")
    for bar in bars:
        bar["quote_semantics"] = "ohlc_not_bid_ask"
    now = bars[-1]["close_time_ms"] + 1000
    rows = evaluate_snapshot("XAUUSD", bars, bars[-30:], now, "1h")
    assert called == []
    assert len(rows) == 1
    assert rows[0]["state"] == "DATA_UNAVAILABLE"
    assert rows[0]["reason"] == "ohlc_not_bid_ask"
    assert rows[0]["state"] != "PAPER_CANDIDATE"


def test_invalid_ohlc_is_rejected():
    bar = _bars(1, STEP, START)[0]
    bar["high"] = bar["low"] - 1
    assert validate_series([bar], "15m")["invalid"] > 0


def test_partial_gold_tick_is_not_a_candle(monkeypatch):
    aligned = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
    payload = {
        "data_state": {"status": "fresh", "source": "upstream", "age_seconds": 1},
        "points": [
            {"t": aligned, "o": 4000.0, "h": 4010.0, "l": 3990.0, "c": 4005.0, "v": 10},
            {"t": aligned + 125, "o": 4005.0, "h": 4005.0, "l": 4005.0, "c": 4005.0, "v": 0},
        ],
    }
    monkeypatch.setattr("ops.feeds._get", lambda *args, **kwargs: (200, json_bytes(payload)))
    now = (aligned + HOUR // 1000) * 1000
    result = xaus_chart("1h", now_ms=now)
    assert result["ok"] is True
    assert result["partial_dropped"] == 1
    assert len(result["bars"]) == 1
    assert result["bars"][0]["open"] == 4000.0
    assert result["bars"][0]["open"] != result["bars"][0]["close"]
    assert result["quote_semantics"] == "ohlc_not_bid_ask"


def test_dukascopy_ticks_keep_bid_and_ask():
    raw = struct.pack(">IIIff", 0, 4_066_000, 4_065_500, 1.0, 2.0)
    ticks = decode_dukascopy_bi5(lzma.compress(raw), 1_700_000_000_000)
    assert ticks[0]["ask"] == 4066
    assert ticks[0]["bid"] == 4065.5
    assert ticks[0]["ask"] > ticks[0]["bid"]


def test_gold_weekend_is_a_close_not_a_hole():
    friday = datetime(2026, 1, 16, 22, 30, tzinfo=timezone.utc)
    sunday_open = datetime(2026, 1, 18, 22, 0, tzinfo=timezone.utc)
    assert gold_market_open(friday) is False
    assert gold_market_open(sunday_open) is True
    assert expected_gold_gap(int(friday.timestamp() * 1000), int(sunday_open.timestamp() * 1000))
    winter = datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)
    before = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    assert gold_signal_session(winter) is True
    assert gold_signal_session(before) is False
    assert gold_signal_session(summer) is True


def test_aggregate_does_not_invent_a_missing_hour():
    bars = _hours(4, START)
    del bars[2]
    assert aggregate(bars, "1h", "4h") == []
    full = _hours(4, START)
    built = aggregate(full, "1h", "4h")
    assert len(built) == 1
    assert built[0]["open"] == full[0]["open"]
    assert built[0]["close"] == full[-1]["close"]


def test_vol_break_needs_expansion_and_ignores_the_future():
    bars = _bars(60, STEP, START, price=100)
    higher = _hours(40, START - 10 * HOUR, price=100)
    quiet = dict(bars[50])
    quiet["close"] = 100.45
    quiet["high"] = 100.46
    quiet["low"] = 100.2
    bars[50] = quiet
    assert e1_observation(bars, 50)["direction"] == "LONG"
    assert vol_break_setup(bars, 50, higher, "BTCUSDT") is None
    loud = dict(bars[52])
    loud["close"] = 103
    loud["high"] = 104
    loud["low"] = 99
    loud["open"] = 100
    bars[52] = loud
    first = vol_break_setup(bars, 52, higher, "BTCUSDT")
    assert first["direction"] == "LONG"
    extended = bars + _bars(5, STEP, bars[-1]["open_time_ms"] + STEP, price=110)
    again = vol_break_setup(extended, 52, higher, "BTCUSDT")
    assert again["anchor_open_ms"] == first["anchor_open_ms"]
    assert again["atr"] == first["atr"]


def test_stop_fills_before_target_and_gap_uses_the_open():
    bars = _bars(5, STEP, START, price=100)
    crash = dict(bars[2])
    crash["open"] = 100
    crash["high"] = 130
    crash["low"] = 90
    bars[2] = crash
    price, reason, _index = _exit(bars, 2, "LONG", 95, 120, 3)
    assert reason == "stop"
    assert price == 95
    gap = dict(bars[2])
    gap["open"] = 94
    gap["low"] = 93
    gap["high"] = 96
    bars[2] = gap
    price, reason, _index = _exit(bars, 2, "LONG", 95, 120, 3)
    assert reason == "stop_gap"
    assert price == 94


def test_snapshot_keeps_e1_unapproved_and_off_the_book():
    bars = _bars(80, STEP, START, price=100)
    higher = _hours(50, START - 20 * HOUR, price=90)
    bars[-1] = dict(bars[-1], close=120, high=121, low=110, open=115)
    now = bars[-1]["close_time_ms"] + 1000
    rows = evaluate_snapshot("BTCUSDT", bars, higher, now, "15m")
    assert all(row["approved"] is False and row["broker"] is False and row["production"] == "WAIT_DEFAULT" for row in rows)
    assert all(row["state"] != "APPROVED_SIGNAL" for row in rows)
    e1 = next(row for row in rows if row["strategy"] == "E1-donchian-20")
    assert e1["state"] == "RESEARCH_OBSERVATION"
    assert e1["reason"] == "benchmark_failed"
    shown = present_book([{"id": "x", "type": "paper_open", "side": "LONG_BIAS"}], {"id": "x", "type": "paper_open", "side": "LONG_BIAS"})
    assert shown["open"] is None
    trades = simulate("BTCUSDT", bars, higher, "vol-break-20261027")
    assert not any(trade.get("type") == "paper_open" for trade in trades)


def test_same_event_does_not_alert_two_users():
    event = {"state": "PAPER_CANDIDATE", "event_id": "same", "expires_at_ms": 10}
    apex = {"experimental_alerts": True, "max_risk_pct": 2.5, "min_rr": 1.7, "currency": "USD", "telegram": {"verified": True, "chat_id": "1"}}
    aegis = {"experimental_alerts": False, "max_risk_pct": 0.8, "min_rr": 2.5, "currency": "NGN", "telegram": {"verified": False}}
    calls = []
    assert dispatch(event, apex, lambda *args, **kwargs: calls.append(args))["reason"] == "production_wait_default"
    assert dispatch(event, aegis, lambda *args, **kwargs: calls.append(args))["send"] is False
    assert calls == []
    assert style_risk(aegis, 2.0)["risk_pct"] == 0.5
    assert style_risk(aegis, 2.0)["rr_allowed"] is False
    assert style_risk({"max_risk_pct": 0.3, "currency": "EUR"}, 2.0)["risk_pct"] == 0.3
    approved = {
        "state": "APPROVED_SIGNAL",
        "event_id": "once",
        "expires_at_ms": 5_000,
        "strategy": "future-strategy",
        "version": "future-1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "fresh": True,
        "complete": True,
    }
    registry = [{"strategy": "future-strategy", "version": "future-1", "symbols": ["BTCUSDT"]}]
    opted = dict(apex)
    first = decide_route(approved, opted, now_ms=100, registry=registry)
    assert first["send"] is True
    assert decide_route(approved, opted, already_sent={"once"}, now_ms=100, registry=registry)["reason"] == "duplicate"
    assert decide_route(approved, opted, now_ms=9_000, registry=registry)["reason"] == "expired"
    def _slow(*args, **kwargs):
        raise TimeoutError("slow")

    failed = dispatch(approved, opted, _slow, now_ms=100, registry=registry)
    assert failed["delivered"] is False
    assert failed["reason"] == "TimeoutError"
    stale = decide_route(approved, {"experimental_alerts": True, "telegram": {"verified": False}}, now_ms=100, registry=registry)
    assert stale["reason"] == "unverified_destination"


def test_holdout_cannot_select_the_candidate():
    rows = [
        {"symbol": "BTCUSDT", "strategy": "vol-break-20261027", "split": "holdout", "judgment": "PASS", "base_mean": 0.01},
        {"symbol": "BTCUSDT", "strategy": "tf-pullback-20261027", "split": "validation", "judgment": "FAIL", "base_mean": -0.01},
    ]
    assert select_candidate(rows) == {}
    rows.append({"symbol": "ETHUSDT", "strategy": "mr-range-20261027", "split": "validation", "judgment": "PASS", "base_mean": 0.002})
    assert select_candidate(rows)["ETHUSDT"]["strategy"] == "mr-range-20261027"


def test_repeat_simulation_matches():
    bars = _bars(90, STEP, START, price=100)
    higher = _hours(40, START - 5 * HOUR, price=100)
    assert simulate("BTCUSDT", bars, higher, "mr-range-20261027") == simulate("BTCUSDT", bars, higher, "mr-range-20261027")


def json_bytes(payload):
    import json
    return json.dumps(payload).encode()
