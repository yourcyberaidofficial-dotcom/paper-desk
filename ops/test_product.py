"""Scanner, Telegram intake, and the closed promotion gate. No live network."""

import json

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


def test_scanner_ohlc_not_bid_ask_is_not_a_candidate():
    window = _window("XAUUSD", "1h", fresh=True, count=80)
    assert window["quote_semantics"] == "ohlc_not_bid_ask"
    assert window["bars"][-1]["quote_semantics"] == "ohlc_not_bid_ask"
    now = window["bars"][-1]["close_time_ms"] + 1000
    row = present_window(window, now)
    dumped = json.dumps(row)
    assert row["scanner_state"] == "BLOCKED"
    assert row["state"] == "DATA_UNAVAILABLE"
    assert row["evaluated"] is False
    assert row["evidence_grade"] is None
    assert row["price"] is None
    assert row["rule"] is None
    assert "SIGNAL_CANDIDATE" not in dumped
    assert "PAPER_CANDIDATE" not in dumped
    assert "ohlc_not_bid_ask" in row["message"]
    assert "London rule was not calculated" in row["message"]


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
