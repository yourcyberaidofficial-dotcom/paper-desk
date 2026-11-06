"""Kraken public OHLC adapter.

XBT/USDT is Bitcoin quoted in Tether, not Bitcoin quoted in US dollars.
ETH/USDT is Ether quoted in Tether. Neither pair is XAUUSD. Native
intervals are 1, 5, 15, 30, 60, 240, 1440, 10080 and 21600 minutes.
There is no native 3-minute candle. The last OHLC row is the forming
candle and is dropped. A public route is not a redistribution grant.
Nothing here opens a socket unless candle display for that exact pair
and interval is verified.
"""

from __future__ import annotations

import json
import urllib.request

from ops.bars import make_bar, ohlc_ok, validate_series

BASE = "https://api.kraken.com"
SOURCE_ID = "kraken_public_ohlc"
PROVIDER = "kraken"

# Confirmed from GET /0/public/AssetPairs on 2026-11-06. No OHLC was stored.
PAIRS = {
    "BTCUSDT": {"rest": "XBTUSDT", "wsname": "XBT/USDT", "base": "XXBT", "quote": "USDT"},
    "ETHUSDT": {"rest": "ETHUSDT", "wsname": "ETH/USDT", "base": "XETH", "quote": "USDT"},
}

INTERVALS = {"1m": 1, "15m": 15, "1h": 60}


def pair_spec(symbol):
    return PAIRS.get(symbol)


def vendor_interval(interval):
    return INTERVALS.get(interval)


def _request(url, timeout, transport):
    if transport is not None:
        return transport(url, timeout)
    request = urllib.request.Request(url, headers={"User-Agent": "paper-desk"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode() or "{}")


def parse_ohlc(payload, symbol, interval, now_ms):
    """Completed native candles only. Gaps are counted. The forming row is dropped."""
    spec = pair_spec(symbol)
    if not spec or vendor_interval(interval) is None:
        return {"ok": False, "reason": "not_listed", "bars": [], "gaps": 0}
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get(spec["rest"]) if isinstance(result, dict) else None
    if not isinstance(rows, list):
        return {"ok": False, "reason": "malformed", "bars": [], "gaps": 0}
    step = vendor_interval(interval) * 60 * 1000
    bars = []
    # Kraken documents the last row as the current, not-yet-committed candle.
    completed = rows[:-1] if rows else []
    for row in completed:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            open_ms = int(float(row[0]) * 1000)
            open_, high, low, close = (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
        except (TypeError, ValueError):
            continue
        close_ms = open_ms + step
        if close_ms > int(now_ms):
            continue
        bar = make_bar(
            symbol=symbol,
            interval=interval,
            open_time_ms=open_ms,
            close_time_ms=close_ms,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=row[6] if len(row) > 6 else None,
            provider=PROVIDER,
            source_type="public_rest_ohlc",
            quote_semantics="ohlc_not_bid_ask",
            retrieved_at_ms=int(now_ms),
            complete=True,
            fresh=True,
        )
        bar["source_id"] = SOURCE_ID
        bar["venue_pair"] = spec["wsname"]
        bar["native"] = True
        if ohlc_ok(bar):
            bars.append(bar)
    report = validate_series(bars, interval)
    return {
        "ok": report.get("ok") is True and bool(bars),
        "reason": None if report.get("ok") else "incomplete_or_invalid",
        "bars": bars,
        "gaps": report.get("gaps") or 0,
        "source_id": SOURCE_ID,
        "provider": PROVIDER,
        "venue_pair": spec["wsname"],
        "native": True,
        "bid_ask": False,
    }


def authorized_bars(symbol, interval, now_ms, transport=None, timeout=8):
    """Fetch one native series, or refuse before the socket.

    One retry, then stop. A failure is not filled from another venue.
    """
    from ops.entitlements import decide_use

    decision = decide_use(SOURCE_ID, "candle_display", symbol=symbol, interval=interval)
    if decision.get("verified") is not True or decision.get("reason") == "derived_from_native_1m":
        return {
            "ok": False,
            "reason": decision.get("reason") or "not_verified",
            "bars": [],
            "called": False,
            "source_id": SOURCE_ID,
        }
    minutes = vendor_interval(interval)
    spec = pair_spec(symbol)
    if minutes is None or spec is None:
        return {"ok": False, "reason": "not_listed", "bars": [], "called": False, "source_id": SOURCE_ID}
    url = f"{BASE}/0/public/OHLC?pair={spec['rest']}&interval={minutes}"
    last_reason = "source_failure"
    for attempt in (1, 2):
        try:
            status, payload = _request(url, timeout, transport)
        except Exception as exc:
            name = type(exc).__name__.lower()
            last_reason = "timeout" if "timeout" in name or "timeout" in str(exc).lower() else "source_failure"
            if attempt == 1:
                continue
            return {"ok": False, "reason": last_reason, "error": type(exc).__name__, "bars": [], "called": True, "source_id": SOURCE_ID, "attempts": attempt}
        if not isinstance(payload, dict):
            last_reason = "malformed"
            if attempt == 1:
                continue
            return {"ok": False, "reason": "malformed", "bars": [], "called": True, "source_id": SOURCE_ID, "attempts": attempt}
        if status != 200 or payload.get("error") or status >= 500:
            last_reason = "timeout" if status == 429 else "source_failure"
            if attempt == 1 and (status >= 500 or status == 429):
                continue
            return {"ok": False, "reason": last_reason, "bars": [], "called": True, "source_id": SOURCE_ID, "attempts": attempt}
        parsed = parse_ohlc(payload, symbol, interval, now_ms)
        if parsed.get("reason") == "malformed" and attempt == 1:
            continue
        parsed["called"] = True
        parsed["attempts"] = attempt
        return parsed
    return {"ok": False, "reason": last_reason, "bars": [], "called": True, "source_id": SOURCE_ID, "attempts": 2}
