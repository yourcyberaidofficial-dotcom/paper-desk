"""Per-instrument observation cycle.

A missing gold grant does not suppress Bitcoin or Ether. A missing
Bitcoin grant does not suppress gold. No candle is invented. A 3-minute
series is emitted only as a derived series when native 1-minute coverage
is complete and that derived use is verified. This module does not approve
a strategy and does not open an order.
"""

from __future__ import annotations

import time

from ops.customer_release import candles_released, reading_released, unavailable_card
from ops.data_rights import DESK
from ops.signal_continuity import classify_card
from ops.signal_ledger import note_unavailable, record_observations


def derive_3m(bars, now_ms):
    """Aggregate complete native 1-minute bars. Incomplete coverage returns no bars."""
    step = 60_000
    bucket = 180_000
    rows = [
        bar for bar in (bars or [])
        if isinstance(bar, dict)
        and bar.get("interval") == "1m"
        and bar.get("complete") is True
        and int(bar.get("close_time_ms") or 0) <= int(now_ms)
    ]
    rows.sort(key=lambda bar: int(bar.get("open_time_ms") or 0))
    if not rows:
        return {"ok": False, "reason": "empty", "bars": [], "incomplete": 0}
    by_open = {}
    for bar in rows:
        stamp = int(bar["open_time_ms"])
        if stamp in by_open:
            return {"ok": False, "reason": "duplicate", "bars": [], "incomplete": 0}
        by_open[stamp] = bar
    start = int(rows[0]["open_time_ms"])
    if start % bucket != 0:
        return {"ok": False, "reason": "incomplete_1m_coverage", "bars": [], "incomplete": 1}
    end = int(rows[-1]["open_time_ms"])
    out = []
    incomplete = 0
    stamp = start
    while stamp <= end:
        trio = [by_open.get(stamp), by_open.get(stamp + step), by_open.get(stamp + 2 * step)]
        if any(item is None for item in trio):
            incomplete += 1
        else:
            out.append({
                "symbol": trio[0].get("symbol"),
                "interval": "3m",
                "open_time_ms": stamp,
                "close_time_ms": int(trio[2]["close_time_ms"]),
                "open": trio[0]["open"],
                "high": max(item["high"] for item in trio),
                "low": min(item["low"] for item in trio),
                "close": trio[2]["close"],
                "complete": True,
                "fresh": True,
                "native": False,
                "derived_from": "1m",
                "provider": trio[0].get("provider"),
                "source_id": trio[0].get("source_id"),
                "quote_semantics": "ohlc_not_bid_ask",
            })
        stamp += bucket
    if incomplete or not out:
        return {"ok": False, "reason": "incomplete_1m_coverage", "bars": [], "incomplete": incomplete}
    return {"ok": True, "reason": "derived_from_native_1m", "bars": out, "incomplete": 0}


def _released(symbol, interval):
    from ops.entitlements import decide_use

    if symbol in {"BTCUSDT", "ETHUSDT"} and decide_use(
        "kraken_public_ohlc", "candle_display", symbol=symbol, interval=interval
    ).get("verified") is True:
        return True
    return candles_released(symbol, interval) or reading_released(symbol, interval)


def _load(symbol, interval, now_ms, transport):
    if symbol == "XAUUSD":
        if interval == "3m" or not _released(symbol, interval):
            return None
        from ops.twelve_data import authorized_bars

        loaded = authorized_bars(symbol, interval, now_ms)
        if isinstance(loaded, tuple):
            return {"bars": loaded[0] or [], "source_id": "twelve_data"}
        return None
    from ops.entitlements import decide_use
    from ops.kraken_public import authorized_bars

    decision = decide_use("kraken_public_ohlc", "candle_display", symbol=symbol, interval=interval)
    if decision.get("verified") is not True:
        return None
    if interval == "3m":
        if decision.get("reason") != "derived_from_native_1m":
            return None
        native = authorized_bars(symbol, "1m", now_ms, transport=transport)
        derived = derive_3m((native or {}).get("bars") or [], now_ms)
        if not derived.get("ok"):
            return {"bars": [], "source_id": "kraken_public_ohlc", "reason": derived.get("reason")}
        return {"bars": derived["bars"], "source_id": "kraken_public_ohlc", "derived": True}
    loaded = authorized_bars(symbol, interval, now_ms, transport=transport)
    return {"bars": (loaded or {}).get("bars") or [], "source_id": "kraken_public_ohlc", "reason": (loaded or {}).get("reason")}


def _observe(symbol, interval, bars, source_id, now_ms):
    from ops.terminal_signal import decide

    result = decide(symbol, interval, "auto", bars, now_ms, None)
    result["source_id"] = source_id
    result["approved"] = False
    result["autopilot_eligible"] = False
    result["manual_paper"] = False
    result["validation_status"] = result.get("validation_status") or "FAIL"
    result["price"] = result.get("price") if result.get("price") is not None else result.get("reference_price")
    result["opportunity_id"] = result.get("opportunity_id") or f"obs:{symbol}:{interval}:{result.get('bar_close_ms') or bars[-1].get('close_time_ms')}"
    if result.get("blocked") in {"stale_or_incomplete", "xau_minute_unlicensed", "commercial_use_unverified"}:
        result["customer_status"] = "reading_unavailable"
        result["quality"] = "unavailable"
    else:
        result["quality"] = "ok"
        result["reading_class"] = result.get("reading_class") or "observational"
    return result


def cycle(now_ms=None, transport=None):
    """One pass across the desk. Each pair keeps its own result."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    markets = []
    for symbol, interval in DESK:
        if not _released(symbol, interval):
            note_unavailable(symbol, interval, "reading_unavailable", now_ms, component="signal_engine")
            markets.append(classify_card(unavailable_card(symbol, interval)))
            continue
        try:
            loaded = _load(symbol, interval, now_ms, transport)
        except Exception:
            loaded = None
        bars = (loaded or {}).get("bars") or []
        if not bars:
            note_unavailable(symbol, interval, (loaded or {}).get("reason") or "source_failure", now_ms, component="signal_engine")
            markets.append(classify_card(unavailable_card(symbol, interval)))
            continue
        try:
            card = _observe(symbol, interval, bars, loaded.get("source_id"), now_ms)
        except Exception:
            note_unavailable(symbol, interval, "evaluation_failed", now_ms, component="signal_engine")
            markets.append(classify_card(unavailable_card(symbol, interval)))
            continue
        stored = record_observations([card], now_ms=now_ms, component="signal_engine")
        classified = classify_card(card)
        if stored.get("rows"):
            classified = {**classified, "persisted": True}
        markets.append(classified)
    return {
        "markets": markets,
        "broker": False,
        "truncated": False,
        "note": "Each instrument is gated on its own. A failed study does not remove an observation.",
    }
