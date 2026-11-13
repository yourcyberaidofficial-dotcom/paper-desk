"""Scanner, Telegram intake, and the closed promotion gate. No live network."""

import json
import time

from ops.bars import make_bar
from ops.scanner import present_window, scan
from ops.telegram_in import UpdateInbox, apply_update, polling_enabled
from ops.users import get, register, start_telegram_link


def _window(symbol="BTCUSDT", interval="15m", fresh=True, count=50):
    step = 900_000 if interval == "15m" else 3_600_000
    start = 1_700_006_400_000
    start -= start % step
    bars = []
    for index in range(count):
        open_time = start + index * step
        close = 100 if index < count - 1 else 100
        bars.append(make_bar(
            symbol=symbol, interval=interval, open_time_ms=open_time, close_time_ms=open_time + step - 1,
            open=100, high=101, low=99, close=close, volume=1,
            provider="binance-public" if symbol != "XAUUSD" else "xaus.com",
            source_type="fixture", quote_semantics="last_trade" if symbol != "XAUUSD" else "ohlc_not_bid_ask",
            retrieved_at_ms=open_time + step, complete=True, fresh=fresh if index == count - 1 else False,
        ))
    return {
        "symbol": symbol,
        "interval": interval,
        "ok": True,
        "bars": bars,
        "higher": bars[-25:],
        "provider": bars[0]["provider"],
        "quote_semantics": bars[0]["quote_semantics"],
        "source_kind": "prospective",
    }


def test_scanner_keeps_gold_failure_specific_and_hides_internal_labels():
    now = _window()["bars"][-1]["close_time_ms"] + 1000
    gold = _window("XAUUSD", "1h", fresh=False, count=5)
    body = scan([_window(), gold], now_ms=now)
    assert body["approved_strategy"] is None
    assert body["notice"].startswith("No approved strategy")
    dumped = json.dumps(body)
    assert "EXPERIMENTAL — NOT VALIDATED" not in dumped
    assert "Traceback" not in dumped
    btc = body["markets"][0]
    assert btc["status"] == "scanning"
    assert btc["approved"] is False
    assert btc["price"] == 100
    stale = present_window(gold, now)
    assert stale["status"] == "unavailable"
    assert stale["scanner_state"] == "BLOCKED"
    assert "ohlc_not_bid_ask" in stale["message"]
    assert stale["evidence_grade"] is None
    missing = present_window({**_window(), "ok": False, "bars": []}, now)
    assert missing["state"] == "DATA_UNAVAILABLE"
    assert "exception" not in missing["message"].lower()


def test_scanner_ohlc_not_bid_ask_is_not_a_london_trade(monkeypatch):
    window = _window("XAUUSD", "1h", fresh=True, count=80)
    assert window["quote_semantics"] == "ohlc_not_bid_ask"
    now = window["bars"][-1]["close_time_ms"] + 1000
    row = present_window(window, now)
    dumped = json.dumps(row)
    assert row["approved"] is False
    assert row["eligible_for_alert"] is False
    assert row.get("rule") != "london-reclaim-1h-20261028"
    assert "London rule was not calculated" in row["message"]
    assert "not a bid/ask" in row["message"]
    assert "SIGNAL_CANDIDATE" not in dumped
    assert row["price"] == 100
    assert row["approved"] is False
    assert row["scanner_state"] != "APPROVED_SIGNAL"


def test_scanner_shows_the_same_experimental_plan_as_the_terminal():
    from ops.terminal_signal import decide
    window = _window("BTCUSDT", "4h", fresh=True, count=50)
    bars = window["bars"]
    for index, bar in enumerate(bars):
        if index < 38:
            bar["high"], bar["low"], bar["close"], bar["open"] = 110, 90, 100, 100
        else:
            bar["high"], bar["low"], bar["close"], bar["open"] = 100.4, 99.8, 100, 100
    bars[-1]["high"], bars[-1]["low"], bars[-1]["close"], bars[-1]["open"] = 107, 100, 106, 100
    now = bars[-1]["close_time_ms"] + 1000
    row = present_window(window, now)
    terminal = decide("BTCUSDT", "4h", "auto", bars, now, None)
    assert row["scanner_state"] == "EXPERIMENTAL"
    assert row["decision"] == terminal["decision"] == "BUY"
    assert row["entry"] == terminal["entry"]
    assert row["stop"] == terminal["stop"]
    assert row["target"] == terminal["target"]
    assert row["approved"] is False
    assert row["eligible_for_alert"] is False
    assert "EXPERIMENTAL — NOT VALIDATED" not in json.dumps(row)


def test_telegram_update_links_once_and_a_public_post_does_not(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    user = register("scan-user", "password-s")
    started = start_telegram_link(user["id"])
    inbox = UpdateInbox(tmp_path / "updates.jsonl")
    update = {"update_id": 41, "message": {"text": "/start " + started["token"], "from": {"id": 9}, "chat": {"id": 9}}}
    assert apply_update(update, inbox)["ok"] is True
    assert get(user["id"])["telegram"]["verified"] is True
    assert apply_update(update, inbox)["duplicate"] is True
    from ops.app import app
    app.config["TESTING"] = True
    response = app.test_client().post("/api/telegram/update", json=update)
    assert response.status_code == 200
    assert response.get_json()["ignored"] is True
    assert app.test_client().get("/api/scanner").status_code == 401
    page = app.test_client().get("/learn")
    assert page.status_code in {302, 401}
    assert polling_enabled() is False
    bare = {"update_id": 42, "message": {"text": "/start", "from": {"id": 8}, "chat": {"id": 8}}}
    assert apply_update(bare, inbox)["reason"] == "start_without_token"
    assert get(user["id"])["telegram"]["chat_id"] == "9"


def test_a_telegram_id_connects_only_when_telegram_accepts_it(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = register("ada", "password-s")
    other = register("bea", "password-s")
    from ops.app import app

    def sender(text, chat_id=None):
        if str(chat_id) == "555555":
            return {"delivered": False, "reason": "Forbidden: bot can't initiate conversation with a user"}
        return {"delivered": True, "telegram_message_id": 7, "telegram_chat_id": int(chat_id)}

    monkeypatch.setattr("ops.notify.send_alert", sender)
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["user_exp"] = time.time() + 3600
    assert client.post("/api/telegram/connect", json={"telegram_id": "not-an-id"}).status_code == 400
    refused = client.post("/api/telegram/connect", json={"telegram_id": "555555"})
    assert refused.status_code == 400
    assert "Start" not in refused.get_data(as_text=True) or refused.get_json()["reason"]
    assert get(owner["id"])["telegram"] in (None, {})
    connected = client.post("/api/telegram/connect", json={"telegram_id": "Id: 424242"})
    assert connected.status_code == 200
    assert connected.get_json()["delivered"] is True
    assert "code" not in json.dumps(connected.get_json())
    assert get(owner["id"])["telegram"]["verified"] is True
    assert get(owner["id"])["telegram"]["chat_id"] == "424242"
    with client.session_transaction() as sess:
        sess["user_id"] = other["id"]
        sess["user_exp"] = time.time() + 3600
    taken = client.post("/api/telegram/connect", json={"telegram_id": "424242"})
    assert taken.status_code == 400
    assert taken.get_json()["error"] == "destination_in_use"


