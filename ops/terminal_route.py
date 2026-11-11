"""Generate Signal HTTP handler. It does not send messages or place orders."""

import time
from datetime import datetime, timezone
from pathlib import Path


def gold_session(now_ms, fetch=None):
    if fetch is None:
        from ops.xau_pull import fetch_day
        fetch = fetch_day
    day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).date()
    cache = Path("/tmp/xau-live")
    bid = fetch(day, "BID", cache, timeout=8, attempts=1)
    ask = fetch(day, "ASK", cache, timeout=8, attempts=1)
    return {
        "day": day.isoformat(),
        "bid": "ok" if bid.get("ok") else bid.get("reason"),
        "ask": "ok" if ask.get("ok") else ask.get("reason"),
        "note": "A missing side means no bid/ask hour was built.",
    }


_BAR_CACHE = {}


def load_crypto_bars(symbol, interval, now_ms):
    from ops.data_rights import network_block

    blocked = network_block("binance_spot_rest_klines", "display")
    if blocked:
        return None, "commercial_use_unverified"
    try:
        if symbol in {"BTCUSDT", "ETHUSDT"}:
            key = (symbol, interval)
            cached = _BAR_CACHE.get(key)
            if cached and now_ms - cached[0] < 30_000:
                return cached[1]
            from ops.bars import interval_ms
            from ops.feeds import binance_bars
            count = 140 if interval == "1d" else 90
            start = now_ms - (count + 2) * interval_ms(interval)
            loaded = binance_bars(symbol, interval, start, now_ms, now_ms, timeout=8, attempts=1)
            if not loaded.get("ok"):
                return None, loaded.get("reason") or "The market feed did not respond."
            bars = loaded.get("bars") or []
            _BAR_CACHE[key] = (now_ms, bars)
            return bars
    except Exception:
        return None, "The market feed could not be read."
    return None, "This market is not supported."


def load_gold_ohlc(interval, now_ms):
    from ops.data_rights import network_block

    if interval in {"1m", "3m"}:
        from ops.twelve_data import authorized_bars

        authorised = authorized_bars("XAUUSD", interval, now_ms)
        if authorised is not None and authorised[0]:
            return authorised[0]
        blocked = network_block("xaus_public_chart", "display")
        if blocked:
            return None, "commercial_use_unverified"
        from ops.feeds import aggregate_ohlc, xaus_chart

        if interval == "1m":
            try:
                loaded = xaus_chart("1m", now_ms=now_ms, timeout=8, attempts=1)
            except Exception as exc:
                return None, type(exc).__name__
            bars = loaded.get("bars") or [] if isinstance(loaded, dict) else []
            return bars if bars else (None, loaded.get("reason") if isinstance(loaded, dict) else "missing_bars")
        try:
            base = xaus_chart("1m", now_ms=now_ms, timeout=8, attempts=1)
        except Exception as exc:
            return None, type(exc).__name__
        if not isinstance(base, dict) or not base.get("ok"):
            return None, (base.get("reason") if isinstance(base, dict) else None) or "missing_bars"
        bars = aggregate_ohlc(base.get("bars") or [], "3m", now_ms)
        return bars if bars else (None, "missing_bars")
    blocked = network_block("xaus_public_chart", "display")
    if blocked:
        return None, "commercial_use_unverified"
    key = ("XAUUSD", interval)
    cached = _BAR_CACHE.get(key)
    if cached and now_ms - cached[0] < 30_000:
        return cached[1]
    from ops.feeds import xaus_chart, xaus_spot_bars
    try:
        loaded = xaus_spot_bars(interval, now_ms=now_ms, timeout=8, attempts=1) if interval in {"15m", "1h"} else {"bars": []}
        bars = loaded.get("bars") or [] if isinstance(loaded, dict) else []
        if interval == "15m" or len(bars) >= 24:
            _BAR_CACHE[key] = (now_ms, bars)
            return bars
        loaded = xaus_chart(interval, now_ms=now_ms, timeout=8, attempts=1)
        bars = loaded.get("bars") or [] if isinstance(loaded, dict) else []
        _BAR_CACHE[key] = (now_ms, bars)
        return bars
    except Exception as exc:
        return None, type(exc).__name__


def _publish(request_body, payload):
    from ops.qualification import evidence_chain
    from ops.terminal_signal import attach_request

    stamped = attach_request(request_body, payload)
    stamped["evidence_chain"] = evidence_chain(stamped)
    stamped["approved_strategy_available"] = False
    return stamped


def handle_signal(user_id, body, now_ms=None, bars_loader=None, quote_loader=None, session_loader=None, ohlc_loader=None):
    from ops.terminal_signal import auto_strategy, decide, open_idea, stamp
    from ops.users import get

    body = body or {}
    symbol = body.get("symbol") or "BTCUSDT"
    interval = body.get("interval") or "4h"
    strategy = body.get("strategy") or "auto"
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    if symbol == "XAUUSD" and interval in {"1m", "3m"}:
        allowed = False
        if interval == "1m":
            from ops.entitlements import decide_use

            decision = decide_use("twelve_data", "customer_reading", symbol="XAUUSD", interval="1m")
            allowed = decision.get("verified") is True and decision.get("allowed") is True
        if not allowed:
            return 200, _publish(body, {
                "decision": "WAIT",
                "symbol": symbol,
                "interval": interval,
                "strategy": "xau-minute-unlicensed",
                "version": "xau-minute-unlicensed",
                "reason": "XAUUSD 1-minute and 3-minute plans stay off until a licensed spot feed is confirmed. A candle was not invented from a five-minute sample, and the 1-hour London rule was not used.",
                "approved": False,
                "fresh": False,
                "reference_price": None,
                "entry": None,
                "stop": None,
                "target": None,
                "blocked": "xau_minute_unlicensed",
                "blockers": ["xau_minute_unlicensed"],
                "decision_label": "UNAVAILABLE",
                "runtime_status": "xau_minute_unlicensed",
                "validation_status": "BLOCKED",
                "delivered": False,
                "filled": False,
                "order": False,
                "size": {"ok": False, "reason": "xau_minute_unlicensed", "order": False, "quantity_orderable": False, "budget_ok": False},
            })
    live_quote = None
    if symbol == "XAUUSD":
        if quote_loader is None:
            from ops.provider_adapter import independent_reference_quote
            quote_loader = independent_reference_quote
        live_quote = quote_loader(now_ms)
        if isinstance(live_quote, dict):
            live_quote = dict(live_quote)
            if session_loader is not None:
                live_quote["session"] = session_loader(now_ms)
        try:
            bars = (ohlc_loader or load_gold_ohlc)(interval, now_ms)
        except Exception as exc:
            bars = (None, type(exc).__name__)
        detail = None
        if isinstance(bars, tuple):
            detail = bars[1]
            bars = []
        if interval in {"1m", "3m"} and not bars:
            if interval == "3m" or detail == "xau_minute_unlicensed":
                return 200, _publish(body, {
                    "decision": "WAIT",
                    "decision_label": "UNAVAILABLE",
                    "symbol": symbol,
                    "interval": interval,
                    "strategy": "xau-minute-unlicensed",
                    "version": "xau-minute-unlicensed",
                    "reason": "XAUUSD 1-minute and 3-minute plans stay off until a licensed spot feed is confirmed. A candle was not invented from a five-minute sample, and the 1-hour London rule was not used.",
                    "approved": False,
                    "fresh": False,
                    "reference_price": None,
                    "entry": None,
                    "stop": None,
                    "target": None,
                    "blocked": "xau_minute_unlicensed",
                    "blockers": ["xau_minute_unlicensed"],
                    "runtime_status": "xau_minute_unlicensed",
                    "validation_status": "BLOCKED",
                    "delivered": False,
                    "filled": False,
                    "order": False,
                    "size": {"ok": False, "reason": "xau_minute_unlicensed", "order": False, "quantity_orderable": False, "budget_ok": False},
                })
            return 200, _publish(body, {
                "decision": "WAIT",
                "decision_label": "WAIT",
                "symbol": symbol,
                "interval": interval,
                "strategy": strategy,
                "reason": "The authorised gold source returned no completed bar. Another source was not substituted.",
                "approved": False,
                "fresh": False,
                "reference_price": None,
                "entry": None,
                "stop": None,
                "target": None,
                "blocked": "missing_bars",
                "delivered": False,
                "filled": False,
                "order": False,
                "provider": "twelve-data",
                "source_id": "twelve_data",
            })
        if detail in {"commercial_use_unverified", "rights_unconfirmed", "prohibited", "restricted"} or (isinstance(live_quote, dict) and live_quote.get("reason") == "commercial_use_unverified" and not bars):
            from ops.data_rights import MESSAGE
            return 200, _publish(body, {
                "decision": "WAIT",
                "decision_label": "RIGHTS",
                "symbol": symbol,
                "interval": interval,
                "strategy": strategy,
                "reason": MESSAGE,
                "message": MESSAGE,
                "approved": False,
                "fresh": False,
                "evaluated": False,
                "reference_price": None,
                "entry": None,
                "stop": None,
                "target": None,
                "blocked": "commercial_use_unverified",
                "rights_status": "rights_unconfirmed",
                "source_reachable": "not_checked",
                "feed_freshness": "not_applicable",
                "delivered": False,
                "filled": False,
                "order": False,
            })
    else:
        bars = (bars_loader or load_crypto_bars)(symbol, interval, now_ms)
    if isinstance(bars, tuple):
        from ops.data_rights import MESSAGE, is_rights_reason
        reason = bars[1]
        rights = is_rights_reason(reason)
        return 200, _publish(body, {
            "decision": "WAIT",
            "decision_label": "RIGHTS" if rights else "WAIT",
            "symbol": symbol,
            "interval": interval,
            "strategy": strategy,
            "reason": MESSAGE if rights else reason,
            "message": MESSAGE if rights else reason,
            "approved": False,
            "fresh": False,
            "evaluated": False,
            "reference_price": None,
            "entry": None,
            "stop": None,
            "target": None,
            "blocked": "commercial_use_unverified" if rights else "feed_error",
            "rights_status": "rights_unconfirmed" if rights else None,
            "source_reachable": "not_checked" if rights else None,
            "feed_freshness": "not_applicable" if rights else None,
            "delivered": False,
            "filled": False,
            "order": False,
        })
    chosen = auto_strategy(symbol) if strategy in {None, "", "auto"} else strategy
    user = get(user_id) or {}
    result = decide(
        symbol, interval, strategy, bars, now_ms, user,
        open_idea(user_id, symbol, chosen), live_quote=live_quote,
    )
    stamped = stamp(user_id, _publish(body, result))
    from ops.inbox import deliver_evaluation
    stamped["inbox_delivery"] = deliver_evaluation(user_id, user, stamped)
    return 200, stamped
