"""Append-only system events.

A blocked notification does not remove an event. Heartbeats are recorded
at most once every five minutes so the log stays a record of state changes,
not a second price feed. The file itself is not trimmed.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path

TYPES = frozenset({
    "worker_started",
    "worker_heartbeat",
    "source_unavailable",
    "source_retrieved",
    "reading_stale",
    "signal_created",
    "signal_updated",
    "signal_invalidated",
    "signal_expired",
    "research_recorded",
    "strategy_rejected",
    "strategy_approved",
    "paper_plan_created",
    "paper_opened",
    "paper_closed",
    "risk_rejected",
    "ollama_status",
    "ai_inference",
})

THROTTLED = {
    "worker_heartbeat": 300_000,
    "source_unavailable": 900_000,
    "reading_stale": 900_000,
    "ollama_status": 900_000,
}

ONCE = frozenset({"worker_started"})


def _path():
    root = Path(os.environ.get("AUREON_DATA") or "data")
    return root / "activity" / "events.jsonl"


def _rows():
    path = _path()
    if not path.is_file():
        return []
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            found.append(row)
    return found


def _exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = (path.parent / (path.name + ".lock")).open("a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def record(event_type, *, entity=None, component=None, account_id=None, detail=None, now_ms=None):
    """Append one event. Unknown types are refused. Nothing already stored is rewritten."""
    if event_type not in TYPES:
        return {"stored": False, "reason": "unknown_event"}
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    path = _path()
    lock = _exclusive(path)
    try:
        if event_type in ONCE or event_type in THROTTLED:
            window = THROTTLED.get(event_type)
            for row in reversed(_rows()):
                if row.get("event_type") != event_type or row.get("entity") != entity:
                    continue
                if event_type in ONCE or now_ms - int(row.get("created_ms") or 0) < window:
                    return {"stored": False, "reason": "already_recorded", "event": row}
                break
        payload = detail if isinstance(detail, dict) else ({"note": str(detail)} if detail else {})
        row = {
            "event_type": event_type,
            "entity": entity,
            "component": component or "desk",
            "account_id": account_id,
            "detail": payload,
            "created_ms": now_ms,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            handle.flush()
        return {"stored": True, "event": row}
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def read(*, account_id=None):
    """Every stored event. Account-scoped reads also keep system events with no account."""
    rows = _rows()
    if account_id is None:
        return rows
    return [row for row in rows if row.get("account_id") in {None, account_id}]
