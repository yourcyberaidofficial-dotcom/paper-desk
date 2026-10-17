"""Paginated Binance history. Closed bars only."""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def fetch_history(symbol, interval, years=2, page=1000):
    end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = end - int(years * 365.25 * 24 * 60 * 60 * 1000)
    bars = []
    cursor = start
    while cursor < end and len(bars) < 20000:
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
