"""Twelve Data client for instruments the public catalog actually lists.

BTC/USD is not BTCUSDT. ETH/USD is not ETHUSDT. A 3-minute bar is not
built from 1-minute or 5-minute rows. The quote route does not supply a
bid or an ask. Nothing here runs unless candle display is verified and an
API key is present. The key is not written into errors.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ops.bars import interval_ms, make_bar, ohlc_ok, validate_series

BASE = "https://api.twelvedata.com"
SOURCE_ID = "twelve_data"
PROVIDER = "twelve-data"

# Confirmed from the public catalog on 2026-11-04 without an API key.
# symbol_search BTC/USDT and ETH/USDT returned count 0.
# symbol_search BTC/USD returned Coinbase Pro, Binance and Bitfinex as US Dollar.
# commodities?symbol=XAU/USD returned one row. /quote does not return bid or ask.
CATALOG = {
    "XAUUSD": {
        "vendor_symbol": "XAU/USD",
        "instrument_name": "Gold Spot / US Dollar",
        "exchange": "COMMODITY",
        "instrument_type": "Precious Metal",
        "not_a_substitute_for": (),
    },
}

REJECTED_PAIRS = {
    "BTCUSDT": "BTC/USD is listed. BTC/USDT is not. They are different pairs.",
    "ETHUSDT": "ETH/USD is listed. ETH/USDT is not. They are different pairs.",
    "BTCUSD": "BTC/USD is not the desk's BTCUSDT market.",
    "ETHUSD": "ETH/USD is not the desk's ETHUSDT market.",
}

INTERVALS = {"1m": "1min", "15m": "15min", "1h": "1h"}


def instrument_spec(symbol):
    return CATALOG.get(symbol)


def vendor_interval(interval):
    return INTERVALS.get(interval)


def _redact(text):
    raw = str(text or "")
    if "apikey=" in raw:
        head, _, tail = raw.partition("apikey=")
        rest = tail.split("&", 1)
        raw = head + "apikey=redacted" + (("&" + rest[1]) if len(rest) > 1 else "")
    return raw


def _stamp(text):
    raw = str(text or "").strip().replace("T", " ")
    try:
        if len(raw) == 10:
            moment = datetime.strptime(raw, "%Y-%m-%d")
        else:
            moment = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return int(moment.replace(tzinfo=timezone.utc).timestamp() * 1000)


def parse_time_series(payload, symbol, interval, now_ms):
    """Turn one Twelve Data body into completed bars. Gaps are counted, not filled."""
    spec = instrument_spec(symbol)
    vendor = vendor_interval(interval)
    if spec is None or vendor is None:
        return {"ok": False, "reason": "unsupported", "bars": [], "synthesized": False}
    payload = payload or {}
    if payload.get("status") == "error" or payload.get("code"):
        return {"ok": False, "reason": "provider_error", "bars": [], "synthesized": False, "provider_code": payload.get("code")}
    meta = payload.get("meta") or {}
    if meta.get("symbol") != spec["vendor_symbol"] or meta.get("interval") != vendor:
        return {
            "ok": False,
            "reason": "symbol_mismatch",
            "bars": [],
            "synthesized": False,
            "returned_symbol": meta.get("symbol"),
            "returned_interval": meta.get("interval"),
        }
    step = interval_ms(interval)
    now_ms = int(now_ms)
    bars = []
    dropped_forming = 0
    for row in payload.get("values") or []:
        if not isinstance(row, dict):
            continue
        open_ms = _stamp(row.get("datetime"))
        if open_ms is None:
            continue
        close_ms = open_ms + step - 1
        if close_ms >= now_ms:
            dropped_forming += 1
            continue
        try:
            open_, high, low, close = (float(row[name]) for name in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
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
            volume=_volume(row.get("volume")),
            complete=True,
            fresh=now_ms - close_ms <= 2 * step,
            provider=PROVIDER,
            source_type="twelve_data_time_series",
            quote_semantics="ohlc_not_bid_ask",
            retrieved_at_ms=now_ms,
        )
        if ohlc_ok(bar) and open_ms % step == 0:
            bars.append(bar)
    bars.sort(key=lambda item: item["open_time_ms"])
    quality = validate_series(bars, interval) if bars else {"ok": False, "duplicates": 0, "gaps": 0, "unsorted": 0, "invalid": 0}
    return {
        "ok": bool(bars) and quality.get("ok") is True,
        "reason": None if bars and quality.get("ok") else "incomplete_or_gapped",
        "bars": bars,
        "synthesized": False,
        "dropped_forming": dropped_forming,
        "quality": quality,
        "vendor_symbol": spec["vendor_symbol"],
        "exchange": spec["exchange"],
    }


def parse_quote(payload):
    """The quote route returns an OHLC-style last price. It is not a bid or an ask."""
    payload = payload or {}
    close = payload.get("close")
    try:
        close = float(close) if close is not None else None
    except (TypeError, ValueError):
        close = None
    return {
        "ok": False,
        "reason": "bid_ask_not_supplied",
        "bid": None,
        "ask": None,
        "last_ohlc_close": close,
        "not_a_candle": True,
        "not_bid_ask": True,
    }


def _volume(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _request(url, timeout, transport):
    if transport is not None:
        return transport(url)
    request = urllib.request.Request(url, headers={"User-Agent": "paper-desk"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode())
        except Exception:
            body = {"status": "error", "code": exc.code}
        return exc.code, body
    except Exception as exc:
        return 0, {"status": "error", "code": type(exc).__name__}


def fetch_time_series(symbol, interval, now_ms, api_key=None, transport=None, timeout=8):
    """Fetch native bars. Refuses a different pair and a missing native interval before any socket."""
    if symbol in REJECTED_PAIRS:
        return {"ok": False, "reason": "pair_not_listed", "detail": REJECTED_PAIRS[symbol], "bars": [], "synthesized": False, "called": False}
    spec = instrument_spec(symbol)
    vendor = vendor_interval(interval)
    if spec is None:
        return {"ok": False, "reason": "pair_not_listed", "bars": [], "synthesized": False, "called": False}
    if vendor is None:
        return {"ok": False, "reason": "native_interval_not_supplied", "bars": [], "synthesized": False, "called": False}
    from ops.entitlements import decide_use

    decision = decide_use(SOURCE_ID, "candle_display", symbol=symbol, interval=interval)
    if decision.get("verified") is not True or decision.get("allowed") is not True:
        return {"ok": False, "reason": "unverified", "bars": [], "synthesized": False, "called": False}
    key = api_key if api_key is not None else os.environ.get("TWELVE_DATA_API_KEY") or ""
    if not key:
        return {"ok": False, "reason": "api_key_missing", "bars": [], "synthesized": False, "called": False}
    query = urllib.parse.urlencode({
        "symbol": spec["vendor_symbol"],
        "interval": vendor,
        "apikey": key,
        "outputsize": 90,
        "timezone": "UTC",
        "order": "ASC",
        "format": "JSON",
    })
    url = f"{BASE}/time_series?{query}"
    status = 0
    payload = {}
    for attempt in range(2):
        status, payload = _request(url, timeout, transport)
        if status != 429 and status < 500:
            break
        if attempt == 0:
            time.sleep(0 if transport is not None else 1)
    parsed = parse_time_series(payload if isinstance(payload, dict) else {}, symbol, interval, now_ms)
    parsed["called"] = True
    parsed["http_status"] = status
    if status == 401:
        parsed["ok"] = False
        parsed["reason"] = "api_key_rejected"
        parsed["bars"] = []
    parsed["error"] = None if parsed.get("ok") else _redact(payload.get("message") if isinstance(payload, dict) else "")
    return parsed


def authorized_bars(symbol, interval, now_ms, transport=None):
    """None when this source is not the authorised reader. A tuple when it is, including a failed read."""
    from ops.entitlements import decide_use

    decision = decide_use(SOURCE_ID, "candle_display", symbol=symbol, interval=interval)
    if decision.get("verified") is not True or decision.get("allowed") is not True:
        return None
    result = fetch_time_series(symbol, interval, now_ms, transport=transport)
    quote = {"ok": False, "reason": "bid_ask_not_supplied", "bid": None, "ask": None, "not_a_candle": True}
    return result.get("bars") or [], PROVIDER, SOURCE_ID, "ohlc_not_bid_ask", quote
