"""Gold reference quotes.

parse_swissquote remains a pure parser for fixtures. swissquote_xau does not
open a socket. XAUS spot, chart, and samples are not a bid/ask.
"""

from datetime import datetime, timezone

# Documented only. No production path passes this URL to urllib.
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


def reference_quote_unavailable(now_ms=None):
    """No independent authorised quote is configured. Bid and ask stay empty."""
    return {
        "ok": False,
        "reason": "reference_quote_unavailable",
        "bid": None,
        "ask": None,
        "spread": None,
        "timestamp_ms": None,
        "not_a_candle": True,
        "rights_status": "restricted",
        "source_reachable": "not_checked",
        "quote_semantics": "independent_reference_unavailable",
        "provider": None,
        "credential": None,
        "requested_ms": now_ms,
        "quote_threshold": 0.0008,
    }


def swissquote_xau(now_ms=None):
    """Closed. Kept so an old caller cannot reach the public BBO URL."""
    return reference_quote_unavailable(now_ms)


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


def completed_bid_ask_bar(bar):
    """A gold rule may run only on a completed Dukascopy hour with both sides."""
    return bool(
        bar
        and bar.get("complete")
        and bar.get("quote_semantics") == "dukascopy_xauusd_bid_ask"
        and bar.get("ask_open") is not None
    )
