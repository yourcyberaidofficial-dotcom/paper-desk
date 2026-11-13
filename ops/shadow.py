"""Shadow observations. Not a portfolio, not an alert, not a promotion.

Rows live in their own file. They are not the paper ledger and they do not
touch user profiles. WAIT_DEFAULT cannot be written as an approved signal.
"""

import json
from pathlib import Path

from ops.worker import PRODUCTION

STATES = frozenset({
    "DATA_UNAVAILABLE",
    "WAIT",
    "RESEARCH_OBSERVATION",
    "PAPER_CANDIDATE",
    "APPROVED_SIGNAL",
})
SOURCE_KINDS = frozenset({"historical_replay", "prospective", "unavailable"})
FORBIDDEN = frozenset({"paper_open", "paper_close", "fill", "order", "holding"})
REQUIRED = (
    "observed_at_ms",
    "symbol",
    "timeframe",
    "source",
    "strategy_version",
    "config_sha256",
    "quality",
    "event_id",
)


def default_path():
    from ops.paths import shadow_observations_path

    return shadow_observations_path()


class ShadowLedger:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seen = {row["event_id"] for row in self.read() if row.get("event_id")}

    def read(self):
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def append(self, event):
        row = dict(event or {})
        if row.get("type") in FORBIDDEN or row.get("state") in FORBIDDEN:
            raise ValueError("shadow_refuses_trade_row")
        row.pop("sender", None)
        row.pop("chat_id", None)
        row.pop("token", None)
        for key in REQUIRED:
            if row.get(key) in (None, ""):
                raise ValueError(f"missing:{key}")
        source_kind = row.get("source_kind")
        if source_kind not in SOURCE_KINDS:
            raise ValueError("bad_source_kind")
        state = row.get("state")
        if state not in STATES:
            raise ValueError("bad_state")
        if state == "APPROVED_SIGNAL" or PRODUCTION == "WAIT_DEFAULT" and row.get("attempted_state") == "APPROVED_SIGNAL":
            if state == "APPROVED_SIGNAL":
                row["attempted_state"] = "APPROVED_SIGNAL"
                row["state"] = "WAIT"
                row["reason"] = "not_approved"
        if source_kind == "prospective" and not row.get("fresh"):
            row["state"] = "DATA_UNAVAILABLE"
            row["source_kind"] = "unavailable"
            row["reason"] = "stale_or_not_live"
            row["quality"] = "stale"
        row["production"] = PRODUCTION
        row["broker"] = False
        row["telegram"] = "NOT_CALLED"
        row["approved"] = False
        event_id = row["event_id"]
        if event_id in self.seen:
            return {"duplicate": True, "event_id": event_id}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        self.seen.add(event_id)
        return row


def observe_setup(ledger, *, symbol, timeframe, bars, index, higher, strategy, setup_fn, source, source_kind, now_ms, config_sha256, fresh):
    """One completed bar. The same setup on a later call is the same event."""
    if not bars:
        return ledger.append({
            "observed_at_ms": now_ms,
            "symbol": symbol,
            "timeframe": timeframe,
            "source": source,
            "source_kind": "unavailable" if source_kind == "prospective" else source_kind,
            "strategy_version": strategy,
            "config_sha256": config_sha256,
            "quality": "missing",
            "fresh": False,
            "state": "DATA_UNAVAILABLE",
            "reason": "no_bars",
            "event_id": f"{strategy}:{symbol}:{timeframe}:NONE:no_bars",
        })
    bar = bars[index]
    setup = setup_fn(bars, index, higher, symbol)
    rejected = isinstance(setup, dict) and setup.get("rejected")
    if not setup or rejected or setup.get("benchmark_failed"):
        state = "RESEARCH_OBSERVATION" if isinstance(setup, dict) and setup.get("benchmark_failed") else "WAIT"
        reason = "benchmark_failed" if state == "RESEARCH_OBSERVATION" else (rejected or "no_setup")
        direction = "NONE"
        anchor = bar["open_time_ms"]
    else:
        state = "PAPER_CANDIDATE"
        reason = "setup_seen_not_an_order"
        direction = setup["direction"]
        anchor = setup["anchor_open_ms"]
    quality = "fresh" if fresh and source_kind == "prospective" else "historical_or_unconfirmed"
    return ledger.append({
        "observed_at_ms": now_ms,
        "symbol": symbol,
        "timeframe": timeframe,
        "source": source,
        "source_kind": source_kind,
        "strategy_version": strategy,
        "config_sha256": config_sha256,
        "quality": quality,
        "fresh": bool(fresh) and source_kind == "prospective",
        "state": state,
        "reason": reason,
        "event_id": f"{strategy}:{symbol}:{timeframe}:{direction}:{anchor}",
        "anchor_open_ms": anchor,
    })
