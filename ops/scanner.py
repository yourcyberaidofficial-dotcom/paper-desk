"""Live scan of completed bars. Observations are not approved signals."""

import time
from datetime import datetime, timezone

from ops.engine_eval import evaluate_snapshot
from ops.gold_live import completed_bid_ask_bar
from ops.plan import evidence_grade

PLAIN = {
    "no_setup": "No qualifying setup on this completed bar.",
    "e1_inside_channel": "Price is inside the prior 20-bar channel. No breakout.",
    "benchmark_failed": "A Donchian breakout was observed. It stays a research note until a strategy is approved.",
    "rules_complete_not_approved": "The rule matched. This is a paper candidate, not an approved signal.",
    "OUTSIDE_SESSION": "Gold is outside the session this rule uses.",
    "MARKET_CLOSED": "The gold market is closed.",
    "stale_bars": "The last completed bar is too old to scan.",
    "insufficient_history": "There are not enough completed bars to evaluate the rule.",
    "invalid_bars": "The latest bars failed the price check.",
    "no_completed_bars": "No completed bar is available.",
    "no_executable_levels": "The rule matched, but a stop and target could not be placed.",
}


def _when(ms):
    if not isinstance(ms, (int, float)) or ms <= 0:
        return "unknown"
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _view_state(state):
    return {
        "DATA_UNAVAILABLE": "BLOCKED",
        "WAIT": "WAIT",
        "RESEARCH_OBSERVATION": "SETUP_WATCH",
        "PAPER_CANDIDATE": "SIGNAL_CANDIDATE",
        "APPROVED_SIGNAL": "APPROVED_SIGNAL",
    }.get(state, "WAIT")


def _headline(rows):
    for state in ("APPROVED_SIGNAL", "QUALIFIED_FOR_REVIEW", "PAPER_CANDIDATE", "RESEARCH_OBSERVATION"):
        for row in rows:
            if row.get("state") == state:
                return row
    return rows[0] if rows else None


def present_window(window, now_ms):
    symbol = window.get("symbol")
    interval = window.get("interval")
    bars = window.get("bars") or []
    last = bars[-1] if bars else None
    updated = last.get("close_time_ms") if last else None
    price = last.get("close") if last else None
    live = bool(window.get("ok") and last and last.get("complete") and last.get("fresh") and window.get("source_kind") == "prospective")
    base = {
        "symbol": symbol,
        "interval": interval,
        "source": window.get("provider") or "unknown",
        "quote": window.get("quote_semantics") or "unknown",
        "price": price,
        "updated_at": _when(updated),
        "updated_at_ms": updated,
        "approved": False,
        "production": "WAIT_DEFAULT",
        "alert": "unavailable",
    }
    if symbol == "XAUUSD":
        quote = window.get("quote_semantics") or (last.get("quote_semantics") if last else None) or "missing_quote"
        if quote != "dukascopy_xauusd_bid_ask" or not completed_bid_ask_bar(last):
            shown = quote if quote != "dukascopy_xauusd_bid_ask" else "missing_bid_ask"
            if quote == "ohlc_not_bid_ask" and last and last.get("complete") and last.get("fresh") and len(bars) >= 60:
                shared = _shared_reading(symbol, interval, bars, now_ms, price)
                if shared is not None:
                    shared["quote"] = quote
                    shared["message"] = "Spot chart OHLC, not a bid/ask hour. The London rule was not calculated. " + (shared.get("message") or "")
                    base.update(shared)
                    base["price"] = price
                    return base
            base.update(
                status="unavailable",
                state="DATA_UNAVAILABLE",
                scanner_state="BLOCKED",
                direction="WAIT",
                rule=None,
                price=None,
                evidence_grade=None,
                evaluated=False,
                message=f"Gold is blocked. The feed is {shown}, not a completed bid/ask bar. The London rule was not calculated.",
            )
            return base
    if symbol == "XAUUSD" and not live:
        base.update(status="unavailable", state="DATA_UNAVAILABLE", scanner_state="BLOCKED", message=f"Gold scanning is temporarily unavailable. Last verified market update: {_when(updated)}.")
        return base
    if not live:
        base.update(status="stale", state="DATA_UNAVAILABLE", scanner_state="BLOCKED", message=f"{symbol} is not being scanned. The latest completed bar is missing or stale.")
        return base
    if symbol in {"BTCUSDT", "ETHUSDT"}:
        shared = _shared_reading(symbol, interval, bars, now_ms, price)
        if shared is not None:
            base.update(shared)
            return base
    rows = evaluate_snapshot(symbol, bars, window.get("higher") or [], now_ms, interval)
    head = _headline(rows) or {}
    state = head.get("state") or "WAIT"
    if state == "DATA_UNAVAILABLE":
        message = PLAIN.get(head.get("reason"), f"{symbol} cannot be scanned from the latest bars.")
        status = "unavailable"
    elif state == "WAIT":
        message = PLAIN.get(head.get("reason"), "No qualifying setup yet.")
        status = "scanning"
    elif state == "RESEARCH_OBSERVATION":
        message = "A condition matched a strategy that has not passed research. It is not an approved signal."
        status = "scanning"
    elif state == "PAPER_CANDIDATE":
        message = PLAIN["rules_complete_not_approved"]
        status = "scanning"
    else:
        message = "No qualifying setup yet."
        state = "WAIT"
        status = "scanning"
    grade = evidence_grade({
        "completed_bar": live,
        "fresh": live,
        "enough_history": head.get("reason") != "insufficient_history",
        "rule_checked": bool(head.get("strategy")),
        "explained": bool(message),
        "promoted": False,
    })
    base.update(
        status=status,
        state=state,
        message=message,
        rule=head.get("strategy"),
        version=head.get("version"),
        event_id=head.get("event_id"),
        direction=head.get("direction") or "WAIT",
        invalidation=head.get("reason"),
        scanner_state=_view_state(state),
        evidence_grade=grade["evidence_grade"],
        evidence_label=grade["label"],
        calibrated=False,
        evaluated=True,
    )
    if not base.get("approved"):
        if base.get("scanner_state") in {"SIGNAL_CANDIDATE", "APPROVED_SIGNAL", "SETUP_WATCH"}:
            base["message"] = "No approved strategy is active. " + (base.get("message") or "")
            base["scanner_state"] = "WAIT"
        base["evidence_grade"] = None
        base["evidence_label"] = "not a probability of profit, and this rule is not approved"
        base["eligible_for_alert"] = False
    return base


def _shared_reading(symbol, interval, bars, now_ms, price):
    """The same decision the terminal uses. It does not write an inbox event."""
    try:
        from ops.terminal_signal import decide
        evaluation = decide(symbol, interval, "auto", bars, now_ms, None)
    except Exception:
        return None
    card = {
        "decision": evaluation.get("decision"),
        "decision_label": evaluation.get("decision_label"),
        "entry": evaluation.get("entry"),
        "stop": evaluation.get("stop"),
        "target": evaluation.get("target"),
        "reward_risk": evaluation.get("reward_risk"),
        "rule": evaluation.get("strategy"),
        "version": evaluation.get("version"),
        "runtime_status": evaluation.get("runtime_status"),
        "message": evaluation.get("reason") or "No qualifying setup yet.",
        "approved": False,
        "eligible_for_alert": False,
        "evaluated": True,
        "evidence_grade": None,
        "evidence_label": "not a probability of profit",
        "price": evaluation.get("reference_price") if evaluation.get("reference_price") is not None else price,
        "direction": evaluation.get("decision") or "WAIT",
    }
    if evaluation.get("blocked"):
        card.update(status="unavailable", state="DATA_UNAVAILABLE", scanner_state="BLOCKED")
        return card
    if evaluation.get("decision") in {"BUY", "SELL"} and evaluation.get("entry") is not None and evaluation.get("runtime_status") == "experimental":
        card.update(
            status="scanning",
            state="PAPER_CANDIDATE",
            scanner_state="EXPERIMENTAL",
            direction="BUY",
            evidence_label="experimental plan, not a probability of profit",
        )
        return card
    card.update(status="scanning", state="WAIT", scanner_state="WAIT")
    return card


def scan(windows, now_ms=None):
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    rows = [present_window(window, now_ms) for window in windows]
    return {
        "scanned_at": _when(now_ms),
        "production": "WAIT_DEFAULT",
        "broker": False,
        "approved_strategy": None,
        "notice": "No approved strategy is currently active; trade alerts are unavailable.",
        "markets": rows,
    }
