"""Strategy lifecycle from the recorded registry. This module does not rescore or approve."""

COST_MODEL = {
    "transaction_cost_bps_per_side": 11,
    "adverse_slippage_bps": 2,
    "meaning": "Paper-book assumptions. Not an observed exchange fee and not a broker fill.",
    "double_count": False,
}

# A Wilson interval around a win rate is too wide to support approval below this count.
# The threshold explains insufficient samples. It is not used to change a stored result.
MIN_COMPLETED_TRADES = 30

LIFECYCLES = (
    "research_only",
    "insufficient_data",
    "backtest_failed",
    "out_of_sample_pending",
    "out_of_sample_passed",
    "paper_forward",
    "approved_for_paper",
    "suspended",
    "retired",
)


def _lifecycle(row):
    status = row.get("research_status")
    evidence = (row.get("evidence") or "").lower()
    if status == "FAIL":
        return "backtest_failed", True
    if status == "BLOCKED":
        small = any(phrase in evidence for phrase in ("too small", "too few", "not opened", "no sample"))
        return "insufficient_data", not small
    if status == "PASS" and row.get("promoted") is True:
        return "approved_for_paper", False
    return "research_only", False


def record(row):
    """One immutable reading of a registry row. Approval stays false unless the row is already promoted."""
    row = row or {}
    lifecycle, further = _lifecycle(row)
    promoted = bool(row.get("promoted")) and lifecycle == "approved_for_paper"
    if not promoted:
        lifecycle = lifecycle if lifecycle != "approved_for_paper" else "research_only"
    return {
        "id": row.get("id"),
        "version": row.get("version"),
        "name": row.get("name"),
        "hypothesis": row.get("entry"),
        "entry": row.get("entry"),
        "invalidation": row.get("invalidation"),
        "instruments": list(row.get("instruments") or []),
        "timeframe": row.get("timeframe"),
        "research_status": row.get("research_status"),
        "lifecycle": lifecycle,
        "evidence": row.get("evidence"),
        "failure_reason": None if lifecycle == "approved_for_paper" else row.get("evidence"),
        "eligible_for_further_research": bool(further) and not promoted,
        "promoted": promoted,
        "approved_for_paper": promoted,
        "paper_approval_is_not_broker_approval": True,
        "holdout_opened": False,
        "cost_model": dict(COST_MODEL),
        "minimum_trades_for_approval": MIN_COMPLETED_TRADES,
        "live": bool(row.get("live")),
    }


def catalog():
    from ops.registry import STRATEGIES

    rows = [record(row) for row in STRATEGIES]
    counts = {name: 0 for name in LIFECYCLES}
    for row in rows:
        counts[row["lifecycle"]] = counts.get(row["lifecycle"], 0) + 1
    return {
        "strategies": rows,
        "approved_for_paper": sum(1 for row in rows if row["approved_for_paper"]),
        "by_lifecycle": counts,
        "selection_bias": "A strategy is not approved because it was the least-bad rank in a compared set.",
        "note": "No registered strategy is approved for paper promotion. Research observations stay research. AutoPilot will not open an order from an unapproved rule.",
    }


def summary():
    body = catalog()
    return {
        "approved_for_paper": body["approved_for_paper"],
        "by_lifecycle": body["by_lifecycle"],
        "note": body["note"],
    }


def find(strategy_id):
    for row in catalog()["strategies"]:
        if row["id"] == strategy_id or row["version"] == strategy_id or row["name"] == strategy_id:
            return row
    return None


def autopilot_may_open(result):
    """A promoted research version may open. So may a completed experimental paper plan on a released public candle."""
    result = result or {}
    if result.get("approved") is True:
        version = result.get("version")
        identity = result.get("strategy_id") or result.get("strategy")
        row = find(identity) or find(version)
        if row and row["approved_for_paper"] and (row["version"] == version or row["id"] == identity):
            return True
    if result.get("runtime_status") != "experimental":
        return False
    if result.get("blocked") or result.get("decision") not in {"BUY", "SELL"}:
        return False
    if result.get("entry") is None or result.get("stop") is None or result.get("target") is None:
        return False
    from ops.customer_release import opportunity_released

    return opportunity_released(result.get("symbol"), result.get("interval"))


def evidence_chain(reading):
    """The decision path. No confidence percentage is invented."""
    reading = reading or {}
    actionable = reading.get("entry") is not None and reading.get("decision") in {"BUY", "SELL"} and not reading.get("blocked")
    return {
        "data_source": reading.get("source_name") or reading.get("quote") or reading.get("source"),
        "instrument": reading.get("symbol"),
        "timeframe": reading.get("interval"),
        "completed_candle_ms": reading.get("bar_close_ms"),
        "observation": reading.get("decision_label") or reading.get("runtime_status") or reading.get("decision"),
        "strategy_version": reading.get("version") or reading.get("strategy"),
        "trigger": reading.get("reason"),
        "invalidation": reading.get("invalidation"),
        "reward_risk": reading.get("reward_risk") if actionable else None,
        "validation_status": reading.get("validation_status") or reading.get("runtime_status"),
        "persona": reading.get("persona_name"),
        "account_permission": (reading.get("paper") or {}).get("reason") if isinstance(reading.get("paper"), dict) else None,
        "decision": reading.get("decision"),
        "approved": reading.get("approved") is True,
        "calibrated_probability": None,
    }
