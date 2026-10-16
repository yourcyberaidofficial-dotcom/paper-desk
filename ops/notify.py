"""Telegram notifier. Fail-closed without a token. Never paper-fills on failure."""

import json
import os
import urllib.request

def send_alert(text: str, token: str | None = None, chat_id: str | None = None) -> dict:
    token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return {"status": "FAILED", "reason": "missing_credentials", "delivered": False, "read_proof": False}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
        return {
            "status": "DELIVERED" if payload.get("ok") else "FAILED",
            "delivered": bool(payload.get("ok")),
            "telegram_message_id": payload.get("result", {}).get("message_id"),
            "read_proof": False,
        }
    except Exception as exc:
        return {"status": "FAILED", "reason": type(exc).__name__, "delivered": False, "read_proof": False}
