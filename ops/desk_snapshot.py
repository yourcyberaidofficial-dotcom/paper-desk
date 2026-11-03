"""One desk observation per instrument and timeframe.

A quote is never written into a candle. A 5-minute sample is never split
into a 1-minute or 3-minute candle. Retention and research stay closed.
This module does not approve a strategy and does not open a paper order.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from ops.bars import interval_ms, validate_series
from ops.data_rights import DESK, source, use_permission

READING_VERSION = "desk-read-20261103b"
QUOTE_LIMIT = 0.0008
_CACHE = {}
_LOCK = threading.Lock()
_TTL_MS = 15_000
_USES = ("display", "indicators", "strategy", "retention", "research")
HEADLINES = (("BTCUSDT", "15m"), ("ETHUSDT", "15m"), ("XAUUSD", "1h"))

ENDPOINTS = {
    "binance_spot_rest_klines": "https://data-api.binance.vision/api/v3/klines",
    "xaus_public_chart": "https://xaus.com/api/v1/chart",
    "xaus_spot_samples": "https://xaus.com/api/v1/intraday",
    "swissquote_public_bbo": "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD",
    "binance_vision_klines": "https://data.binance.vision/data/spot/",
    "dukascopy_datafeed_bi5": "https://datafeed.dukascopy.com/datafeed/XAUUSD",
}


def quote_alignment(close, mid):
    """The existing rule: a gap above 0.08 percent diverges. Exactly 0.08 percent stays aligned."""
    if not close or not mid:
        return None, None
    gap = abs(float(close) - float(mid)) / float(mid)
    return ("diverged" if gap > QUOTE_LIMIT else "aligned"), gap


def permission_for(symbol, interval):
    if symbol == "XAUUSD" and interval in {"1m", "3m"}:
        closed = {
            "allowed": False,
            "status": "xau_minute_unlicensed",
            "reason": "xau_minute_unlicensed",
            "evidence": "No licensed one-minute XAUUSD source. A five-minute sample is not split into a 1-minute or 3-minute candle.",
        }
        return {use: dict(closed) for use in _USES}
    source_id = "xaus_public_chart" if symbol == "XAUUSD" else "binance_spot_rest_klines"
    row = source(source_id) or {}
    out = {}
    for use in _USES:
        decision = use_permission(source_id, use)
        if decision.get("reason") == "paper_desk_live":
            evidence = "Public endpoint used for this paper desk only. Not a written commercial licence."
        else:
            evidence = str(row.get("note") or decision.get("reason") or "")[:280]
        out[use] = {
            "allowed": bool(decision.get("allowed")),
            "status": decision.get("status"),
            "reason": decision.get("reason"),
            "evidence": evidence,
        }
    return out


def archive_restrictions():
    """Uses that stay closed. Reachability is not approval."""
    vision = source("binance_vision_klines") or {}
    duka = source("dukascopy_datafeed_bi5") or {}
    return [
        {
            "source_id": "binance_vision_klines",
            "endpoint": ENDPOINTS["binance_vision_klines"],
            "status": vision.get("status") or "prohibited",
            "retention": False,
            "research": False,
            "evidence": str(vision.get("note") or "")[:280],
        },
        {
            "source_id": "dukascopy_datafeed_bi5",
            "endpoint": ENDPOINTS["dukascopy_datafeed_bi5"],
            "status": duka.get("status") or "rights_unconfirmed",
            "retention": False,
            "research": False,
            "evidence": "Historical bi5 files stay closed. Gold 15m and 1h on the desk come from the public chart, not this archive.",
        },
    ]


def _substituted(interval, bars):
    for bar in bars or []:
        native = bar.get("native_interval") or bar.get("interval")
        if native and native != interval:
            return True
    return False


def _candle_from(bar):
    if not bar:
        return None
    return {
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "open_time_ms": bar.get("open_time_ms"),
        "close_time_ms": bar.get("close_time_ms"),
        "complete": bool(bar.get("complete")),
        "fresh": bool(bar.get("fresh")),
    }


def _quote_view(payload):
    if not isinstance(payload, dict) or not payload.get("ok"):
        return None
    bid, ask = payload.get("bid"), payload.get("ask")
    if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
        return None
    return {
        "price": (float(bid) + float(ask)) / 2,
        "bid": bid,
        "ask": ask,
        "timestamp_ms": payload.get("timestamp_ms"),
        "semantics": "bid_ask_snapshot",
        "not_a_candle": True,
        "source_id": "swissquote_public_bbo",
    }


def _quality(symbol, interval, bars, now_ms):
    if symbol == "XAUUSD" and interval in {"1m", "3m"}:
        return "unlicensed", "xau_minute_unlicensed", {"ok": False, "errors": ["xau_minute_unlicensed"], "duplicates": 0, "gaps": 0, "unsorted": 0}
    if _substituted(interval, bars):
        return "degraded", "timeframe_mismatch", {"ok": False, "errors": ["timeframe_mismatch"], "duplicates": 0, "gaps": 0, "unsorted": 0}
    if not bars:
        return "unavailable", "missing_bars", {"ok": False, "errors": ["empty"], "duplicates": 0, "gaps": 0, "unsorted": 0}
    report = validate_series(bars, interval)
    last = bars[-1]
    close_ms = last.get("close_time_ms") or 0
    step = interval_ms(interval)
    if not last.get("complete") or close_ms > now_ms:
        return "incomplete", "incomplete_candle", report
    if not isinstance(close_ms, (int, float)) or now_ms - close_ms > 2 * step:
        return "stale", "stale_or_incomplete", report
    if report.get("duplicates") or report.get("unsorted") or not report.get("ok"):
        return "degraded", "series_quality", report
    return "ok", None, report


def assemble(symbol, interval, now_ms, bars=None, quote=None, provider=None, source_id=None, semantics=None):
    """Build one snapshot from bars already in hand. Does not fetch and does not invent a close."""
    now_ms = int(now_ms)
    bars = list(bars or [])
    if symbol == "XAUUSD" and interval in {"1m", "3m"}:
        bars = []
    quality, blocked, report = _quality(symbol, interval, bars, now_ms)
    show_last = bool(bars) and quality not in {"unlicensed"} and not _substituted(interval, bars)
    last = bars[-1] if show_last else None
    candle = _candle_from(last)
    if candle is not None:
        candle["fresh"] = quality == "ok"
    usable = bars if quality == "ok" else []
    quote_view = _quote_view(quote) if symbol == "XAUUSD" else None
    alignment, gap = (None, None)
    if candle and candle.get("close") is not None and quote_view:
        alignment, gap = quote_alignment(candle["close"], quote_view["price"])
    if symbol == "XAUUSD" and interval in {"1m", "3m"}:
        source_name = "none"
        provider = "none"
        semantics = "unavailable"
    elif symbol == "XAUUSD":
        source_name = source_id or "xaus_public_chart"
        provider = provider or "xaus.com"
        semantics = semantics or (last or {}).get("quote_semantics") or "ohlc_not_bid_ask"
    else:
        source_name = source_id or "binance_spot_rest_klines"
        provider = provider or "binance-public"
        semantics = semantics or "last_trade"
    close_ms = (candle or {}).get("close_time_ms") or "none"
    display_close = None if candle is None else candle.get("close")
    snap = {
        "instrument": symbol,
        "timeframe": interval,
        "provider": provider,
        "source_id": source_name,
        "endpoint": ENDPOINTS.get(source_name),
        "permission": permission_for(symbol, interval),
        "quote": quote_view,
        "candle": candle,
        "source_timestamp_ms": (candle or {}).get("close_time_ms"),
        "ingested_at_ms": now_ms,
        "completeness": "complete" if quality == "ok" else ("missing" if not bars else quality),
        "freshness": "fresh" if quality == "ok" else quality,
        "quality": quality,
        "blocked_reason": blocked,
        "series": {
            "bars": len(bars),
            "duplicates": report.get("duplicates") or 0,
            "gaps": report.get("gaps") or 0,
            "unsorted": report.get("unsorted") or 0,
        },
        "quote_alignment": alignment,
        "quote_gap": gap,
        "reading_at_ms": now_ms,
        "reading_version": READING_VERSION,
        "snapshot_id": f"{symbol}:{interval}:{close_ms}:{READING_VERSION}",
        "candle_semantics": semantics,
        "display": {
            "price": display_close,
            "close": display_close,
            "fresh": quality == "ok",
            "timeframe": interval,
            "close_time_ms": (candle or {}).get("close_time_ms"),
            "open_time_ms": (candle or {}).get("open_time_ms"),
            "quality": quality,
            "source_id": source_name,
            "provider": provider,
            "snapshot_id": f"{symbol}:{interval}:{close_ms}:{READING_VERSION}",
            "reading_version": READING_VERSION,
            "quote": None if quote_view is None else {
                "price": quote_view["price"],
                "timestamp_ms": quote_view["timestamp_ms"],
                "semantics": quote_view["semantics"],
                "not_a_candle": True,
            },
        },
        "_bars": usable,
        "_live_quote": quote if symbol == "XAUUSD" and interval not in {"1m", "3m"} else None,
    }
    return snap


def _load_bars(symbol, interval, now_ms):
    if symbol == "XAUUSD" and interval in {"1m", "3m"}:
        return [], "none", "none", "unavailable", None
    if symbol == "XAUUSD":
        from ops.terminal_route import load_gold_ohlc
        loaded = load_gold_ohlc(interval, now_ms)
        quote = None
        try:
            from ops.gold_live import swissquote_xau
            quote = swissquote_xau(now_ms)
        except Exception as exc:
            quote = {"ok": False, "reason": type(exc).__name__}
        if isinstance(loaded, tuple):
            return [], "xaus.com", "xaus_public_chart", "ohlc_not_bid_ask", quote
        bars = loaded or []
        semantics = (bars[-1].get("quote_semantics") if bars else None) or "ohlc_not_bid_ask"
        source_name = "xaus_spot_samples" if semantics == "spot_sample_not_bid_ask" else "xaus_public_chart"
        return bars, "xaus.com", source_name, semantics, quote
    from ops.terminal_route import load_crypto_bars
    loaded = load_crypto_bars(symbol, interval, now_ms)
    if isinstance(loaded, tuple):
        return [], "binance-public", "binance_spot_rest_klines", "last_trade", None
    return loaded or [], "binance-public", "binance_spot_rest_klines", "last_trade", None


def observe(symbol, interval, now_ms, bars=None, quote=None, provider=None, source_id=None, semantics=None):
    """Return the cached network snapshot, or assemble injected bars without caching them."""
    now_ms = int(now_ms)
    if bars is not None or quote is not None:
        return assemble(symbol, interval, now_ms, bars=bars, quote=quote, provider=provider, source_id=source_id, semantics=semantics)
    key = (symbol, interval)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now_ms - hit[0] < _TTL_MS:
            return hit[1]
    try:
        loaded, feed, source_name, feed_semantics, live_quote = _load_bars(symbol, interval, now_ms)
    except Exception as exc:
        loaded, feed, source_name, feed_semantics, live_quote = [], "none", "none", "unavailable", {"ok": False, "reason": type(exc).__name__}
        snap = assemble(symbol, interval, now_ms, bars=[], quote=live_quote, provider=feed, source_id=source_name, semantics=feed_semantics)
        snap["blocked_reason"] = type(exc).__name__
        snap["quality"] = "unavailable"
        snap["freshness"] = "unavailable"
        return snap
    snap = assemble(
        symbol, interval, now_ms,
        bars=loaded, quote=live_quote, provider=feed, source_id=source_name, semantics=feed_semantics,
    )
    with _LOCK:
        _CACHE[key] = (now_ms, snap)
    return snap


def _ordered(loader, now_ms):
    return [loader(symbol, interval, now_ms) for symbol, interval in DESK]


def board(now_ms):
    now_ms = int(now_ms)
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [pool.submit(observe, symbol, interval, now_ms) for symbol, interval in DESK]
        return [job.result() for job in jobs]


def headline(now_ms):
    now_ms = int(now_ms)
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(observe, symbol, interval, now_ms) for symbol, interval in HEADLINES]
        return [job.result() for job in jobs]


def window_from(snap):
    snap = snap or {}
    return {
        "symbol": snap.get("instrument"),
        "interval": snap.get("timeframe"),
        "ok": snap.get("quality") == "ok" and bool(snap.get("_bars")),
        "reason": snap.get("blocked_reason"),
        "bars": list(snap.get("_bars") or []),
        "higher": [],
        "provider": snap.get("provider"),
        "quote_semantics": snap.get("candle_semantics"),
        "source_kind": "prospective",
        "live_quote": snap.get("_live_quote"),
    }


def classify(card, snap):
    """Label an existing reading. Does not calculate a new setup or a probability."""
    card = dict(card or {})
    snap = snap or {}
    quality = snap.get("quality") or "unavailable"
    label = card.get("decision_label") or card.get("decision") or "WAIT"
    decision = card.get("decision")
    message = card.get("message") or card.get("reason") or ""
    if quality == "unlicensed" or card.get("blocked") == "xau_minute_unlicensed" or label == "UNAVAILABLE":
        reading_class, setup_state, direction = "unavailable", "unavailable", "neutral"
    elif quality in {"unavailable", "incomplete", "stale", "degraded"}:
        reading_class, setup_state, direction = "insufficient", "unavailable", "neutral"
    elif label == "WATCH" or card.get("runtime_status") == "watch":
        reading_class, setup_state = "developing", "forming"
        raw = str(card.get("direction") or card.get("decision") or "")
        if raw in {"SELL", "SHORT", "SHORT_IDEA"}:
            direction = "bearish"
        elif raw in {"BUY", "LONG"}:
            direction = "bullish"
        else:
            direction = "neutral"
    elif decision in {"BUY", "SELL"} and card.get("entry") is not None and card.get("stop") is not None and card.get("target") is not None:
        reading_class = "validated" if card.get("approved") is True else "manual_plan"
        setup_state = "confirmed"
        direction = "bullish" if decision == "BUY" else "bearish"
    else:
        reading_class, setup_state, direction = "observational", "none", "neutral"
        if decision == "BUY":
            direction = "bullish"
        elif decision == "SELL":
            direction = "bearish"
    if quality != "ok":
        card["entry"] = None
        card["stop"] = None
        card["target"] = None
        if reading_class == "manual_plan":
            reading_class, setup_state = "insufficient", "unavailable"
    manual = reading_class == "manual_plan"
    close_ms = ((snap.get("candle") or {}).get("close_time_ms"))
    card.update({
        "snapshot_id": snap.get("snapshot_id"),
        "reading_version": snap.get("reading_version") or READING_VERSION,
        "source_id": snap.get("source_id"),
        "provider": card.get("source") or snap.get("provider"),
        "candle_close_ms": close_ms,
        "candle_open_ms": (snap.get("candle") or {}).get("open_time_ms"),
        "freshness": snap.get("freshness"),
        "quality": quality,
        "reading_class": reading_class,
        "setup_state": setup_state,
        "direction_label": direction,
        "manual_paper": manual,
        "autopilot_eligible": False,
        "approved": False if card.get("approved") is not True else True,
        "probability": None,
        "explanation": message,
        "invalidation": card.get("invalidation") or _changes(reading_class)[0],
        "changes_when": _changes(reading_class)[1],
        "quote_separated": True,
    })
    return card


def _changes(reading_class):
    text = {
        "manual_plan": (
            "The stop on this reading. A later completed candle can retire the plan. Confirming it does not approve a strategy.",
            "The plan changes only when a new completed candle is read. AutoPilot cannot open it.",
        ),
        "developing": (
            "The setup is still forming. It is not a paper plan until entry, stop and target are confirmed on a completed candle.",
            "A later completed candle can confirm it or let it expire. A quote is not that candle.",
        ),
        "insufficient": (
            "No plan is calculated from a stale, incomplete or degraded candle.",
            "A fresh completed candle is required before a setup is shown.",
        ),
        "unavailable": (
            "This timeframe is not available. No substitute candle is used.",
            "It stays closed until an exact permitted source exists. A five-minute sample is not split into a shorter candle.",
        ),
        "validated": (
            "A validated signal would name its approved strategy version. None is approved.",
            "Approval is a separate record. Agreement between readings is not approval.",
        ),
    }.get(reading_class, (
        "No qualifying setup on this candle. A later completed candle can change the observation.",
        "An observation is not an order and not an AutoPilot signal.",
    ))
    return text


def public_reading(card):
    card = card or {}
    return {
        "snapshot_id": card.get("snapshot_id"),
        "reading_version": card.get("reading_version"),
        "reading_class": card.get("reading_class"),
        "setup_state": card.get("setup_state"),
        "direction_label": card.get("direction_label"),
        "decision": card.get("decision_label") or card.get("decision"),
        "manual_paper": card.get("manual_paper") is True,
        "autopilot_eligible": False,
        "approved": card.get("approved") is True,
        "probability": None,
        "explanation": card.get("explanation"),
        "invalidation": card.get("invalidation"),
        "changes_when": card.get("changes_when"),
        "quality": card.get("quality"),
        "source_id": card.get("source_id"),
        "provider": card.get("provider"),
        "candle_close_ms": card.get("candle_close_ms"),
        "entry": card.get("entry"),
        "stop": card.get("stop"),
        "target": card.get("target"),
    }


def public_snapshot(snap):
    hidden = {"_bars", "_live_quote"}
    return {key: value for key, value in snap.items() if key not in hidden}


def source_rows(snaps):
    rows = []
    for snap in snaps:
        permission = snap.get("permission") or {}
        rows.append({
            "instrument": snap.get("instrument"),
            "timeframe": snap.get("timeframe"),
            "provider": snap.get("provider"),
            "source_id": snap.get("source_id"),
            "endpoint": snap.get("endpoint"),
            "display": (permission.get("display") or {}).get("status"),
            "retention": (permission.get("retention") or {}).get("status"),
            "research": (permission.get("research") or {}).get("status"),
            "quality": snap.get("quality"),
            "snapshot_id": snap.get("snapshot_id"),
        })
    return rows


def desk_scan(now_ms):
    from ops.scanner import scan

    snaps = board(now_ms)
    windows = [window_from(snap) for snap in snaps]
    body = scan(windows, now_ms=int(now_ms))
    by_key = {(snap["instrument"], snap["timeframe"]): snap for snap in snaps}
    body["markets"] = [
        classify(card, by_key.get((card.get("symbol"), card.get("interval"))) or {})
        for card in (body.get("markets") or [])
    ]
    body["reading_version"] = READING_VERSION
    body["snapshots"] = [public_snapshot(snap) for snap in snaps]
    body["sources"] = source_rows(snaps)
    body["archives"] = archive_restrictions()
    return body


def headline_board(now_ms):
    """Prices and readings for the overview instruments. One observation each."""
    snaps = headline(now_ms)
    cards = []
    try:
        from ops.scanner import scan
        body = scan([window_from(snap) for snap in snaps], now_ms=int(now_ms))
        cards = body.get("markets") or []
    except Exception:
        cards = []
    labeled = []
    for index, snap in enumerate(snaps):
        card = cards[index] if index < len(cards) else {}
        labeled.append(classify(card, snap))
    return snaps, labeled


def reading_for(symbol, interval, now_ms, bars=None, quote=None):
    """The same classification the desk uses, for one instrument and timeframe."""
    if (symbol, interval) not in DESK:
        return None
    snap = observe(symbol, interval, now_ms, bars=bars, quote=quote)
    try:
        from ops.scanner import scan
        body = scan([window_from(snap)], now_ms=int(now_ms))
        card = (body.get("markets") or [{}])[0]
    except Exception:
        card = {}
    return classify(card, snap)
