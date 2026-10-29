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
    from ops.users import ROOT
    safe = _safe(user_id)
    if safe is None:
        return None
    return ROOT / "inbox" / f"{safe}.jsonl"


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
    elif kind == "experimental":
        if notice.get("approved") or notice.get("state") == "APPROVED_SIGNAL":
            return {"ok": False, "reason": "not_approved", "stored": False}
        actionable = False
        label = "Experimental and unapproved. Not a validated or profitable strategy."
    elif kind == "status":
        actionable = False
        label = "WAIT notice. Not a trade." if notice.get("decision") == "WAIT" else "Scanner status"
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
        "decision": notice.get("decision"),
        "entry": notice.get("entry"),
        "stop": notice.get("stop"),
        "target": notice.get("target"),
        "invalidation": notice.get("invalidation"),
        "size": notice.get("size"),
        "reference_price": notice.get("reference_price"),
        "fresh": notice.get("fresh"),
        "validation_status": notice.get("validation_status"),
        "approved": bool(notice.get("approved")),
        "bar_close_ms": notice.get("bar_close_ms"),
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


def inbox_settings(user):
    """Missing keys stay at the default. Experimental alerts and WAIT notices start off."""
    saved = (user or {}).get("inbox_delivery") if isinstance((user or {}).get("inbox_delivery"), dict) else {}
    markets = saved.get("markets") if "markets" in saved else ["BTCUSDT", "ETHUSDT", "XAUUSD"]
    timeframes = saved.get("timeframes") if "timeframes" in saved else ["15m", "1h", "4h", "1d"]
    return {
        "enabled": bool(saved["enabled"]) if "enabled" in saved else True,
        "markets": [item for item in markets if item in {"BTCUSDT", "ETHUSDT", "XAUUSD"}],
        "timeframes": [item for item in timeframes if item in {"15m", "1h", "4h", "1d"}],
        "buy": bool(saved["buy"]) if "buy" in saved else True,
        "sell": bool(saved["sell"]) if "sell" in saved else True,
        "experimental": bool(saved["experimental"]) if "experimental" in saved else False,
        "wait_notices": bool(saved["wait_notices"]) if "wait_notices" in saved else False,
    }


def deliver_evaluation(user_id, user, result):
    """History is separate. This only stores an inbox event the saved filters allow."""
    result = result or {}
    settings = inbox_settings(user)
    if result.get("blocked") or result.get("rejected") == "market_mismatch":
        return {"stored": False, "duplicate": False, "reason": "blocked"}
    if not settings["enabled"]:
        return {"stored": False, "duplicate": False, "reason": "disabled"}
    symbol = result.get("symbol")
    interval = str(result.get("interval") or "")
    if symbol not in settings["markets"]:
        return {"stored": False, "duplicate": False, "reason": "market"}
    if interval not in settings["timeframes"]:
        return {"stored": False, "duplicate": False, "reason": "timeframe"}
    decision = result.get("decision")
    match = result.get("experimental_match") if isinstance(result.get("experimental_match"), dict) else {}
    official = (
        decision in {"BUY", "SELL"}
        and result.get("approved") is True
        and result.get("validation_status") == "PASS"
        and result.get("eligible_for_alert") is True
    )
    if official:
        side = decision
        payload = result
        kind = "official"
    elif decision in {"BUY", "SELL"}:
        side = decision
        payload = result
        kind = "experimental"
    elif match.get("decision") in {"BUY", "SELL"}:
        side = match["decision"]
        payload = match
        kind = "experimental"
    elif decision == "WAIT":
        if not settings["wait_notices"]:
            return {"stored": False, "duplicate": False, "reason": "wait_suppressed"}
        side = "WAIT"
        payload = result
        kind = "status"
    else:
        return {"stored": False, "duplicate": False, "reason": "not_actionable"}
    if side == "BUY" and not settings["buy"]:
        return {"stored": False, "duplicate": False, "reason": "buy_off"}
    if side == "SELL" and not settings["sell"]:
        return {"stored": False, "duplicate": False, "reason": "sell_off"}
    if kind == "experimental" and not settings["experimental"]:
        return {"stored": False, "duplicate": False, "reason": "experimental_off"}
    if kind != "status" and (result.get("fresh") is False or result.get("reference_price") is None):
        return {"stored": False, "duplicate": False, "reason": "incomplete"}
    if kind != "status" and side == "BUY" and (payload.get("entry") is None or payload.get("stop") is None):
        return {"stored": False, "duplicate": False, "reason": "incomplete"}
    from ops.delivery import load_promotions
    saved = offer(user_id, {
        "id": f"{kind}:{symbol}:{interval}:{result.get('strategy')}:{result.get('bar_close_ms')}:{side}",
        "kind": kind,
        "symbol": symbol,
        "interval": interval,
        "strategy": result.get("strategy"),
        "version": result.get("strategy"),
        "state": "APPROVED_SIGNAL" if kind == "official" else side,
        "decision": side,
        "message": payload.get("reason") or result.get("reason"),
        "entry": payload.get("entry"),
        "stop": payload.get("stop"),
        "target": payload.get("target"),
        "invalidation": result.get("invalidation"),
        "size": payload.get("size"),
        "reference_price": result.get("reference_price"),
        "fresh": result.get("fresh"),
        "validation_status": result.get("validation_status"),
        "approved": False if kind != "official" else True,
        "bar_close_ms": result.get("bar_close_ms"),
        "created_ms": result.get("requested_ms"),
    }, registry=load_promotions() if kind == "official" else None)
    return {
        "stored": bool(saved.get("stored")),
        "duplicate": bool(saved.get("duplicate")),
        "reason": saved.get("reason") or ("stored" if saved.get("stored") else "duplicate" if saved.get("duplicate") else "refused"),
        "id": f"{kind}:{symbol}:{interval}:{result.get('strategy')}:{result.get('bar_close_ms')}:{side}",
        "kind": kind,
    }
