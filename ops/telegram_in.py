"""One Telegram intake path. Polling is the operating mode.

Webhook posts are acknowledged so Telegram stops retrying, and they do not
link an account unless the webhook secret matches. Duplicate update_id values
are ignored.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from ops.users import process_start_command

ROOT = Path(__file__).resolve().parents[1]
OFFSET_PATH = ROOT / "data" / "paper" / "telegram_offset.txt"
SEEN_PATH = ROOT / "data" / "paper" / "telegram_updates.jsonl"


def polling_enabled():
    flag = os.environ.get("AUREON_TELEGRAM_POLL", "").strip().lower()
    if flag in {"0", "false", "off"}:
        return False
    if flag in {"1", "true", "on"}:
        return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
    if "pytest" in sys.modules:
        return False
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


class UpdateInbox:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else SEEN_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seen = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        self.seen.add(int(json.loads(line)["update_id"]))
                    except (ValueError, KeyError, TypeError):
                        continue
        if len(self.seen) > 2000:
            self.seen = set(sorted(self.seen)[-1000:])

    def accept(self, update_id):
        if update_id is None:
            return True
        try:
            update_id = int(update_id)
        except (TypeError, ValueError):
            return False
        if update_id in self.seen:
            return False
        self.seen.add(update_id)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"update_id": update_id}) + "\n")
        return True


def apply_update(update, inbox=None):
    update = update or {}
    inbox = inbox or UpdateInbox()
    update_id = update.get("update_id")
    if not inbox.accept(update_id):
        return {"ok": True, "duplicate": True}
    message = update.get("message") or {}
    text = str(message.get("text") or "")
    if not text.startswith("/start "):
        return {"ok": True, "ignored": True}
    token = text.split(" ", 1)[1].strip().split()[0]
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    result = process_start_command(token, str(sender.get("id") or ""), str(chat.get("id") or ""))
    return {"ok": bool(result.get("ok")), "error": result.get("error"), "user_id": result.get("user_id")}


def _api(token, method, params):
    query = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{token}/{method}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "aureon-paper-desk"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode())
    if not payload.get("ok"):
        raise RuntimeError("telegram_api_not_ok")
    return payload.get("result")


def poll_once(token, offset=None, opener=None):
    params = {"timeout": 0, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = int(offset)
    if opener is None:
        result = _api(token, "getUpdates", params)
    else:
        result = opener(token, "getUpdates", params)
    updates = result or []
    next_offset = offset
    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            next_offset = update_id + 1
        apply_update(update)
    return updates, next_offset


_webhook_cleared = False


def poll_if_enabled(opener=None):
    global _webhook_cleared
    if not polling_enabled():
        return None
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    if not _webhook_cleared:
        try:
            if opener is None:
                _api(token, "deleteWebhook", {"drop_pending_updates": "false"})
            else:
                opener(token, "deleteWebhook", {})
        except Exception:
            return None
        _webhook_cleared = True
    offset = None
    if OFFSET_PATH.exists():
        raw = OFFSET_PATH.read_text(encoding="utf-8").strip()
        if raw.isdigit():
            offset = int(raw)
    _updates, next_offset = poll_once(token, offset, opener=opener)
    if next_offset is not None:
        OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
        OFFSET_PATH.write_text(str(next_offset), encoding="utf-8")
    return next_offset
