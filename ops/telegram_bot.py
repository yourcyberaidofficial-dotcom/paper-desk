"""Telegram delivery outbox. One update mode, one delivery per event.

No token means no network call. A message cannot approve a strategy,
change a risk limit, or open an order.
"""

from __future__ import annotations

import json
from pathlib import Path

from ops.ai_safety import order_language

EVENTS = frozenset({
    "forming",
    "confirmed",
    "invalidated",
    "expired",
    "feed_interrupted",
    "health",
    "research_change",
})


class Bot:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.outbox = self.root / "outbox.jsonl"
        self.seen = self.root / "update_ids.json"
        self.mode_path = self.root / "mode.json"

    def configure(self, mode):
        if mode not in {"webhook", "polling"}:
            return {"ok": False, "reason": "unknown_mode"}
        current = self.mode()
        if current and current != mode:
            return {"ok": False, "reason": "one_update_mode", "mode": current}
        self.mode_path.write_text(json.dumps({"mode": mode}), encoding="utf-8")
        return {"ok": True, "mode": mode}

    def mode(self):
        if not self.mode_path.exists():
            return None
        return json.loads(self.mode_path.read_text(encoding="utf-8")).get("mode")

    def get_me(self, token, transport=None):
        if not token:
            return {"ok": False, "reason": "missing_credentials", "network": False, "username": None}
        if transport is None:
            return {"ok": False, "reason": "transport_not_configured", "network": False, "username": None}
        status, payload = transport("GET", "getMe", None)
        user = payload.get("result") if isinstance(payload, dict) else None
        if status != 200 or not isinstance(user, dict) or not user.get("username"):
            return {"ok": False, "reason": "telegram_unavailable", "network": True, "username": None}
        return {"ok": True, "reason": None, "network": True, "username": user["username"], "live": False}

    def accept_update(self, update_id):
        try:
            update_id = int(update_id)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "invalid_update"}
        seen = set(json.loads(self.seen.read_text(encoding="utf-8"))) if self.seen.exists() else set()
        if update_id in seen:
            return {"ok": False, "reason": "duplicate_update"}
        seen.add(update_id)
        self.seen.write_text(json.dumps(sorted(seen)), encoding="utf-8")
        return {"ok": True, "reason": "accepted"}

    def enqueue(self, event):
        kind = event.get("event")
        if kind == "wait" or kind == "WAIT":
            return {"stored": False, "reason": "wait_suppressed"}
        if kind not in EVENTS:
            return {"stored": False, "reason": "unknown_event"}
        text = str(event.get("text") or "")
        if order_language(text):
            return {"stored": False, "reason": "order_language_blocked"}
        account = str(event.get("account_id") or "")
        event_id = str(event.get("event_id") or "")
        if not account or not event_id:
            return {"stored": False, "reason": "missing_identity"}
        if any(row["event_id"] == event_id for row in self.pending()):
            return {"stored": False, "reason": "duplicate_event"}
        row = {
            "event_id": event_id,
            "event": kind,
            "account_id": account,
            "chat_id": str(event.get("chat_id") or ""),
            "text": text,
            "status": "pending",
            "attempts": 0,
            "authorizes_trade": False,
        }
        self._write(self.pending() + [row])
        return {"stored": True, "reason": "queued", "row": row}

    def deliver(self, transport):
        rows = self.pending()
        delivered = []
        for row in rows:
            if row["status"] == "delivered":
                continue
            if not row["chat_id"]:
                row["status"] = "failed"
                row["reason"] = "missing_chat"
                row["attempts"] += 1
                continue
            row["attempts"] += 1
            try:
                status, payload = transport("POST", "sendMessage", {"chat_id": row["chat_id"], "text": row["text"]})
            except Exception:
                row["status"] = "pending"
                row["reason"] = "transport_error"
                continue
            result = payload.get("result") if isinstance(payload, dict) else None
            message_id = result.get("message_id") if isinstance(result, dict) else None
            if status == 200 and message_id is not None:
                row["status"] = "delivered"
                row["telegram_message_id"] = message_id
                delivered.append(row)
            elif status == 429 and row["attempts"] < 2:
                row["status"] = "pending"
                row["reason"] = "rate_limited"
            else:
                row["status"] = "failed"
                row["reason"] = "telegram_rejected"
        self._write(rows)
        return {"delivered": len(delivered), "rows": rows}

    def for_account(self, account_id):
        return [row for row in self.pending() if row["account_id"] == account_id]

    def pending(self):
        if not self.outbox.exists():
            return []
        return [json.loads(line) for line in self.outbox.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _write(self, rows):
        text = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
        self.outbox.write_text(text, encoding="utf-8")
