"""Telegram response handling. No network."""

import io
import json
import urllib.error

from ops.notify import send_alert


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_ok_without_message_is_not_delivery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr("ops.notify.urllib.request.urlopen", lambda *args, **kwargs: _Response({"ok": True, "result": {}}))
    result = send_alert("hello")
    assert result["delivered"] is False
    assert result["status"] == "FAILED"


def test_http_error_is_not_delivery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    def boom(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.telegram.org", 400, "bad", {}, io.BytesIO(b'{"ok":false,"description":"chat not found"}'))

    monkeypatch.setattr("ops.notify.urllib.request.urlopen", boom)
    result = send_alert("hello")
    assert result["delivered"] is False
    assert result["reason"] == "chat not found"


def test_message_and_chat_count_as_delivery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "9")
    payload = {"ok": True, "result": {"message_id": 42, "chat": {"id": 7}}}
    monkeypatch.setattr("ops.notify.urllib.request.urlopen", lambda *args, **kwargs: _Response(payload))
    result = send_alert("hello", chat_id="7")
    assert result["delivered"] is True
    assert result["status"] == "DELIVERED"
    assert result["telegram_message_id"] == 42
    assert result["telegram_chat_id"] == 7
    assert "secret-token" not in json.dumps(result)


def test_rate_limit_retries_once_then_fails(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    sleeps = []
    monkeypatch.setattr("ops.notify.time.sleep", lambda seconds: sleeps.append(seconds))
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            body = b'{"ok":false,"description":"Too Many Requests","parameters":{"retry_after":5}}'
            raise urllib.error.HTTPError("https://api.telegram.org", 429, "limited", {}, io.BytesIO(body))
        body = b'{"ok":false,"description":"chat not found"}'
        raise urllib.error.HTTPError("https://api.telegram.org", 400, "bad", {}, io.BytesIO(body))

    monkeypatch.setattr("ops.notify.urllib.request.urlopen", boom)
    result = send_alert("hello")
    assert calls["n"] == 2
    assert sleeps == [5]
    assert result["delivered"] is False
    assert result["status"] == "FAILED"
    assert result["reason"] == "chat not found"
    assert "secret-token" not in json.dumps(result)


def test_exception_is_not_delivery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    def boom(*args, **kwargs):
        raise TimeoutError("slow")

    monkeypatch.setattr("ops.notify.urllib.request.urlopen", boom)
    result = send_alert("hello")
    assert result["delivered"] is False
    assert result["status"] == "FAILED"
    assert result["reason"] == "TimeoutError"
    assert "secret-token" not in json.dumps(result)

