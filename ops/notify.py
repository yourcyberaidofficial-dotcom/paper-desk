"""Telegram notifier. Fail-closed without a token. Never paper-fills on failure."""

import json
import os
import time
import urllib.error
import urllib.request


def _retry_delay(value):
    try:
        delay = int(value)
    except (TypeError, ValueError):
        return None
    return min(max(delay, 0), 30)


def _accepted(payload: dict) -> dict:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    chat = result.get("chat") if isinstance(result.get("chat"), dict) else {}
    message_id = result.get("message_id")
    chat_id = chat.get("id")
    if payload.get("ok") is True and message_id is not None and chat_id is not None:
        return {
            "status": "DELIVERED",
            "delivered": True,
            "telegram_message_id": message_id,
            "telegram_chat_id": chat_id,
            "read_proof": False,
        }
    return {
        "status": "FAILED",
        "delivered": False,
        "reason": payload.get("description") or "telegram_not_ok",
        "read_proof": False,
    }


def _blocked_text(text: str) -> str | None:
    """The pre-patch experimental sender must not reach Telegram under any flag."""
    sample = text or ""
    if "EXPERIMENTAL — NOT VALIDATED" in sample:
        return "experimental_message_blocked"
    if "LONG_BIAS" in sample or "SHORT_BIAS" in sample:
        return "experimental_message_blocked"
    if "stale or unavailable" in sample:
        return "experimental_message_blocked"
    return None


def send_alert(text: str, token: str | None = None, chat_id: str | None = None) -> dict:
    blocked = _blocked_text(text)
    if blocked:
        return {"status": "FAILED", "reason": blocked, "delivered": False, "read_proof": False}
    token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN")
    if chat_id is None:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {"status": "FAILED", "reason": "missing_credentials", "delivered": False, "read_proof": False}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode())
            return _accepted(payload)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {}
            retry_after = (payload.get("parameters") or {}).get("retry_after")
            failed = {
                "status": "FAILED",
                "delivered": False,
                "reason": payload.get("description") or f"http_{exc.code}",
                "read_proof": False,
            }
            if exc.code == 429 and attempt == 1:
                delay = _retry_delay(retry_after)
                if delay is None:
                    return failed
                time.sleep(delay)
                continue
            return failed
        except Exception as exc:
            return {"status": "FAILED", "reason": type(exc).__name__, "delivered": False, "read_proof": False}
    return {"status": "FAILED", "reason": "retry_exhausted", "delivered": False, "read_proof": False}
