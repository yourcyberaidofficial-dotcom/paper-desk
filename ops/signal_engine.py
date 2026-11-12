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


def canonical_opportunity_id(symbol, interval, result, bars=None):
    """Paper and inbox use opp:instrument:timeframe:family:direction:origin.

    A stored id is kept. Missing fields are not filled with an obs: fallback.
    """
    from ops.inbox import opportunity_identity

    result = result or {}
    existing = result.get("opportunity_id")
    if isinstance(existing, str) and existing.startswith("opp:"):
        return existing
    if isinstance(existing, str) and existing.strip() and not existing.startswith("obs:"):
        return existing
    family = result.get("family") or result.get("rule") or result.get("strategy")
    direction = result.get("direction") or result.get("decision")
    anchor = result.get("bar_close_ms")
    if anchor in (None, "") and bars:
        anchor = bars[-1].get("close_time_ms")
    return opportunity_identity(symbol, interval, family, direction, anchor)


def _released(symbol, interval):
    from ops.entitlements import decide_use

    if symbol in {"BTCUSDT", "ETHUSDT"} and decide_use(
        "kraken_public_ohlc", "candle_display", symbol=symbol, interval=interval
    ).get("verified") is True:
        return True
    return candles_released(symbol, interval) or reading_released(symbol, interval)


def _public_bars(symbol, interval, now_ms):
    """The released public feed. This is not a substitute for a different venue's grant."""
    if symbol == "XAUUSD":
        from ops.terminal_route import load_gold_ohlc

        loaded = load_gold_ohlc(interval, now_ms)
        source = "xaus_public_chart"
    elif symbol in {"BTCUSDT", "ETHUSDT"}:
        from ops.terminal_route import load_crypto_bars

        loaded = load_crypto_bars(symbol, interval, now_ms)
        source = "binance_spot_rest_klines"
    else:
        return None
    if isinstance(loaded, tuple) or not loaded:
        reason = loaded[1] if isinstance(loaded, tuple) else "missing_bars"
        return {"bars": [], "source_id": source, "reason": reason}
    return {"bars": loaded, "source_id": (loaded[-1].get("source_id") or source)}


def _load(symbol, interval, now_ms, transport):
    if symbol == "XAUUSD":
        from ops.twelve_data import authorized_bars

        if interval != "3m" and _released(symbol, interval):
            loaded = authorized_bars(symbol, interval, now_ms)
            if isinstance(loaded, tuple) and loaded[0]:
                return {"bars": loaded[0], "source_id": "twelve_data"}
        if candles_released(symbol, interval) or reading_released(symbol, interval):
            return _public_bars(symbol, interval, now_ms)
        return None
    from ops.entitlements import decide_use
    from ops.kraken_public import authorized_bars

    decision = decide_use("kraken_public_ohlc", "candle_display", symbol=symbol, interval=interval)
    if decision.get("verified") is True:
        if interval == "3m":
            if decision.get("reason") != "derived_from_native_1m":
                return _public_bars(symbol, interval, now_ms) if _released(symbol, interval) else None
            native = authorized_bars(symbol, "1m", now_ms, transport=transport)
            derived = derive_3m((native or {}).get("bars") or [], now_ms)
            if not derived.get("ok"):
                return {"bars": [], "source_id": "kraken_public_ohlc", "reason": derived.get("reason")}
            return {"bars": derived["bars"], "source_id": "kraken_public_ohlc", "derived": True}
        loaded = authorized_bars(symbol, interval, now_ms, transport=transport)
        bars = (loaded or {}).get("bars") or []
        if bars:
            return {"bars": bars, "source_id": "kraken_public_ohlc", "reason": (loaded or {}).get("reason")}
    if _released(symbol, interval):
        return _public_bars(symbol, interval, now_ms)
    return None


def _higher(symbol, interval):
    order = ("1m", "3m", "15m", "1h")
    if interval not in order:
        return "No higher timeframe is defined."
    wanted = order[order.index(interval) + 1 :]
    if not wanted:
        return "This is the highest desk timeframe."
    from ops.signal_ledger import read

    rows = [row for row in read() if row.get("symbol") == symbol and row.get("interval") in wanted]
    if not rows:
        return "No higher-timeframe observation is stored."
    last = rows[-1]
    return f"{last.get('interval')} is {last.get('observation')}. Research {last.get('research')}. Context only. Not a new signal."


def _expire_or_invalidate(card, now_ms):
    """Append a later state. The earlier row stays."""
    if card.get("quality") != "ok" or card.get("price") is None:
        return None
    from ops.bars import interval_ms
    from ops.signal_ledger import read

    priors = [
        row for row in read()
        if row.get("symbol") == card.get("symbol")
        and row.get("interval") == card.get("interval")
        and row.get("observation") == "active_signal"
    ]
    if not priors:
        return None
    prior = priors[-1]
    price = card.get("price")
    stop = prior.get("stop")
    decision = prior.get("decision")
    if isinstance(price, (int, float)) and isinstance(stop, (int, float)) and decision in {"BUY", "SELL"}:
        crossed = (decision == "BUY" and price <= stop) or (decision == "SELL" and price >= stop)
        if crossed:
            return {
                "symbol": prior.get("symbol"),
                "interval": prior.get("interval"),
                "opportunity_id": prior.get("opportunity_id"),
                "source_id": prior.get("source_id"),
                "lifecycle": "invalidated",
                "observation": "invalidated",
                "research": prior.get("research") or "research_failed",
                "execution": "not_eligible",
                "decision": decision,
                "price": price,
                "entry": prior.get("entry"),
                "stop": stop,
                "target": prior.get("target"),
                "quality": "ok",
                "approved": False,
                "note": "The completed close crossed the stored stop. The earlier signal remains in history.",
            }
    try:
        limit = 48 * interval_ms(card.get("interval") or "15m")
    except ValueError:
        return None
    if int(now_ms) - int(prior.get("created_ms") or now_ms) > limit:
        return {
            "symbol": prior.get("symbol"),
            "interval": prior.get("interval"),
            "opportunity_id": prior.get("opportunity_id"),
            "source_id": prior.get("source_id"),
            "lifecycle": "expired",
            "observation": "expired",
            "research": prior.get("research") or "research_failed",
            "execution": "not_eligible",
            "decision": decision or "WAIT",
            "quality": "ok",
            "approved": False,
            "price": None,
            "entry": prior.get("entry"),
            "stop": prior.get("stop"),
            "target": prior.get("target"),
            "note": "The stored signal is older than 48 candles. It was not deleted.",
        }
    return None


def _observe(symbol, interval, bars, source_id, now_ms):
    from ops.market_conditions import assess
    from ops.terminal_signal import decide

    facts = assess(bars, now_ms, interval)
    result = decide(symbol, interval, "auto", bars, now_ms, None)
    result["source_id"] = source_id
    result["approved"] = False
    result["autopilot_eligible"] = False
    result["manual_paper"] = False
    if result.get("validation_status") in {None, "", "FAIL", "FAILED", "BLOCKED", "REJECTED"}:
        result["validation_status"] = "not_promoted"
    result["price"] = result.get("price") if result.get("price") is not None else result.get("reference_price")
    result["opportunity_id"] = canonical_opportunity_id(symbol, interval, result, bars)
    result["conditions"] = facts["evidence"]
    result["freshness"] = facts["freshness"]
    result["higher_timeframe"] = _higher(symbol, interval)
    if facts["freshness"] == "stale" or result.get("blocked") == "stale_or_incomplete":
        result["quality"] = "stale"
        result["reading_class"] = "observational"
        result["customer_status"] = None
        result["decision"] = "WAIT"
        result["decision_label"] = "WAIT"
        result["price"] = None
        result["entry"] = None
        result["stop"] = None
        result["target"] = None
        result["setup_state"] = "stale"
        try:
            from ops.activity import record
            record(
                "reading_stale",
                component="signal_engine",
                entity=f"{symbol}:{interval}",
                detail={"note": "The completed candle is too old to treat as current. No price was stored.", "symbol": symbol, "interval": interval},
                now_ms=now_ms,
            )
        except Exception:
            pass
    elif result.get("blocked") in {"xau_minute_unlicensed", "commercial_use_unverified"}:
        result["customer_status"] = "reading_unavailable"
        result["quality"] = "unavailable"
        result["price"] = None
    else:
        result["quality"] = "ok"
        if result.get("decision") in {"BUY", "SELL"} and None not in (result.get("entry"), result.get("stop"), result.get("target")):
            result["reading_class"] = result.get("reading_class") or "observational"
            result["setup_state"] = "confirmed"
        else:
            result["reading_class"] = "developing"
            result["setup_state"] = "forming"
            result["decision_label"] = result.get("decision_label") or "WATCH"
    return result


def _gated(symbol, interval, reason):
    card = classify_card(unavailable_card(symbol, interval))
    card["permission"] = "not_granted"
    card["freshness"] = "not_retrieved"
    card["price"] = None
    card["entry"] = None
    card["stop"] = None
    card["target"] = None
    if symbol == "XAUUSD":
        card["note"] = "Gold stays on its own adapter. No XAUUSD reading was synthesized from crypto."
    elif reason == "source_failure":
        card["note"] = "This pair's source failed. No other venue was used, and no candle was invented."
    else:
        card["note"] = "This pair has no display grant. Kraken and Binance are not substitutes for each other."
    return card


def cycle(now_ms=None, transport=None):
    """One pass across the desk. Each pair keeps its own result."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    markets = []
    for symbol, interval in DESK:
        if not _released(symbol, interval):
            note_unavailable(symbol, interval, "reading_unavailable", now_ms, component="signal_engine")
            markets.append(_gated(symbol, interval, "reading_unavailable"))
            continue
        try:
            loaded = _load(symbol, interval, now_ms, transport)
        except Exception:
            loaded = None
        bars = (loaded or {}).get("bars") or []
        if not bars:
            note_unavailable(symbol, interval, (loaded or {}).get("reason") or "source_failure", now_ms, component="signal_engine")
            markets.append(_gated(symbol, interval, "source_failure"))
            continue
        try:
            card = _observe(symbol, interval, bars, loaded.get("source_id"), now_ms)
        except Exception:
            note_unavailable(symbol, interval, "evaluation_failed", now_ms, component="signal_engine")
            markets.append(_gated(symbol, interval, "source_failure"))
            continue
        stored = record_observations([card], now_ms=now_ms, component="signal_engine")
        follow = _expire_or_invalidate(card, now_ms)
        if follow:
            record_observations([follow], now_ms=now_ms, component="signal_engine")
        classified = classify_card(card)
        classified["conditions"] = card.get("conditions")
        classified["higher_timeframe"] = card.get("higher_timeframe")
        classified["freshness"] = card.get("freshness")
        classified["permission"] = "granted"
        if card.get("freshness") == "stale" or card.get("quality") == "stale":
            classified["price"] = None
            classified["entry"] = None
            classified["stop"] = None
            classified["target"] = None
            classified["note"] = "The candle is stale. It is not a current signal and it is not a missing licence."
        if stored.get("rows"):
            classified = {**classified, "persisted": True}
        markets.append(classified)
    return {
        "markets": markets,
        "broker": False,
        "truncated": False,
        "note": "Each instrument is gated on its own. A failed study does not remove an observation.",
    }
