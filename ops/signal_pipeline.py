"""Deterministic observation pipeline. It does not call a model or AutoPilot.

States are OBSERVATION, FORMING, CONFIRMED_ACTIVE, INVALIDATED, EXPIRED,
and UNAVAILABLE. UNAVAILABLE always has signal false. Confirmation is not
paper approval and cannot open an order.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

STRATEGY_ID = "desk-observation-20261107"
STRATEGY_VERSION = "obs-1"
LOOKBACK = 20

LIFECYCLE = ("OBSERVATION", "FORMING", "CONFIRMED_ACTIVE", "INVALIDATED", "EXPIRED", "UNAVAILABLE")


class SignalBook:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "lifecycle.jsonl"

    def evaluate(self, candles, *, symbol, interval, now_ms, rights="missing", step_ms=None):
        """Append one lifecycle row. Earlier rows are not rewritten."""
        if rights not in {"approved", "fixture"}:
            return self._append(self._unavailable(symbol, interval, now_ms, "rights_not_approved"))
        usable = [row for row in candles or [] if row.get("complete") is True and int(row.get("close_time_ms") or 0) <= int(now_ms)]
        usable.sort(key=lambda row: int(row["open_time_ms"]))
        if len(usable) < LOOKBACK + 1:
            return self._append(self._unavailable(symbol, interval, now_ms, "insufficient_candles"))
        last = usable[-1]
        step = int(step_ms or (int(last["close_time_ms"]) - int(last["open_time_ms"]) + 1))
        if int(now_ms) - int(last["close_time_ms"]) > step * 2:
            return self._append(self._unavailable(symbol, interval, now_ms, "stale_feed"))
        prior = usable[-(LOOKBACK + 1):-1]
        high = max(float(row["high"]) for row in prior)
        low = min(float(row["low"]) for row in prior)
        close = float(last["close"])
        side = None
        state = "OBSERVATION"
        if close > high:
            side, state = "BUY", "CONFIRMED_ACTIVE"
        elif close < low:
            side, state = "SELL", "CONFIRMED_ACTIVE"
        elif high != low and min(abs(close - high), abs(close - low)) / (high - low) <= 0.1:
            state = "FORMING"
        entry = close if side else None
        stop = low if side == "BUY" else high if side == "SELL" else None
        risk = abs(entry - stop) if side else None
        target = entry + risk * 1.5 if side == "BUY" else entry - risk * 1.5 if side == "SELL" else None
        reward = abs(target - entry) / risk if risk else None
        opportunity = _opportunity(symbol, interval, side or "NONE", last["open_time_ms"])
        row = {
            "opportunity_id": opportunity,
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "symbol": symbol,
            "interval": interval,
            "lifecycle": state,
            "signal": state == "CONFIRMED_ACTIVE",
            "approved": False,
            "paper_eligible": False,
            "autopilot": False,
            "decision": side or "WAIT",
            "entry": entry,
            "stop": stop,
            "target": target,
            "reward_risk": reward,
            "bar_open_ms": int(last["open_time_ms"]),
            "source_id": last.get("source_id"),
            "rights": "fixture_only" if rights == "fixture" else "approved",
            "live": False,
            "now_ms": int(now_ms),
        }
        return self._append(row)

    def expire_or_invalidate(self, *, symbol, interval, price, now_ms, max_age_ms):
        prior = [row for row in self.rows() if row["symbol"] == symbol and row["interval"] == interval and row["lifecycle"] == "CONFIRMED_ACTIVE"]
        if not prior:
            return None
        last = prior[-1]
        if last["decision"] == "BUY" and price is not None and price <= last["stop"]:
            state = "INVALIDATED"
        elif last["decision"] == "SELL" and price is not None and price >= last["stop"]:
            state = "INVALIDATED"
        elif int(now_ms) - int(last["now_ms"]) > int(max_age_ms):
            state = "EXPIRED"
        else:
            return None
        follow = dict(last)
        follow["lifecycle"] = state
        follow["signal"] = False
        follow["approved"] = False
        follow["now_ms"] = int(now_ms)
        follow["price"] = price
        return self._append(follow)

    def rows(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _unavailable(self, symbol, interval, now_ms, reason):
        return {
            "opportunity_id": _opportunity(symbol, interval, "UNAVAILABLE", now_ms),
            "strategy_id": STRATEGY_ID,
            "strategy_version": STRATEGY_VERSION,
            "symbol": symbol,
            "interval": interval,
            "lifecycle": "UNAVAILABLE",
            "signal": False,
            "approved": False,
            "paper_eligible": False,
            "autopilot": False,
            "decision": "UNAVAILABLE",
            "entry": None,
            "stop": None,
            "target": None,
            "reward_risk": None,
            "reason": reason,
            "live": False,
            "now_ms": int(now_ms),
        }

    def _append(self, row):
        existing = {(item["opportunity_id"], item["lifecycle"]) for item in self.rows()}
        key = (row["opportunity_id"], row["lifecycle"])
        if key in existing:
            return {"stored": False, "reason": "duplicate", "row": row}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        return {"stored": True, "reason": "stored", "row": row}


def _opportunity(symbol, interval, side, origin):
    raw = f"{STRATEGY_VERSION}|{symbol}|{interval}|{side}|{origin}"
    return "opp:" + hashlib.sha256(raw.encode()).hexdigest()[:16]
