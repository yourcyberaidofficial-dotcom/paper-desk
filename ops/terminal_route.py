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
    if interval in {"1m", "3m"}:
        return (None, "xau_minute_unlicensed")
    key = ("XAUUSD", interval)
    cached = _BAR_CACHE.get(key)
    if cached and now_ms - cached[0] < 30_000:
        return cached[1]
    from ops.feeds import xaus_chart, xaus_spot_bars
    loaded = xaus_spot_bars(interval, now_ms=now_ms, timeout=8, attempts=1) if interval in {"15m", "1h"} else {"bars": []}
    bars = loaded.get("bars") or [] if isinstance(loaded, dict) else []
    if interval == "15m" or len(bars) >= 24:
        _BAR_CACHE[key] = (now_ms, bars)
        return bars
    loaded = xaus_chart(interval, now_ms=now_ms, timeout=8, attempts=1)
    bars = loaded.get("bars") or [] if isinstance(loaded, dict) else []
    _BAR_CACHE[key] = (now_ms, bars)
    return bars


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
            from ops.gold_live import swissquote_xau
            quote_loader = swissquote_xau
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
    else:
        bars = (bars_loader or load_crypto_bars)(symbol, interval, now_ms)
    if isinstance(bars, tuple):
        return 200, _publish(body, {
            "decision": "WAIT",
            "symbol": symbol,
            "interval": interval,
            "strategy": strategy,
            "reason": bars[1],
            "approved": False,
            "fresh": False,
            "reference_price": None,
            "blocked": "feed_error",
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
