"""Worker-facing shadow records. Uses evaluate_snapshot and does not send."""

import hashlib
import json

from ops.bars import aggregate
from ops.engine_eval import evaluate_snapshot
from ops.hypotheses import VERSIONS
from ops.shadow import STATES

PROMOTIONS = "data/promotions.json"


def config_sha256():
    raw = json.dumps(VERSIONS, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def promotion_ids(path=None):
    """Empty unless a future review writes a list of approved strategy versions."""
    from pathlib import Path

    target = Path(path) if path is not None else Path(__file__).resolve().parents[1] / PROMOTIONS
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, str) and item]


def load_live_windows(now_ms):
    """Completed public bars only. A failure is an empty window, not a price."""
    from ops.data_rights import MESSAGE, network_block

    now_ms = int(now_ms)
    crypto = network_block("binance_spot_rest_klines", "display")
    gold = network_block("xaus_public_chart", "display")
    if crypto or gold:
        windows = []
        for symbol in ("BTCUSDT", "ETHUSDT", "XAUUSD"):
            for interval in ("1m", "3m", "15m", "1h"):
                if symbol == "XAUUSD" and interval in {"1m", "3m"}:
                    windows.append(_empty(symbol, interval, "none", "unavailable", "xau_minute_unlicensed"))
                    continue
                block = gold if symbol == "XAUUSD" else crypto
                if block:
                    row = _empty(symbol, interval, "withheld", "withheld", "commercial_use_unverified")
                    row["rights_status"] = block.get("rights_status")
                    row["message"] = MESSAGE
                    row["price"] = None
                    windows.append(row)
                else:
                    windows.append(_empty(symbol, interval, "unknown", "unknown", "missing_bars"))
        return windows
    from concurrent.futures import ThreadPoolExecutor
    from ops.feeds import binance_bars, xaus_chart

    crypto_start = now_ms - 50 * 60 * 60 * 1000
    with ThreadPoolExecutor(max_workers=3) as pool:
        btc = pool.submit(_crypto_window, "BTCUSDT", crypto_start, now_ms, binance_bars)
        eth = pool.submit(_crypto_window, "ETHUSDT", crypto_start, now_ms, binance_bars)
        gold = pool.submit(_gold_window, now_ms, xaus_chart)
        return [btc.result(), eth.result(), gold.result()]


def _crypto_window(symbol, start_ms, now_ms, fetch):
    try:
        entry = fetch(symbol, "15m", start_ms, now_ms, now_ms=now_ms, timeout=8, attempts=1)
        higher = fetch(symbol, "1h", start_ms, now_ms, now_ms=now_ms, timeout=8, attempts=1)
    except Exception as exc:
        return _empty(symbol, "15m", "binance-public", "last_trade", type(exc).__name__)
    bars = entry.get("bars") or []
    upper = higher.get("bars") or []
    ok = bool(entry.get("ok") and higher.get("ok") and bars and upper)
    reason = None if ok else (entry.get("reason") or higher.get("reason") or "missing_bars")
    return {
        "symbol": symbol,
        "interval": "15m",
        "ok": ok,
        "reason": reason,
        "bars": bars,
        "higher": upper,
        "provider": "binance-public",
        "quote_semantics": "last_trade",
        "source_kind": "prospective",
    }


def _gold_window(now_ms, fetch):
    chart = None
    try:
        from ops.feeds import xaus_spot_bars
        spot = xaus_spot_bars("1h", now_ms=now_ms, timeout=8, attempts=1)
        if len(spot.get("bars") or []) >= 24:
            chart = spot
    except Exception:
        chart = None
    if chart is None:
        try:
            chart = fetch("1h", now_ms=now_ms, timeout=8, attempts=1)
        except Exception as exc:
            return _empty("XAUUSD", "1h", "xaus.com", "ohlc_not_bid_ask", type(exc).__name__)
    bars = chart.get("bars") or []
    quote = chart.get("quote_semantics") or (bars[-1].get("quote_semantics") if bars else "ohlc_not_bid_ask")
    try:
        higher = aggregate(bars, "1h", "4h") if bars else []
    except ValueError:
        higher = []
    ok = bool(chart.get("ok") and bars)
    return {
        "symbol": "XAUUSD",
        "interval": "1h",
        "ok": ok,
        "reason": None if ok else (chart.get("reason") or "GOLD_FEED_UNAVAILABLE"),
        "bars": bars,
        "higher": higher,
        "provider": chart.get("provider") or "xaus.com",
        "quote_semantics": quote,
        "source_kind": "prospective",
    }


def _empty(symbol, interval, provider, semantics, reason):
    return {
        "symbol": symbol,
        "interval": interval,
        "ok": False,
        "reason": reason,
        "bars": [],
        "higher": [],
        "provider": provider,
        "quote_semantics": semantics,
        "source_kind": "prospective",
    }


def _live(window):
    if window.get("source_kind") != "prospective" or not window.get("ok"):
        return False
    bars = window.get("bars") or []
    if not bars:
        return False
    last = bars[-1]
    return bool(last.get("complete") and last.get("fresh"))


def observe_prospective(ledger, now_ms, loader, promotions=None):
    """Record the canonical snapshot. Historical bars are not labeled live."""
    digest = config_sha256()
    allowed = set(promotions if promotions is not None else promotion_ids())
    written = []
    for window in loader(now_ms):
        if _live(window):
            written.extend(_from_engine(ledger, window, now_ms, digest, allowed))
        else:
            written.append(_unavailable(ledger, window, now_ms, digest))
    return written


def _unavailable(ledger, window, now_ms, digest):
    bars = window.get("bars") or []
    last = bars[-1] if bars else None
    historical = window.get("source_kind") == "historical_replay"
    if historical:
        source_kind = "historical_replay"
        state = "WAIT"
        reason = "historical_replay"
        quality = "historical_or_unconfirmed"
    elif last is not None and not last.get("complete"):
        source_kind = "unavailable"
        state = "DATA_UNAVAILABLE"
        reason = "incomplete_bar"
        quality = "rejected"
    else:
        source_kind = "unavailable"
        state = "DATA_UNAVAILABLE"
        reason = window.get("reason") or ("stale_or_not_live" if last else "no_bars")
        quality = "stale" if last else "missing"
    anchor = last["open_time_ms"] if last else "none"
    symbol = window["symbol"]
    interval = window["interval"]
    return ledger.append({
        "observed_at_ms": now_ms,
        "symbol": symbol,
        "timeframe": interval,
        "source": window.get("provider") or "unknown",
        "source_kind": source_kind,
        "strategy_version": "engine",
        "config_sha256": digest,
        "quality": quality,
        "fresh": False,
        "state": state,
        "reason": reason,
        "event_id": f"engine:{symbol}:{interval}:{state}:{anchor}",
        "quote_semantics": window.get("quote_semantics") or "unknown",
        "classification": "historical_replay" if historical else "DATA_UNAVAILABLE",
        "eligibility": "not_eligible",
    })


def _from_engine(ledger, window, now_ms, digest, allowed):
    symbol = window["symbol"]
    interval = window["interval"]
    bars = window["bars"]
    results = evaluate_snapshot(symbol, bars, window.get("higher") or [], now_ms, interval)
    anchor = bars[-1]["open_time_ms"]
    rows = []
    for result in results:
        state = result.get("state")
        reason = result.get("reason")
        if state == "APPROVED_SIGNAL" or result.get("approved") or result.get("version") in allowed and state == "APPROVED_SIGNAL":
            state = "WAIT"
            reason = "not_approved"
        if state not in STATES:
            state = "WAIT"
            reason = reason or "unrecognized_state"
        data_gap = state == "DATA_UNAVAILABLE"
        event = result.get("event_id") or f"{result.get('strategy')}:{symbol}:{interval}:{result.get('direction') or state}:{anchor}"
        rows.append(ledger.append({
            "observed_at_ms": now_ms,
            "symbol": symbol,
            "timeframe": interval,
            "source": window.get("provider") or "unknown",
            "source_kind": "unavailable" if data_gap else "prospective",
            "strategy_version": result.get("version") or result.get("strategy"),
            "config_sha256": digest,
            "quality": "rejected" if data_gap else "fresh",
            "fresh": not data_gap,
            "state": state,
            "reason": reason,
            "event_id": event,
            "anchor_open_ms": anchor,
            "quote_semantics": window.get("quote_semantics") or "unknown",
            "classification": result.get("state"),
            "eligibility": "not_eligible_for_promotion",
            "direction": result.get("direction"),
        }))
    return rows
