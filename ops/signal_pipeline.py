"""Deterministic observation pipeline. It does not call a model or AutoPilot.

States are OBSERVATION, FORMING, CONFIRMED_ACTIVE, INVALIDATED, EXPIRED,
and UNAVAILABLE. UNAVAILABLE always has signal false. Confirmation is not
paper approval and cannot open an order.
"""

from __future__ import annotations

import hashlib
import json
import os
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

    def evaluate(self, candles, *, symbol, interval, now_ms, rights="missing", step_ms=None, account_id=None):
        """Append one lifecycle row. Earlier rows are not rewritten."""
        if rights not in {"approved", "fixture", "user_provided"}:
            return self._store(self._unavailable(symbol, interval, now_ms, "rights_not_approved"), account_id)
        usable = [row for row in candles or [] if row.get("complete") is True and int(row.get("close_time_ms") or 0) <= int(now_ms)]
        usable.sort(key=lambda row: int(row["open_time_ms"]))
        if len(usable) < LOOKBACK + 1:
            return self._store(self._unavailable(symbol, interval, now_ms, "insufficient_candles"), account_id)
        last = usable[-1]
        step = int(step_ms or (int(last["close_time_ms"]) - int(last["open_time_ms"]) + 1))
        if int(now_ms) - int(last["close_time_ms"]) > step * 2:
            return self._store(self._unavailable(symbol, interval, now_ms, "stale_feed"), account_id)
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
            "rights": "user_provided" if rights == "user_provided" else ("fixture_only" if rights == "fixture" else "approved"),
            "live": False,
            "now_ms": int(now_ms),
        }
        if rights == "user_provided":
            row["source_label"] = "user_provided_historical"
            row["live"] = False
        return self._store(row, account_id)

    def _store(self, row, account_id):
        stored = self._append(row)
        if stored["stored"] and account_id:
            _activity(account_id, stored["row"])
        return stored

    def expire_or_invalidate(self, *, symbol, interval, price, now_ms, max_age_ms, account_id=None):
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
        stored = self._append(follow)
        if stored["stored"] and account_id:
            _activity(account_id, stored["row"])
        return stored

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


def read_pipeline():
    """Stored pipeline rows only. Missing rights do not create a row on read."""
    path = Path(os.environ.get("AUREON_DATA") or "data") / "signals" / "pipeline" / "lifecycle.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append({key: value for key, value in row.items() if key != "account_id"})
    return rows


def _opportunity(symbol, interval, side, origin):
    raw = f"{STRATEGY_VERSION}|{symbol}|{interval}|{side}|{origin}"
    return "opp:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _activity(account_id, row):
    from ops.activity import record_once

    mapping = {
        "OBSERVATION": "signal_created",
        "FORMING": "signal_forming",
        "CONFIRMED_ACTIVE": "signal_confirmed",
        "INVALIDATED": "signal_invalidated",
        "EXPIRED": "signal_expired",
        "UNAVAILABLE": "source_unavailable",
    }
    kind = mapping.get(row.get("lifecycle"))
    if not kind:
        return
    entity = f"{row.get('symbol')}:{row.get('interval')}:UNAVAILABLE" if row.get("lifecycle") == "UNAVAILABLE" else f"{row.get('opportunity_id')}:{row.get('lifecycle')}"
    record_once(
        kind,
        entity=entity,
        component="signal_pipeline",
        account_id=account_id,
        detail={
            "note": f"{row.get('symbol')} {row.get('interval')} is {row.get('lifecycle')}. Not an order.",
            "opportunity_id": row.get("opportunity_id"),
            "symbol": row.get("symbol"),
            "interval": row.get("interval"),
            "lifecycle": row.get("lifecycle"),
            "signal": False if row.get("lifecycle") == "UNAVAILABLE" else bool(row.get("signal")),
        },
        now_ms=row.get("now_ms"),
    )
