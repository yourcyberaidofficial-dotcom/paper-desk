"""Per-user in-app notices. This module does not call Telegram."""

import json
import time
from pathlib import Path

from ops.users import ROOT as USER_ROOT


def _safe(user_id):
    text = str(user_id or "")
    if not text or "/" in text or "\\" in text or ".." in text:
        return None
    return text


def _path(user_id):
    return USER_ROOT / "inbox" / f"{_safe(user_id)}.jsonl"


def _read(user_id):
    path = _path(user_id)
    if path is None or not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _write(user_id, rows):
    path = _path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows[-200:]), encoding="utf-8")


def offer(user_id, notice, registry=None):
    if _safe(user_id) is None:
        return {"ok": False, "reason": "bad_user"}
    kind = notice.get("kind")
    if kind == "official":
        promoted = [
            row for row in (registry or [])
            if row.get("promoted") and row.get("strategy") == notice.get("strategy") and row.get("symbol") == notice.get("symbol")
        ]
        if notice.get("state") != "APPROVED_SIGNAL" or not promoted:
            return {"ok": False, "reason": "not_approved", "stored": False}
        actionable = True
        label = "Approved signal"
    elif kind == "research":
        actionable = False
        label = "Informational. Not an approved trade."
    elif kind == "status":
        actionable = False
        label = "Scanner status"
    else:
        return {"ok": False, "reason": "unknown_kind", "stored": False}
    event_id = str(notice.get("id") or "")
    if not event_id:
        return {"ok": False, "reason": "missing_id", "stored": False}
    rows = _read(user_id)
    if any(row.get("id") == event_id for row in rows):
        return {"ok": True, "duplicate": True, "stored": False}
    rows.append({
        "id": event_id,
        "kind": kind,
        "label": label,
        "actionable": actionable,
        "symbol": notice.get("symbol"),
        "interval": notice.get("interval"),
        "strategy": notice.get("strategy"),
        "version": notice.get("version"),
        "state": notice.get("state"),
        "message": notice.get("message"),
        "created_ms": int(notice.get("created_ms") or time.time() * 1000),
        "read": False,
    })
    _write(user_id, rows)
    return {"ok": True, "duplicate": False, "stored": True}


def items(user_id):
    rows = _read(user_id) if _safe(user_id) else []
    return list(reversed(rows))


def unread_count(user_id):
    return sum(1 for row in items(user_id) if not row.get("read"))


def mark_read(user_id, event_id=None):
    if _safe(user_id) is None:
        return {"ok": False}
    rows = _read(user_id)
    for row in rows:
        if event_id in (None, row.get("id")):
            row["read"] = True
    _write(user_id, rows)
    return {"ok": True, "unread": unread_count(user_id)}


def record_scan(user_id, body, plan, now_ms):
    """One note per event id. A quiet scan is recorded once per UTC day, not on every refresh."""
    plan = plan or {}
    stored = []
    day = time.strftime("%Y-%m-%d", time.gmtime(now_ms / 1000))
    markets = body.get("markets") or []
    actionable = [row for row in markets if row.get("scanner_state") in {"SIGNAL_CANDIDATE", "SETUP_WATCH", "APPROVED_SIGNAL"}]
    for row in markets:
        if row.get("scanner_state") == "BLOCKED":
            result = offer(user_id, {
                "id": f"feed:{row.get('symbol')}:{day}",
                "kind": "status",
                "symbol": row.get("symbol"),
                "interval": row.get("interval"),
                "state": "BLOCKED",
                "message": row.get("message") or "This market could not be scanned.",
                "created_ms": now_ms,
            })
            stored.append(result)
        elif row.get("scanner_state") in {"SETUP_WATCH", "SIGNAL_CANDIDATE"} and plan.get("research_alerts"):
            result = offer(user_id, {
                "id": row.get("event_id") or f"watch:{row.get('symbol')}:{row.get('updated_at_ms')}",
                "kind": "research",
                "symbol": row.get("symbol"),
                "interval": row.get("interval"),
                "strategy": row.get("rule"),
                "version": row.get("version"),
                "state": row.get("scanner_state"),
                "message": row.get("message"),
                "created_ms": now_ms,
            })
            stored.append(result)
        elif row.get("scanner_state") == "APPROVED_SIGNAL":
            stored.append(offer(user_id, {**row, "id": row.get("event_id"), "kind": "official", "strategy": row.get("rule")}, registry=[]))
    if not actionable:
        names = ", ".join(row.get("symbol") or "?" for row in markets) or "the configured markets"
        stored.append(offer(user_id, {
            "id": f"quiet:{day}",
            "kind": "status",
            "state": "WAIT",
            "message": f"Scan completed for {names}. No qualifying setup.",
            "created_ms": now_ms,
        }))
    return stored
