"""Closed-candle evaluator. Always WAIT. Idempotent. No fills."""

import json
import time
from pathlib import Path

from ops.build_id import shadow_enabled
from ops.delivery import authorize
from ops.market import fetch_last_closed, fetch_klines
from ops.notify import send_alert
from ops.e1 import e1_side
from ops.experimental import ExperimentalBook

COVERAGE = tuple(
    (symbol, interval)
    for symbol in ("BTCUSDT", "ETHUSDT", "XAUUSD")
    for interval in ("1m", "3m", "15m", "1h")
)


def pair_availability():
    """Live desk pairs. Gold uses the public chart, including 1m and 3m."""
    rows = []
    for symbol, interval in COVERAGE:
        if symbol == "XAUUSD":
            rows.append({
                "symbol": symbol,
                "interval": interval,
                "status": "ready",
                "feed": "xaus_public_chart",
                "reason": None,
            })
        else:
            rows.append({
                "symbol": symbol,
                "interval": interval,
                "status": "ready",
                "feed": "binance_spot_rest_klines",
                "reason": None,
            })
    return rows

PRODUCTION = "WAIT_DEFAULT"


def may_send_observation(profile, production=PRODUCTION):
    """Opt-in is required and is not enough while production is WAIT_DEFAULT."""
    if production == "WAIT_DEFAULT":
        return False
    if not profile or not profile.get("experimental_alerts"):
        return False
    telegram = profile.get("telegram") or {}
    chat_id = telegram.get("chat_id")
    return bool(telegram.get("verified") and chat_id not in (None, ""))


def direction_event_id(user_id, symbol, interval, direction, version="e1-20261016"):
    """Unchanged direction is one event. A later candle is not a new alert."""
    return f"dir:{user_id}:{symbol}:{interval}:{version}:{direction}"


def _account_views():
    """Profiles and verified chat ids only. Password hashes are not copied."""
    try:
        from ops.users import list_users
        rows = list_users()
    except Exception:
        return []
    views = []
    for user in rows:
        profile = dict(user.get("profile") or {})
        telegram = user.get("telegram") or {}
        verified = bool(telegram.get("verified"))
        profile["telegram"] = {
            "verified": verified,
            "chat_id": telegram.get("chat_id") if verified else None,
        }
        views.append({"id": user.get("id"), "profile": profile})
    return views


DEFAULT_PREFS = {
    "assets": ["BTCUSDT", "ETHUSDT"],
    "interval": "15m",
    "quiet_hours_utc": [],
    "max_alerts_per_day": 24,
    "alerts_enabled": True,
    "experimental_alerts": False,
}


class Worker:
    def __init__(self, ledger, prefs_path: Path, experimental_path=None, shadow_path=None):
        self.ledger = ledger
        self.prefs_path = Path(prefs_path)
        self.book = ExperimentalBook(experimental_path or self.prefs_path.parent / "experimental.jsonl")
        self.shadow_path = shadow_path
        self.shadow = None
        self.shadow_loader = None
        self.last_beat_ms = 0
        self.last_monitor_ms = 0
        self.last_result = None
        self.last_monitor = None
        self.last_monitor_error = None
        self.last_cycle_error = None
        try:
            from ops.desk_pulse import reset

            reset()
        except Exception:
            pass

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
        from ops.files import update_json

        def apply(current):
            merged = dict(DEFAULT_PREFS)
            if isinstance(current, dict):
                merged.update({key: current[key] for key in DEFAULT_PREFS if key in current})
            for key in ("assets", "interval", "quiet_hours_utc", "max_alerts_per_day", "alerts_enabled", "experimental_alerts"):
                if key in (payload or {}):
                    merged[key] = payload[key]
            merged["assets"] = [item for item in merged.get("assets", []) if item in {"BTCUSDT", "ETHUSDT"}] or ["BTCUSDT"]
            if merged.get("interval") not in {"15m", "1h", "4h"}:
                merged["interval"] = "15m"
            merged["max_alerts_per_day"] = min(max(int(merged.get("max_alerts_per_day", 24)), 0), 48)
            merged["quiet_hours_utc"] = [hour for hour in merged.get("quiet_hours_utc") or [] if isinstance(hour, int) and 0 <= hour <= 23]
            return merged

        return update_json(self.prefs_path, apply, dict(DEFAULT_PREFS))

    def _seen(self, key: str) -> bool:
        return any(row.get("id") == key for row in self.ledger.read())

    def _alerts_today(self, now_ms: int) -> int:
        day = now_ms // 86_400_000
        count = 0
        for row in self.ledger.read():
            if row.get("type") != "notify" or row.get("rule") == "WAIT_DEFAULT":
                continue
            stamp = row.get("attempted_at_ms", row.get("ts_ms", 0)) or 0
            if stamp // 86_400_000 == day:
                count += 1
        return count

    def evaluate(self, now_ms: int | None = None, sender=send_alert) -> list[dict]:
        now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        self.last_beat_ms = now_ms
        try:
            from ops.activity import record
            record("worker_started", component="worker", entity="desk", detail={"note": "Worker loop reached an evaluation. This is not a market reading."}, now_ms=now_ms)
            record("worker_heartbeat", component="worker", entity="desk", detail={"note": "Heartbeat only. Not a market retrieval."}, now_ms=now_ms)
        except Exception:
            pass
        if PRODUCTION == "WAIT_DEFAULT":
            sender = None
        prefs = self.prefs()
        hour = time.gmtime(now_ms / 1000).tm_hour
        quiet = hour in set(prefs.get("quiet_hours_utc") or [])
        accounts = _account_views()
        out = []
        for symbol in prefs["assets"]:
            bar = fetch_last_closed(symbol, prefs["interval"], now_ms=now_ms)
            close_time = bar.get("close_time_ms")
            key = f"eval:{symbol}:{prefs['interval']}:{close_time or 'none'}"
            if self._seen(key):
                continue
            fresh = bool(bar.get("fresh"))
            if not fresh:
                try:
                    from ops.activity import record as record_event
                    record_event(
                        "reading_stale",
                        component="worker",
                        entity=f"{symbol}:{prefs['interval']}",
                        detail={"note": "No fresh completed candle. No price was stored.", "symbol": symbol, "interval": prefs["interval"]},
                        now_ms=now_ms,
                    )
                except Exception:
                    pass
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
            record["notification"] = {
                "status": "NOT_SENT",
                "delivered": False,
                "reason": authorize(
                    {
                        "state": "RESEARCH_OBSERVATION" if experimental else "WAIT",
                        "symbol": symbol,
                        "timeframe": prefs["interval"],
                        "strategy": "E1-donchian-20",
                        "version": "e1-20261016",
                        "fresh": fresh,
                        "complete": bool(fresh),
                    },
                    {"experimental_alerts": True, "telegram": {"verified": True, "chat_id": "blocked"}},
                    now_ms=now_ms,
                )["reason"],
            }
            self.ledger.append(record)
            over_cap = self._alerts_today(now_ms) >= int(prefs["max_alerts_per_day"])
            for user in accounts:
                profile = user["profile"]
                direction = (experimental or {}).get("result") or "WAIT"
                event = direction_event_id(user.get("id"), symbol, prefs["interval"], direction)
                allowed = may_send_observation(profile)
                if sender is None or not allowed or not prefs.get("alerts_enabled") or quiet or over_cap or self._seen(event):
                    continue
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
            out.append(record)
        self._write_shadow(now_ms)
        self.last_result = out[-1] if out else self.last_result
        return out

    def monitor(self, now_ms: int | None = None, windows=None) -> dict:
        """Same decision as the terminal. A WAIT is not an inbox card. No Telegram."""
        now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        self.last_monitor_ms = now_ms
        try:
            summary = self._monitor(now_ms, windows)
        except Exception as exc:
            self.last_monitor_error = type(exc).__name__
            summary = {"evaluated_at_ms": now_ms, "evaluations": [], "delivered": 0, "error": type(exc).__name__}
        self.last_monitor = summary
        return summary

    def _monitor(self, now_ms, windows):
        from ops.users import list_users

        if windows is None:
            windows = self._monitor_windows(now_ms)
        try:
            from ops.signal_engine import cycle, take_decisions

            cycle(now_ms, windows=windows)
            self.last_cycle_error = None
            decisions = take_decisions()
        except Exception as exc:
            self.last_cycle_error = type(exc).__name__
            decisions = {}
        for window in windows:
            shared = decisions.get((window.get("symbol"), window.get("interval")))
            if isinstance(shared, dict):
                window["engine_result"] = shared
        users = list_users()
        evaluations = []
        delivered = 0
        unchanged = 0
        for window in windows:
            symbol = window.get("symbol")
            interval = window.get("interval")
            try:
                from ops.desk_pulse import carried, same_bar

                if same_bar(window):
                    remembered = carried(window)
                    if remembered:
                        evaluations.append(remembered)
                        unchanged += 1
                        continue
                delivered += self._monitor_one(now_ms, window, users, evaluations)
            except Exception as exc:
                evaluations.append({
                    "symbol": symbol,
                    "interval": interval,
                    "decision": "DATA BLOCK",
                    "reason": type(exc).__name__,
                })
        return {"evaluated_at_ms": now_ms, "evaluations": evaluations, "delivered": delivered, "unchanged": unchanged, "error": None}

    def _monitor_one(self, now_ms, window, users, evaluations):
        from ops.inbox import append_event, deliver_evaluation, expire_stale
        from ops.paperbook import observe
        from ops.plan import observe_levels
        from ops.terminal_signal import apply_persona, decide

        symbol = window.get("symbol")
        interval = window.get("interval")
        bars = window.get("bars") or []
        delivered = 0
        try:
            from ops.customer_release import candles_released, reading_released
            from ops.signal_ledger import note_unavailable
            if not (candles_released(symbol, interval) or reading_released(symbol, interval)):
                note_unavailable(symbol, interval, window.get("reason") or window.get("blocked") or "reading_unavailable", now_ms)
        except Exception:
            pass
        if symbol == "XAUUSD" and interval in {"1m", "3m"} and not bars:
            reason = window.get("reason") or "missing_bars"
            evaluations.append({
                "symbol": symbol,
                "interval": interval,
                "decision": "DATA BLOCK",
                "reason": reason,
                "blocked": reason,
            })
            return 0
        from ops.data_rights import is_rights_reason
        rights_reason = window.get("reason") or window.get("blocked")
        if is_rights_reason(rights_reason) or window.get("rights_status") in {"rights_unconfirmed", "prohibited", "restricted", "fixture_only"}:
            evaluations.append({
                "symbol": symbol,
                "interval": interval,
                "decision": "RIGHTS",
                "blocked": "commercial_use_unverified",
                "reason": "commercial_use_unverified",
                "rights_status": window.get("rights_status") or "rights_unconfirmed",
            })
            return 0
        if not bars:
            evaluations.append({"symbol": symbol, "interval": interval, "decision": "DATA BLOCK", "reason": window.get("reason") or "missing_bars"})
            return 0
        shared = window.get("engine_result")
        if isinstance(shared, dict) and shared.get("decision"):
            result = dict(shared)
        else:
            result = decide(symbol, interval, "auto", bars, now_ms, None, live_quote=window.get("live_quote"))
        result["feed_state"] = window.get("feed_state") or "live"
        try:
            from ops.signal_engine import _higher

            result["higher_timeframe"] = result.get("higher_timeframe") or _higher(symbol, interval)
        except Exception:
            pass
        try:
            from ops.desk_pulse import publish

            publish(result, now_ms)
        except Exception:
            pass
        try:
            from ops.customer_release import candles_released, reading_released
            if candles_released(symbol, interval) or reading_released(symbol, interval):
                from ops.signal_ledger import record_observations
                record_observations([result], now_ms=now_ms, component="worker")
        except Exception:
            pass
        evaluations.append({
            "symbol": result.get("symbol"),
            "interval": result.get("interval"),
            "decision": result.get("decision_label") or result.get("decision"),
            "strategy": result.get("strategy"),
            "bar_close_ms": result.get("bar_close_ms"),
            "id": result.get("id") if result.get("id") else None,
            "blocked": result.get("blocked"),
        })
        if result.get("blocked") == "xau_minute_unlicensed":
            return 0
        last_bar = bars[-1]
        source = {
            "name": last_bar.get("provider") or "completed_candle",
            "bar_close_ms": last_bar.get("close_time_ms"),
            "quote": last_bar.get("quote_semantics"),
        }
        if result.get("decision") not in {"BUY", "SELL"} or result.get("entry") is None or result.get("stop") is None or result.get("target") is None:
            for user in users:
                expire_stale(user.get("id"), symbol, interval, now_ms)
                observe(user.get("id"), symbol, interval, last_bar, now_ms, source)
            return 0
        for user in users:
            personal = apply_persona(dict(result), user)
            if window.get("feed_state"):
                personal["feed_state"] = window.get("feed_state")
            outcome = deliver_evaluation(user.get("id"), user, personal)
            if outcome.get("stored"):
                delivered += 1
            observation = observe_levels(personal.get("decision"), personal.get("stop"), personal.get("target"), last_bar)
            if observation and outcome.get("opportunity_id"):
                append_event(user.get("id"), outcome.get("opportunity_id"), {
                    "id": f"evt:{outcome.get('opportunity_id')}:{observation['state']}:{result.get('bar_close_ms')}",
                    "state": observation["state"],
                    "note": observation["note"],
                    "created_ms": now_ms,
                    "source": source.get("name"),
                })
            observe(user.get("id"), symbol, interval, last_bar, now_ms, source)
            from ops.autopilot import consider
            account = dict(user)
            account["id"] = user.get("id")
            consider(account, personal, now_ms, outcome.get("opportunity_id"))
            expire_stale(user.get("id"), symbol, interval, now_ms, protect_bar_ms=result.get("bar_close_ms"))
        return delivered

    def _monitor_windows(self, now_ms):
        from ops.terminal_route import feed_state, load_crypto_bars, load_gold_ohlc

        windows = []
        for symbol, interval in COVERAGE:
            if symbol == "XAUUSD":
                gold = load_gold_ohlc(interval, now_ms)
                if isinstance(gold, tuple):
                    windows.append({
                        "symbol": symbol,
                        "interval": interval,
                        "bars": [],
                        "reason": gold[1],
                        "blocked": gold[1],
                        "live_quote": None,
                    })
                    continue
                windows.append({"symbol": symbol, "interval": interval, "bars": gold or [], "live_quote": None, "reason": None if gold else "missing_bars", "feed_state": feed_state(symbol, interval)})
                continue
            loaded = load_crypto_bars(symbol, interval, now_ms)
            if isinstance(loaded, tuple):
                windows.append({"symbol": symbol, "interval": interval, "bars": [], "reason": loaded[1]})
            else:
                windows.append({"symbol": symbol, "interval": interval, "bars": loaded or [], "feed_state": feed_state(symbol, interval)})
        return windows

    def _shadow_book(self):
        if not shadow_enabled():
            return None
        if self.shadow is None:
            from ops.shadow import ShadowLedger

            self.shadow = ShadowLedger(self.shadow_path)
        return self.shadow

    def _write_shadow(self, now_ms):
        book = self._shadow_book()
        if book is None:
            return []
        from ops.shadow_bridge import load_live_windows, observe_prospective

        loader = self.shadow_loader or load_live_windows
        return observe_prospective(book, now_ms, loader)

    def status(self) -> dict:
        return {
            "last_beat_ms": self.last_beat_ms,
            "last_result": self.last_result,
            "last_monitor_ms": getattr(self, "last_monitor_ms", 0),
            "last_monitor": self.last_monitor,
            "last_monitor_error": self.last_monitor_error,
            "prefs": self.prefs(),
        }
