"""Send an inbox card to the account's own Telegram chat.

The market loop only queues the text. Delivery reads this outbox, not every
account file. A row is delivered only after Telegram returns a message id.
A 429 waits. A blocked chat is not retried. Missing prices are not filled in.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from pathlib import Path

from ops.delivery import DeliveryLog

_WAKE = threading.Event()


def wake():
    """Ask the sender to run. This does not read the user directory."""
    _WAKE.set()


def wait_for_work(seconds, stop_event=None):
    """Sleep until a notice is queued, the pause ends, or the desk is stopping.

    True means the caller should stop. False means it should send or poll.
    """
    end = time.monotonic() + max(0.0, float(seconds))
    while True:
        if stop_event is not None and stop_event.is_set():
            return True
        remaining = end - time.monotonic()
        if remaining <= 0:
            return False
        if _WAKE.wait(timeout=min(0.25, remaining)):
            _WAKE.clear()
            return False


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


def allowed(user, card):
    """A saved inbox filter is authoritative. An account with no filter is unchanged."""
    saved = (user or {}).get("inbox_delivery") if isinstance(user, dict) else None
    if not isinstance(saved, dict):
        return True
    from ops.inbox import inbox_settings

    settings = inbox_settings(user)
    if not settings["enabled"]:
        return False
    symbol = (card or {}).get("symbol")
    interval = str((card or {}).get("interval") or "")
    side = (card or {}).get("decision") or (card or {}).get("state")
    if symbol not in settings["markets"] or interval not in settings["timeframes"]:
        return False
    if side == "BUY" and not settings["buy"]:
        return False
    if side == "SELL" and not settings["sell"]:
        return False
    if side in {"BUY", "SELL"} and not settings["experimental"]:
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
    wake()
    return {"queued": True, "reason": "queued"}


def queue_open(user=None):
    """Queue this account's stored cards once it is connected.

    Other accounts are not opened. The sender does not call this on a timer.
    """
    if not isinstance(user, dict) or not enabled(user):
        return 0
    from ops.inbox import items

    queued = 0
    for row in items(user.get("id")):
        if row.get("lifecycle") not in (None, "", "active"):
            continue
        if row.get("decision") not in {"BUY", "SELL"}:
            continue
        if queue_card(user.get("id"), user, row).get("queued"):
            queued += 1
    return queued


def classify_transport(status, payload):
    """One delivery decision for the inbox outbox and the research outbox."""
    payload = payload if isinstance(payload, dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if status == 200 and result.get("message_id") is not None:
        return "delivered", result.get("message_id"), None
    description = str(payload.get("description") or "")
    if status == 429 or "429" in description:
        delay = (payload.get("parameters") or {}).get("retry_after") or 2
        try:
            delay = min(60, max(1, int(delay)))
        except (TypeError, ValueError):
            delay = 2
        return "retry", None, delay
    lowered = description.lower()
    if status == 403 or any(word in lowered for word in ("blocked", "forbidden", "chat not found", "deactivated")):
        return "blocked", None, None
    return "failed", None, None


def _classify_alert(result):
    result = result or {}
    reason = str(result.get("reason") or "")
    lowered = reason.lower()
    if (
        result.get("delivered")
        and result.get("telegram_message_id") is not None
    ):
        return "delivered", None
    if "429" in reason or "retry_after" in lowered or result.get("retry_after") is not None:
        delay = result.get("retry_after") or 2
        try:
            delay = min(60, max(1, int(delay)))
        except (TypeError, ValueError):
            delay = 2
        return "retry", delay
    if any(word in lowered for word in ("blocked", "forbidden", "chat not found", "deactivated", "can't initiate", "cannot initiate")):
        return "blocked", None
    if reason in {"missing_credentials", "URLError", "TimeoutError", "timeout"} or "timeout" in lowered:
        return "retry", None
    return "failed", None


def flush(sender=None):
    """Send pending rows. This reads the outbox only, never the user tree."""
    from ops.notify import send_alert

    sender = sender or send_alert
    path = _outbox()
    handle = _locked(path)
    sent = 0
    pending = 0
    retry_after = None
    now = time.time()
    try:
        rows = _read(path)
        log = _delivered()
        for row in rows:
            if row.get("status") == "delivered":
                continue
            if row.get("status") == "failed":
                continue
            if row.get("key") in log.sent:
                row["status"] = "delivered"
                continue
            not_before = row.get("not_before")
            if isinstance(not_before, (int, float)) and float(not_before) > now:
                pending += 1
                wait = float(not_before) - now
                retry_after = wait if retry_after is None else min(retry_after, wait)
                continue
            try:
                result = sender(row.get("text") or "", chat_id=row.get("chat_id")) or {}
            except Exception as exc:
                row["status"] = "pending"
                row["reason"] = type(exc).__name__
                pending += 1
                continue
            accepted = (
                bool(result.get("delivered"))
                and result.get("telegram_message_id") is not None
                and str(result.get("telegram_chat_id")) == str(row.get("chat_id"))
            )
            kind, delay = ("delivered", None) if accepted else _classify_alert(result)
            if kind == "delivered" and not accepted:
                kind = "failed"
            if kind == "delivered":
                row["status"] = "delivered"
                row["telegram_message_id"] = result.get("telegram_message_id")
                row.pop("reason", None)
                row.pop("not_before", None)
                log.remember(row["key"], {
                    "delivered": True,
                    "user_id": row.get("user_id"),
                    "event_key": row.get("key"),
                    "telegram_message_id": result.get("telegram_message_id"),
                })
                sent += 1
            elif kind == "retry":
                row["status"] = "pending"
                row["reason"] = result.get("reason") or "retry"
                row["attempts"] = int(row.get("attempts") or 0) + 1
                if delay:
                    row["not_before"] = now + float(delay)
                    retry_after = float(delay) if retry_after is None else min(retry_after, float(delay))
                else:
                    row.pop("not_before", None)
                pending += 1
            elif kind == "blocked":
                row["status"] = "failed"
                row["reason"] = "user_blocked"
                row.pop("not_before", None)
            else:
                row["status"] = "failed"
                row["reason"] = result.get("reason") or "telegram_not_ok"
                row.pop("not_before", None)
        _write(path, rows[-400:])
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
    return {"sent": sent, "pending": pending, "retry_after": retry_after}


def queue_card(user_id, user, card):
    if not allowed(user, card):
        return {"queued": False, "reason": "filtered"}
    return queue(user_id, user, card.get("event_id") or card.get("id"), card_text(card))


def queue_update(user_id, user, event_id, symbol, interval, state, note):
    if not allowed(user, {"symbol": symbol, "interval": interval}):
        return {"queued": False, "reason": "filtered"}
    return queue(user_id, user, event_id, update_text(symbol, interval, state, note))
