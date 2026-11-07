"""Recorded strategy status and a supplied-bar evaluation.

Thresholds are not changed. This module cannot promote a strategy.
"""

from __future__ import annotations

import json
from pathlib import Path

from ops.qualification import MIN_COMPLETED_TRADES, catalog
from ops.signal_pipeline import STRATEGY_ID, STRATEGY_VERSION, SignalBook


def registry_finding():
    body = catalog()
    failed = [row for row in body["strategies"] if row["lifecycle"] == "backtest_failed"]
    small = [row for row in body["strategies"] if row["lifecycle"] == "insufficient_data"]
    return {
        "strategies": len(body["strategies"]),
        "failed": len(failed),
        "insufficient": len(small),
        "approved_for_paper": body["approved_for_paper"],
        "minimum_trades_for_approval": MIN_COMPLETED_TRADES,
        "thresholds_changed": False,
        "failed_ids": [row["id"] for row in failed],
        "insufficient_ids": [row["id"] for row in small],
        "autopilot": "blocked",
        "note": "No stored result was rewritten. An unapproved rule can still be recorded as a research observation.",
    }


def evaluate_supplied(candles, *, symbol, interval, now_ms, root: Path, rights="approved"):
    """Run the observation rule on candles the caller supplied. Approval stays false."""
    book = SignalBook(root)
    result = book.evaluate(candles, symbol=symbol, interval=interval, now_ms=now_ms, rights=rights)
    evidence = {
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "symbol": symbol,
        "interval": interval,
        "lifecycle": result["row"]["lifecycle"],
        "signal": result["row"]["signal"],
        "approved_for_paper": False,
        "promoted": False,
        "cost_model": {"transaction_cost_bps_per_side": 11, "adverse_slippage_bps": 2},
        "out_of_sample": "not_run",
        "paper_forward": "not_run",
        "minimum_trades_for_approval": MIN_COMPLETED_TRADES,
        "completed_trades": 0,
        "thresholds_changed": False,
    }
    path = Path(root) / "evaluation.json"
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    evidence["row"] = result["row"]
    return evidence
