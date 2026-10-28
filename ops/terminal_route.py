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


def load_crypto_bars(symbol, interval, now_ms):
    try:
        if symbol in {"BTCUSDT", "ETHUSDT"}:
            from ops.feeds import binance_bars
            span = 400 if interval == "1d" else 120
            start = now_ms - span * 24 * 60 * 60 * 1000
            loaded = binance_bars(symbol, interval, start, now_ms, now_ms)
            if not loaded.get("ok"):
                return None, loaded.get("reason") or "The market feed did not respond."
            return loaded.get("bars") or []
    except Exception:
        return None, "The market feed could not be read."
    return None, "This market is not supported."


def handle_signal(user_id, body, now_ms=None, bars_loader=None, quote_loader=None, session_loader=None):
    from ops.terminal_signal import attach_request, auto_strategy, decide, open_idea, stamp
    from ops.users import get

    body = body or {}
    symbol = body.get("symbol") or "BTCUSDT"
    interval = body.get("interval") or "4h"
    strategy = body.get("strategy") or "auto"
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    live_quote = None
    if symbol == "XAUUSD":
        if quote_loader is None:
            from ops.gold_live import swissquote_xau
            quote_loader = swissquote_xau
        live_quote = quote_loader(now_ms)
        if isinstance(live_quote, dict):
            live_quote = dict(live_quote)
            live_quote["session"] = (session_loader or gold_session)(now_ms)
        bars = []
    else:
        bars = (bars_loader or load_crypto_bars)(symbol, interval, now_ms)
    if isinstance(bars, tuple):
        return 200, attach_request(body, {
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
    return 200, stamp(user_id, attach_request(body, result))
