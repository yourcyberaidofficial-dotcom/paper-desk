"""The latest closed-candle reading for each market.

The worker publishes a reading when a candle closes. Pages read this
instead of deciding the same candle again. The record is also written
under $AUREON_DATA so a restart does not blank the desk.
"""

import hashlib
import json
import os
import threading
from pathlib import Path

_LOCK = threading.Lock()
_READINGS = {}
_REVISION = 0
SCHEMA = 1

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
    "higher_timeframe",
    "snapshot_id",
)


def _path():
    root = os.environ.get("AUREON_DATA", "").strip()
    if not root:
        return None
    return Path(root) / "canonical" / "readings.json"


def _snapshot_id(row):
    identity = "|".join([
        str(row.get("symbol") or ""),
        str(row.get("interval") or ""),
        str(row.get("bar_close_ms") or ""),
        str(row.get("decision") or ""),
        str(row.get("feed_state") or ""),
    ])
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def _save():
    path = _path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema": SCHEMA, "readings": [dict(row) for row in _READINGS.values()]}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def load():
    """Fill an empty memory from disk. A restart calls this before the next close."""
    path = _path()
    if path is None or not path.is_file():
        return False
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        return False
    rows = body.get("readings")
    if not isinstance(rows, list):
        return False
    global _REVISION
    with _LOCK:
        if _READINGS:
            return False
        for row in rows:
            if not isinstance(row, dict) or not row.get("symbol") or not row.get("interval"):
                continue
            _READINGS[(row["symbol"], row["interval"])] = {key: row.get(key) for key in _FIELDS}
            _READINGS[(row["symbol"], row["interval"])]["evaluated_at_ms"] = row.get("evaluated_at_ms")
        _REVISION = len(_READINGS)
    return bool(_READINGS)


def bind():
    """Use the current data directory. A restart reloads the file. A test directory starts empty."""
    global _REVISION
    with _LOCK:
        _READINGS.clear()
        _REVISION = 0
    if _path() is not None:
        load()


def get(symbol, interval):
    load()
    with _LOCK:
        row = _READINGS.get((symbol, interval))
        return dict(row) if row else None


def latest(symbol):
    load()
    with _LOCK:
        rows = [dict(row) for row in _READINGS.values() if row.get("symbol") == symbol and row.get("interval") not in {"1m", "3m"}]
    if not rows:
        return None
    rows.sort(key=lambda item: int(item.get("bar_close_ms") or 0), reverse=True)
    return rows[0]


def health_label(row, now_ms):
    """live, cached, market_closed, or feed_down. A closed gold market is not a dead feed."""
    if not row:
        return "feed_down"
    if row.get("symbol") == "XAUUSD":
        from datetime import datetime, timezone
        from ops.sessions import gold_market_open

        if not gold_market_open(datetime.fromtimestamp(int(now_ms) / 1000, timezone.utc)):
            return "market_closed"
    state = row.get("feed_state") or "live"
    if state == "last_good":
        return "cached"
    if state in {"down", "feed_down"}:
        return "feed_down"
    return "live"


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
    row["snapshot_id"] = result.get("snapshot_id") or _snapshot_id(row)
    row["schema"] = SCHEMA
    key = (symbol, interval)
    with _LOCK:
        previous = _READINGS.get(key)
        if previous and int(previous.get("bar_close_ms") or 0) > int(close_ms):
            return False
        if previous and previous.get("bar_close_ms") == close_ms and previous.get("feed_state") == row.get("feed_state"):
            return False
        _READINGS[key] = row
        _REVISION += 1
        _save()
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
    load()
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
            "snapshot_id": row.get("snapshot_id"),
            "fresh": personal.get("fresh"),
            "feed_state": personal.get("feed_state") or "live",
            "persona_release": personal.get("persona_release"),
            "explanation": personal.get("explanation"),
            "higher_timeframe": personal.get("higher_timeframe"),
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
        path = _path()
    if path is not None and path.exists():
        path.unlink()
