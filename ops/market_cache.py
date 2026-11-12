"""Last completed candles for the desk loop.

A failed pull returns these bars instead of a blank. The file is not a
quote, not a broker fill, and not a fresh signal by itself.
"""

import json
import os
from pathlib import Path

_MAX_AGE_MS = {
    "1m": 15 * 60 * 1000,
    "3m": 30 * 60 * 1000,
    "15m": 3 * 60 * 60 * 1000,
    "1h": 8 * 60 * 60 * 1000,
    "4h": 24 * 60 * 60 * 1000,
    "1d": 3 * 24 * 60 * 60 * 1000,
}


def _path(symbol, interval):
    root = Path(os.environ.get("AUREON_DATA", "data")) / "cache" / "loop"
    name = f"{symbol}-{interval}.json"
    if "/" in name or ".." in name:
        return None
    return root / name


def remember(symbol, interval, bars, now_ms):
    path = _path(symbol, interval)
    if path is None or not isinstance(bars, list) or not bars:
        return False
    kept = [row for row in bars[-180:] if isinstance(row, dict) and row.get("close") is not None]
    if not kept:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"saved_at_ms": int(now_ms), "bars": kept}), encoding="utf-8")
    return True


def recall(symbol, interval, now_ms):
    path = _path(symbol, interval)
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    saved = payload.get("saved_at_ms") if isinstance(payload, dict) else None
    bars = payload.get("bars") if isinstance(payload, dict) else None
    if not isinstance(saved, (int, float)) or not isinstance(bars, list) or not bars:
        return None
    age = int(now_ms) - int(saved)
    if age < 0 or age > _MAX_AGE_MS.get(interval, 15 * 60 * 1000):
        return None
    return bars
