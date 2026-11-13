"""One Telegram path. The bot update binds the chat. The outbox does not scan accounts."""

import threading

from ops.inbox_notify import flush, queue_card
from ops.telegram_in import UpdateInbox, apply_update, intake_mode, poll_if_enabled
from ops.users import connect_telegram, get, process_start_command, register, start_telegram_link


def _account(tmp_path, monkeypatch, name):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    return register(name, "password-s")


def test_start_token_binds_one_chat_and_a_username_does_not(tmp_path, monkeypatch):
    owner = _account(tmp_path, monkeypatch, "ada")
    started = start_telegram_link(owner["id"])
    refused = process_start_command(started["token"], "@ada", "@ada")
    assert refused["error"] == "username_not_accepted"
    assert "not a chat id" in refused["message"]
    assert get(owner["id"]).get("telegram") in (None, {})
    linked = process_start_command(started["token"], "424242", "424242")
    assert linked["ok"] is True
    assert get(owner["id"])["telegram"]["chat_id"] == "424242"
    assert process_start_command(started["token"], "424242", "424242")["error"] == "not_found"


def test_two_accounts_cannot_claim_one_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    first = register("ada", "password-s")
    second = register("bea", "password-s")
    token_a = start_telegram_link(first["id"])["token"]
    token_b = start_telegram_link(second["id"])["token"]
    barrier = threading.Barrier(2)
    found = {}

    def claim(name, token):
        barrier.wait()
        found[name] = process_start_command(token, "515151", "515151")

    threads = [threading.Thread(target=claim, args=("ada", token_a)), threading.Thread(target=claim, args=("bea", token_b))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(row.get("error") or "ok" for row in found.values()) == ["destination_in_use", "ok"]
    owners = [
        user_id for user_id in (first["id"], second["id"])
        if (get(user_id).get("telegram") or {}).get("verified") and str((get(user_id).get("telegram") or {}).get("chat_id")) == "515151"
    ]
    assert len(owners) == 1
    again = connect_telegram(second["id"] if owners[0] == first["id"] else first["id"], "515151")
    assert again["error"] == "destination_in_use"


def test_outbox_backs_off_without_listing_users(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))

    def explode():
        raise AssertionError("list_users")

    monkeypatch.setattr("ops.users.list_users", explode)
    user = {"id": "acct-a", "telegram": {"verified": True, "revoked": False, "chat_id": "42"}, "profile": {"telegram_notices": True}}
    card = {
        "event_id": "evt-rate",
        "symbol": "BTCUSDT",
        "interval": "15m",
        "decision": "BUY",
        "entry": 1,
        "stop": 0.5,
        "target": 2,
    }
    assert queue_card("acct-a", user, card)["queued"] is True
    calls = {"n": 0}

    def limited(text, chat_id=None):
        calls["n"] += 1
        return {"delivered": False, "reason": "http_429", "retry_after": 30, "telegram_chat_id": chat_id}

    assert flush(limited)["sent"] == 0
    assert flush(limited)["pending"] == 1
    assert calls["n"] == 1
    blocked = dict(card)
    blocked["event_id"] = "evt-block"
    assert queue_card("acct-a", user, blocked)["queued"] is True
    blocked_calls = {"n": 0}

    def forbid(text, chat_id=None):
        blocked_calls["n"] += 1
        if chat_id == "42" and blocked_calls["n"] == 1:
            return {"delivered": False, "reason": "Forbidden: bot was blocked by the user", "telegram_chat_id": chat_id}
        return {"delivered": True, "telegram_message_id": 3, "telegram_chat_id": chat_id}

    assert flush(forbid)["sent"] == 0
    assert flush(forbid)["sent"] == 0
    assert blocked_calls["n"] == 1


def test_webhook_and_polling_do_not_run_together(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fixture-token")
    monkeypatch.setenv("AUREON_TELEGRAM_POLL", "1")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "fixture-secret")
    assert intake_mode() == "webhook"
    called = []
    assert poll_if_enabled(opener=lambda *args: called.append(args) or {"ok": True}) is None
    assert called == []
    from ops.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    ignored = client.post("/api/telegram/update", json={"update_id": 1, "message": {"text": "/start token", "chat": {"id": 1}, "from": {"id": 1}}})
    assert ignored.get_json()["reason"] == "webhook_secret"
    accepted = client.post(
        "/api/telegram/update",
        json={"update_id": 2, "message": {"text": "/start", "chat": {"id": 1}, "from": {"id": 1}}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "fixture-secret"},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["ignored"] is True
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET")
    assert intake_mode() == "polling"


def test_settings_shows_one_link_and_not_a_typed_id(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = register("ada", "password-s")
    from ops.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["user_exp"] = 9_999_999_999
    page = client.get("/settings").get_data(as_text=True)
    assert "Create a one-time Telegram link" in page
    assert "Numeric ID" not in page
    assert "press the link button" not in page
    assert "@username is not a chat id" in page
    assert 'id="tgtest"' in page and 'id="tgunlink"' in page
    started = start_telegram_link(owner["id"])
    inbox = UpdateInbox(tmp_path / "seen.jsonl")
    assert apply_update({"update_id": 9, "message": {"text": "/start " + started["token"], "from": {"id": 77}, "chat": {"id": 77}}}, inbox)["ok"] is True
    assert client.get("/api/me").get_json()["telegram_state"] == "connected"
    assert client.post(f"/api/users/{owner['id']}/telegram", json={"telegram_id": "@ada"}).status_code == 404
