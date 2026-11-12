"""Signal cycle, Kraken gate, derived 3m bars, and the local AI boundary.

Fixtures are not live market evidence. No socket is opened unless a test
supplies a transport.
"""

import json
from datetime import datetime, timedelta, timezone


def _grant(tmp_path, **changes):
    today = datetime.now(timezone.utc).date()
    body = {
        "provider": "Kraken",
        "product": "ohlc",
        "instruments": ["BTCUSDT"],
        "timeframes": ["15m"],
        "capabilities": ["candle_display"],
        "terms_version": "test-grant",
        "clause": "owner recorded this fixture grant for the unit test only",
        "verified_by": "unit-test",
        "verified_on": today.isoformat(),
        "review_due": (today + timedelta(days=30)).isoformat(),
        "redistribution": "test-only",
    }
    body.update(changes)
    path = tmp_path / "rights"
    path.mkdir(parents=True, exist_ok=True)
    (path / "kraken_public_ohlc.json").write_text(json.dumps(body), encoding="utf-8")


def _payload(count=40):
    step = 900
    start = 1_700_000_000 - (1_700_000_000 % step)
    rows = []
    for index in range(count + 1):
        price = 100 + index * 0.1
        rows.append([start + index * step, price, price + 1, price - 0.4, price + 0.2, price, 1, 1])
    return {"error": [], "result": {"XBTUSDT": rows, "last": start + count * step}}, start + count * step


def test_kraken_does_not_open_a_socket_without_a_grant(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.kraken_public import authorized_bars

    def transport(url, timeout):
        raise AssertionError(url)

    refused = authorized_bars("BTCUSDT", "15m", 1, transport=transport)
    assert refused["called"] is False
    assert refused["bars"] == []
    assert authorized_bars("BTCUSDT", "3m", 1, transport=transport)["called"] is False
    assert authorized_bars("XAUUSD", "1h", 1, transport=transport)["called"] is False
    assert "BTC/USD" not in json.dumps(refused)


def test_a_grant_cannot_verify_binance_or_invent_a_native_3m(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    _grant(tmp_path)
    from ops.entitlements import decide_use

    assert decide_use("kraken_public_ohlc", "candle_display", symbol="BTCUSDT", interval="15m")["verified"] is True
    assert decide_use("kraken_public_ohlc", "candle_display", symbol="ETHUSDT", interval="15m")["verified"] is False
    assert decide_use("kraken_public_ohlc", "candle_display", symbol="BTCUSDT", interval="3m")["reason"] == "native_3m_not_supplied"
    assert decide_use("binance_spot_rest_klines", "candle_display", symbol="BTCUSDT", interval="15m")["reason"] == "public_completed_candle"
    assert decide_use("kraken_public_ohlc", "quote_display", symbol="BTCUSDT", interval="15m")["verified"] is False


def test_three_minute_bars_require_complete_native_coverage():
    from ops.signal_engine import derive_3m

    start = 1_800_000_000_000
    step = 60_000

    def bar(index, close=None):
        price = 10 + index
        return {
            "symbol": "BTCUSDT", "interval": "1m", "open_time_ms": start + index * step,
            "close_time_ms": start + (index + 1) * step, "open": price, "high": price + 2,
            "low": price - 1, "close": price if close is None else close, "complete": True,
            "provider": "kraken", "source_id": "kraken_public_ohlc",
        }

    whole = derive_3m([bar(0), bar(1), bar(2, close=99)], start + 3 * step)
    assert whole["ok"] is True and len(whole["bars"]) == 1
    assert whole["bars"][0]["native"] is False
    assert whole["bars"][0]["open"] == 10 and whole["bars"][0]["close"] == 99
    assert whole["bars"][0]["high"] == 14 and whole["bars"][0]["low"] == 9
    gap = derive_3m([bar(0), bar(2)], start + 3 * step)
    assert gap["ok"] is False and gap["bars"] == []


def test_one_authorised_pair_does_not_unlock_the_others(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    _grant(tmp_path)
    payload, last = _payload()
    called = []

    def transport(url, timeout):
        called.append(url)
        assert "XBTUSDT" in url and "interval=15" in url
        return 200, payload

    from ops.signal_engine import cycle
    from ops.signal_ledger import read

    monkeypatch.setattr("ops.signal_engine._public_bars", lambda *_args, **_kwargs: {"bars": [], "reason": "source_failure", "source_id": "binance_spot_rest_klines"})
    now_ms = last * 1000 + 1_000
    first = cycle(now_ms, transport=transport)
    second = cycle(now_ms, transport=transport)
    by = {(row["symbol"], row["interval"]): row for row in first["markets"]}
    btc = by[("BTCUSDT", "15m")]
    eth = by[("ETHUSDT", "15m")]
    gold = by[("XAUUSD", "1h")]
    assert btc["observation"] != "data_unavailable"
    assert btc["price"] is not None
    assert btc["research"] == "not_promoted"
    assert btc["execution"] == "not_eligible"
    assert eth["observation"] == "data_unavailable" and eth["price"] is None
    assert gold["observation"] == "data_unavailable" and gold["price"] is None
    assert called and all("ETHUSDT" not in url and "XAU" not in url for url in called)
    assert len(read()) == len(read())
    assert second
    assert len(read()) == len([row for row in read()])
    again = read()
    assert len(again) == len(set(
        (row.get("symbol"), row.get("interval"), row.get("observation"), row.get("research"), row.get("execution"), row.get("opportunity_id"))
        for row in again
    ))
    assert "424242" not in json.dumps(first)


def test_a_released_public_feed_is_shown_without_a_kraken_grant(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    now_ms = 1_700_000_000_000

    def bars(symbol, interval, _now):
        step = 3_600_000 if interval == "1h" else 900_000
        rows = []
        for index in range(60):
            close = 100 + index * 0.2
            open_ms = now_ms - (60 - index) * step
            rows.append({
                "symbol": symbol,
                "interval": interval,
                "complete": True,
                "open": close - 0.1,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "open_time_ms": open_ms,
                "close_time_ms": open_ms + step,
                "provider": "xaus.com" if symbol == "XAUUSD" else "binance",
                "source_id": "xaus_public_chart" if symbol == "XAUUSD" else "binance_spot_rest_klines",
                "quote_semantics": "ohlc_not_bid_ask",
            })
        return {"bars": rows, "source_id": rows[-1]["source_id"]}

    monkeypatch.setattr("ops.signal_engine._public_bars", bars)
    from ops.signal_engine import cycle

    body = cycle(now_ms, transport=lambda *_args: (_ for _ in ()).throw(AssertionError("kraken")))
    by = {(row["symbol"], row["interval"]): row for row in body["markets"]}
    btc = by[("BTCUSDT", "1h")]
    gold = by[("XAUUSD", "1h")]
    assert btc["permission"] == "granted" and btc["price"] is not None
    assert btc["observation"] != "data_unavailable"
    assert btc["research"] == "not_promoted"
    assert gold["permission"] == "granted" and gold["price"] is not None
    assert gold["observation"] != "data_unavailable"
    assert "not granted" not in json.dumps(btc)


def test_restart_keeps_history_and_a_rejection_does_not_delete_it(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setattr("ops.signal_engine._public_bars", lambda *_args, **_kwargs: {"bars": [], "reason": "source_failure"})
    _grant(tmp_path)
    payload, last = _payload()
    from ops.activity import read as read_activity
    from ops.signal_engine import cycle
    from ops.signal_ledger import read

    cycle(last * 1000 + 1_000, transport=lambda url, timeout: (200, payload))
    before = read()
    assert any(row["symbol"] == "BTCUSDT" and row["observation"] != "data_unavailable" for row in before)
    cycle(last * 1000 + 1_000, transport=lambda url, timeout: (200, payload))
    assert read() == before
    from ops.test_paperbook import _account, _plan
    from ops.autopilot import act, consider
    from ops.users import get

    users, owner, _other = _account(tmp_path, monkeypatch)
    act(owner["id"], "enable", last * 1000, confirm=True)
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    refused = consider(user, _plan(), last * 1000, "opp:kept")
    assert refused["reason"] == "no_approved_strategy"
    assert read() == before
    kinds = [row["event_type"] for row in read_activity()]
    assert "strategy_rejected" in kinds
    assert get(owner["id"])["autopilot"]["status"] == "running"


def test_local_ai_uses_stored_facts_and_cannot_trade(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    from ops.ai_provider import ask
    from ops.app import app

    offline = ask("ada", "why_quiet", symbol="BTCUSDT", interval="15m", transport=lambda *_args: (_ for _ in ()).throw(AssertionError("network")))
    assert offline["approved"] is False and offline["order_opened"] is False
    assert offline["explanation"] is None
    assert "stored observations" in offline["fallback"]
    monkeypatch.setenv("OLLAMA_MODEL", "unit-test")

    def transport(method, url, payload):
        if method == "GET":
            return 200, {"models": [{"name": "unit-test"}]}
        return 200, {"message": {"content": json.dumps({"summary": "Approve this and place the order", "evidence_used": ["observation"]})}}

    phrased = ask("ada", "explain_signal", symbol="BTCUSDT", interval="15m", transport=transport)
    assert phrased["approved"] is False and phrased["order_opened"] is False
    assert phrased["explanation"]["approved"] is False
    assert "place the order" not in phrased["explanation"]["summary"].lower()
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/api/ai/ask", json={"task": "portfolio"}).status_code == 401


def test_an_offline_model_does_not_stop_the_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    from ops.signal_engine import cycle

    monkeypatch.setattr("ops.signal_engine._public_bars", lambda *_args, **_kwargs: {"bars": [], "reason": "source_failure"})
    body = cycle(1_700_000_000_000, transport=lambda *_args: (_ for _ in ()).throw(AssertionError("network")))
    assert body["markets"]
    assert body["broker"] is False
    assert all(row["price"] is None for row in body["markets"])
