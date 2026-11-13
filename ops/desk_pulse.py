"""The latest closed-candle reading for each market.

The worker publishes a reading when a candle closes. Pages read this
instead of deciding the same candle again. Nothing here is a tick, a
broker fill, or another account's record.
"""

import threading

_LOCK = threading.Lock()
_READINGS = {}
_REVISION = 0

_FIELDS = (
    "symbol",
    "interval",
    "decision",
    "decision_label",
    "entry",
    "stop",
    "target",
    "reward_risk",
    "bar_close_ms",
    "fresh",
    "reference_price",
    "blocked",
    "strategy",
    "source_name",
    "feed_state",
    "runtime_status",
)


def publish(result, now_ms):
    """Store one market reading. A repeated close does not advance the revision."""
    global _REVISION
    result = result or {}
    symbol = result.get("symbol")
    interval = result.get("interval")
    close_ms = result.get("bar_close_ms")
    if not symbol or not interval or close_ms is None:
        return False
    row = {key: result.get(key) for key in _FIELDS}
    row["evaluated_at_ms"] = int(now_ms)
    key = (symbol, interval)
    with _LOCK:
        previous = _READINGS.get(key)
        if previous and previous.get("bar_close_ms") == close_ms and previous.get("feed_state") == row.get("feed_state"):
            return False
        _READINGS[key] = row
        _REVISION += 1
    return True


def same_bar(window):
    window = window or {}
    bars = window.get("bars") or []
    if not bars or not isinstance(bars[-1], dict):
        return False
    close_ms = bars[-1].get("close_time_ms")
    if close_ms is None:
        return False
    key = (window.get("symbol"), window.get("interval"))
    with _LOCK:
        previous = _READINGS.get(key)
    if not previous:
        return False
    return previous.get("bar_close_ms") == close_ms and previous.get("feed_state") == (window.get("feed_state") or "live")


def carried(window):
    key = ((window or {}).get("symbol"), (window or {}).get("interval"))
    with _LOCK:
        row = dict(_READINGS.get(key) or {})
    if not row:
        return None
    return {
        "symbol": row.get("symbol"),
        "interval": row.get("interval"),
        "decision": row.get("decision_label") or row.get("decision"),
        "strategy": row.get("strategy"),
        "bar_close_ms": row.get("bar_close_ms"),
        "id": None,
        "blocked": row.get("blocked"),
        "carried": True,
    }


def account_view(user):
    """This account's markets only. The persona is applied here, not stored."""
    from ops.inbox import inbox_settings
    from ops.terminal_signal import apply_persona, explain_reading

    settings = inbox_settings(user)
    with _LOCK:
        revision = _REVISION
        rows = [dict(row) for row in _READINGS.values()]
    shown = []
    for row in rows:
        if row.get("symbol") not in settings["markets"] or row.get("interval") not in settings["timeframes"]:
            continue
        personal = apply_persona(dict(row), user or {})
        personal["explanation"] = explain_reading(personal, user or {})
        shown.append({
            "symbol": personal.get("symbol"),
            "interval": personal.get("interval"),
            "decision": personal.get("decision"),
            "decision_label": personal.get("decision_label") or personal.get("decision"),
            "entry": personal.get("entry"),
            "stop": personal.get("stop"),
            "target": personal.get("target"),
            "reward_risk": personal.get("reward_risk"),
            "bar_close_ms": personal.get("bar_close_ms"),
            "fresh": personal.get("fresh"),
            "feed_state": personal.get("feed_state") or "live",
            "persona_release": personal.get("persona_release"),
            "explanation": personal.get("explanation"),
            "evaluated_at_ms": row.get("evaluated_at_ms"),
        })
    shown.sort(key=lambda item: (item.get("symbol") or "", item.get("interval") or ""))
    return {
        "revision": revision,
        "readings": shown,
        "broker": False,
        "paper_only": True,
    }


def reset():
    """Test isolation. Production does not call this."""
    global _REVISION
    with _LOCK:
        _READINGS.clear()
        _REVISION = 0
