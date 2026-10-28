"""Live XAUUSD quotes. A bid/ask snapshot is not turned into a candle."""

import json
import urllib.request
from datetime import datetime, timezone

URL = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD"


def parse_swissquote(payload, now_ms):
    if not isinstance(payload, list) or not payload:
        return {"ok": False, "reason": "empty", "quote_semantics": "bid_ask_snapshot"}
    row = payload[0]
    prices = (row.get("spreadProfilePrices") or [None])[0] or {}
    bid = prices.get("bid")
    ask = prices.get("ask")
    stamp = row.get("ts")
    if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)) or ask < bid:
        return {"ok": False, "reason": "invalid_bbo", "quote_semantics": "bid_ask_snapshot"}
    if not isinstance(stamp, int):
        return {"ok": False, "reason": "missing_timestamp", "quote_semantics": "bid_ask_snapshot"}
    age = int(now_ms) - stamp
    return {
        "ok": True,
        "bid": bid,
        "ask": ask,
        "spread": ask - bid,
        "timestamp_ms": stamp,
        "age_ms": age,
        "fresh": -5_000 <= age <= 15 * 60 * 1000,
        "spread_profile": prices.get("spreadProfile"),
        "platform": (row.get("topo") or {}).get("platform"),
        "provider": "swissquote-public-bbo",
        "quote_semantics": "bid_ask_snapshot",
        "not_a_candle": True,
        "credential": None,
    }


def swissquote_xau(now_ms=None):
    now_ms = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    request = urllib.request.Request(URL, headers={"User-Agent": "aureon-paper-desk"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "quote_semantics": "bid_ask_snapshot", "credential": None}
    return parse_swissquote(payload, now_ms)


def snapshot_reason(quote):
    if not quote or not quote.get("ok"):
        return "No live gold bid/ask quote was returned. No candle was invented."
    moment = datetime.fromtimestamp(quote["timestamp_ms"] / 1000, timezone.utc).isoformat()
    session = quote.get("session") or {}
    session_text = ""
    if session:
        session_text = f" Dukascopy today bid {session.get('bid')} and ask {session.get('ask')}."
    return (
        f"Swissquote {quote.get('platform')} {quote.get('spread_profile')} bid {quote['bid']} ask {quote['ask']} "
        f"at {moment}. Spread {quote['spread']}. This is one quote, not a completed hour, so the London rule was not calculated."
        + session_text
    )
