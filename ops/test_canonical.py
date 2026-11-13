"""One stored reading survives a restart and is what the pages project."""

import json

from ops.desk_pulse import get, health_label, latest, load, publish, reset


def _row(symbol="BTCUSDT", interval="15m", close_ms=1_700_000_000_000, decision="WAIT"):
    return {
        "symbol": symbol,
        "interval": interval,
        "decision": decision,
        "decision_label": decision,
        "bar_close_ms": close_ms,
        "feed_state": "live",
        "entry": None,
        "stop": None,
        "target": None,
    }


def test_a_restart_keeps_the_same_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    reset()
    assert publish(_row(), 1_700_000_100_000) is True
    first = get("BTCUSDT", "15m")
    from ops import desk_pulse

    desk_pulse._READINGS.clear()
    assert load() is True
    restored = get("BTCUSDT", "15m")
    assert restored["snapshot_id"] == first["snapshot_id"]
    assert restored["bar_close_ms"] == 1_700_000_000_000
    assert json.loads((tmp_path / "canonical" / "readings.json").read_text())["schema"] == 1
    reset()


def test_terminal_and_gold_project_the_worker_reading(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    reset()
    publish(_row("XAUUSD", "1h", 1_700_000_300_000, "SELL"), 1_700_000_400_000)
    publish(_row("BTCUSDT", "15m", 1_700_000_300_000, "BUY"), 1_700_000_400_000)
    from ops.app import app
    import ops.users as users

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    created = users.register("ada", "password-s")
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = created["id"]
        sess["user_exp"] = 9_999_999_999

    def explode(*_args, **_kwargs):
        raise AssertionError("a page must not decide again")

    monkeypatch.setattr("ops.terminal_signal.decide", explode)
    gold = client.get("/api/gold/signal").get_json()
    terminal = client.post("/api/terminal/signal", json={"symbol": "BTCUSDT", "interval": "15m", "strategy": "auto"}).get_json()
    assert gold["snapshot_id"] == get("XAUUSD", "1h")["snapshot_id"]
    assert gold["bar_close_ms"] == 1_700_000_300_000
    assert terminal["snapshot_id"] == get("BTCUSDT", "15m")["snapshot_id"]
    assert terminal["bar_close_ms"] == 1_700_000_300_000
    assert terminal["source"] == "canonical"
    reset()


def test_a_failed_symbol_does_not_drop_the_other(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.worker import Worker

    def crypto(symbol, interval, now_ms):
        if symbol == "ETHUSDT":
            raise TimeoutError("eth stalled")
        return [{"close_time_ms": now_ms - 1000, "close": 1}]

    def gold(interval, now_ms):
        return [{"close_time_ms": now_ms - 1000, "close": 2}]

    monkeypatch.setattr("ops.terminal_route.load_crypto_bars", crypto)
    monkeypatch.setattr("ops.terminal_route.load_gold_ohlc", gold)
    windows = Worker(None, "/tmp/unused-prefs.json")._monitor_windows(1_700_000_000_000)
    by_symbol = {row["symbol"] for row in windows}
    assert "BTCUSDT" in by_symbol and "XAUUSD" in by_symbol
    eth = [row for row in windows if row["symbol"] == "ETHUSDT"]
    assert eth and eth[0]["reason"] == "TimeoutError"
    assert health_label(latest("XAUUSD"), 1_700_000_000_000) in {"live", "cached", "market_closed", "feed_down"}


def test_readers_reload_when_the_file_changes_and_keep_the_price(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    reset()
    assert publish({**_row(), "reference_price": 2500.5}, 1_700_000_100_000) is True
    stored = get("BTCUSDT", "15m")
    assert stored["price"] == 2500.5
    assert stored["reference_price"] == 2500.5
    path = tmp_path / "canonical" / "readings.json"
    assert path.is_file()
    assert not path.with_suffix(".json.tmp").exists()
    from ops import desk_pulse

    desk_pulse._READINGS[("BTCUSDT", "15m")]["price"] = 999
    assert get("BTCUSDT", "15m")["price"] == 999
    body = json.loads(path.read_text(encoding="utf-8"))
    body["readings"][0]["decision"] = "SELL"
    body["readings"][0]["decision_label"] = "SELL"
    body["readings"][0]["price"] = 2500.5
    path.write_text(json.dumps(body), encoding="utf-8")
    refreshed = get("BTCUSDT", "15m")
    assert refreshed["decision"] == "SELL"
    assert refreshed["price"] == 2500.5
    assert refreshed["snapshot_id"]
    reset()
    monkeypatch.delenv("AUREON_DATA", raising=False)
    assert desk_pulse._path() == desk_pulse.Path("data") / "canonical" / "readings.json"
    compose = (desk_pulse.Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "desk-canonical:/app/data/canonical" in compose


def _sign_in(tmp_path, monkeypatch):
    from ops.app import app
    import ops.users as users

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    created = users.register("ada", "password-s")
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = created["id"]
        sess["user_exp"] = 9_999_999_999
    return client


def test_customer_pages_share_one_stored_candle(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    reset()
    close_ms = 1_700_000_300_000
    publish({**_row("BTCUSDT", "15m", close_ms, "BUY"), "reference_price": 64000, "entry": 64000, "stop": 63000, "target": 66000}, close_ms + 1)
    publish({**_row("ETHUSDT", "15m", close_ms, "WAIT"), "reference_price": 3200}, close_ms + 1)
    publish({**_row("XAUUSD", "1h", close_ms, "SELL"), "reference_price": 2650, "entry": 2650, "stop": 2660, "target": 2620}, close_ms + 1)
    btc = get("BTCUSDT", "15m")
    eth = get("ETHUSDT", "15m")
    gold_row = get("XAUUSD", "1h")

    def fake_scan(_now):
        rows = []
        for symbol, interval in (("BTCUSDT", "1m"), ("BTCUSDT", "15m"), ("ETHUSDT", "15m"), ("XAUUSD", "1h")):
            rows.append({
                "symbol": symbol,
                "interval": interval,
                "decision": "WAIT",
                "decision_label": "OTHER",
                "snapshot_id": "not-the-stored-reading",
                "bar_close_ms": 1,
                "price": 1,
                "close": 1,
                "entry": 9,
                "data": {"price": 1, "close": 1, "bar_close_ms": 1},
            })
        return {"markets": rows, "broker": False, "notice": "fixture"}

    def fake_board(_now):
        snaps = []
        readings = []
        for symbol in ("BTCUSDT", "ETHUSDT", "XAUUSD"):
            snaps.append({
                "instrument": symbol,
                "snapshot_id": "board-other",
                "candle_semantics": "ohlc_not_bid_ask",
                "display": {"price": 1, "close": 1, "bar_close_ms": 1, "fresh": False},
            })
            readings.append({"symbol": symbol, "decision": "WAIT", "snapshot_id": "board-other", "entry": 9})
        return snaps, readings

    monkeypatch.setattr("ops.desk_snapshot.desk_scan", fake_scan)
    monkeypatch.setattr("ops.desk_snapshot.headline_board", fake_board)
    monkeypatch.setattr("ops.terminal_signal.decide", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("auto must not decide again")))
    client = _sign_in(tmp_path, monkeypatch)
    scanner = client.get("/api/scanner").get_json()
    desk = client.get("/api/desk").get_json()
    workspace = client.get("/api/workspace").get_json()
    markets = client.get("/api/markets").get_json()
    gold = client.get("/api/gold/signal").get_json()
    pulse = client.get("/api/desk/pulse").get_json()
    terminal = client.post("/api/terminal/signal", json={"symbol": "BTCUSDT", "interval": "15m", "strategy": "auto"}).get_json()

    def card(body, symbol, interval):
        return next(row for row in body["markets"] if row["symbol"] == symbol and row["interval"] == interval)

    for body in (scanner, desk):
        found = card(body, "BTCUSDT", "15m")
        assert found["snapshot_id"] == btc["snapshot_id"]
        assert found["bar_close_ms"] == close_ms
        assert found["decision"] == "BUY"
        assert found["price"] == 64000
        assert found["source"] == "canonical"
    panel = next(row for row in workspace["panels"] if row["symbol"] == "BTCUSDT")
    assert panel["interval"] == "15m"
    assert panel["snapshot_id"] == btc["snapshot_id"]
    assert panel["bar_close_ms"] == close_ms
    assert panel["decision"] == "BUY"
    btc_market = next(row for row in markets["markets"] if row["symbol"] == "BTCUSDT")
    eth_market = next(row for row in markets["markets"] if row["symbol"] == "ETHUSDT")
    gold_market = next(row for row in markets["markets"] if row["symbol"] == "XAUUSD")
    assert btc_market["snapshot_id"] == btc["snapshot_id"]
    assert btc_market["bar_close_ms"] == close_ms
    assert btc_market["data"]["price"] == 64000
    assert btc_market["data"]["close"] == 64000
    assert btc_market["data"]["bar_close_ms"] == close_ms
    assert eth_market["snapshot_id"] == eth["snapshot_id"]
    assert eth_market["data"]["price"] == 3200
    assert gold_market["snapshot_id"] == gold_row["snapshot_id"]
    assert gold_market["data"]["price"] == 2650
    assert gold_market["data"]["bar_close_ms"] == close_ms
    assert gold["snapshot_id"] == gold_row["snapshot_id"]
    assert gold["bar_close_ms"] == close_ms
    assert gold["decision"] == "SELL"
    pulse_btc = next(row for row in pulse["readings"] if row["symbol"] == "BTCUSDT" and row["interval"] == "15m")
    pulse_gold = next(row for row in pulse["readings"] if row["symbol"] == "XAUUSD" and row["interval"] == "1h")
    assert pulse_btc["snapshot_id"] == btc["snapshot_id"]
    assert pulse_btc["bar_close_ms"] == close_ms
    assert pulse_gold["snapshot_id"] == gold_row["snapshot_id"]
    assert pulse_gold["bar_close_ms"] == close_ms
    assert terminal["snapshot_id"] == btc["snapshot_id"]
    assert terminal["bar_close_ms"] == close_ms
    assert terminal["decision"] == "BUY"
    assert terminal["source"] == "canonical"
    reset()


def test_an_explicit_strategy_is_not_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    reset()
    publish(_row(), 1_700_000_100_000)
    seen = {}

    def decide(symbol, interval, strategy, bars, now_ms, user, *args, **kwargs):
        seen["strategy"] = strategy
        seen["calls"] = seen.get("calls", 0) + 1
        return {"decision": "WAIT", "symbol": symbol, "interval": interval, "strategy": strategy, "bar_close_ms": 5, "approved": False}

    monkeypatch.setattr("ops.terminal_signal.decide", decide)
    monkeypatch.setattr("ops.terminal_signal.stamp", lambda _user, payload: payload)
    monkeypatch.setattr("ops.inbox.deliver_evaluation", lambda *_args, **_kwargs: {"stored": False})
    from ops.terminal_route import handle_signal

    _status, auto = handle_signal("user-a", {"symbol": "BTCUSDT", "interval": "15m", "strategy": "auto"}, 1_700_000_000_000)
    assert auto["source"] == "canonical"
    assert seen == {}
    _status, explicit = handle_signal(
        "user-a", {"symbol": "BTCUSDT", "interval": "15m", "strategy": "ema-cross"}, 1_700_000_000_000,
        bars_loader=lambda *_args: [{"close": 1}],
    )
    assert explicit.get("source") != "canonical"
    assert seen["strategy"] == "ema-cross"
    _status, injected = handle_signal(
        "user-a", {"symbol": "BTCUSDT", "interval": "15m", "strategy": "auto"}, 1_700_000_000_000,
        bars_loader=lambda *_args: [{"close": 1}],
    )
    assert injected.get("source") != "canonical"
    assert seen["calls"] == 2
    reset()


def test_health_reports_live_cached_closed_and_down(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    reset()
    close_ms = 1_700_000_300_000
    publish(_row("BTCUSDT", "15m", close_ms, "WAIT"), close_ms + 1)
    publish({**_row("ETHUSDT", "15m", close_ms, "WAIT"), "feed_state": "last_good"}, close_ms + 1)
    publish(_row("XAUUSD", "1h", close_ms, "WAIT"), close_ms + 1)
    assert health_label(get("BTCUSDT", "15m"), close_ms) == "live"
    assert health_label(get("ETHUSDT", "15m"), close_ms) == "cached"
    assert health_label(None, close_ms) == "feed_down"
    from datetime import datetime, timezone

    saturday = int(datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc).timestamp() * 1000)
    thursday = int(datetime(2026, 11, 12, 16, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert health_label(get("XAUUSD", "1h"), saturday) == "market_closed"
    assert health_label(get("XAUUSD", "1h"), thursday) == "live"
    assert health_label({**get("XAUUSD", "1h"), "feed_state": "down"}, thursday) == "feed_down"
    now = int(__import__("time").time() * 1000)
    monkeypatch.setattr("ops.app.market_snapshot", lambda: {
        "BTCUSDT": {"close_time_ms": now - 1000, "checked_at_ms": now, "source": "test"},
        "ETHUSDT": {"close_time_ms": now - 1000, "checked_at_ms": now, "source": "test"},
    })
    from ops.app import app

    app.config["TESTING"] = True
    report = app.test_client().get("/health").get_json()["market_data"]
    assert report["BTCUSDT"]["status"] == "fresh"
    assert report["BTCUSDT"]["feed"] == "live"
    assert report["BTCUSDT"]["snapshot_id"] == get("BTCUSDT", "15m")["snapshot_id"]
    assert report["ETHUSDT"]["feed"] == "cached"
    assert report["XAUUSD"]["status"] in {"live", "market_closed"}
    assert report["XAUUSD"]["snapshot_id"] == get("XAUUSD", "1h")["snapshot_id"]
    monkeypatch.setattr("ops.sessions.gold_market_open", lambda _moment: False)
    closed = app.test_client().get("/health").get_json()["market_data"]
    assert closed["XAUUSD"]["status"] == "market_closed"
    publish({**_row("BTCUSDT", "15m", close_ms, "WAIT"), "feed_state": "down"}, close_ms + 2)
    down = app.test_client().get("/health").get_json()["market_data"]
    assert down["BTCUSDT"]["feed"] == "feed_down"
    reset()


def test_a_feed_error_uses_public_kraken_then_the_last_good_bar(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.market_cache import remember
    from ops.worker import Worker

    now = 1_800_000_180_000
    remember("ETHUSDT", "15m", [{"close": 42, "close_time_ms": now - 1000}], now)
    remember("XAUUSD", "1h", [{"close": 1900, "close_time_ms": now - 1000}], now)
    gold_called = []

    def crypto(symbol, interval, _now):
        if (symbol, interval) in {("BTCUSDT", "3m"), ("ETHUSDT", "15m")}:
            return (None, "source_failure")
        return [{"close": 1, "close_time_ms": _now - 1000}]

    def gold(interval, _now):
        gold_called.append(interval)
        if interval == "1h":
            return (None, "source_failure")
        return [{"close": 2, "close_time_ms": _now - 1000}]

    def kraken(symbol, interval, _now, timeout=8):
        assert interval != "3m"
        if symbol == "BTCUSDT" and interval == "1m":
            start = 1_800_000_000_000
            step = 60_000
            return {"ok": True, "called": True, "bars": [
                {
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "open_time_ms": start + index * step,
                    "close_time_ms": start + (index + 1) * step,
                    "open": 10, "high": 12, "low": 9, "close": 11,
                    "complete": True,
                }
                for index in range(3)
            ]}
        return {"ok": False, "bars": [], "called": True, "reason": "source_failure"}

    monkeypatch.setattr("ops.terminal_route.load_crypto_bars", crypto)
    monkeypatch.setattr("ops.terminal_route.load_gold_ohlc", gold)
    monkeypatch.setattr("ops.kraken_public.authorized_bars", kraken)
    windows = {(row["symbol"], row["interval"]): row for row in Worker(None, tmp_path / "prefs.json")._monitor_windows(now)}
    assert "1m" not in gold_called and "3m" not in gold_called
    assert windows[("XAUUSD", "1m")]["reason"] == "xau_minute_unsupported"
    assert windows[("BTCUSDT", "3m")]["feed_state"] == "live"
    assert windows[("BTCUSDT", "3m")]["bars"][0]["interval"] == "3m"
    assert windows[("BTCUSDT", "3m")]["bars"][0]["native"] is False
    assert windows[("ETHUSDT", "15m")]["feed_state"] == "last_good"
    assert windows[("ETHUSDT", "15m")]["bars"][0]["close"] == 42
    assert windows[("XAUUSD", "1h")]["feed_state"] == "last_good"
    assert windows[("XAUUSD", "1h")]["bars"][0]["close"] == 1900

