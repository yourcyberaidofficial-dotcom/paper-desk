"""Append-only observation history.

A failed study does not delete an earlier row. The file is never rewritten
or trimmed. A data-unavailable row is not a signal and carries no price.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ops.signal_continuity import OBSERVATIONS, classify_card

FIELDS = (
    "symbol",
    "interval",
    "observation",
    "research",
    "execution",
    "decision",
    "opportunity_id",
    "source_id",
    "note",
)
NUMBERS = ("price", "entry", "stop", "target")
SIGNAL_STATES = frozenset({"forming", "active_signal", "invalidated", "expired"})


def _path():
    root = Path(os.environ.get("AUREON_DATA") or "data")
    return root / "signals" / "history.jsonl"


def read():
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


def _identity(row):
    return "|".join(str(row.get(key) or "") for key in ("symbol", "interval", "observation", "research", "execution", "opportunity_id"))


def _project(card):
    released = card.get("observation") != "data_unavailable"
    row = {key: card.get(key) for key in FIELDS}
    for key in NUMBERS:
        row[key] = card.get(key) if released else None
    row["signal"] = card.get("observation") in SIGNAL_STATES and released
    return row


def _classified(card):
    card = card or {}
    if card.get("observation") in OBSERVATIONS and card.get("research") and card.get("execution"):
        return card
    return classify_card(card)


def _activity(row, component, now_ms):
    from ops.activity import record

    entity = row.get("opportunity_id") or f"{row.get('symbol')}:{row.get('interval')}:{row.get('observation')}"
    detail = {
        "note": row.get("note") or "Observation recorded. Not an order.",
        "symbol": row.get("symbol"),
        "interval": row.get("interval"),
        "observation": row.get("observation"),
    }
    kind = {
        "data_unavailable": "source_unavailable",
        "invalidated": "signal_invalidated",
        "expired": "signal_expired",
        "forming": "signal_created",
        "active_signal": "signal_created",
        "market_observation": "source_retrieved",
    }.get(row.get("observation"))
    if not kind:
        return
    if kind == "signal_created" and row.get("opportunity_id"):
        earlier = [
            item for item in read()
            if item.get("opportunity_id") == row.get("opportunity_id")
            and item.get("signal") is True
            and item.get("created_ms") != row.get("created_ms")
        ]
        if earlier:
            kind = "signal_updated"
    record(kind, entity=entity, component=component, detail=detail, now_ms=now_ms)
    if row.get("research") == "research_failed":
        record(
            "research_recorded",
            entity=entity,
            component=component,
            detail={
                "note": "Research did not pass. The observation was not removed.",
                "symbol": row.get("symbol"),
                "interval": row.get("interval"),
                "observation": row.get("observation"),
            },
            now_ms=now_ms,
        )
    elif row.get("research") == "approved":
        record(
            "strategy_approved",
            entity=entity,
            component=component,
            detail={
                "note": "The stored research status is approved. This event does not place an order.",
                "symbol": row.get("symbol"),
                "interval": row.get("interval"),
            },
            now_ms=now_ms,
        )


def record_observations(cards, *, now_ms=None, component="lifecycle"):
    """Store each new identity once. Existing rows are left untouched."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    seen = {_identity(row) for row in read()}
    stored = []
    path = _path()
    for raw in cards or []:
        row = _project(_classified(raw))
        if row.get("observation") not in OBSERVATIONS:
            row["observation"] = "data_unavailable"
            row["signal"] = False
            for key in NUMBERS:
                row[key] = None
        ident = _identity(row)
        if ident in seen:
            continue
        row["created_ms"] = now_ms
        row["component"] = component
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        seen.add(ident)
        stored.append(row)
        try:
            _activity(row, component, now_ms)
        except Exception:
            pass
    return {"stored": len(stored), "rows": stored, "truncated": False}


def note_unavailable(symbol, interval, reason, now_ms, component="worker"):
    """Record that this pair could not be shown. Does not invent a price or a signal."""
    return record_observations(
        [{
            "symbol": symbol,
            "interval": interval,
            "customer_status": "reading_unavailable",
            "quality": "unavailable",
            "reading_class": "unavailable",
            "blocked": reason,
            "price": None,
            "entry": None,
            "stop": None,
            "target": None,
        }],
        now_ms=now_ms,
        component=component,
    )
