"""Per-user routing for a future approved event. This build does not send."""

from ops.worker import PRODUCTION, may_send_observation


def decide_route(event, profile, already_sent=None, now_ms=0, production=PRODUCTION):
    """Read the user switch at decision time. WAIT_DEFAULT and unapproved events never send."""
    profile = profile or {}
    telegram = profile.get("telegram") or {}
    event = event or {}
    if production == "WAIT_DEFAULT" or event.get("state") != "APPROVED_SIGNAL":
        reason = "production_wait_default" if production == "WAIT_DEFAULT" else "not_approved"
        return {"send": False, "delivered": False, "reason": reason}
    if event.get("expires_at_ms") is not None and now_ms > event["expires_at_ms"]:
        return {"send": False, "delivered": False, "reason": "expired"}
    event_key = event.get("event_id")
    if event_key and already_sent and event_key in already_sent:
        return {"send": False, "delivered": False, "reason": "duplicate"}
    if not may_send_observation(profile, production=production):
        if not profile.get("experimental_alerts"):
            reason = "alerts_off"
        elif not (telegram.get("verified") and telegram.get("chat_id")):
            reason = "unverified_destination"
        else:
            reason = "not_eligible"
        return {"send": False, "delivered": False, "reason": reason}
    cap = profile.get("max_risk_pct")
    proposed = 0.5
    if cap is not None:
        proposed = min(float(cap), proposed)
    return {
        "send": True,
        "delivered": False,
        "reason": "eligible_to_attempt",
        "chat_id": str(telegram.get("chat_id")),
        "risk_pct": proposed,
        "event_id": event_key,
    }


def dispatch(event, profile, sender, already_sent=None, now_ms=0, production=PRODUCTION):
    decision = decide_route(event, profile, already_sent=already_sent, now_ms=now_ms, production=production)
    if not decision["send"]:
        return decision
    try:
        result = sender("approved event", chat_id=decision["chat_id"])
    except Exception as exc:
        return {"send": False, "delivered": False, "reason": type(exc).__name__, "status": "FAILED"}
    delivered = bool(result.get("delivered")) and result.get("telegram_message_id") is not None and result.get("telegram_chat_id") is not None
    out = {
        "send": True,
        "delivered": delivered,
        "status": "DELIVERED" if delivered else "FAILED",
        "reason": None if delivered else (result.get("reason") or "telegram_not_ok"),
        "event_id": decision.get("event_id"),
        "telegram_message_id": result.get("telegram_message_id"),
        "telegram_chat_id": result.get("telegram_chat_id"),
    }
    return out


def style_risk(profile, strategy_rr):
    """Risk may be under the style cap and must not go over it. No currency conversion."""
    cap = profile.get("max_risk_pct")
    proposed = 0.5 if cap is None else min(0.5, float(cap))
    min_rr = profile.get("min_rr")
    allowed = strategy_rr is None or min_rr is None or strategy_rr + 1e-9 >= float(min_rr)
    return {"risk_pct": proposed, "cap": cap, "rr_allowed": allowed, "currency": profile.get("currency")}
