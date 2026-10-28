"""Persist and check real OHLCV. A forming bar is not stored as complete."""

import csv
import json
from pathlib import Path

from ops.bars import interval_ms, ohlc_ok, validate_series

ROOT = Path(__file__).resolve().parents[1] / "research" / "history"


def validate_bars(bars, interval):
    report = validate_series(bars, interval)
    gaps = report.get("gaps") or 0
    duplicates = report.get("duplicates") or 0
    invalid = report.get("invalid") or 0
    forming = sum(1 for bar in bars if not bar.get("complete"))
    return {
        "ok": bool(report.get("ok")) and forming == 0 and gaps == 0 and duplicates == 0 and invalid == 0,
        "bars": len(bars),
        "gaps": gaps,
        "duplicates": duplicates,
        "invalid": invalid,
        "forming": forming,
        "errors": report.get("errors") or [],
    }


def save_csv(path, bars):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for bar in bars:
            writer.writerow({key: bar.get(key) for key in fields})
    return path


def load_csv(path, symbol, interval, provider, quote):
    step = interval_ms(interval)
    bars = []
    with Path(path).open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            bar = {
                "symbol": symbol,
                "instrument": symbol,
                "interval": interval,
                "open_time_ms": int(row["open_time_ms"]),
                "close_time_ms": int(row["close_time_ms"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"] or 0),
                "provider": provider,
                "source_type": "stored_history",
                "quote_semantics": quote,
                "complete": True,
                "fresh": False,
            }
            if not ohlc_ok(bar) or bar["close_time_ms"] - bar["open_time_ms"] + 1 != step:
                bar["complete"] = False
            bars.append(bar)
    return bars


def load_jsonl(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
