"""Paper-trade diagnostics. Counts and excursions only.

Nothing here fetches a market, calls a model, writes a promotion, or
approves a strategy. A sample under the qualification minimum stays
"not enough evidence". Confidence is always null.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ops.qualification import MIN_COMPLETED_TRADES

CLOSED = {"stopped", "target", "closed"}


def session_label(symbol, now_ms):
    """A clock bucket from the order time. Not a venue session and not a probability."""
    try:
        moment = datetime.fromtimestamp(int(now_ms) / 1000, timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return "unknown"
    if symbol == "XAUUSD":
        from ops.sessions import gold_market_open, gold_signal_session

        if gold_signal_session(moment):
            return "gold_ny_cash"
        if gold_market_open(moment):
            return "gold_open_outside_cash"
        return "gold_closed"
    hour = moment.hour
    if hour < 7:
        return "utc_asia"
    if hour < 13:
        return "utc_london"
    if hour < 21:
        return "utc_new_york"
    return "utc_late"


def regime_from(row, bars, now_ms, interval):
    """Use a regime that was already supplied. Do not fetch candles."""
    existing = None
    if isinstance(row, dict):
        if isinstance(row.get("regime"), dict):
            existing = row.get("regime")
        elif isinstance(row.get("market_condition"), dict):
            existing = row.get("market_condition")
    if existing and existing.get("trend"):
        return {
            "trend": existing.get("trend") or "unknown",
            "momentum": existing.get("momentum") or "unknown",
            "volatility": existing.get("volatility") or "unknown",
            "freshness": existing.get("freshness") or "unknown",
            "source": "supplied",
            "evidence": existing.get("evidence") or "Supplied with the paper order. Not fetched.",
        }
    if bars:
        from ops.market_conditions import assess

        assessed = dict(assess(bars, now_ms, interval or "1h"))
        if assessed.get("freshness") != "missing":
            assessed["source"] = "supplied_bars"
            return assessed
    return {
        "trend": "unknown",
        "momentum": "unknown",
        "volatility": "unknown",
        "freshness": "missing",
        "source": "not_supplied",
        "evidence": "No completed bars were supplied. No regime was fetched.",
    }


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def attach_entry(order, row, now_ms, bars=None):
    """Stamp entry context onto a new paper order. Missing bars stay unknown."""
    row = row or {}
    order["strategy_version"] = row.get("version") or row.get("strategy_version") or order.get("family")
    if row.get("snapshot_id"):
        order["snapshot_id"] = row.get("snapshot_id")
    order["session"] = session_label(order.get("symbol"), now_ms)
    order["regime"] = regime_from(row, bars, now_ms, order.get("interval"))
    entry = _number(order.get("entry"))
    stop = _number(order.get("stop"))
    risk = abs(entry - stop) if entry is not None and stop is not None else None
    order["initial_risk"] = risk if risk and risk > 0 else None
    order["mae_r"] = None
    order["mfe_r"] = None
    order["bars_held"] = 0
    order["realized_r"] = None
    order["realized_r_price"] = None
    order["excursion"] = "no_bar_yet"
    return order


def _price_risk(order):
    risk = _number(order.get("initial_risk"))
    if risk is not None and risk > 0:
        return risk
    entry = _number(order.get("entry"))
    stop = _number(order.get("stop"))
    if entry is None or stop is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    order["initial_risk"] = risk
    return risk


def note_bar(order, bar, bars=None, now_ms=None, interval=None):
    """Update MAE/MFE from one bar that is already in hand. Returns True if the order changed."""
    if not isinstance(order, dict):
        return False
    changed = False
    regime = order.get("regime") if isinstance(order.get("regime"), dict) else {}
    if bars and regime.get("source") in {None, "not_supplied"}:
        assessed = regime_from({}, bars, now_ms or 0, interval or order.get("interval"))
        if assessed.get("freshness") != "missing":
            assessed["source"] = "bars_already_in_hand"
            order["regime"] = assessed
            changed = True
    high = _number((bar or {}).get("high"))
    low = _number((bar or {}).get("low"))
    if high is None or low is None:
        return changed
    entry = _number(order.get("entry"))
    risk = _price_risk(order)
    if entry is None or risk is None:
        return changed
    if order.get("direction") == "BUY":
        adverse = max(0.0, entry - low)
        favorable = max(0.0, high - entry)
    elif order.get("direction") == "SELL":
        adverse = max(0.0, high - entry)
        favorable = max(0.0, entry - low)
    else:
        return changed
    mae_r = adverse / risk
    mfe_r = favorable / risk
    previous_mae = _number(order.get("mae_r"))
    previous_mfe = _number(order.get("mfe_r"))
    if previous_mae is None or mae_r > previous_mae:
        order["mae_r"] = mae_r
    if previous_mfe is None or mfe_r > previous_mfe:
        order["mfe_r"] = mfe_r
    try:
        order["bars_held"] = int(order.get("bars_held") or 0) + 1
    except (TypeError, ValueError):
        order["bars_held"] = 1
    order["excursion"] = "measured"
    return True


def stamp_realized(order):
    """R from the recorded pnl and exit. Ambiguous stays null. No price is invented."""
    if not isinstance(order, dict) or order.get("pnl_usd") is None or order.get("status") == "ambiguous":
        if isinstance(order, dict):
            order["realized_r"] = None
            order["realized_r_price"] = None
        return order
    budget = _number(order.get("risk_budget_usd"))
    pnl = _number(order.get("pnl_usd"))
    if budget is not None and budget > 0 and pnl is not None:
        order["realized_r"] = pnl / budget
    else:
        order["realized_r"] = None
    risk = _number(order.get("initial_risk"))
    exit_price = _number(order.get("exit_price"))
    entry = _number(order.get("entry"))
    if risk is None or risk <= 0 or exit_price is None or entry is None:
        order["realized_r_price"] = None
        return order
    move = (exit_price - entry) if order.get("direction") == "BUY" else (entry - exit_price)
    order["realized_r_price"] = move / risk
    return order


def _derived_r(order):
    stored = _number(order.get("realized_r"))
    if stored is not None:
        return stored
    pnl = _number(order.get("pnl_usd"))
    budget = _number(order.get("risk_budget_usd"))
    if pnl is None or budget is None or budget <= 0:
        return None
    return pnl / budget


def _closed(orders):
    return [
        row for row in (orders or [])
        if isinstance(row, dict) and row.get("status") in CLOSED and row.get("pnl_usd") is not None
    ]


def _slice(rows):
    n = len(rows)
    rs = [value for value in (_derived_r(row) for row in rows) if value is not None]
    stops = sum(1 for row in rows if row.get("exit_kind") == "market_stop")
    targets = sum(1 for row in rows if row.get("exit_kind") == "market_target")
    wins = sum(1 for row in rows if _number(row.get("pnl_usd")) is not None and float(row["pnl_usd"]) > 0)
    enough = n >= MIN_COMPLETED_TRADES and len(rs) >= MIN_COMPLETED_TRADES
    return {
        "n": n,
        "sample": "counted" if enough else "not_enough_evidence",
        "expectancy_r": (sum(rs) / len(rs)) if enough else None,
        "win_rate": (wins / n) if enough else None,
        "confidence": None,
        "stops": stops,
        "targets": targets,
        "measured_r": len(rs),
        "minimum_trades": MIN_COMPLETED_TRADES,
    }


def _group(rows, key, value_of):
    buckets = {}
    for row in rows:
        label = value_of(row) or "unspecified"
        buckets.setdefault(str(label), []).append(row)
    segments = []
    for label in sorted(buckets):
        body = _slice(buckets[label])
        body["by"] = key
        body["value"] = label
        segments.append(body)
    return segments


def _hypotheses(closed, overall):
    base = {
        "promotes": False,
        "confidence": None,
        "changes_approval": False,
        "n": overall["n"],
        "sample": overall["sample"],
    }
    if overall["sample"] != "counted":
        return [{
            **base,
            "statement": (
                "Not enough closed paper trades to describe expectancy, "
                "whether stops are hit before targets, or whether a regime degrades results."
            ),
            "counts": {"stops": overall["stops"], "targets": overall["targets"], "n": overall["n"]},
        }]
    found = []
    if overall["stops"] > overall["targets"]:
        found.append({
            **base,
            "statement": (
                f"Stops were observed before targets in this counted sample "
                f"({overall['stops']} stops, {overall['targets']} targets). "
                "This does not move a stop and does not promote a strategy."
            ),
            "counts": {"stops": overall["stops"], "targets": overall["targets"]},
        })
    elif overall["targets"] > overall["stops"]:
        found.append({
            **base,
            "statement": (
                f"Targets were observed before stops in this counted sample "
                f"({overall['targets']} targets, {overall['stops']} stops). "
                "This does not widen a target and does not promote a strategy."
            ),
            "counts": {"stops": overall["stops"], "targets": overall["targets"]},
        })
    measured = [row for row in closed if _number(row.get("mae_r")) is not None]
    if len(measured) >= MIN_COMPLETED_TRADES:
        beyond = sum(1 for row in measured if float(row["mae_r"]) > 1)
        found.append({
            **base,
            "statement": (
                f"Adverse excursion passed 1R on {beyond} of {len(measured)} measured paper trades. "
                "The count is not a probability and does not change a stop."
            ),
            "counts": {"mae_beyond_1r": beyond, "measured": len(measured)},
        })
    regime_rows = _group(closed, "regime", lambda row: (row.get("regime") or {}).get("trend") if isinstance(row.get("regime"), dict) else None)
    counted = [item for item in regime_rows if item["sample"] == "counted" and item["expectancy_r"] is not None]
    if len(counted) >= 2:
        counted.sort(key=lambda item: item["expectancy_r"])
        low, high = counted[0], counted[-1]
        if low["value"] != high["value"]:
            found.append({
                **base,
                "statement": (
                    f"Counted paper expectancy is {low['expectancy_r']:.4f} R in regime {low['value']} "
                    f"and {high['expectancy_r']:.4f} R in regime {high['value']}. "
                    "The gap is not a probability and does not approve a rule."
                ),
                "counts": {"low_n": low["n"], "high_n": high["n"]},
            })
    if not found:
        found.append({
            **base,
            "statement": "The counted sample has no stop, target, excursion, or regime contrast to report. Nothing is promoted.",
            "counts": {"stops": overall["stops"], "targets": overall["targets"]},
        })
    return found


def _simulation_placeholder():
    return {
        "ran": False,
        "reason": "bars_not_supplied",
        "promotes": False,
        "changes_approval": False,
        "confidence": None,
        "note": (
            "No simulation was run. The paper diagnostic does not fetch candles. "
            "A caller that already holds completed bars can compare base and stress cost. "
            "That comparison cannot promote a strategy."
        ),
    }


def report(orders, unreadable=False):
    """Segment one account's orders. Does not write and does not call a model."""
    orders = [row for row in (orders or []) if isinstance(row, dict)]
    if unreadable:
        body = _slice([])
        body.update({
            "closed_trades": 0,
            "open": 0,
            "ambiguous": 0,
            "segments": [],
            "hypotheses": [{
                "statement": "The paper book could not be read. No expectancy was estimated.",
                "sample": "not_enough_evidence",
                "n": 0,
                "promotes": False,
                "confidence": None,
                "changes_approval": False,
            }],
            "simulation": _simulation_placeholder(),
            "model": {"called": False, "required": False},
            "changes_approval": False,
            "promotes": False,
            "note": "The paper book could not be read. No expectancy was estimated.",
        })
        return body
    closed = _closed(orders)
    overall = _slice(closed)
    segments = []
    segments.extend(_group(closed, "strategy", lambda row: row.get("strategy_version") or row.get("family")))
    segments.extend(_group(closed, "symbol", lambda row: row.get("symbol")))
    segments.extend(_group(closed, "interval", lambda row: row.get("interval")))
    segments.extend(_group(closed, "session", lambda row: row.get("session")))
    segments.extend(_group(closed, "regime", lambda row: (row.get("regime") or {}).get("trend") if isinstance(row.get("regime"), dict) else None))
    segments.extend(_group(closed, "exit_kind", lambda row: row.get("exit_kind")))
    note = (
        f"{overall['n']} closed paper trades. {MIN_COMPLETED_TRADES} with a measured R are required "
        "before an expectancy is stated. No confidence is assigned. Nothing is promoted."
        if overall["sample"] != "counted"
        else (
            "Expectancy is the mean realized R of this counted paper sample after the recorded costs. "
            "It is not a probability, not a validated return, and not an approval."
        )
    )
    return {
        **overall,
        "closed_trades": overall["n"],
        "open": sum(1 for row in orders if row.get("status") == "open"),
        "ambiguous": sum(1 for row in orders if row.get("status") == "ambiguous"),
        "segments": segments,
        "hypotheses": _hypotheses(closed, overall),
        "simulation": _simulation_placeholder(),
        "model": {
            "called": False,
            "required": False,
            "note": "Learning is computed from the paper book on this desk. A missing local model does not block it.",
        },
        "changes_approval": False,
        "promotes": False,
        "note": note,
    }


def for_account(user_id):
    from ops.paperbook import load

    book = load(user_id)
    return report(book.get("orders") or [], unreadable=bool(book.get("unreadable")))


def stress_comparison(symbol, bars, higher, strategy):
    """Compare base and stress cost only when the caller already holds bars.

    The result never promotes a strategy and never assigns a confidence.
    """
    refused = {
        "ran": False,
        "promotes": False,
        "changes_approval": False,
        "confidence": None,
        "approved_for_paper": False,
    }
    if not bars:
        return {**refused, "reason": "bars_not_supplied", "note": _simulation_placeholder()["note"]}
    from ops.simulate import metrics, simulate

    try:
        base = simulate(symbol, bars, higher, strategy, stress=False)
        stressed = simulate(symbol, bars, higher, strategy, stress=True)
    except KeyError:
        return {**refused, "reason": "unknown_strategy", "note": "The named strategy is not in the frozen research table. Nothing was promoted."}
    n = len(base)
    enough = n >= MIN_COMPLETED_TRADES
    base_metrics = metrics(base) if enough else None
    stress_metrics = metrics(stressed) if enough else None
    return {
        "ran": True,
        "reason": "supplied_bars",
        "symbol": symbol,
        "strategy": strategy,
        "base_trades": n,
        "stress_trades": len(stressed),
        "sample": "counted" if enough else "not_enough_evidence",
        "base_mean": None if not base_metrics else base_metrics.get("base_mean"),
        "stress_mean": None if not stress_metrics else stress_metrics.get("base_mean"),
        "promotes": False,
        "changes_approval": False,
        "confidence": None,
        "approved_for_paper": False,
        "holdout_opened": False,
        "note": (
            "Base cost versus stress cost on the bars the caller supplied. "
            "A small sample is not evidence. This does not promote a strategy and does not open a holdout."
        ),
    }
