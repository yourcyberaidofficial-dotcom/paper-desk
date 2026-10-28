"""Validation-only selection. Holdout rows are ignored."""

from ops.hypotheses import GATES, GOLD_COST


def judge(summary, halves_summary, symbol, measured_bid_ask=None):
    trades = summary.get("trades") or 0
    blocked = []
    failed = []
    if trades < GATES["min_trades"]:
        blocked.append("sample")
    else:
        if not (summary.get("base_mean") is not None and summary["base_mean"] > 0 and summary.get("stress_mean", 0) > 0):
            failed.append("expectancy")
        lower = summary.get("normal_95_lower")
        if lower is None or not (lower > 0):
            failed.append("uncertainty")
        if summary.get("equity", 0) <= 1:
            failed.append("flat")
        if summary.get("max_drawdown", 1) > GATES["max_drawdown"]:
            failed.append("drawdown")
        if summary.get("worst_loss_streak", 99) > GATES["max_loss_streak"]:
            failed.append("streak")
    for name in ("first", "second"):
        part = halves_summary.get(name) or {}
        if (part.get("trades") or 0) < GATES["min_half_trades"]:
            blocked.append(f"half_{name}")
        elif not (part.get("base_mean") is not None and part["base_mean"] > 0):
            failed.append(f"half_{name}")
    measured = GOLD_COST["measured_bid_ask"] if measured_bid_ask is None else measured_bid_ask
    if symbol == "XAUUSD" and not measured:
        blocked.append("no_measured_bid_ask")
    if failed:
        return "FAIL", failed, blocked
    if blocked:
        return "BLOCKED", failed, blocked
    return "PASS", failed, blocked


def select_candidate(rows):
    """At most one validation PASS per instrument. Other splits cannot win."""
    chosen = {}
    for row in rows:
        if row.get("split") != "validation" or row.get("judgment") != "PASS":
            continue
        symbol = row["symbol"]
        current = chosen.get(symbol)
        if current is None or row["base_mean"] > current["base_mean"]:
            chosen[symbol] = row
    return chosen
