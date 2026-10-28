"""Shared signal history. Personal money stays out of this file. Telegram is not called."""

import json
import os
from pathlib import Path

from ops.engine_eval import evaluate_snapshot
from ops.registry import BY_ID
from ops.scanner import _view_state


def _path():
    root = Path(os.environ.get("AUREON_DATA", "data"))
    return root / "paper" / "signal_ledger.jsonl"


def read_events():
    path = _path()
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def remember(event):
    event_id = str(event.get("id") or "")
    if not event_id:
        return {"ok": False, "reason": "missing_id", "stored": False}
    rows = read_events()
    if any(row.get("id") == event_id for row in rows):
        return {"ok": True, "duplicate": True, "stored": False}
    approved = bool(event.get("approved")) and event.get("state") == "APPROVED_SIGNAL"
    if not approved:
        approved = False
    stored = {
        "id": event_id,
        "source": event.get("source") if event.get("source") in {"live", "historical_replay"} else "live",
        "symbol": event.get("symbol"),
        "interval": event.get("interval"),
        "strategy": event.get("strategy"),
        "version": event.get("version"),
        "state": "APPROVED_SIGNAL" if approved else event.get("state") or "WAIT",
        "scanner_state": event.get("scanner_state") or _view_state(event.get("state") or "WAIT"),
        "direction": event.get("direction") or "WAIT",
        "bar_close_ms": event.get("bar_close_ms"),
        "message": event.get("message"),
        "approved": approved,
        "delivered": False,
        "filled": False,
        "pnl": None,
    }
    if stored["scanner_state"] == "APPROVED_SIGNAL" and not approved:
        stored["scanner_state"] = "SETUP_WATCH"
        stored["state"] = "RESEARCH_OBSERVATION"
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(stored) + "\n")
    return {"ok": True, "duplicate": False, "stored": True}


def remember_live(body):
    stored = []
    for row in body.get("markets") or []:
        close_ms = row.get("updated_at_ms") or 0
        state = row.get("scanner_state") or "BLOCKED"
        stored.append(remember({
            "id": row.get("event_id") or f"{state}:{row.get('symbol')}:{close_ms}",
            "source": "live",
            "symbol": row.get("symbol"),
            "interval": row.get("interval"),
            "strategy": row.get("rule"),
            "version": row.get("version"),
            "state": row.get("state"),
            "scanner_state": state,
            "direction": row.get("direction"),
            "bar_close_ms": close_ms,
            "message": row.get("message"),
            "approved": False,
        }))
    return stored


def replay(symbol, bars, higher, now_ms):
    """Walk completed bars. A later bar is not visible when an earlier one is judged."""
    saved = []
    if len(bars) < 41:
        return saved
    for index in range(40, len(bars) - 1):
        past = bars[: index + 1]
        upper = [bar for bar in higher if bar["open_time_ms"] <= past[-1]["open_time_ms"]]
        if len(upper) < 20:
            upper = past[-25:]
        moment = past[-1]["close_time_ms"] + 1
        if moment > now_ms:
            break
        for row in evaluate_snapshot(symbol, past, upper, moment, past[-1]["interval"]):
            if row.get("state") in {"WAIT", "DATA_UNAVAILABLE"}:
                continue
            spec = BY_ID.get(row.get("strategy")) or {}
            if spec.get("research_status") in {"FAIL", "BLOCKED"}:
                row = {**row, "state": "RESEARCH_OBSERVATION", "approved": False}
            result = remember({
                "id": row.get("event_id") or f"replay:{symbol}:{past[-1]['open_time_ms']}:{row.get('strategy')}",
                "source": "historical_replay",
                "symbol": symbol,
                "interval": past[-1]["interval"],
                "strategy": row.get("strategy"),
                "version": row.get("version"),
                "state": row.get("state"),
                "direction": row.get("direction"),
                "bar_close_ms": past[-1]["close_time_ms"],
                "message": row.get("reason"),
                "approved": False,
            })
            saved.append(result)
    return saved
