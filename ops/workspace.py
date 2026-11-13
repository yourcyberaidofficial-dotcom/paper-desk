"""One signed-in view of the three markets. Shared events, private instructions."""

from ops.plan import normalize, present_size, propose_size, visible_to_user
from ops.profiles import risk_cap
from ops.registry import BY_ID, catalog

PANELS = (("BTCUSDT", "15m"), ("ETHUSDT", "15m"), ("XAUUSD", "1h"))


def _instruction(event, user):
    profile = user.get("profile") or {}
    cap = risk_cap(profile.get("signal_style"))
    plan = user.get("plan") or normalize({}, {}, cap)
    gate = visible_to_user({**event, "evidence_grade": event.get("evidence_grade") or 0}, plan)
    spec = BY_ID.get(event.get("strategy")) or {}
    size = {"ok": False, "reason": "missing_inputs", "order": False}
    if event.get("entry") is not None and event.get("stop") is not None and profile.get("capital") and plan.get("risk_per_trade_percent"):
        size = propose_size(profile["capital"], plan["risk_per_trade_percent"], event["entry"], event["stop"])
    shown = present_size(size)
    size = dict(size)
    size["quantity_orderable"] = bool(size.get("quantity_orderable"))
    size["executable_quantity"] = shown["executable_quantity"]
    size["size_presentation"] = shown["text"]
    approved = bool(event.get("approved"))
    if gate.get("reason") == "below_threshold":
        why_not = "This setup did not meet your minimum quality threshold."
    elif not approved:
        why_not = "No strategy is approved, so this cannot be a trade instruction."
    else:
        why_not = ""
    return {
        "id": event.get("id"),
        "what": f"Saved observation · {event.get('symbol')} {event.get('interval') or ''} {event.get('direction') or 'WAIT'}".strip(),
        "live": False,
        "strategy": spec.get("name") or event.get("strategy") or "No single strategy",
        "why": event.get("message") or "The rule did not produce a setup.",
        "qualifies": False,
        "why_not": "This is a saved research observation. It is not the current scan. " + (why_not or "It is not a trade instruction."),
        "account": size,
        "currency": profile.get("currency"),
        "invalidation": spec.get("invalidation") or "The setup is invalid when the recorded condition no longer holds.",
        "learn": spec.get("evidence") or "A failed or blocked research result stays unapproved.",
        "source": event.get("source"),
        "scanner_state": event.get("scanner_state"),
        "your_plan": gate.get("reason"),
    }


def compose(user, scan_body, history):
    by_pair = {}
    by_symbol = {}
    for row in (scan_body or {}).get("markets") or []:
        if not isinstance(row, dict):
            continue
        by_symbol[row.get("symbol")] = row
        by_pair[(row.get("symbol"), row.get("interval"))] = row
    panels = []
    for symbol, interval in PANELS:
        row = dict(by_pair.get((symbol, interval)) or by_symbol.get(symbol) or {})
        row.setdefault("symbol", symbol)
        row.setdefault("interval", interval)
        row.setdefault("scanner_state", "BLOCKED")
        row.setdefault("approved", False)
        if row["scanner_state"] == "BLOCKED" and not row.get("message"):
            row["message"] = f"{symbol} was not scanned. The feed did not return a usable completed bar."
        if symbol == "XAUUSD":
            row["quote_note"] = "Chart OHLC is not a verified bid/ask price."
        panels.append(row)
    user = user or {}
    current = []
    labeled = []
    for event in history or []:
        labeled.append({
            "id": event.get("id"),
            "source": event.get("source"),
            "symbol": event.get("symbol"),
            "strategy": event.get("strategy"),
            "scanner_state": event.get("scanner_state"),
            "message": event.get("message"),
            "delivered": False,
            "filled": False,
            "pnl": None,
            "label": "Historical replay" if event.get("source") == "historical_replay" else "Live observation",
        })
        if event.get("scanner_state") not in {"SETUP_WATCH", "SIGNAL_CANDIDATE", "APPROVED_SIGNAL"}:
            continue
        view = visible_to_user(event, user.get("plan") or normalize({}, {}, None))
        if view.get("show") is False:
            continue
        current.append(_instruction(event, user))
    return {
        "panels": panels,
        "current": current[:12],
        "history": list(reversed(labeled))[:40],
        "strategies": catalog()["strategies"],
        "approved_strategy": None,
        "production": "WAIT_DEFAULT",
        "broker": False,
        "notice": (scan_body or {}).get("notice") or "No approved strategy is currently active; trade alerts are unavailable.",
        "leaders": (scan_body or {}).get("leaders") or [],
    }
