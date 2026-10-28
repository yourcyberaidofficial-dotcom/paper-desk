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
    result = decide("BTCUSDT", "4h", "auto", bars, now, _user())
    assert result["decision"] == "BUY"
    assert result["validation_status"] == "FAIL"
    assert result["approved"] is False
    assert result["stop"] < result["entry"] < result["target"]
    assert result["size"]["ok"] is True
    assert result["size"]["order"] is False
    assert result["filled"] is False


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


def test_gold_chart_feed_is_blocked():
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
    assert body["approved"] is False
    assert body["validation_status"] == "FAIL"
    history = client.get("/api/terminal/history").get_json()
    assert history["items"][0]["decision"] == "BUY"
    assert history["items"][0]["source"] == "user_requested"
