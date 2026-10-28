"""Per-user routing. Trade alerts go through ops.delivery and nowhere else."""

from ops.delivery import authorize, dispatch as deliver


def decide_route(event, profile, already_sent=None, now_ms=0, production=None, registry=None):
    """An empty promotion registry blocks every send. production does not override that."""
    return authorize(event, profile, now_ms=now_ms, registry=registry, already_sent=already_sent)


def dispatch(event, profile, sender, already_sent=None, now_ms=0, production=None, registry=None, delivery_log=None, user_id=None):
    return deliver(
        event,
        profile,
        sender,
        already_sent=already_sent,
        now_ms=now_ms,
        registry=registry,
        delivery_log=delivery_log,
        user_id=user_id,
    )


def style_risk(profile, strategy_rr):
    """Risk may be under the style cap and must not go over it. No currency conversion."""
    cap = profile.get("max_risk_pct")
    proposed = 0.5 if cap is None else min(0.5, float(cap))
    min_rr = profile.get("min_rr")
    allowed = strategy_rr is None or min_rr is None or strategy_rr + 1e-9 >= float(min_rr)
    return {"risk_pct": proposed, "cap": cap, "rr_allowed": allowed, "currency": profile.get("currency")}
