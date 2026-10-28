"""Live scan of completed bars. Observations are not approved signals."""

import time
from datetime import datetime, timezone

from ops.engine_eval import evaluate_snapshot

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
    if symbol == "XAUUSD" and not live:
        base.update(status="unavailable", state="DATA_UNAVAILABLE", message=f"Gold scanning is temporarily unavailable. Last verified market update: {_when(updated)}.")
        return base
    if not live:
        base.update(status="stale", state="DATA_UNAVAILABLE", message=f"{symbol} is not being scanned. The latest completed bar is missing or stale.")
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
        message = PLAIN["benchmark_failed"]
        status = "scanning"
    elif state == "PAPER_CANDIDATE":
        message = PLAIN["rules_complete_not_approved"]
        status = "scanning"
    else:
        message = "No qualifying setup yet."
        state = "WAIT"
        status = "scanning"
    base.update(
        status=status,
        state=state,
        message=message,
        rule=head.get("strategy"),
        version=head.get("version"),
        event_id=head.get("event_id"),
        direction=head.get("direction") or "WAIT",
        invalidation=head.get("reason"),
    )
    return base


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
