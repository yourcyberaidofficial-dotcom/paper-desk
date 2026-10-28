"""Canonical delivery policy. No network and no production Telegram call."""

import io
import json
import urllib.error

from ops.delivery import DeliveryLog, authorize, dispatch, load_promotions
from ops.ledger import Ledger
from ops.notify import send_alert
from ops.profiles import PROFILES
from ops.users import get, process_start_command, register, start_telegram_link, unlink_telegram, update_prefs, update_profile
from ops.worker import PRODUCTION, Worker

SPAM = "EXPERIMENTAL — NOT VALIDATED BTCUSDT 15m LONG_BIAS. Not a trade."
REGISTRY = [{"strategy": "future-strategy", "version": "future-1", "symbols": ["BTCUSDT", "ETHUSDT", "XAUUSD"]}]


def _approved(**extra):
    event = {
        "state": "APPROVED_SIGNAL",
        "event_id": "evt-1",
        "strategy": "future-strategy",
        "version": "future-1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "fresh": True,
        "complete": True,
        "expires_at_ms": 5_000,
        "text": "Aureon approved signal.",
    }
    event.update(extra)
    return event


def _user(chat="11", alerts=True):
    return {
        "id": "user-a",
        "experimental_alerts": alerts,
        "telegram": {"verified": True, "chat_id": chat, "revoked": False},
        "prefs": {"markets": ["BTCUSDT", "ETHUSDT", "XAUUSD"], "timeframes": {"BTCUSDT": "15m", "ETHUSDT": "15m", "XAUUSD": "1h"}},
    }


def _ok(chat="11"):
    def send(text, chat_id=None):
        assert SPAM not in text
        assert "LONG_BIAS" not in text
        return {"delivered": True, "status": "DELIVERED", "telegram_message_id": 7, "telegram_chat_id": chat_id}
    return send


def test_screenshot_message_cannot_be_sent(monkeypatch):
    called = []
    monkeypatch.setattr("ops.notify.urllib.request.urlopen", lambda *args, **kwargs: called.append(args))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    result = send_alert(SPAM)
    assert result["delivered"] is False
    assert result["reason"] == "experimental_message_blocked"
    assert called == []
    blocked = authorize({"state": "APPROVED_SIGNAL", "text": SPAM, "fresh": True}, _user(), registry=REGISTRY)
    assert blocked["send"] is False
    assert "EXPERIMENTAL — NOT VALIDATED" not in open("ops/worker.py", encoding="utf-8").read()


def test_empty_registry_blocks_even_when_every_switch_is_on():
    event = _approved()
    account = _user()
    account["experimental_alerts"] = True
    decision = dispatch(event, account, _ok(), now_ms=100, registry=[])
    assert decision["reason"] == "production_wait_default"
    assert decision["delivered"] is False
    assert authorize({"state": "PAPER_CANDIDATE", "strategy": "future-strategy", "version": "future-1", "symbol": "BTCUSDT", "fresh": True, "complete": True}, account, registry=REGISTRY)["reason"] == "not_approved"
    assert authorize({"state": "RESEARCH_OBSERVATION", "strategy": "E1-donchian-20", "version": "e1-20261016", "symbol": "BTCUSDT", "fresh": True}, account, registry=REGISTRY)["reason"] == "not_approved"


def test_promotion_is_required_and_a_real_send_is_not_repeated(tmp_path):
    sent = []

    def send(text, chat_id=None):
        sent.append((text, chat_id))
        return {"delivered": True, "telegram_message_id": 9, "telegram_chat_id": chat_id}

    log = DeliveryLog(tmp_path / "deliveries.jsonl")
    first = dispatch(_approved(), _user(), send, now_ms=100, registry=REGISTRY, delivery_log=log, user_id="user-a")
    assert first["delivered"] is True
    assert sent == [("Aureon approved signal.", "11")]
    again = dispatch(_approved(), _user(), send, now_ms=100, registry=REGISTRY, delivery_log=DeliveryLog(tmp_path / "deliveries.jsonl"), user_id="user-a")
    assert again["reason"] == "duplicate"
    assert len(sent) == 1
    assert load_promotions(tmp_path / "missing.json") == []


def test_user_settings_are_isolated_and_checked_at_send_time():
    calls = []
    other = _user(chat="22")
    other["id"] = "user-b"
    dispatch(_approved(), _user(), lambda text, chat_id=None: calls.append(chat_id) or {"delivered": True, "telegram_message_id": 1, "telegram_chat_id": chat_id}, now_ms=100, registry=REGISTRY)
    assert calls == ["11"]
    off = _user()
    off["notifications_enabled"] = False
    off["experimental_alerts"] = True
    assert dispatch(_approved(), off, _ok(), now_ms=100, registry=REGISTRY)["reason"] == "alerts_off"
    missing = _user()
    missing["telegram"] = {"verified": False, "chat_id": "11"}
    assert authorize(_approved(), missing, now_ms=100, registry=REGISTRY)["reason"] == "unverified_destination"
    revoked = _user()
    revoked["telegram"]["revoked"] = True
    assert authorize(_approved(), revoked, now_ms=100, registry=REGISTRY)["reason"] == "unverified_destination"
    expired = dispatch(_approved(expires_at_ms=50), _user(), _ok(), now_ms=90, registry=REGISTRY)
    assert expired["reason"] == "expired"
    same = authorize(_approved(), _user(), now_ms=100, registry=REGISTRY, already_sent={"evt-1"})
    assert same["reason"] == "duplicate"


def test_telegram_failures_are_not_success():
    def malformed(text, chat_id=None):
        return {"ok": True, "delivered": True, "telegram_chat_id": chat_id}

    assert dispatch(_approved(), _user(), malformed, now_ms=100, registry=REGISTRY)["delivered"] is False

    def wrong_chat(text, chat_id=None):
        return {"delivered": True, "telegram_message_id": 3, "telegram_chat_id": "999"}

    assert dispatch(_approved(), _user(), wrong_chat, now_ms=100, registry=REGISTRY)["delivered"] is False


def test_http_errors_do_not_count_as_delivery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def http(code, body):
        def boom(*args, **kwargs):
            raise urllib.error.HTTPError("https://api.telegram.org", code, "bad", {}, io.BytesIO(body))
        return boom

    monkeypatch.setattr("ops.notify.urllib.request.urlopen", http(403, b'{"ok":false,"description":"Forbidden"}'))
    denied = send_alert("hello", chat_id="11")
    assert denied["delivered"] is False
    assert denied["reason"] == "Forbidden"
    monkeypatch.setattr("ops.notify.time.sleep", lambda seconds: None)
    calls = {"n": 0}

    def limited(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError("https://api.telegram.org", 429, "limited", {}, io.BytesIO(b'{"parameters":{"retry_after":0}}'))
        raise TimeoutError("slow")

    monkeypatch.setattr("ops.notify.urllib.request.urlopen", limited)
    failed = send_alert("hello", chat_id="11")
    assert failed["delivered"] is False
    assert "secret-token" not in json.dumps(failed)


def test_pairing_token_is_single_use_and_not_a_typed_id(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    first = register("ada", "password-a")
    second = register("bea", "password-b")
    assert update_profile(first["id"], {"signal_style": "apex_momentum", "currency": "USD", "capital": 25, "experimental_alerts": False})
    saved = get(first["id"])
    assert saved["profile"]["signal_style"] == "apex_momentum"
    assert saved["profile"]["max_risk_pct"] == 2.5
    assert PROFILES["orion_precision"]["risk_per_trade_percent"] == 1.5
    assert PROFILES["aegis_shield"]["risk_per_trade_percent"] == 0.8
    prefs = update_prefs(first["id"], {"markets": ["XAUUSD", "BTCUSDT"]})
    assert prefs["prefs"]["timeframes"]["XAUUSD"] == "1h"
    started = start_telegram_link(first["id"], claimed_id="999")
    pending = get(first["id"]).get("telegram_pending")
    assert pending.get("token_hash")
    assert "token" not in pending
    assert started["token"] not in json.dumps(pending)
    linked = process_start_command(started["token"], "555", "777")
    assert linked["ok"] is True
    assert get(first["id"])["telegram"]["chat_id"] == "777"
    assert process_start_command(started["token"], "555", "777")["error"] == "not_found"
    assert process_start_command("other", "1", "2")["error"] == "not_found"
    stolen = start_telegram_link(second["id"])
    assert process_start_command(stolen["token"], "4", "777")["error"] == "destination_in_use"
    assert unlink_telegram(first["id"]) is True
    assert get(first["id"])["telegram"]["revoked"] is True
    account = get(first["id"])
    account["profile"]["experimental_alerts"] = True
    assert authorize(_approved(), account, now_ms=100, registry=REGISTRY)["reason"] == "unverified_destination"


def test_worker_does_not_send_bias_or_open_a_position(tmp_path, monkeypatch):
    monkeypatch.delenv("AUREON_SHADOW", raising=False)
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: {"symbol": symbol, "close_time_ms": 9000, "fresh": True, "close": 10})
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": [{"h": 12, "l": 11, "c": 11.5} for _ in range(21)]})
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":true}')
    sent = []
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), prefs, experimental_path=tmp_path / "book.jsonl")
    worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text, chat_id=None: sent.append(text) or {"delivered": True, "telegram_message_id": 1, "telegram_chat_id": chat_id})
    assert sent == []
    assert not any(row.get("type") in {"paper_open", "paper_close", "notify"} for row in worker.ledger.read())
    assert not any(row.get("type") in {"paper_open", "paper_close"} for row in worker.book.read())
    assert PRODUCTION == "WAIT_DEFAULT"
