"""Closed-candle evaluator. Always WAIT. Idempotent. No fills."""

import json
import time
from pathlib import Path

from ops.market import fetch_last_closed, fetch_klines
from ops.notify import send_alert
from ops.e1 import e1_side
from ops.experimental import ExperimentalBook

DEFAULT_PREFS = {
    "assets": ["BTCUSDT", "ETHUSDT"],
    "interval": "15m",
    "quiet_hours_utc": [],
    "max_alerts_per_day": 24,
    "alerts_enabled": True,
    "experimental_alerts": False,
}


class Worker:
    def __init__(self, ledger, prefs_path: Path, experimental_path=None):
        self.ledger = ledger
        self.prefs_path = Path(prefs_path)
        self.book = ExperimentalBook(experimental_path or self.prefs_path.parent / "experimental.jsonl")
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
        return sum(1 for row in self.ledger.read() if row.get("type") == "notify" and row.get("rule") != "WAIT_DEFAULT" and row.get("ts_ms", 0) // 86_400_000 == day)

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
                candles = fetch_klines(symbol, prefs["interval"], limit=22, now_ms=now_ms).get("candles") or []
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
            text = None
            if experimental and experimental["result"] in {"LONG_BIAS", "SHORT_BIAS"}:
                text = (
                    f"EXPERIMENTAL — NOT VALIDATED {symbol} {prefs['interval']} {experimental['result']}. "
                    f"E1-donchian-20. close={experimental.get('reference')}. candle={close_time}. fresh={fresh}. Not a trade."
                )
            elif not fresh:
                text = f"Aureon {symbol} {prefs['interval']} stale or unavailable. candle={close_time}. Not a trade."
            if text and prefs.get("alerts_enabled") and not quiet and self._alerts_today(now_ms) < prefs["max_alerts_per_day"]:
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
            if experimental and experimental["result"] in {"LONG_BIAS", "SHORT_BIAS"}:
                self.book.append({
                    "id": f"signal:{key}",
                    "type": "paper_signal",
                    "asset": symbol,
                    "side": experimental["result"],
                    "rule": "E1-donchian-20",
                    "candle_ts_ms": close_time,
                    "reference": experimental.get("reference"),
                    "label": "EXPERIMENTAL PAPER — NOT VALIDATED",
                })
            pending = [r for r in self.book.read() if r.get("type") == "paper_signal" and r.get("asset") == symbol]
            opened = {r.get("signal_id") for r in self.book.read() if r.get("type") == "paper_open"}
            if pending and self.book.open_position() is None:
                sig = pending[-1]
                if sig["id"] not in opened and sig.get("candle_ts_ms") != close_time and bar.get("open") is not None:
                    fee = 11 / 10000
                    self.book.append({
                        "id": f"open:{sig['id']}",
                        "type": "paper_open",
                        "signal_id": sig["id"],
                        "asset": symbol,
                        "side": sig["side"],
                        "entry_price": bar["open"],
                        "entry_ts_ms": close_time,
                        "fee_bps": 11,
                        "label": "EXPERIMENTAL PAPER — NOT VALIDATED",
                    })
            pos = self.book.open_position()
            if pos and pos.get("asset") == symbol and experimental and pos.get("entry_ts_ms") != close_time:
                age_bars = max(0, int((close_time - pos.get("entry_ts_ms", close_time)) / (15 * 60 * 1000)))
                opposite = experimental["result"] == ("SHORT_BIAS" if pos["side"] == "LONG_BIAS" else "LONG_BIAS")
                if opposite or age_bars >= 20:
                    exit_price = bar.get("close")
                    side = 1 if pos["side"] == "LONG_BIAS" else -1
                    gross = side * (exit_price - pos["entry_price"]) / pos["entry_price"]
                    net = gross - 22 / 10000
                    self.book.append({
                        "id": f"close:{pos['id']}",
                        "type": "paper_close",
                        "open_id": pos["id"],
                        "exit_price": exit_price,
                        "exit_ts_ms": close_time,
                        "net": net,
                        "label": "EXPERIMENTAL PAPER — NOT VALIDATED",
                    })
            out.append(record)
        self.last_result = out[-1] if out else self.last_result
        return out

    def status(self) -> dict:
        return {
            "last_beat_ms": self.last_beat_ms,
            "last_result": self.last_result,
            "prefs": self.prefs(),
        }
