"""Persistent candle book. It stores only candles the caller already holds.

It does not download a feed, invent a price, or report the book as live.
A 3-minute bar is derived only when the caller says the licence allows it
and the 1-minute coverage is complete.
"""

from __future__ import annotations

import json
from pathlib import Path

from ops.market_data import MarketDataError, normalise_candle
from ops.signal_engine import derive_3m


class CandleBook:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "candles.jsonl"

    def accept(self, raw, *, now_ms):
        try:
            candle = normalise_candle(raw, now_ms=int(now_ms))
        except MarketDataError as exc:
            return {"stored": False, "reason": str(exc), "live": False}
        prior = self._rows()
        fingerprint = (candle["instrument"], candle["native_interval"], candle["open_time_ms"])
        if any((row["instrument"], row["native_interval"], row["open_time_ms"]) == fingerprint for row in prior):
            return {"stored": False, "reason": "duplicate", "live": False, "candle": candle}
        same = [row for row in prior if row["instrument"] == candle["instrument"] and row["native_interval"] == candle["native_interval"]]
        latest = max((row["open_time_ms"] for row in same), default=None)
        candle["out_of_order"] = latest is not None and candle["open_time_ms"] < latest
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(candle, separators=(",", ":")) + "\n")
        return {"stored": True, "reason": "out_of_order" if candle["out_of_order"] else "stored", "live": False, "candle": candle}

    def history(self, instrument, interval):
        rows = [
            row for row in self._rows()
            if row.get("instrument") == instrument and row.get("native_interval") == interval
        ]
        return sorted(rows, key=lambda row: row["open_time_ms"])

    def health(self, *, now_ms):
        rows = self._rows()
        books = {}
        for row in rows:
            key = (row["instrument"], row["native_interval"])
            books.setdefault(key, []).append(row)
        feeds = []
        for (instrument, interval), items in sorted(books.items()):
            items = sorted(items, key=lambda row: row["open_time_ms"])
            step = items[0]["close_time_ms"] - items[0]["open_time_ms"] + 1
            gaps = []
            for left, right in zip(items, items[1:]):
                if right["open_time_ms"] - left["open_time_ms"] != step:
                    gaps.append({"after_ms": left["open_time_ms"], "next_ms": right["open_time_ms"]})
            last = items[-1]
            stale = int(now_ms) - int(last["close_time_ms"]) > step * 2
            feeds.append({
                "instrument": instrument,
                "interval": interval,
                "candles": len(items),
                "source_id": last.get("source_id"),
                "provider": last.get("provider"),
                "last_close_ms": last["close_time_ms"],
                "gaps": gaps,
                "stale": stale,
                "out_of_order": any(row.get("out_of_order") for row in items),
                "live": False,
            })
        return {"live": False, "downloaded": False, "feeds": feeds}

    def resample_3m(self, instrument, *, now_ms, derived_allowed):
        if not derived_allowed:
            return {"ok": False, "reason": "licence_does_not_permit_resample", "bars": [], "live": False}
        bars = []
        for row in self.history(instrument, "1m"):
            bars.append({
                "symbol": instrument,
                "interval": "1m",
                "open_time_ms": row["open_time_ms"],
                "close_time_ms": row["close_time_ms"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "complete": True,
                "fresh": True,
                "provider": row.get("provider"),
                "source_id": row.get("source_id"),
            })
        derived = derive_3m(bars, now_ms)
        derived["live"] = False
        return derived

    def _rows(self):
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
