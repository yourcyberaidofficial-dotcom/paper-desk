"""Customer responses for unverified market data.

A verified capability is the only reason a number from a provider is
returned. This module does not read environment flags and does not fetch.
"""

from __future__ import annotations

STATUS = "A verified live reading is not available."

PRICE_KEYS = (
    "entry",
    "stop",
    "target",
    "price",
    "close",
    "open",
    "high",
    "low",
    "bid",
    "ask",
    "reference_price",
    "watch_entry",
    "watch_stop",
    "watch_target",
    "reward_risk",
    "quote_gap",
    "volume",
)


def verified(source_id, capability, symbol=None, interval=None):
    from ops.entitlements import decide_use

    row = decide_use(source_id, capability, symbol=symbol, interval=interval)
    return row.get("verified") is True and row.get("allowed") is True and row.get("status") == "verified"


def source_for(symbol, semantics=None):
    if symbol == "XAUUSD":
        if semantics == "spot_sample_not_bid_ask":
            return "xaus_spot_samples"
        return "xaus_public_chart"
    return "binance_spot_rest_klines"


def _twelve_covers(capability, symbol, interval):
    """A recorded gold grant releases only the named capability. 3m is never native."""
    if symbol != "XAUUSD" or interval == "3m":
        return False
    return verified("twelve_data", capability, symbol=symbol, interval=interval)


def candles_released(symbol, interval, semantics=None):
    if _twelve_covers("candle_display", symbol, interval):
        return True
    source = source_for(symbol, semantics)
    capability = "sampled_reference_display" if source == "xaus_spot_samples" else "candle_display"
    return verified(source, capability, symbol=symbol, interval=interval)


def reading_released(symbol, interval, semantics=None):
    if _twelve_covers("customer_reading", symbol, interval):
        return True
    return verified(source_for(symbol, semantics), "customer_reading", symbol=symbol, interval=interval)


def opportunity_released(symbol, interval, semantics=None):
    if _twelve_covers("opportunity_generation", symbol, interval):
        return True
    return verified(source_for(symbol, semantics), "opportunity_generation", symbol=symbol, interval=interval)


def any_customer_display():
    from ops.data_rights import DESK

    return any(candles_released(symbol, interval) or reading_released(symbol, interval) for symbol, interval in DESK)


def unavailable_card(symbol, interval):
    minute = symbol == "XAUUSD" and interval in {"1m", "3m"}
    return {
        "symbol": symbol,
        "interval": interval,
        "price": None,
        "entry": None,
        "stop": None,
        "target": None,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "bid": None,
        "ask": None,
        "reference_price": None,
        "decision": "WAIT",
        "decision_label": "Unavailable" if minute else "WAIT",
        "direction": "neutral",
        "direction_label": "neutral",
        "reading_class": "unavailable",
        "setup_state": "unavailable",
        "scanner_state": "WAIT",
        "status": "unavailable",
        "state": "WAIT",
        "customer_status": "reading_unavailable",
        "blocked": "xau_minute_unlicensed" if minute else None,
        "message": "This timeframe is not available." if minute else STATUS,
        "explanation": "This timeframe is not available." if minute else STATUS,
        "manual_paper": False,
        "approved": False,
        "autopilot_eligible": False,
        "evaluated": False,
        "probability": None,
        "quality": "unavailable",
        "fresh": False,
        "order": False,
        "broker": False,
    }


def empty_desk():
    from ops.data_rights import DESK

    return {
        "markets": [unavailable_card(symbol, interval) for symbol, interval in DESK],
        "notice": "No eligible live reading is available.",
        "broker": False,
        "approved_strategy": None,
        "snapshots": [],
        "sources": [],
        "customer_status": "reading_unavailable",
    }


def customer_markets():
    rows = []
    for symbol, row_id, frame in (("BTCUSDT", "BTC", "15m"), ("ETHUSDT", "ETH", "15m"), ("XAUUSD", "GOLD", "1h")):
        rows.append({
            "id": row_id,
            "symbol": symbol,
            "status": "configured",
            "data": {
                "price": None,
                "close": None,
                "fresh": False,
                "quality": "unavailable",
                "timeframe": frame,
                "customer_status": "reading_unavailable",
                "note": STATUS,
            },
            "reading": {
                "customer_status": "reading_unavailable",
                "reading_class": "unavailable",
                "direction_label": "neutral",
                "decision": "WAIT",
                "manual_paper": False,
                "approved": False,
                "autopilot_eligible": False,
                "probability": None,
                "explanation": STATUS,
                "entry": None,
                "stop": None,
                "target": None,
            },
        })
    return {"markets": rows, "broker": False, "production": "WAIT_DEFAULT", "customer_status": "reading_unavailable"}


def unavailable_candles(symbol, interval):
    minute = symbol == "XAUUSD" and interval in {"1m", "3m"}
    return {
        "symbol": symbol,
        "interval": interval,
        "candles": [],
        "count": 0,
        "customer_status": "reading_unavailable",
        "blocked": "xau_minute_unlicensed" if minute else None,
        "not_a_quote": True,
        "execution_grade": False,
        "kind": "unavailable",
        "note": "This timeframe is not available." if minute else STATUS,
        "fresh": False,
    }


def unavailable_quote(symbol):
    return {
        "symbol": symbol,
        "price": None,
        "close": None,
        "fresh": False,
        "customer_status": "reading_unavailable",
        "note": STATUS,
        "broker": False,
    }


def redact_feed_view(row):
    """Copy for a customer. The stored row is not rewritten."""
    from ops.entitlements import is_feed_derived

    row = dict(row or {})
    if not is_feed_derived(row):
        return row
    symbol = row.get("symbol")
    interval = row.get("interval")
    semantics = row.get("candle_semantics") or row.get("quote")
    sample = "spot_sample_not_bid_ask" if semantics == "spot_sample_not_bid_ask" else None
    if reading_released(symbol, interval, sample) or candles_released(symbol, interval, sample):
        return row
    for key in PRICE_KEYS:
        if key in row:
            row[key] = None
    if isinstance(row.get("events"), list):
        cleaned = []
        for event in row["events"]:
            if not isinstance(event, dict):
                cleaned.append(event)
                continue
            event = dict(event)
            for key in PRICE_KEYS:
                if key in event:
                    event[key] = None
            cleaned.append(event)
        row["events"] = cleaned
    if row.get("decision") in {"BUY", "SELL"}:
        row["decision"] = "WAIT"
    row["message"] = STATUS
    row["explanation"] = STATUS
    row["reason"] = STATUS
    row["customer_status"] = "reading_unavailable"
    row["manual_paper"] = False
    return row


def present_card(card):
    """One desk row. A verified capability is copied. Everything else is withheld."""
    card = dict(card or {})
    symbol = card.get("symbol")
    interval = str(card.get("interval") or "")
    semantics = card.get("candle_semantics") or card.get("quote")
    sampled = semantics == "spot_sample_not_bid_ask"
    if symbol == "XAUUSD" and interval in {"1m", "3m"} and not candles_released(symbol, interval):
        return unavailable_card(symbol, interval)
    sample = "spot_sample_not_bid_ask" if sampled else None
    price_ok = candles_released(symbol, interval, sample)
    quote_ok = verified(source_for(symbol, sample), "quote_display", symbol=symbol, interval=interval)
    reading_ok = reading_released(symbol, interval, sample)
    opportunity_ok = opportunity_released(symbol, interval, sample)
    if not price_ok and not quote_ok:
        for key in ("price", "open", "high", "low", "close", "bid", "ask", "volume", "reference_price", "quote_gap"):
            card[key] = None
        card["customer_status"] = "reading_unavailable"
    if not reading_ok:
        if card.get("decision") in {"BUY", "SELL"}:
            card["decision"] = "WAIT"
            card["decision_label"] = "WAIT"
        card["direction"] = "neutral"
        card["direction_label"] = "neutral"
        card["manual_paper"] = False
        if price_ok:
            card["message"] = "Completed candle only. A derived reading is not released."
            card["explanation"] = card["message"]
            card["reason"] = card["message"]
            card["customer_status"] = "candle_only"
            card["reading_class"] = "observational"
            card["status"] = "candle"
        else:
            card["message"] = STATUS
            card["explanation"] = STATUS
            card["reason"] = STATUS
            card["customer_status"] = "reading_unavailable"
            card["source_id"] = None
            card["provider"] = None
            card["snapshot_id"] = None
            card["reading_class"] = "unavailable"
            card["status"] = "unavailable"
        if card.get("scanner_state") in {None, "", "RIGHTS", "withheld"}:
            card["scanner_state"] = "WAIT"
    if not opportunity_ok or not reading_ok:
        for key in ("entry", "stop", "target", "watch_entry", "watch_stop", "watch_target", "reward_risk"):
            card[key] = None
        card["manual_paper"] = False
    return card


def release_scan(body):
    """Customer copy of a scan. Raw snapshots are not part of the response."""
    body = dict(body or {})
    body["markets"] = [present_card(card) for card in (body.get("markets") or [])]
    body["snapshots"] = []
    sources = []
    for row in body.get("sources") or []:
        if not isinstance(row, dict):
            continue
        sources.append({
            "instrument": row.get("instrument"),
            "timeframe": row.get("timeframe"),
            "quality": row.get("quality"),
            "display": row.get("display"),
            "retention": row.get("retention"),
            "research": row.get("research"),
        })
    body["sources"] = sources
    return body


def customer_terminal(symbol, interval):
    minute = symbol == "XAUUSD" and interval in {"1m", "3m"}
    note = "This timeframe is not available." if minute else STATUS
    return {
        "decision": "WAIT",
        "decision_label": "UNAVAILABLE" if minute else "WAIT",
        "symbol": symbol,
        "interval": interval,
        "customer_status": "reading_unavailable",
        "blocked": "xau_minute_unlicensed" if minute else None,
        "reason": note,
        "message": note,
        "approved": False,
        "validated": False,
        "fresh": False,
        "entry": None,
        "stop": None,
        "target": None,
        "reference_price": None,
        "price": None,
        "reward_risk": None,
        "watch_entry": None,
        "watch_stop": None,
        "watch_target": None,
        "delivered": False,
        "filled": False,
        "order": False,
        "broker": False,
        "manual_paper": False,
        "autopilot_eligible": False,
        "production": "WAIT_DEFAULT",
    }


def derived_withheld(symbol, interval=None):
    return {
        "symbol": symbol,
        "interval": interval,
        "customer_status": "reading_unavailable",
        "production": "WAIT_DEFAULT",
        "approved": False,
        "validated": False,
        "broker": False,
        "fresh": False,
        "states": [],
        "rows": [],
        "engine": [],
        "council": None,
        "state": "DATA_UNAVAILABLE",
        "reason": STATUS,
        "message": STATUS,
        "result": "WAIT",
        "direction": "WAIT",
        "note": "No eligible live reading is available. Whether a research strategy is approved is a separate record.",
        "entry": None,
        "stop": None,
        "target": None,
        "price": None,
        "paper_candidates": [],
    }


def diagnostic_monitor(monitor):
    """A customer status may say a check ran. It does not receive prices or an unreleased direction."""
    if not isinstance(monitor, dict):
        return None
    rows = []
    for row in monitor.get("evaluations") or []:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        interval = row.get("interval")
        released = candles_released(symbol, interval) or reading_released(symbol, interval)
        rows.append({
            "symbol": symbol,
            "interval": interval,
            "decision": row.get("decision") if released else "not_shown",
            "blocked": row.get("blocked"),
        })
    return {"evaluations": rows, "error": monitor.get("error")}


def redact_public_numbers(value):
    """Copy. User-authored rows keep the numbers the account typed."""
    if isinstance(value, list):
        return [redact_public_numbers(item) for item in value]
    if not isinstance(value, dict):
        return value
    from ops.entitlements import is_feed_derived

    row = {key: redact_public_numbers(item) for key, item in value.items()}
    if row.get("provenance") == "user_authored" and row.get("source_id") == "user_authored":
        return row
    if is_feed_derived(row) or any(key in row for key in ("open", "high", "low", "close", "bid", "ask")):
        for key in PRICE_KEYS:
            if key in row and isinstance(row[key], (int, float)):
                row[key] = None
        if is_feed_derived(row):
            row["customer_status"] = "reading_unavailable"
            row["message"] = STATUS
    return row
