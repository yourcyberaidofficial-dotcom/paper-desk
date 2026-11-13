"""Inbox notices are queued first and marked delivered only after Telegram accepts them."""

from ops.inbox_notify import card_text, enabled, flush, queue_card, queue_update


def _user(chat="42"):
    return {
        "id": "acct-a",
        "telegram": {"verified": True, "revoked": False, "chat_id": chat},
        "profile": {"telegram_notices": True},
    }


def _card():
    return {
        "event_id": "evt-1",
        "symbol": "BTCUSDT",
        "interval": "15m",
        "decision": "SELL",
        "entry": 100.0,
        "stop": 110.0,
        "target": 80.0,
        "reward_risk": 2.0,
        "strategy": "Trend pullback",
        "explanation": "The completed candle met this account's sell rules.",
    }


def test_a_complete_card_is_sent_once_and_only_after_acceptance(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    user = _user()
    assert queue_card("acct-a", user, _card())["queued"] is True
    assert queue_card("acct-a", user, _card())["reason"] == "duplicate"

    def rejected(text, chat_id=None):
        return {"delivered": False, "reason": "URLError"}

    assert flush(rejected)["sent"] == 0

    calls = []

    def accepted(text, chat_id=None):
        calls.append((text, chat_id))
        return {"delivered": True, "telegram_message_id": 9, "telegram_chat_id": chat_id}

    assert flush(accepted)["sent"] == 1
    assert flush(accepted)["sent"] == 0
    assert len(calls) == 1
    text, chat = calls[0]
    assert chat == "42"
    assert "Entry 100.0" in text and "Stop 110.0" in text and "Target 80.0" in text
    assert "not a fill" in text
    assert "bot" not in text.lower()


def test_missing_or_unlicensed_levels_are_not_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    broken = _card()
    broken["stop"] = None
    assert card_text(broken) is None
    assert queue_card("acct-a", _user(), broken)["queued"] is False
    licensed = _card()
    licensed["event_id"] = "evt-2"
    licensed["levels_persisted"] = False
    assert card_text(licensed) is None


def test_another_account_is_not_sent_this_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    queue_card("acct-a", _user("1"), _card())
    other = _card()
    other["event_id"] = "evt-b"
    queue_card("acct-b", _user("2"), other)
    seen = []

    def accepted(text, chat_id=None):
        seen.append(chat_id)
        return {"delivered": True, "telegram_message_id": len(seen), "telegram_chat_id": chat_id}

    flush(accepted)
    assert seen == ["1", "2"]


def test_notices_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    user = _user()
    user["profile"]["telegram_notices"] = False
    assert enabled(user) is False
    assert queue_card("acct-a", user, _card())["queued"] is False


def test_a_level_update_is_queued_without_a_new_price(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    note = "The candle range reached the stop. Bid and ask were not used. This is not a fill."
    queued = queue_update("acct-a", _user(), "evt-stop", "ETHUSDT", "1h", "stop_touched", note)
    assert queued["queued"] is True
    sent = []

    def accepted(text, chat_id=None):
        sent.append(text)
        return {"delivered": True, "telegram_message_id": 3, "telegram_chat_id": chat_id}

    flush(accepted)
    assert "ETHUSDT 1h" in sent[0]
    assert "Entry" not in sent[0]


def test_cards_already_in_the_inbox_are_sent_without_scanning_every_account(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.inbox_notify import flush, queue_open

    user = _user()
    card = _card()
    card["lifecycle"] = "active"

    def explode():
        raise AssertionError("the outbox must not list every account")

    monkeypatch.setattr("ops.users.list_users", explode)
    monkeypatch.setattr("ops.inbox.items", lambda user_id: [card] if user_id == "acct-a" else [])
    calls = []

    def accepted(text, chat_id=None):
        calls.append(chat_id)
        return {"delivered": True, "telegram_message_id": 4, "telegram_chat_id": chat_id}

    assert queue_open(user) == 1
    assert flush(accepted)["sent"] == 1
    assert flush(accepted)["sent"] == 0
    assert calls == ["42"]


def test_each_account_only_gets_the_markets_it_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    btc = _user("1")
    btc["inbox_delivery"] = {
        "enabled": True,
        "markets": ["BTCUSDT"],
        "timeframes": ["15m"],
        "buy": True,
        "sell": True,
        "experimental": True,
    }
    eth = _user("2")
    eth["id"] = "acct-b"
    eth["inbox_delivery"] = {
        "enabled": True,
        "markets": ["ETHUSDT"],
        "timeframes": ["1h"],
        "buy": False,
        "sell": True,
        "experimental": True,
    }
    btc_card = _card()
    eth_card = _card()
    eth_card["event_id"] = "evt-eth"
    eth_card["symbol"] = "ETHUSDT"
    eth_card["interval"] = "1h"
    assert queue_card("acct-a", btc, btc_card)["queued"] is True
    assert queue_card("acct-a", btc, eth_card)["reason"] == "filtered"
    assert queue_card("acct-b", eth, eth_card)["queued"] is True
    assert queue_card("acct-b", eth, btc_card)["reason"] == "filtered"
