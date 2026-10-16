"""Closed-candle evaluator. Always WAIT. Idempotent. No fills."""

import json
import time
from pathlib import Path

from ops.market import fetch_last_closed, fetch_klines
from ops.notify import send_alert
from ops.e1 import e1_side

DEFAULT_PREFS = {
    "assets": ["BTCUSDT", "ETHUSDT"],
    "interval": "15m",
    "quiet_hours_utc": [],
    "max_alerts_per_day": 24,
    "alerts_enabled": True,
    "experimental_alerts": False,
}


class Worker:
    def __init__(self, ledger, prefs_path: Path):
        self.ledger = ledger
        self.prefs_path = Path(prefs_path)
        self.last_beat_ms = 0
        self.last_result = None

    def prefs(self) -> dict:
        if not self.prefs_path.exists():
            return dict(DEFAULT_PREFS)
        data = json.loads(self.prefs_path.read_text())
        merged = dict(DEFAULT_PREFS)
        merged.update({k: data[k] for k in DEFAULT_PREFS if k in data})
        merged["assets"] = [a for a in merged["assets"] if a in {"BTCUSDT", "ETHUSDT"}]
        merged["max_alerts_per_day"] = min(int(merged["max_alerts_per_day"]), 48)
        return merged

    def save_prefs(self, payload: dict) -> dict:
        current = self.prefs()
        for key in ("assets", "interval", "quiet_hours_utc", "max_alerts_per_day", "alerts_enabled", "experimental_alerts"):
            if key in payload:
                current[key] = payload[key]
        current["assets"] = [a for a in current.get("assets", []) if a in {"BTCUSDT", "ETHUSDT"}] or ["BTCUSDT"]
        if current.get("interval") not in {"15m", "1h", "4h"}:
            current["interval"] = "15m"
        current["max_alerts_per_day"] = min(max(int(current.get("max_alerts_per_day", 24)), 0), 48)
        current["quiet_hours_utc"] = [h for h in current.get("quiet_hours_utc") or [] if isinstance(h, int) and 0 <= h <= 23]
        self.prefs_path.parent.mkdir(parents=True, exist_ok=True)
        self.prefs_path.write_text(json.dumps(current, indent=2))
        return current

    def _seen(self, key: str) -> bool:
        return any(row.get("id") == key for row in self.ledger.read())

    def _alerts_today(self, now_ms: int) -> int:
        day = now_ms // 86_400_000
        return sum(1 for row in self.ledger.read() if row.get("type") == "notify" and row.get("ts_ms", 0) // 86_400_000 == day)

    def evaluate(self, now_ms: int | None = None, sender=send_alert) -> list[dict]:
        now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        self.last_beat_ms = now_ms
        prefs = self.prefs()
        hour = time.gmtime(now_ms / 1000).tm_hour
        quiet = hour in set(prefs.get("quiet_hours_utc") or [])
        out = []
        for symbol in prefs["assets"]:
            bar = fetch_last_closed(symbol, prefs["interval"], now_ms=now_ms)
            close_time = bar.get("close_time_ms")
            key = f"eval:{symbol}:{prefs['interval']}:{close_time or 'none'}"
            if self._seen(key):
                continue
            fresh = bool(bar.get("fresh"))
            reason = "no_validated_strategy" if fresh else "stale_or_unavailable"
            record = {
                "id": key,
                "type": "evaluation",
                "asset": symbol,
                "timeframe": prefs["interval"],
                "candle_ts_ms": close_time,
                "evaluated_at_ms": now_ms,
                "result": "WAIT",
                "reason": reason,
                "fresh": fresh,
                "classification": "no_validated_strategy",
                "validated": False,
            }
            experimental = None
            if prefs.get("experimental_alerts") and fresh:
                candles = fetch_klines(symbol, prefs["interval"], limit=21, now_ms=now_ms).get("candles") or []
                bars = [{"high": c["h"], "low": c["l"], "close": c["c"]} for c in candles]
                side = e1_side(bars) if len(bars) >= 21 else "WAIT"
                experimental = {
                    "rule": "E1-donchian-20",
                    "version": "e1-20261016",
                    "classification": "experimental_unvalidated",
                    "result": side,
                    "reference": bar.get("close"),
                    "candle_ts_ms": close_time,
                    "validated": False,
                }
                record["experimental"] = experimental
            self.ledger.append(record)
            notified = None
            if prefs.get("alerts_enabled") and not quiet and self._alerts_today(now_ms) < prefs["max_alerts_per_day"]:
                if experimental and experimental["result"] != "WAIT":
                    text = f"EXPERIMENTAL NOT VALIDATED {symbol} {prefs['interval']} {experimental['result']}. E1-donchian-20. Not a trade."
                else:
                    text = f"Aureon {symbol} {prefs['interval']} WAIT. {reason}. Not a trade."
                notified = sender(text)
                self.ledger.append({
                    "type": "notify",
                    "id": f"notify:{key}",
                    "eval_id": key,
                    "rule": "E1-donchian-20" if experimental and experimental.get("result") != "WAIT" else "WAIT_DEFAULT",
                    "asset": symbol,
                    "timeframe": prefs["interval"],
                    "candle_ts_ms": close_time,
                    "attempted_at_ms": now_ms,
                    "status": notified.get("status"),
                    "delivered": notified.get("delivered"),
                    "reason": notified.get("reason"),
                    "telegram_message_id": notified.get("telegram_message_id"),
                    "read_proof": False,
                })
            record["notification"] = notified
            out.append(record)
        self.last_result = out[-1] if out else self.last_result
        return out

    def status(self) -> dict:
        return {
            "last_beat_ms": self.last_beat_ms,
            "last_result": self.last_result,
            "prefs": self.prefs(),
        }
