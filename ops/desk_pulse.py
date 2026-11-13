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
_SEEN = None
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
    "price",
    "blocked",
    "strategy",
    "source_name",
    "feed_state",
    "runtime_status",
    "higher_timeframe",
    "snapshot_id",
)


def _path():
    root = os.environ.get("AUREON_DATA", "").strip() or "data"
    return Path(root) / "canonical" / "readings.json"


def _stamp(path):
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_size, digest)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema": SCHEMA, "readings": [dict(row) for row in _READINGS.values()]}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    global _SEEN
    _SEEN = _stamp(path)


def load():
    """Reload when the file changes. An unchanged file does not wipe a newer memory row."""
    path = _path()
    for _attempt in range(2):
        if not path.is_file():
            return False
        try:
            stamp = _stamp(path)
            body = json.loads(path.read_text(encoding="utf-8"))
            if _stamp(path) != stamp:
                continue
        except (OSError, ValueError):
            return False
        if not isinstance(body, dict) or body.get("schema") != SCHEMA:
            return False
        rows = body.get("readings")
        if not isinstance(rows, list):
            return False
        global _REVISION, _SEEN
        with _LOCK:
            try:
                current = _stamp(path) if path.is_file() else None
            except OSError:
                return bool(_READINGS)
            if current != stamp:
                continue
            if stamp == _SEEN and _READINGS:
                return True
            _READINGS.clear()
            for row in rows:
                if not isinstance(row, dict) or not row.get("symbol") or not row.get("interval"):
                    continue
                stored = {key: row.get(key) for key in _FIELDS}
                stored["evaluated_at_ms"] = row.get("evaluated_at_ms")
                if stored.get("price") is None:
                    stored["price"] = stored.get("reference_price")
                _READINGS[(row["symbol"], row["interval"])] = stored
            _REVISION = len(_READINGS)
            _SEEN = stamp
            return bool(_READINGS)
    return bool(_READINGS)


def bind():
    """Use the current data directory. A restart reloads the file. A test directory starts empty."""
    global _REVISION, _SEEN
    with _LOCK:
        _READINGS.clear()
        _REVISION = 0
        _SEEN = None
    if _path().is_file():
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
    if row.get("price") is None:
        row["price"] = row.get("reference_price")
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


def project_markets(body):
    """Replace a page's market rows with the stored candle when that pair is released."""
    if not isinstance(body, dict):
        return body
    markets = body.get("markets")
    if not isinstance(markets, list):
        return body
    from ops.customer_release import reading_released

    shown = []
    for item in markets:
        if not isinstance(item, dict):
            shown.append(item)
            continue
        symbol = item.get("symbol") or item.get("instrument")
        interval = item.get("interval") or item.get("timeframe")
        stored = get(symbol, interval) if symbol and interval else None
        if not stored or not stored.get("snapshot_id") or not reading_released(symbol, interval):
            shown.append(item)
            continue
        row = dict(item)
        decision = stored.get("decision_label") or stored.get("decision")
        price = stored.get("reference_price")
        if price is None:
            price = stored.get("price")
        row["snapshot_id"] = stored.get("snapshot_id")
        row["bar_close_ms"] = stored.get("bar_close_ms")
        row["decision"] = stored.get("decision")
        row["decision_label"] = decision
        row["entry"] = stored.get("entry")
        row["stop"] = stored.get("stop")
        row["target"] = stored.get("target")
        row["source"] = "canonical"
        data = dict(row.get("data") or {})
        data["bar_close_ms"] = stored.get("bar_close_ms")
        data["timeframe"] = interval
        if price is not None:
            row["price"] = price
            row["close"] = price
            row["reference_price"] = stored.get("reference_price")
            data["price"] = price
            data["close"] = price
        row["data"] = data
        shown.append(row)
    body = dict(body)
    body["markets"] = shown
    return body


def reset():
    """Test isolation. Production does not call this."""
    global _REVISION, _SEEN
    with _LOCK:
        _READINGS.clear()
        _REVISION = 0
        _SEEN = None
        path = _path()
    if path.exists():
        path.unlink()
