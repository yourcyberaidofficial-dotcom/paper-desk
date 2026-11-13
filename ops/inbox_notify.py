"""Send an inbox card to the account's own Telegram chat.

The market loop only queues the text. A later pass sends it. A row is
delivered only after Telegram returns a message id. Missing prices are not
filled in, and an unlicensed card is not sent.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from ops.delivery import DeliveryLog


def _root():
    return Path(os.environ.get("AUREON_DATA") or "data") / "paper"


def _outbox():
    return _root() / "telegram_inbox.jsonl"


def _delivered():
    return DeliveryLog(_root() / "telegram_inbox_sent.jsonl")


def _telegram(user):
    telegram = (user or {}).get("telegram") if isinstance(user, dict) else None
    return telegram if isinstance(telegram, dict) else {}


def enabled(user):
    telegram = _telegram(user)
    if telegram.get("revoked") or not telegram.get("verified") or telegram.get("chat_id") in (None, ""):
        return False
    profile = (user or {}).get("profile") if isinstance(user, dict) else None
    if isinstance(profile, dict) and profile.get("telegram_notices") is False:
        return False
    return True


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def card_text(card):
    """Use only stored fields. A missing level means there is no message."""
    card = card or {}
    if card.get("levels_persisted") is False:
        return None
    side = card.get("decision") or card.get("state")
    if side not in {"BUY", "SELL"}:
        return None
    entry, stop, target = _number(card.get("entry")), _number(card.get("stop")), _number(card.get("target"))
    symbol, interval = card.get("symbol"), card.get("interval")
    if entry is None or stop is None or target is None or not symbol or not interval:
        return None
    lines = [
        "Aureon paper notice",
        f"{symbol} {interval} {side}",
        f"Entry {entry}",
        f"Stop {stop}",
        f"Target {target}",
    ]
    reward = _number(card.get("reward_risk"))
    if reward is not None:
        lines.append(f"Reward/risk {reward}")
    if card.get("strategy"):
        lines.append(f"Strategy {card['strategy']}")
    note = card.get("explanation") or card.get("message")
    if note:
        lines.append(str(note).strip()[:400])
    lines.append("Paper only. This is not a fill.")
    return "\n".join(lines)


def update_text(symbol, interval, state, note):
    if state not in {"stop_touched", "target_touched", "ambiguous", "invalidated", "expired"}:
        return None
    if not symbol or not interval or not note:
        return None
    return "\n".join([
        "Aureon paper update",
        f"{symbol} {interval}",
        str(note).strip()[:400],
        "Paper only. This is not a fill.",
    ])


def _read(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = (path.parent / "telegram_inbox.lock").open("a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def queue(user_id, user, event_id, text):
    """Remember one message. This does not call Telegram."""
    if not enabled(user) or not user_id or not event_id or not text:
        return {"queued": False, "reason": "not_eligible"}
    key = f"{user_id}:{event_id}"
    if key in _delivered().sent:
        return {"queued": False, "reason": "duplicate"}
    path = _outbox()
    handle = _locked(path)
    try:
        rows = _read(path)
        if any(row.get("key") == key for row in rows):
            return {"queued": False, "reason": "duplicate"}
        rows.append({
            "key": key,
            "user_id": str(user_id),
            "chat_id": str(_telegram(user).get("chat_id")),
            "text": text,
            "status": "pending",
        })
        _write(path, rows)
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
    return {"queued": True, "reason": "queued"}


def queue_open():
    """Queue complete inbox cards that were stored before Telegram was connected."""
    from ops.inbox import items
    from ops.users import list_users

    queued = 0
    for user in list_users():
        if not isinstance(user, dict) or not enabled(user):
            continue
        for row in items(user.get("id")):
            if row.get("lifecycle") not in (None, "", "active"):
                continue
            if row.get("decision") not in {"BUY", "SELL"}:
                continue
            if queue_card(user.get("id"), user, row).get("queued"):
                queued += 1
    return queued


def flush(sender=None):
    """Send pending rows. Delivered means Telegram returned a message id."""
    from ops.notify import send_alert

    sender = sender or send_alert
    queue_open()
    path = _outbox()
    handle = _locked(path)
    sent = 0
    try:
        rows = _read(path)
        log = _delivered()
        for row in rows:
            if row.get("status") == "delivered":
                continue
            if row.get("key") in log.sent:
                row["status"] = "delivered"
                continue
            try:
                result = sender(row.get("text") or "", chat_id=row.get("chat_id")) or {}
            except Exception as exc:
                row["status"] = "pending"
                row["reason"] = type(exc).__name__
                continue
            accepted = (
                bool(result.get("delivered"))
                and result.get("telegram_message_id") is not None
                and str(result.get("telegram_chat_id")) == str(row.get("chat_id"))
            )
            reason = result.get("reason") or "telegram_not_ok"
            retry = reason in {"missing_credentials", "URLError", "TimeoutError", "timeout"} or "timeout" in str(reason).lower()
            if accepted:
                row["status"] = "delivered"
                row["telegram_message_id"] = result.get("telegram_message_id")
                row.pop("reason", None)
                log.remember(row["key"], {
                    "delivered": True,
                    "user_id": row.get("user_id"),
                    "event_key": row.get("key"),
                    "telegram_message_id": result.get("telegram_message_id"),
                })
                sent += 1
            elif retry:
                row["status"] = "pending"
                row["reason"] = reason
            else:
                row["status"] = "failed"
                row["reason"] = reason
        _write(path, rows[-400:])
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
    return {"sent": sent}


def queue_card(user_id, user, card):
    return queue(user_id, user, card.get("event_id") or card.get("id"), card_text(card))


def queue_update(user_id, user, event_id, symbol, interval, state, note):
    return queue(user_id, user, event_id, update_text(symbol, interval, state, note))
