"""Unverified provider numbers stay out of customer HTTP responses."""

import json
import time

SENTINEL = 424242.42


def _sentinel_scan(*_args, **_kwargs):
    markets = []
    for symbol in ("BTCUSDT", "ETHUSDT", "XAUUSD"):
        for interval in ("1m", "3m", "15m", "1h"):
            markets.append({
                "symbol": symbol,
                "interval": interval,
                "price": SENTINEL,
                "open": SENTINEL,
                "high": SENTINEL,
                "low": SENTINEL,
                "close": SENTINEL,
                "entry": SENTINEL,
                "stop": SENTINEL - 1,
                "target": SENTINEL + 1,
                "decision": "BUY",
                "decision_label": "BUY",
                "scanner_state": "SIGNAL_CANDIDATE",
                "status": "fresh",
                "source_id": "binance_spot_rest_klines",
                "provider": "binance-public",
                "snapshot_id": "snap-sentinel",
                "manual_paper": True,
            })
    return {
        "markets": markets,
        "snapshots": [{"display": {"price": SENTINEL, "close": SENTINEL}, "candle": {"close": SENTINEL}}],
        "sources": [{"instrument": "BTCUSDT", "timeframe": "15m", "provider": "binance-public", "display": {"price": SENTINEL}}],
        "notice": f"price {SENTINEL}",
    }


def _install_feeds(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("unverified feed was called")

    monkeypatch.setattr("ops.desk_snapshot.observe", boom)
    monkeypatch.setattr("ops.desk_snapshot.desk_scan", boom)
    monkeypatch.setattr("ops.desk_snapshot.headline_board", boom)
    monkeypatch.setattr("ops.desk_snapshot.reading_for", boom)
    monkeypatch.setattr("ops.market.fetch_klines", boom)
    monkeypatch.setattr("ops.feeds.binance_bars", boom)
    monkeypatch.setattr("ops.feeds.xaus_chart", boom)
    monkeypatch.setattr("ops.feeds.xaus_spot", boom)
    monkeypatch.setattr("ops.app.market_snapshot", lambda: {
        "BTCUSDT": {"close": SENTINEL, "open": SENTINEL, "close_time_ms": 10, "checked_at_ms": 20, "source": "binance-public"},
        "ETHUSDT": {"close": SENTINEL, "open": SENTINEL, "close_time_ms": 10, "checked_at_ms": 20, "source": "binance-public"},
    })
    from ops.app import worker
    worker.last_monitor = {"evaluations": [{"symbol": "BTCUSDT", "interval": "15m", "decision": "BUY", "entry": SENTINEL, "price": SENTINEL}]}


def _session(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_exp"] = time.time() + 3600


def _bodies(client, user_id):
    _session(client, user_id)
    found = {}
    public = [
        "/api/markets",
        "/api/market",
        "/api/klines?symbol=BTCUSDT&interval=15m",
        "/api/klines?symbol=ETHUSDT&interval=1h",
        "/api/klines?symbol=BTCUSDT&interval=1m",
        "/api/klines?symbol=BTCUSDT&interval=4h",
        "/api/gold/candles?interval=15m",
        "/api/gold/candles?interval=1h",
        "/api/gold/candles?interval=1m",
        "/api/gold/signal",
        "/api/engine?symbol=BTCUSDT",
        "/api/engine?symbol=ETHUSDT",
        "/api/engine?symbol=XAUUSD",
        "/api/research-signals?symbol=BTCUSDT",
        "/api/research-signals?symbol=ETHUSDT",
        "/api/research-signals?symbol=XAUUSD",
        "/api/council",
        "/api/triad?symbol=BTCUSDT",
        "/health",
        "/api/coverage",
        "/api/signal-history",
        "/api/notify-history",
        "/api/deep-board",
        "/api/leaderboard",
        "/api/replay",
        "/api/period",
    ]
    private = [
        "/api/desk",
        "/api/scanner",
        "/api/workspace",
        "/api/notifications",
        "/api/terminal/history",
        "/api/eligibility?symbol=BTCUSDT",
        "/api/eligibility?symbol=ETHUSDT",
        "/api/eligibility?symbol=XAUUSD",
    ]
    for path in public + private:
        found[path] = client.get(path)
    found["POST /api/terminal/signal"] = client.post("/api/terminal/signal", json={"symbol": "BTCUSDT", "interval": "15m", "strategy": "auto", "request_id": "r1"})
    found["POST /api/desk/plan"] = client.post("/api/desk/plan", json={"symbol": "BTCUSDT", "interval": "15m"})
    return found


def test_unverified_feeds_are_not_called_and_the_sentinel_is_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    created = users.register("ada", "password-s")
    _install_feeds(monkeypatch)
    from ops.app import _FEED_CACHE, app
    _FEED_CACHE[("binance", "BTCUSDT", "15m")] = (time.time(), {"ok": True, "bars": [{"close": SENTINEL, "open": SENTINEL, "high": SENTINEL, "low": SENTINEL}]})
    app.config["TESTING"] = True
    client = app.test_client()
    found = _bodies(client, created["id"])
    for path, response in found.items():
        text = response.get_data(as_text=True)
        assert str(SENTINEL) not in text, path
        assert "424242" not in text, path
        assert response.status_code < 500, path
    assert found["/api/klines?symbol=BTCUSDT&interval=15m"].get_json()["candles"] == []
    assert found["/api/gold/candles?interval=15m"].get_json()["candles"] == []
    assert found["/api/gold/candles?interval=1m"].get_json()["blocked"] == "xau_minute_unlicensed"
    assert found["/api/markets"].get_json()["markets"][0]["data"]["price"] is None
    desk = found["/api/desk"].get_json()
    assert desk["snapshots"] == []
    assert all(row.get("entry") is None and row.get("price") is None for row in desk["markets"])
    assert found["POST /api/terminal/signal"].get_json()["customer_status"] == "reading_unavailable"
    assert found["POST /api/desk/plan"].get_json()["reason"] == "reading_unavailable"
    health = found["/health"].get_json()
    assert health["market_data"]["BTCUSDT"]["last_close_time_ms"] == 10
    assert "close" not in health["market_data"]["BTCUSDT"]
    for row in (health["worker"]["last_monitor"] or {}).get("evaluations") or []:
        assert "entry" not in row
        assert "price" not in row


def test_a_cached_sentinel_is_not_served_as_current(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    _install_feeds(monkeypatch)
    from ops.app import app
    monkeypatch.setattr("ops.desk_snapshot.desk_scan", _sentinel_scan)
    monkeypatch.setattr("ops.desk_snapshot.observe", _sentinel_scan)
    app.config["TESTING"] = True
    client = app.test_client()
    for path in ("/api/markets", "/api/klines?symbol=BTCUSDT&interval=15m", "/api/gold/candles?interval=1h", "/api/engine?symbol=ETHUSDT", "/api/council"):
        assert str(SENTINEL) not in client.get(path).get_data(as_text=True), path


def test_one_verified_candle_does_not_release_the_other_instruments(monkeypatch):
    def allow(source_id, capability, symbol=None, interval=None):
        return source_id == "binance_spot_rest_klines" and capability == "candle_display" and symbol == "BTCUSDT" and interval == "15m"

    monkeypatch.setattr("ops.customer_release.verified", allow)
    monkeypatch.setattr("ops.desk_snapshot.desk_scan", _sentinel_scan)
    from ops.app import app
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = "ada"
        sess["user_exp"] = time.time() + 3600
    body = client.get("/api/desk").get_json()
    btc = next(row for row in body["markets"] if row["symbol"] == "BTCUSDT" and row["interval"] == "15m")
    eth = next(row for row in body["markets"] if row["symbol"] == "ETHUSDT" and row["interval"] == "15m")
    gold = next(row for row in body["markets"] if row["symbol"] == "XAUUSD" and row["interval"] == "1h")
    assert btc["price"] == SENTINEL
    assert btc["entry"] is None
    assert eth["price"] is None
    assert eth["entry"] is None
    assert gold["price"] is None
    assert gold["entry"] is None
    assert body["snapshots"] == []
    eth_candles = client.get("/api/klines?symbol=ETHUSDT&interval=15m").get_json()
    assert eth_candles["candles"] == []
    assert str(SENTINEL) not in json.dumps(eth_candles)


def test_customer_routes_do_not_rewrite_an_existing_paper_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    from ops.paperbook import _path, save
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    created = users.register("ada", "password-s")
    save(created["id"], {"orders": [{"id": "kept", "status": "open", "entry": 1, "symbol": "BTCUSDT"}], "cash": 10})
    written = _path(created["id"])
    before = written.read_bytes()
    _install_feeds(monkeypatch)
    from ops.app import app
    app.config["TESTING"] = True
    client = app.test_client()
    _bodies(client, created["id"])
    assert written.read_bytes() == before


def test_a_feed_notice_is_redacted_and_a_typed_plan_is_not(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    from ops.inbox import offer
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    created = users.register("ada", "password-s")
    offer(created["id"], {
        "id": "feed-1",
        "kind": "experimental",
        "symbol": "BTCUSDT",
        "interval": "15m",
        "source_id": "binance_spot_rest_klines",
        "provider": "binance-public",
        "decision": "BUY",
        "entry": SENTINEL,
        "stop": 1,
        "target": 2,
        "created_ms": 1,
    })
    offer(created["id"], {
        "id": "mine-1",
        "kind": "experimental",
        "symbol": "BTCUSDT",
        "interval": "15m",
        "source_id": "user_authored",
        "provenance": "user_authored",
        "decision": "BUY",
        "entry": 100,
        "stop": 98,
        "target": 104,
        "created_ms": 2,
    })
    from ops.app import app
    app.config["TESTING"] = True
    client = app.test_client()
    _session(client, created["id"])
    text = client.get("/api/notifications").get_data(as_text=True)
    assert str(SENTINEL) not in text
    assert "100" in text
    stored = [json.loads(line) for line in (tmp_path / "users" / "inbox" / f"{created['id']}.jsonl").read_text().splitlines() if line.strip()]
    feed = next(row for row in stored if row["id"] == "feed-1")
    assert feed["entry"] == SENTINEL
