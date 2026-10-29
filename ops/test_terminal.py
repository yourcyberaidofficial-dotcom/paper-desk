"""Generate Signal decisions. Feeds are fixtures except where a test says otherwise."""

import time

from ops.bars import make_bar
from ops.terminal_signal import decide, read_history, stamp


def _flat(index, close=100, high=100.2, low=99.9, interval="4h", start=None):
    step = 14_400_000 if interval == "4h" else 3_600_000
    if start is None:
        start = 1_700_000_000_000 - (1_700_000_000_000 % step)
    open_time = start + index * step
    return make_bar(
        symbol="BTCUSDT", interval=interval, open_time_ms=open_time, close_time_ms=open_time + step - 1,
        open=close, high=high, low=low, close=close, volume=1, complete=True, fresh=True,
        provider="fixture", source_type="fixture", quote_semantics="last_trade",
    )


def _compress_bars(start=None):
    bars = []
    for index in range(50):
        if index < 38:
            bars.append(_flat(index, close=100, high=110, low=90, start=start))
        else:
            bars.append(_flat(index, close=100, high=100.4, low=99.8, start=start))
    bars[-1] = _flat(49, close=106, high=107, low=100, start=start)
    return bars


def _user(capital=1000, risk=1.0, style="orion_balance"):
    return {"profile": {"capital": capital, "currency": "USD", "signal_style": style}, "plan": {"risk_per_trade_percent": risk}}


def test_buy_is_labelled_unvalidated_and_sized():
    bars = _compress_bars()
    now = bars[-1]["close_time_ms"] + 1000
    result = decide("BTCUSDT", "4h", "compress-break-4h-20261028", bars, now, _user())
    assert result["decision"] == "BUY"
    assert result["decision_label"] == "BUY"
    assert result["validation_status"] == "FAIL"
    assert result["approved"] is False
    assert result["eligible_for_alert"] is False
    assert result["stop"] < result["entry"] < result["target"]
    assert result["size"]["ok"] is True
    assert result["size"]["order"] is False
    assert result["filled"] is False


def test_auto_shows_a_failed_rule_match_without_approving_it():
    bars = _compress_bars()
    now = bars[-1]["close_time_ms"] + 1000
    result = decide("BTCUSDT", "4h", "auto", bars, now, _user())
    assert result["decision"] == "BUY"
    assert result["decision_label"] == "BUY · Experimental"
    assert result["runtime_status"] == "experimental"
    assert result["auto_selected"] is False
    assert result["approved"] is False
    assert result["eligible_for_alert"] is False
    assert result["validation_status"] == "FAIL"
    assert result["stop"] < result["entry"] < result["target"]
    assert result["experimental_match"]["approved"] is False
    assert result["size"]["order"] is False
    assert "not an approved trade" in result["reason"]
    assert result["persona"] == "orion_precision"


def test_aegis_keeps_the_plan_but_does_not_size_below_its_floor():
    bars = _compress_bars()
    now = bars[-1]["close_time_ms"] + 1000
    result = decide("BTCUSDT", "4h", "auto", bars, now, _user(style="aegis_shield"))
    assert result["decision"] == "BUY"
    assert result["approved"] is False
    assert result["entry"] is not None
    assert result["persona_release"] is False
    assert result["size"]["ok"] is False
    assert result["size"]["order"] is False
    assert "Aegis Shield" in result["reason"]


def test_wait_explains_the_failed_condition_and_ignores_risk_style():
    bars = [_flat(i) for i in range(50)]
    now = bars[-1]["close_time_ms"] + 1000
    quiet = decide("BTCUSDT", "4h", "auto", bars, now, _user(style="apex_momentum", risk=2.5))
    assert quiet["decision"] == "WAIT"
    assert "ATR" in quiet["reason"] or "high" in quiet["reason"]
    assert quiet["approved"] is False


def test_stale_or_missing_feed_does_not_invent_a_trade():
    missing = decide("BTCUSDT", "4h", "auto", [], 1, _user())
    assert missing["decision"] == "WAIT"
    assert missing["reference_price"] is None
    bars = _compress_bars()
    stale = decide("BTCUSDT", "4h", "auto", bars, bars[-1]["close_time_ms"] + 10 * 14_400_000, _user())
    assert stale["decision"] == "WAIT"
    assert stale["fresh"] is False
    assert stale.get("entry") is None


def test_sell_exits_a_recorded_idea_and_is_not_a_short():
    bars = [_flat(i, close=90, high=91, low=89) for i in range(50)]
    now = bars[-1]["close_time_ms"] + 1000
    prior = {"decision": "BUY", "stop": 95, "target": 120, "hold_bars": 12, "bar_open_ms": bars[0]["open_time_ms"], "strategy": "compress-break-4h-20261028"}
    result = decide("BTCUSDT", "4h", "auto", bars, now, _user(), prior)
    assert result["decision"] == "SELL"
    assert "not a spot short" in result["reason"]
    assert result["filled"] is False


def test_a_shorter_request_is_judged_on_those_candles():
    bars = []
    for index in range(80):
        close = 200 - index * 0.15
        bars.append(_flat(index, close=close, high=close + 0.3, low=close - 0.3, interval="15m"))
    last = bars[-1]["close"]
    bars[-1] = _flat(79, close=last - 0.05, high=last + 2, low=last - 0.4, interval="15m")
    now = bars[-1]["close_time_ms"] + 1000
    result = decide("BTCUSDT", "15m", "auto", bars, now, _user())
    assert result["interval"] == "15m"
    assert result["strategy"] == "interval-reading"
    assert result.get("blocked") != "timeframe"
    assert result["decision"] == "SELL"
    assert result["decision_label"] == "SELL · Short idea"
    assert result["sell_meaning"] == "short_idea"
    assert result["approved"] is False
    assert result["eligible_for_alert"] is False
    assert result["order"] is False
    assert result["stop"] > result["entry"] > result["target"]
    assert "No broker order" in result["reason"]
    assert "not an exit of a long" in result["reason"]
    assert "15m" in result["reason"]


def test_a_named_4h_rule_is_not_run_on_15m():
    bars = [_flat(i, interval="15m") for i in range(70)]
    now = bars[-1]["close_time_ms"] + 1000
    result = decide("BTCUSDT", "15m", "compress-break-4h-20261028", bars, now, _user())
    assert result["blocked"] == "timeframe"
    assert result["decision_label"] == "BLOCKED"
    assert result.get("entry") is None
    assert result["approved"] is False


def test_gold_spot_ohlc_is_read_and_london_is_not(now=None):
    bars = []
    for index in range(80):
        close = 2000 + index * 0.4
        bars.append(_flat(index, close=close, high=close + 0.5, low=close - 0.5, interval="1h"))
    for bar in bars:
        bar["symbol"] = "XAUUSD"
        bar["quote_semantics"] = "ohlc_not_bid_ask"
    now = bars[-1]["close_time_ms"] + 1000
    quote = {"ok": True, "bid": 2032.0, "ask": 2032.4, "spread": 0.4, "timestamp_ms": now, "platform": "fixture", "spread_profile": "premium", "provider": "fixture"}
    result = decide("XAUUSD", "1h", "auto", bars, now, _user(), live_quote=quote)
    assert result.get("blocked") != "quote_not_bid_ask"
    assert result["strategy"] == "gold-ohlc-reading"
    assert result["approved"] is False
    assert result["eligible_for_alert"] is False
    assert "London rule was not calculated" in result["reason"]
    assert "spot chart" in result["reason"]
    assert "2032" in result["reason"]
    named = decide("XAUUSD", "1h", "london-reclaim-1h-20261028", bars, now, _user(), live_quote=quote)
    assert named["blocked"] == "quote_not_bid_ask"
    assert named.get("entry") is None
    far = dict(quote, bid=1900.0, ask=1900.4, spread=0.4)
    diverged = decide("XAUUSD", "1h", "auto", bars, now, _user(), live_quote=far)
    assert diverged["quote_alignment"] == "diverged"
    assert "not treated as one price" in diverged["reason"]
    assert diverged["reference_price"] != 1900


def test_an_uptrend_without_a_trigger_is_a_watch_not_a_buy():
    bars = []
    for index in range(80):
        close = 100 + index * 0.3
        bars.append(_flat(index, close=close, high=close + 0.2, low=close - 0.2, interval="15m"))
    now = bars[-1]["close_time_ms"] + 1000
    result = decide("BTCUSDT", "15m", "auto", bars, now, _user())
    assert result["decision"] in {"WAIT", "BUY"}
    assert result["approved"] is False
    if result["decision"] == "BUY":
        assert result["stop"] < result["entry"] < result["target"]
    else:
        assert result["decision_label"] in {"WAIT", "WATCH"}
        if result["decision_label"] == "WATCH":
            assert result["entry"] is None
            assert result["watch_stop"] < result["watch_entry"] < result["watch_target"]
            assert "not an entry" in result["reason"]


def test_range_expansion_is_a_separate_long_plan():
    bars = []
    for index in range(70):
        close = 100 + (0.2 if index % 2 else -0.2)
        bars.append(_flat(index, close=close, high=101, low=99, interval="15m"))
    bars[-1] = _flat(69, close=104, high=104.4, low=101.2, interval="15m")
    now = bars[-1]["close_time_ms"] + 1000
    result = decide("ETHUSDT", "15m", "auto", bars, now, _user())
    assert result["decision"] == "BUY"
    assert result["decision_label"] == "BUY · Experimental"
    assert "Range expansion" in result["reason"]
    assert result["stop"] < result["entry"] < result["target"]
    assert result["approved"] is False
    assert result["order"] is False


def test_gold_chart_and_quote_are_not_forced_into_one_price():
    bar = _flat(0, interval="1h")
    bar["symbol"] = "XAUUSD"
    bar["quote_semantics"] = "ohlc_not_bid_ask"
    now = bar["close_time_ms"] + 1000
    result = decide("XAUUSD", "1h", "auto", [bar], now, _user())
    assert result["decision"] == "WAIT"
    assert result["blocked"] == "quote_not_bid_ask"


def test_history_is_private_and_the_same_bar_is_not_duplicated(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    bars = _compress_bars()
    now = bars[-1]["close_time_ms"] + 1000
    first = stamp("ada", decide("BTCUSDT", "4h", "auto", bars, now, _user()))
    second = stamp("ada", decide("BTCUSDT", "4h", "auto", bars, now, _user()))
    other = stamp("bea", decide("ETHUSDT", "4h", "auto", [_flat(i, close=100) for i in range(20)], now, _user()))
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert len(read_history("ada")) == 1
    assert len(read_history("bea")) == 1
    assert read_history("ada")[0]["symbol"] == "BTCUSDT"
    assert other["decision"] == "WAIT"


def test_terminal_route_requires_a_user_and_uses_completed_bars(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.app import app
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    created = users.register("ada", "password-s")
    users.update_profile(created["id"], {"capital": 1000, "currency": "USD", "signal_style": "orion_balance"})
    now = int(time.time() * 1000)
    bars = _compress_bars(now - 50 * 14_400_000)
    monkeypatch.setattr("ops.feeds.binance_bars", lambda *args, **kwargs: {"ok": True, "bars": bars})
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/api/terminal/signal", json={"symbol": "BTCUSDT", "interval": "4h", "strategy": "auto"}).status_code == 401
    with client.session_transaction() as sess:
        sess["user_id"] = created["id"]
        sess["user_exp"] = time.time() + 3600
    response = client.post("/api/terminal/signal", json={"symbol": "BTCUSDT", "interval": "4h", "strategy": "auto"})
    body = response.get_json()
    assert response.status_code == 200
    assert body["decision"] == "BUY"
    assert body["decision_label"] == "BUY · Experimental"
    assert body["approved"] is False
    assert body["eligible_for_alert"] is False
    assert body["validation_status"] == "FAIL"
    assert body["entry"] is not None
    assert body["experimental_match"]["decision"] == "BUY"
    history = client.get("/api/terminal/history").get_json()
    assert history["items"][0]["decision"] == "BUY"
    assert history["items"][0]["source"] == "user_requested"
