"""Worker tests. No network. No fills."""

import json
from pathlib import Path

from ops.ledger import Ledger
from ops.experimental import present_book
from ops.worker import Worker, direction_event_id, may_send_observation


def _bar(symbol, close_time, fresh=True):
    return {
        "symbol": symbol,
        "interval": "15m",
        "close_time_ms": close_time,
        "fresh": fresh,
        "source": "fixture",
    }


def test_duplicate_and_wait(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 1000))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    worker = Worker(ledger, tmp_path / "prefs.json")
    sent = []
    first = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status": "DELIVERED", "delivered": True})
    second = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status": "DELIVERED", "delivered": True})
    assert len(first) == 2
    assert second == []
    assert all(row["result"] == "WAIT" for row in first)
    assert sent == []
    assert not any(row.get("type") == "fill" for row in ledger.read())


def test_stale_and_quiet(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 2000, fresh=False))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text(json.dumps({"assets": ["BTCUSDT"], "quiet_hours_utc": list(range(24)), "alerts_enabled": True}))
    worker = Worker(ledger, prefs)
    sent = []
    rows = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status": "DELIVERED", "delivered": True})
    assert rows[0]["reason"] == "stale_or_unavailable"
    assert sent == []


def test_prefs_cap(tmp_path):
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")
    saved = worker.save_prefs({"assets": ["BTCUSDT", "XAU"], "max_alerts_per_day": 999})
    assert saved["assets"] == ["BTCUSDT"]
    assert saved["max_alerts_per_day"] == 48


def test_experimental_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 3000))
    candles = [{"h": 10, "l": 9, "c": 9.5} for _ in range(20)] + [{"h": 12, "l": 11, "c": 11}]
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": candles})
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":false}')
    worker = Worker(ledger, prefs)
    sent = []
    rows = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status":"FAILED","delivered":False})
    assert rows[0]["experimental"]["result"] == "LONG_BIAS"
    assert rows[0]["experimental"]["classification"] == "experimental_unvalidated"
    assert sent == []
    again = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status":"FAILED","delivered":False})
    assert again == []
    assert sent == []


def test_wait_does_not_notify(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 4000))
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": [{"h": 10, "l": 9, "c": 9.5} for _ in range(21)]})
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":true}')
    worker = Worker(ledger, prefs)
    sent = []
    rows = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status":"DELIVERED","delivered":True})
    assert rows[0]["experimental"]["result"] == "WAIT"
    assert sent == []
    assert any(r.get("type") == "evaluation" for r in ledger.read())


def test_trigger_notifies(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 5000))
    candles = [{"h": 10, "l": 9, "c": 9.5} for _ in range(20)] + [{"h": 12, "l": 11, "c": 11}]
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": candles})
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":true}')
    worker = Worker(ledger, prefs)
    sent = []
    worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status":"DELIVERED","delivered":True,"telegram_message_id":1})
    assert sent == []
    stored = [row for row in ledger.read() if row.get("type") == "evaluation"]
    assert stored and stored[0]["experimental"]["result"] == "LONG_BIAS"
    assert stored[0]["notification"]["delivered"] is False
    assert stored[0]["notification"]["reason"] == "production_wait_default"
    assert stored[0]["result"] == "WAIT"
    book = worker.book.read()
    assert not any(row.get("type") in {"paper_open", "paper_close"} for row in book)
    shown = present_book(book, worker.book.open_position())
    assert shown["open"] is None
    assert shown["trades"] == []


def test_same_direction_on_next_candle_does_not_send(tmp_path, monkeypatch):
    calls = {"n": 5000}

    def bar(symbol, interval, now_ms=None):
        calls["n"] += 1
        return _bar(symbol, calls["n"])

    monkeypatch.setattr("ops.worker.fetch_last_closed", bar)
    candles = [{"h": 10, "l": 9, "c": 9.5} for _ in range(20)] + [{"h": 12, "l": 11, "c": 11}]
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": candles})
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":true}')
    worker = Worker(ledger, prefs)
    sent = []
    sender = lambda text: sent.append(text) or {"status": "DELIVERED", "delivered": True, "telegram_message_id": 1, "telegram_chat_id": 9}
    worker.evaluate(now_ms=1_700_000_000_000, sender=sender)
    worker.evaluate(now_ms=1_700_000_900_000, sender=sender)
    assert sent == []
    assert direction_event_id("u", "BTCUSDT", "15m", "LONG_BIAS") == direction_event_id("u", "BTCUSDT", "15m", "LONG_BIAS")
    assert direction_event_id("u", "BTCUSDT", "15m", "LONG_BIAS") != direction_event_id("u", "BTCUSDT", "15m", "SHORT_BIAS")
    assert not any(row.get("type") == "notify" for row in ledger.read())


def test_two_users_are_not_sent_or_rewritten(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    from ops.users import register, update_profile
    first = register("desk-a", "password-a")
    second = register("desk-b", "password-b")
    update_profile(first["id"], {"signal_style": "aegis_shield", "currency": "NGN", "capital": 10, "experimental_alerts": False})
    update_profile(second["id"], {"signal_style": "apex_momentum", "currency": "USD", "capital": 20, "experimental_alerts": True})
    path_b = users.ROOT / f"{second['id']}.json"
    stored_b = json.loads(path_b.read_text())
    stored_b["telegram"] = {"verified": True, "chat_id": "1"}
    path_b.write_text(json.dumps(stored_b))
    before_a = json.loads((users.ROOT / f"{first['id']}.json").read_text())
    before_b = json.loads(path_b.read_text())
    assert before_a["profile"]["experimental_alerts"] is False
    assert before_b["profile"]["experimental_alerts"] is True
    assert before_a["profile"]["signal_style"] != before_b["profile"]["signal_style"]
    assert may_send_observation(before_a["profile"]) is False
    opted = dict(before_b["profile"])
    opted["telegram"] = {"verified": True, "chat_id": "1"}
    assert may_send_observation(opted) is False
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 7000))
    candles = [{"h": 10, "l": 9, "c": 9.5} for _ in range(20)] + [{"h": 12, "l": 11, "c": 11}]
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": candles})
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":true}')
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), prefs)
    sent = []
    worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text, chat_id=None: sent.append((text, chat_id)) or {"status": "DELIVERED", "delivered": True, "telegram_message_id": 1, "telegram_chat_id": chat_id})
    assert sent == []
    after_a = json.loads((users.ROOT / f"{first['id']}.json").read_text())
    after_b = json.loads(path_b.read_text())
    assert after_a == before_a
    assert after_b == before_b
    assert "password" not in json.dumps(worker.last_result)


def test_stale_warns(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 6000, fresh=False))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"alerts_enabled":true,"quiet_hours_utc":[]}')
    worker = Worker(ledger, prefs)
    sent = []
    worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status":"FAILED","delivered":False,"reason":"Timeout"})
    assert sent == []
    assert not any(row.get("type") == "notify" for row in ledger.read())
    assert any(row.get("reason") == "stale_or_unavailable" for row in ledger.read())


def test_alerts_today_counts_attempted_at(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    worker = Worker(ledger, tmp_path / "prefs.json")
    now = 1_700_000_000_000
    ledger.append({"type": "notify", "id": "n1", "attempted_at_ms": now, "ts_ms": 0, "rule": "E1"})
    assert worker._alerts_today(now) == 1
    ledger.append({"type": "notify", "id": "n2", "attempted_at_ms": now, "rule": "WAIT_DEFAULT"})
    assert worker._alerts_today(now) == 1


def test_evaluate_does_not_call_sender(tmp_path, monkeypatch):
    import inspect
    source = inspect.getsource(Worker.evaluate)
    assert "sender(" not in source
    assert "send_alert(" not in source
    monkeypatch.setattr("ops.worker.may_send_observation", lambda profile, production="WAIT_DEFAULT": True)
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 8000))
    candles = [{"h": 10, "l": 9, "c": 9.5} for _ in range(20)] + [{"h": 12, "l": 11, "c": 11}]
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": candles})
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    from ops.users import register, update_profile
    user = register("desk-c", "password-c")
    update_profile(user["id"], {"signal_style": "apex_momentum", "currency": "USD", "capital": 5, "experimental_alerts": True})
    path = users.ROOT / f"{user['id']}.json"
    saved = json.loads(path.read_text())
    saved["telegram"] = {"verified": True, "chat_id": "1"}
    path.write_text(json.dumps(saved))
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":true}')
    sent = []
    Worker(Ledger(tmp_path / "ledger.jsonl"), prefs).evaluate(
        now_ms=1_700_000_000_000,
        sender=lambda *args, **kwargs: sent.append((args, kwargs)) or {"delivered": True, "status": "DELIVERED", "telegram_message_id": 1},
    )
    assert sent == []


def test_anonymous_session_and_bias_book(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.delenv("DESK_COOKIE_SECURE", raising=False)
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    from ops.app import app
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/eligibility").status_code == 401
    created = client.post("/api/register", json={"name": "desk-session", "password": "password-s"})
    assert created.status_code == 200
    saved = client.post("/api/profile", json={"signal_style": "orion_precision", "currency": "EUR", "capital": 40, "experimental_alerts": True})
    assert saved.status_code == 200
    me = client.get("/api/me")
    assert me.status_code == 200
    profile = me.get_json()["profile"]
    assert profile["signal_style_name"] == "Orion Precision"
    assert profile["currency"] == "EUR"
    assert profile["capital"] == 40
    assert profile["experimental_alerts"] is True
    book = tmp_path / "paper" / "experimental.jsonl"
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(json.dumps({
        "id": "open:1",
        "type": "paper_open",
        "asset": "BTCUSDT",
        "side": "SHORT_BIAS",
        "entry_price": 80245.75,
    }) + "\n")
    paper = client.get("/api/paper-status").get_json()
    assert paper["open"] is None
    assert paper["rows"] == []
    assert paper["broker"] is False
    monkeypatch.setattr("ops.app.market_snapshot", lambda: {"BTCUSDT": {"fresh": False}, "ETHUSDT": {"fresh": False}})
    health = client.get("/health").get_json()
    assert health["broker"] is False
    assert health["strategy_status"] == "WAIT_DEFAULT"
    assert "TELEGRAM" not in json.dumps(health)
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/eligibility").status_code == 401
    text = __import__("pathlib").Path(__file__).with_name("app.py").read_text(encoding="utf-8")
    assert "Production is WAIT_DEFAULT, so no trade alert is sent until a strategy is promoted." in text
    assert 'SESSION_COOKIE_SECURE=os.environ.get("DESK_COOKIE_SECURE", "0") == "1"' in text

