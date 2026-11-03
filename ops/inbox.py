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
            rows.append(bind_identity(json.loads(line)))
    return rows


def _write(user_id, rows):
    path = _path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows[-200:]), encoding="utf-8")


def opportunity_identity(symbol, interval, family, direction, anchor):
    """One key for a setup: instrument, timeframe, family, direction, originating bar."""
    if symbol in (None, "") or interval in (None, "") or family in (None, "") or direction in (None, ""):
        return None
    try:
        origin = int(anchor)
    except (TypeError, ValueError):
        return None
    return f"opp:{symbol}:{interval}:{family}:{direction}:{origin}"


def identity_from_row(row):
    """Use a stored key. Otherwise derive one. Never invent a bar or a family."""
    row = row or {}
    if row.get("opportunity_id"):
        return row["opportunity_id"]
    family = row.get("family") or row.get("rule") or row.get("strategy")
    direction = row.get("direction") or row.get("decision")
    return opportunity_identity(row.get("symbol"), row.get("interval"), family, direction, row.get("bar_close_ms"))


def bind_identity(row):
    """Fill a missing key in memory. Entry, stop and target are not touched."""
    if row.get("opportunity_id"):
        return row
    derived = identity_from_row(row)
    if derived:
        row["opportunity_id"] = derived
        row["identity_source"] = "derived_from_stored_fields"
    else:
        row["opportunity_id"] = f"legacy:{row.get('id')}"
        row["identity_source"] = "legacy_unkeyed"
    return row


def notice_id(kind, opportunity_id):
    return f"{kind}:{opportunity_id}"


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
    row = {
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
        "market_evaluation_id": notice.get("market_evaluation_id"),
        "opportunity_id": notice.get("opportunity_id"),
        "plan_version": notice.get("plan_version"),
        "account_decision_id": notice.get("account_decision_id"),
        "family": notice.get("family"),
        "direction": notice.get("direction"),
        "lifecycle": "active",
        "events": [{
            "id": notice.get("event_id") or event_id,
            "state": "active",
            "note": "The plan was recorded. Active means it is still the visible plan, not that an order was opened.",
            "created_ms": int(notice.get("created_ms") or time.time() * 1000),
            "entry": notice.get("entry"),
            "stop": notice.get("stop"),
            "target": notice.get("target"),
        }],
    }
    for key in ("snapshot_id", "reading_version", "source_id", "provider", "explanation", "candle_open_ms"):
        if notice.get(key) not in (None, ""):
            row[key] = notice.get(key)
    if notice.get("snapshot_id"):
        row["events"][0]["snapshot_id"] = notice.get("snapshot_id")
        if notice.get("reading_version"):
            row["events"][0]["reading_version"] = notice.get("reading_version")
    rows.append(row)
    _write(user_id, rows)
    return {"ok": True, "duplicate": False, "stored": True}


def find_open_opportunity(user_id, opportunity_id):
    """Match the full key only. A shared market or family is not the same setup."""
    if not opportunity_id or str(opportunity_id).startswith("legacy:"):
        return None
    for row in _read(user_id):
        if row.get("kind") != "experimental":
            continue
        if row.get("lifecycle") in {"superseded", "expired", "invalidated"}:
            continue
        if row.get("opportunity_id") == opportunity_id:
            return row
    return None


def append_event(user_id, opportunity_id, event):
    """Add an observation. The original entry, stop and target stay as first recorded."""
    if _safe(user_id) is None or not opportunity_id:
        return {"ok": False, "reason": "missing"}
    rows = _read(user_id)
    for row in rows:
        if row.get("opportunity_id") != opportunity_id:
            continue
        events = list(row.get("events") or [])
        if any(item.get("id") == event.get("id") for item in events):
            return {"ok": True, "duplicate": True, "stored": False, "opportunity_id": opportunity_id}
        events.append(event)
        row["events"] = events[-40:]
        row["lifecycle"] = event.get("state") or row.get("lifecycle")
        row["lifecycle_note"] = event.get("note")
        _write(user_id, rows)
        return {"ok": True, "stored": True, "opportunity_id": opportunity_id}
    return {"ok": False, "reason": "missing", "stored": False}


def retire_opportunity(user_id, opportunity_id, now_ms, note=None):
    """Retire one originating setup. Other cards, including the same market, stay."""
    if _safe(user_id) is None or not opportunity_id:
        return 0
    rows = _read(user_id)
    changed = 0
    for row in rows:
        if row.get("opportunity_id") != opportunity_id:
            continue
        if row.get("lifecycle") in {"superseded", "expired", "invalidated"}:
            continue
        row["lifecycle"] = "superseded"
        row["lifecycle_note"] = note or "This originating setup was retired. Its entry, stop and target were not rewritten, and no other setup was retired with it."
        row["retired_ms"] = now_ms
        changed += 1
    if changed:
        _write(user_id, rows)
    return changed


def expire_stale(user_id, symbol, interval, now_ms, protect_bar_ms=None):
    """Expire a card only when its own originating bar is no longer current."""
    if _safe(user_id) is None:
        return 0
    from ops.bars import interval_ms
    try:
        step = interval_ms(interval)
    except ValueError:
        step = 60_000
    rows = _read(user_id)
    changed = 0
    for row in rows:
        if row.get("kind") != "experimental" or row.get("symbol") != symbol or row.get("interval") != interval:
            continue
        if row.get("lifecycle") in {"superseded", "expired", "invalidated"}:
            continue
        try:
            close = int(row.get("bar_close_ms") or 0)
        except (TypeError, ValueError):
            continue
        if not close or now_ms - close <= 2 * step:
            continue
        if protect_bar_ms is not None:
            try:
                if close == int(protect_bar_ms):
                    continue
            except (TypeError, ValueError):
                pass
        row["lifecycle"] = "expired"
        row["lifecycle_note"] = "This entry expired because its own candle is no longer current. Other setups were not retired."
        changed += 1
    if changed:
        _write(user_id, rows)
    return changed


def items(user_id):
    rows = _read(user_id) if _safe(user_id) else []
    return list(reversed(rows))


def notice_view(item, now_ms):
    """Display fields only. The stored notice is not rewritten."""
    row = dict(item or {})
    created = row.get("created_ms")
    if isinstance(created, (int, float)):
        age = max(0, int(now_ms) - int(created))
        row["age_ms"] = age
        if age >= 3 * 86400000:
            row["freshness"] = "historical"
            row["age_label"] = f"{age // 86400000} days ago"
        elif age >= 86400000:
            row["freshness"] = "stale"
            row["age_label"] = "1 day ago" if age < 2 * 86400000 else f"{age // 86400000} days ago"
        else:
            hours = age // 3600000
            row["freshness"] = "current"
            row["age_label"] = "just now" if hours < 1 else f"{hours} hours ago"
    else:
        row["freshness"] = "unknown"
        row["age_label"] = "time unknown"
    row["read_state"] = "read" if row.get("read") else "unread"
    decision = row.get("decision")
    if row.get("blocked") == "xau_minute_unlicensed" or row.get("validation_status") == "BLOCKED":
        row["notice_class"] = "blocked research observation"
    elif decision == "WAIT":
        row["notice_class"] = "WAIT notification"
    elif decision in {"BUY", "SELL"} and not row.get("approved"):
        row["notice_class"] = "research observation"
    else:
        row["notice_class"] = "inbox notice"
    row["paper_order"] = False
    return row


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
    actionable = [row for row in markets if row.get("scanner_state") in {"SIGNAL_CANDIDATE", "SETUP_WATCH", "APPROVED_SIGNAL", "EXPERIMENTAL"}]
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
        "timeframes": [item for item in timeframes if item in {"1m", "3m", "15m", "1h", "4h", "1d"}],
        "buy": bool(saved["buy"]) if "buy" in saved else True,
        "sell": bool(saved["sell"]) if "sell" in saved else True,
        "experimental": bool(saved["experimental"]) if "experimental" in saved else False,
        "wait_notices": bool(saved["wait_notices"]) if "wait_notices" in saved else False,
    }


def deliver_evaluation(user_id, user, result):
    """History is separate. This only stores an inbox event the saved filters allow."""
    result = result or {}
    from ops.data_rights import is_rights_reason
    if result.get("rights_status") in {"rights_unconfirmed", "prohibited", "restricted", "fixture_only"} or is_rights_reason(result.get("reason")) or is_rights_reason(result.get("blocked")):
        return {"stored": False, "duplicate": False, "reason": "commercial_use_unverified"}
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
    if kind != "status" and side in {"BUY", "SELL"} and (payload.get("entry") is None or payload.get("stop") is None or payload.get("target") is None):
        return {"stored": False, "duplicate": False, "reason": "incomplete"}
    family = str(result.get("rule") or result.get("strategy") or "unspecified")
    direction = side
    anchor = result.get("bar_close_ms")
    opportunity_id = opportunity_identity(symbol, interval, family, direction, anchor)
    if opportunity_id is None:
        return {"stored": False, "duplicate": False, "reason": "incomplete"}
    plan_version = f"plan:{payload.get('entry')}:{payload.get('stop')}:{payload.get('target')}"
    market_evaluation_id = f"mkt:{symbol}:{interval}:{anchor}:{result.get('version') or result.get('strategy')}"
    account_decision_id = f"acct:{user_id}:{opportunity_id}:{plan_version}"
    event_id = f"evt:{account_decision_id}:active"
    card_id = notice_id(kind, opportunity_id)
    existing = find_open_opportunity(user_id, opportunity_id) if kind == "experimental" else None
    if existing:
        appended = append_event(user_id, existing.get("opportunity_id"), {
            "id": f"evt:{existing.get('opportunity_id')}:reevaluated:{plan_version}",
            "state": "reevaluated",
            "note": "A later reading of this same originating setup was recorded. The original entry, stop and target were not rewritten.",
            "created_ms": result.get("requested_ms"),
            "market_evaluation_id": market_evaluation_id,
            "observed_entry": payload.get("entry"),
            "observed_stop": payload.get("stop"),
            "observed_target": payload.get("target"),
        })
        return {
            "stored": False,
            "duplicate": True,
            "reason": "same_opportunity",
            "id": existing.get("id"),
            "opportunity_id": existing.get("opportunity_id"),
            "appended": appended.get("stored"),
        }
    from ops.delivery import load_promotions
    saved = offer(user_id, {
        "id": card_id,
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
        "market_evaluation_id": market_evaluation_id,
        "opportunity_id": opportunity_id,
        "plan_version": plan_version,
        "account_decision_id": account_decision_id,
        "event_id": event_id,
        "family": family,
        "direction": direction,
    }, registry=load_promotions() if kind == "official" else None)
    return {
        "stored": bool(saved.get("stored")),
        "duplicate": bool(saved.get("duplicate")),
        "reason": saved.get("reason") or ("stored" if saved.get("stored") else "duplicate" if saved.get("duplicate") else "refused"),
        "id": card_id,
        "opportunity_id": opportunity_id,
        "kind": kind,
    }


def record_desk_plan(user_id, user, result):
    """Save a plan the account asked to review.

    This is not a notification, not an AutoPilot signal, and not an order.
    Experimental alert settings do not apply. The original entry is not rewritten.
    """
    result = result or {}
    from ops.data_rights import is_rights_reason
    if result.get("rights_status") in {"rights_unconfirmed", "prohibited", "restricted", "fixture_only"} or is_rights_reason(result.get("reason")) or is_rights_reason(result.get("blocked")):
        return {"stored": False, "duplicate": False, "reason": "commercial_use_unverified", "order_opened": False}
    if result.get("reading_class") != "manual_plan" or result.get("manual_paper") is not True:
        return {"stored": False, "duplicate": False, "reason": "not_a_manual_plan", "reading_class": result.get("reading_class"), "order_opened": False}
    if result.get("autopilot_eligible") is True or result.get("approved") is True:
        return {"stored": False, "duplicate": False, "reason": "not_a_manual_plan", "order_opened": False}
    if result.get("quality") != "ok":
        return {"stored": False, "duplicate": False, "reason": "not_fresh", "order_opened": False}
    decision = result.get("decision")
    if decision not in {"BUY", "SELL"}:
        return {"stored": False, "duplicate": False, "reason": "not_a_plan", "order_opened": False}
    entry, stop, target = result.get("entry"), result.get("stop"), result.get("target")
    if entry is None or stop is None or target is None:
        return {"stored": False, "duplicate": False, "reason": "incomplete", "order_opened": False}
    symbol = result.get("symbol")
    interval = str(result.get("interval") or "")
    anchor = result.get("bar_close_ms")
    if anchor in (None, ""):
        anchor = result.get("candle_close_ms")
    family = str(result.get("rule") or result.get("strategy") or "unspecified")
    opportunity_id = opportunity_identity(symbol, interval, family, decision, anchor)
    if opportunity_id is None:
        return {"stored": False, "duplicate": False, "reason": "incomplete", "order_opened": False}
    plan_version = f"plan:{entry}:{stop}:{target}"
    existing = find_open_opportunity(user_id, opportunity_id)
    if existing:
        appended = append_event(user_id, existing.get("opportunity_id"), {
            "id": f"evt:{existing.get('opportunity_id')}:reviewed:{result.get('snapshot_id') or plan_version}",
            "state": "reviewed",
            "note": "The account reviewed this plan again. The original entry, stop and target were not rewritten.",
            "created_ms": result.get("reading_at_ms") or int(time.time() * 1000),
            "snapshot_id": result.get("snapshot_id"),
            "reading_version": result.get("reading_version"),
            "observed_entry": entry,
            "observed_stop": stop,
            "observed_target": target,
        })
        return {
            "stored": False,
            "duplicate": True,
            "reason": "same_opportunity",
            "opportunity_id": existing.get("opportunity_id"),
            "appended": appended.get("stored"),
            "order_opened": False,
        }
    explanation = result.get("explanation") or result.get("message") or result.get("reason")
    saved = offer(user_id, {
        "id": notice_id("experimental", opportunity_id),
        "kind": "experimental",
        "symbol": symbol,
        "interval": interval,
        "strategy": result.get("strategy") or family,
        "version": result.get("reading_version") or result.get("strategy"),
        "state": decision,
        "decision": decision,
        "message": explanation,
        "entry": entry,
        "stop": stop,
        "target": target,
        "invalidation": result.get("invalidation"),
        "reference_price": result.get("reference_price") if result.get("reference_price") is not None else result.get("price"),
        "fresh": True,
        "validation_status": result.get("validation_status") or "FAIL",
        "approved": False,
        "bar_close_ms": anchor,
        "created_ms": result.get("reading_at_ms") or int(time.time() * 1000),
        "market_evaluation_id": f"mkt:{symbol}:{interval}:{anchor}:{result.get('reading_version') or family}",
        "opportunity_id": opportunity_id,
        "plan_version": plan_version,
        "account_decision_id": f"acct:{user_id}:{opportunity_id}:{plan_version}",
        "event_id": f"evt:acct:{user_id}:{opportunity_id}:{plan_version}:active",
        "family": family,
        "direction": decision,
        "snapshot_id": result.get("snapshot_id"),
        "reading_version": result.get("reading_version"),
        "source_id": result.get("source_id"),
        "provider": result.get("provider"),
        "explanation": explanation,
        "candle_open_ms": result.get("candle_open_ms"),
    })
    return {
        "stored": bool(saved.get("stored")),
        "duplicate": bool(saved.get("duplicate")),
        "reason": saved.get("reason") or ("stored" if saved.get("stored") else "refused"),
        "opportunity_id": opportunity_id if saved.get("stored") or saved.get("duplicate") else None,
        "order_opened": False,
    }
