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

QUOTE_LABELS = {
    "last_trade": "Last completed candle close",
    "spot_sample_not_bid_ask": "Indicative gold price",
    "ohlc_not_bid_ask": "Chart price, not a bid and ask",
    "dukascopy_xauusd_bid_ask": "Gold bid and ask",
    "missing_quote": "Quote unavailable",
    "missing_bid_ask": "Quote available, candle unavailable",
    "snapshot_not_candle": "Quote available, candle unavailable",
    "sample_is_5m": "Source is not a completed candle",
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
        "quote_label": QUOTE_LABELS.get(window.get("quote_semantics") or "", None),
    }
    from ops.data_rights import MESSAGE, is_rights_reason
    rights_reason = window.get("reason") or window.get("blocked")
    if is_rights_reason(rights_reason) or window.get("rights_status") in {"rights_unconfirmed", "prohibited", "restricted", "fixture_only"}:
        base.update(
            status="withheld",
            state="DATA_UNAVAILABLE",
            scanner_state="RIGHTS",
            direction="WAIT",
            decision="WAIT",
            decision_label="RIGHTS",
            rule=None,
            price=None,
            entry=None,
            stop=None,
            target=None,
            evidence_grade=None,
            evaluated=False,
            approved=False,
            eligible_for_alert=False,
            rights_status=window.get("rights_status") or "rights_unconfirmed",
            source_reachable="not_checked",
            feed_freshness="not_applicable",
            message=MESSAGE,
        )
        return base
    if symbol == "XAUUSD" and interval in {"1m", "3m"}:
        public = (last or {}).get("provider") == "xaus.com" and last.get("complete")
        native = interval == "1m" and ((last or {}).get("provider") == "twelve-data" or window.get("provider") == "twelve-data")
        released = public
        if native:
            from ops.entitlements import decide_use

            decision = decide_use("twelve_data", "candle_display", symbol="XAUUSD", interval="1m")
            released = released or (decision.get("verified") is True and decision.get("allowed") is True)
        if not released:
            base.update(
                status="unavailable",
                state="DATA_UNAVAILABLE",
                scanner_state="BLOCKED",
                direction="WAIT",
                decision_label="UNAVAILABLE",
                price=None,
                entry=None,
                stop=None,
                target=None,
                evidence_grade=None,
                evaluated=False,
                blocked="xau_minute_unlicensed",
                message="No licensed one-minute XAUUSD spot feed. A five-minute sample is not split into a 1-minute or 3-minute candle.",
            )
            return base
    if symbol == "XAUUSD":
        quote = window.get("quote_semantics") or (last.get("quote_semantics") if last else None) or "missing_quote"
        if quote != "dukascopy_xauusd_bid_ask" or not completed_bid_ask_bar(last):
            shown = quote if quote != "dukascopy_xauusd_bid_ask" else "missing_bid_ask"
            if quote in {"ohlc_not_bid_ask", "spot_sample_not_bid_ask"} and last and last.get("complete") and len(bars) >= (24 if quote == "spot_sample_not_bid_ask" else 50):
                if "live_quote" in window:
                    live_quote = window.get("live_quote")
                elif last.get("source_type") != "fixture":
                    from ops.provider_adapter import independent_reference_quote
                    live_quote = independent_reference_quote(now_ms)
                else:
                    live_quote = None
                shared = _shared_reading(symbol, interval, bars, now_ms, price, live_quote)
                if shared is not None:
                    if (last or {}).get("provider") == "twelve-data" or window.get("provider") == "twelve-data":
                        lead = "Native XAU/USD OHLC from Twelve Data. Not a bid or ask and not an execution price. "
                    elif quote == "spot_sample_not_bid_ask":
                        lead = "First-party spot samples, not the Yahoo chart. "
                    else:
                        lead = "Public chart candles, not a bid/ask. "
                    shared["quote"] = quote
                    message = shared.get("message") or ""
                    preface = lead + "The London rule was not calculated. "
                    if not message.startswith(lead):
                        shared["message"] = preface + message
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
                message=f"Gold has no completed candle yet. The feed reported {shown}. A bid/ask bar was not invented, and the London rule was not calculated.",
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


def _shared_reading(symbol, interval, bars, now_ms, price, live_quote=None):
    """The same decision the terminal uses. It does not write an inbox event."""
    try:
        from ops.terminal_signal import decide
        evaluation = decide(symbol, interval, "auto", bars, now_ms, None, live_quote=live_quote)
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
        "diagnostic": evaluation.get("reason") or "",
        "approved": False,
        "eligible_for_alert": False,
        "evaluated": True,
        "evidence_grade": None,
        "evidence_label": "not a probability of profit",
        "price": evaluation.get("reference_price") if evaluation.get("reference_price") is not None else price,
        "direction": evaluation.get("decision") or "WAIT",
        "quote_gap": evaluation.get("quote_gap"),
        "quote_threshold": evaluation.get("quote_threshold"),
        "quote_time_ms": evaluation.get("quote_time_ms"),
        "compared_bar_close_ms": evaluation.get("compared_bar_close_ms") or evaluation.get("bar_close_ms"),
        "bar_close_ms": evaluation.get("bar_close_ms"),
        "source_name": evaluation.get("source_name"),
        "blocked": evaluation.get("blocked"),
        "quote_label": QUOTE_LABELS.get(evaluation.get("quote") or "", None),
    }
    if evaluation.get("blocked") == "xau_minute_unlicensed":
        card.update(
            status="unavailable",
            state="DATA_UNAVAILABLE",
            scanner_state="BLOCKED",
            decision="WAIT",
            decision_label="UNAVAILABLE",
            entry=None,
            stop=None,
            target=None,
            message="Licensed spot minute data is unavailable. No 1-minute or 3-minute plan is calculated.",
        )
        return card
    if evaluation.get("runtime_status") == "quote_divergence":
        gap = evaluation.get("quote_gap")
        shown = f"{float(gap) * 100:.2f}" if isinstance(gap, (int, float)) else "more than 0.08"
        card.update(
            status="unavailable",
            state="DATA_UNAVAILABLE",
            scanner_state="QUOTE_DIVERGENCE",
            decision="WAIT",
            decision_label="QUOTE DIVERGENCE",
            entry=None,
            stop=None,
            target=None,
            reward_risk=None,
            eligible_for_alert=False,
            message=f"The spot sample and the separate quote differ by {shown} percent. The limit is 0.08 percent, so entry, stop and target are withheld.",
        )
        return card
    if evaluation.get("blocked"):
        card.update(status="unavailable", state="DATA_UNAVAILABLE", scanner_state="BLOCKED", entry=None, stop=None, target=None)
        return card
    if evaluation.get("decision") in {"BUY", "SELL"} and evaluation.get("entry") is not None and evaluation.get("runtime_status") == "experimental":
        card.update(
            status="scanning",
            state="PAPER_CANDIDATE",
            scanner_state="EXPERIMENTAL",
            direction=evaluation.get("decision") or "WAIT",
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
