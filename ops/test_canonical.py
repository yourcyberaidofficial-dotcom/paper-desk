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


def test_a_failed_symbol_does_not_drop_the_other(monkeypatch):
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
