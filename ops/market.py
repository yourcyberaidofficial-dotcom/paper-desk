"""BTC/ETH closed-bar monitor. Gold is not traded."""

import json
import time
import urllib.parse
import urllib.request

STALE_MS = 15 * 60 * 1000


def fetch_last_closed(symbol: str, interval: str = "15m", now_ms: int | None = None) -> dict:
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": 2})
    request = urllib.request.Request(
        f"https://data-api.binance.vision/api/v3/klines?{query}",
        headers={"User-Agent": "paper-desk"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            rows = json.loads(response.read().decode())
    except Exception as exc:
        return {"symbol": symbol, "fresh": False, "error": type(exc).__name__, "checked_at_ms": now_ms}
    closed = [row for row in rows if int(row[6]) < now_ms]
    if not closed:
        return {"symbol": symbol, "fresh": False, "error": "no_closed_bar", "checked_at_ms": now_ms}
    bar = closed[-1]
    close_time = int(bar[6])
    return {
        "symbol": symbol,
        "interval": interval,
        "open_time_ms": int(bar[0]),
        "close_time_ms": close_time,
        "close": float(bar[4]),
        "fresh": (now_ms - close_time) <= STALE_MS,
        "checked_at_ms": now_ms,
        "source": "binance-public",
        "label": "WATCH ONLY",
    }


def fetch_klines(symbol: str, interval: str = "15m", limit: int = 100, now_ms: int | None = None) -> dict:
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    if symbol not in {"BTCUSDT", "ETHUSDT"}:
        return {"symbol": symbol, "error": "symbol_not_allowed", "candles": []}
    if interval not in {"15m", "1h", "4h", "1d"}:
        return {"symbol": symbol, "error": "interval_not_allowed", "candles": []}
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": min(limit, 200)})
    request = urllib.request.Request(
        f"https://data-api.binance.vision/api/v3/klines?{query}",
        headers={"User-Agent": "paper-desk"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            rows = json.loads(response.read().decode())
    except Exception as exc:
        return {"symbol": symbol, "error": type(exc).__name__, "candles": []}
    candles = []
    for row in rows:
        if int(row[6]) >= now_ms:
            continue
        candles.append({
            "t": int(row[0]),
            "o": float(row[1]),
            "h": float(row[2]),
            "l": float(row[3]),
            "c": float(row[4]),
            "v": float(row[5]),
        })
    return {"symbol": symbol, "interval": interval, "source": "binance-public", "label": "WATCH ONLY", "candles": candles}


def snapshot(now_ms: int | None = None) -> dict:
    return {
        "BTCUSDT": fetch_last_closed("BTCUSDT", now_ms=now_ms),
        "ETHUSDT": fetch_last_closed("ETHUSDT", now_ms=now_ms),
        "gold": {"symbol": "XAU", "status": "observation_only", "signal": False},
    }
