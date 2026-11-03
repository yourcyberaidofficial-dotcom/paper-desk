"""Paginated Binance history. Closed bars only. No artificial bar ceiling."""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def fetch_history(symbol, interval, years=3, page=1000):
    from ops.data_rights import ingestion_allowed

    decision = ingestion_allowed("binance_spot_rest_klines", "historical_research")
    if not decision["allowed"]:
        raise PermissionError(decision["reason"])
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - int(years * 365.25 * 24 * 60 * 60 * 1000)
    bars = []
    cursor = start
    pages = 0
    while cursor < end:
        query = urllib.parse.urlencode({
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "limit": page,
        })
        request = urllib.request.Request(
            f"https://data-api.binance.vision/api/v3/klines?{query}",
            headers={"User-Agent": "paper-desk"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            rows = json.loads(response.read().decode())
        pages += 1
        if not rows:
            break
        for row in rows:
            close_ms = int(row[6])
            if close_ms >= end:
                continue
            bars.append({
                "open_time_ms": int(row[0]),
                "close_time_ms": close_ms,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
            })
        nxt = int(rows[-1][0]) + 1
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(0.05)
    unique = {b["open_time_ms"]: b for b in bars}
    ordered = [unique[k] for k in sorted(unique)]
    return ordered


def coverage_status(bars, end_ms, interval):
    if not bars:
        return "FAILED"
    steps = {"15m": 15 * 60 * 1000, "1h": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000}
    step = steps.get(interval)
    ts = [b["open_time_ms"] for b in bars]
    gaps = 0 if step is None else sum(1 for a, b in zip(ts, ts[1:]) if b - a != step)
    last = bars[-1]["close_time_ms"]
    recent = end_ms - last < 2 * 24 * 60 * 60 * 1000
    if gaps:
        return "PARTIAL"
    return "COMPLETE" if recent else "PARTIAL"
