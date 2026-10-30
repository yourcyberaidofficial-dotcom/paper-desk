"""A personal plan. It measures. It does not create trades or lower a failed strategy's gate."""

from datetime import datetime, timezone

from ops.registry import BY_ID

WEIGHTS = {
    "completed_bar": 20,
    "fresh": 20,
    "enough_history": 20,
    "rule_checked": 15,
    "explained": 15,
    "promoted": 10,
}


def evidence_grade(checks):
    score = 0
    used = {}
    for name, weight in WEIGHTS.items():
        passed = bool((checks or {}).get(name))
        used[name] = passed
        if passed:
            score += weight
    return {
        "evidence_grade": score,
        "checks": used,
        "calibrated": False,
        "label": "checklist score, not a probability of profit",
    }


def _number(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number < low or number > high:
        return None
    return number


def normalize(incoming, current, risk_cap):
    incoming = incoming or {}
    current = current or {}
    notes = []
    mode = incoming.get("mode", current.get("mode", "auto"))
    if mode not in {"auto", "selected"}:
        mode = current.get("mode", "auto")
        notes.append("Strategy mode must be auto or selected.")
    requested = incoming.get("strategies", current.get("strategies", []))
    strategies = [item for item in requested if item in BY_ID]
    if mode == "selected" and not strategies:
        strategies = ["E1-donchian-20"]
        notes.append("Selected mode needs at least one known strategy. E1 was kept so the plan is not empty.")
    markets = [item for item in incoming.get("markets", current.get("markets", ["BTCUSDT", "ETHUSDT", "XAUUSD"])) if item in {"BTCUSDT", "ETHUSDT", "XAUUSD"}]
    if not markets:
        markets = ["BTCUSDT", "ETHUSDT", "XAUUSD"]
        notes.append("At least one supported market is required.")
    grade = incoming.get("min_evidence_grade", current.get("min_evidence_grade", 0))
    grade_number = _number(grade, 0, 100)
    if grade_number is None:
        grade_number = float(current.get("min_evidence_grade") or 0)
        notes.append("The quality threshold must be a number from 0 to 100.")
    aim = incoming.get("weekly_aim_percent", current.get("weekly_aim_percent"))
    aim_number = None if aim in (None, "") else _number(aim, 0, 100)
    if aim not in (None, "") and aim_number is None:
        notes.append("The weekly aim must be a percentage from 0 to 100, or left blank.")
    loss = incoming.get("weekly_loss_limit_percent", current.get("weekly_loss_limit_percent"))
    loss_number = None if loss in (None, "") else _number(loss, 0, 100)
    if loss not in (None, "") and loss_number is None:
        notes.append("The weekly loss limit must be a percentage from 0 to 100, or left blank.")
    risk = incoming.get("risk_per_trade_percent", current.get("risk_per_trade_percent"))
    risk_number = None if risk in (None, "") else _number(risk, 0, 100)
    if risk_cap is None:
        if risk not in (None, ""):
            notes.append("Choose a signal style before setting a per-trade risk limit.")
        risk_number = None
    elif risk_number is None:
        risk_number = risk_cap
    elif risk_number > risk_cap:
        notes.append(f"The style cap is {risk_cap:g}%. A higher request was not saved.")
        risk_number = risk_cap
    return {
        "mode": mode,
        "strategies": strategies,
        "markets": markets,
        "min_evidence_grade": int(grade_number),
        "weekly_aim_percent": aim_number,
        "weekly_loss_limit_percent": loss_number,
        "risk_per_trade_percent": risk_number,
        "research_alerts": bool(incoming.get("research_alerts", current.get("research_alerts", False))),
        "approved_alerts": True,
        "notes": notes,
        "forces_signals": False,
    }


def propose_size(capital, risk_percent, entry, stop):
    try:
        capital = float(capital)
        risk_percent = float(risk_percent)
        entry = float(entry)
        stop = float(stop)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "missing_inputs", "order": False}
    distance = abs(entry - stop)
    if capital <= 0 or risk_percent <= 0 or distance <= 0:
        return {"ok": False, "reason": "risk_not_calculable", "order": False}
    risk_amount = capital * risk_percent / 100.0
    return {
        "ok": True,
        "quantity": risk_amount / distance,
        "risk_amount": risk_amount,
        "risk_percent": risk_percent,
        "order": False,
    }


def week_id(now_ms):
    moment = datetime.fromtimestamp(int(now_ms) / 1000, timezone.utc)
    year, week, _day = moment.isocalendar()
    return f"{year}-W{week:02d}"


def week_status(plan, now_ms, recorded=None):
    fills = [row for row in (recorded or []) if row.get("kind") == "paper_fill"]
    pnl = None
    if fills:
        pnl = sum(float(row.get("pnl") or 0) for row in fills)
    return {
        "week": week_id(now_ms),
        "aim_percent": (plan or {}).get("weekly_aim_percent"),
        "loss_limit_percent": (plan or {}).get("weekly_loss_limit_percent"),
        "paper_pnl": pnl,
        "paper_note": "No simulated results recorded." if pnl is None else "Paper result only. Not a broker fill.",
        "simulated_trades": len(fills),
        "approved_alerts": 0,
        "qualified_candidates": 0,
        "forces_signals": False,
    }


def visible_to_user(event, plan):
    plan = plan or normalize({}, {}, None)
    strategy = event.get("strategy")
    if plan["mode"] == "selected" and strategy and strategy not in plan["strategies"]:
        return {"show": False, "reason": "not_in_plan"}
    if event.get("symbol") not in plan["markets"]:
        return {"show": False, "reason": "market_off"}
    grade = int(event.get("evidence_grade") or 0)
    if grade < plan["min_evidence_grade"] and event.get("state") not in {"WAIT", "DATA_UNAVAILABLE"}:
        return {"show": True, "eligible": False, "reason": "below_threshold", "message": "This setup did not meet your minimum quality threshold."}
    return {
        "show": True,
        "eligible": event.get("state") in {"RESEARCH_OBSERVATION", "PAPER_CANDIDATE", "APPROVED_SIGNAL"},
        "reason": "visible",
        "trade_alert": False if event.get("state") != "APPROVED_SIGNAL" else bool(plan.get("approved_alerts")),
    }


def qualify_size(symbol, capital, risk_percent, currency, entry, stop):
    """A risk budget is not an order quantity.

    Spot BTC and ETH move one quote unit per base unit. That identity is not a
    venue lot step. Gold has no verified contract size here. A non-USD account
    is not converted, because no FX rate is loaded.
    """
    try:
        capital = float(capital)
        risk_percent = float(risk_percent)
        entry = float(entry)
        stop = float(stop)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "missing_inputs", "order": False, "quantity_orderable": False, "budget_ok": False}
    distance = abs(entry - stop)
    if capital <= 0 or risk_percent <= 0 or distance <= 0:
        return {"ok": False, "reason": "risk_not_calculable", "order": False, "quantity_orderable": False, "budget_ok": False}
    budget = capital * risk_percent / 100.0
    if currency != "USD":
        return {
            "ok": False,
            "reason": "fx_unverified",
            "order": False,
            "quantity_orderable": False,
            "budget_ok": False,
            "note": f"No validated {currency} rate is loaded, so no money figure was converted.",
        }
    if symbol == "XAUUSD":
        return {
            "ok": False,
            "reason": "contract_unverified",
            "order": False,
            "quantity_orderable": False,
            "budget_ok": True,
            "risk_budget_usd": budget,
            "note": "The USD risk budget is shown. Gold is not sized, because the contract (ounce, gram, or CFD lot) is not verified.",
        }
    if symbol not in {"BTCUSDT", "ETHUSDT"}:
        return {"ok": False, "reason": "instrument_unknown", "order": False, "quantity_orderable": False, "budget_ok": False}
    return {
        "ok": True,
        "budget_ok": True,
        "quantity": budget / distance,
        "quantity_orderable": False,
        "risk_amount": budget,
        "risk_budget_usd": budget,
        "risk_percent": risk_percent,
        "currency": "USD",
        "quote": "USDT",
        "multiplier": 1,
        "multiplier_basis": "spot_base_unit",
        "order": False,
        "costs_included_in_quantity": False,
        "note": "USD risk budget and an unrounded spot estimate. The venue quantity step was not loaded, and USDT was not converted. This is not an order.",
    }


def present_size(size):
    """The risk budget and the executable quantity are different facts."""
    size = size or {}
    budget = size.get("risk_budget_usd")
    if budget is None:
        budget = size.get("risk_amount")
    if size.get("quantity_orderable") is True and size.get("quantity") is not None:
        return {
            "executable_quantity": size["quantity"],
            "risk_budget": budget,
            "text": f"Executable quantity {size['quantity']}. Risk budget {budget} {size.get('currency') or 'USD'}.",
        }
    if size.get("quantity_orderable") is not True and budget is not None and (size.get("budget_ok") or size.get("ok")):
        why = size.get("note") or "The venue quantity step, contract size, or tick value is not verified."
        return {
            "executable_quantity": None,
            "risk_budget": budget,
            "text": f"Risk budget {budget} USD. Executable quantity is unavailable. {why}",
        }
    why = size.get("note") or size.get("reason") or "not calculated"
    return {"executable_quantity": None, "risk_budget": None, "text": f"Executable sizing is unavailable: {why}"}


def paper_cap_status(cap, paper_orders_today):
    """The stored persona cap counts paper orders, never inbox cards."""
    try:
        count = int(paper_orders_today or 0)
    except (TypeError, ValueError):
        count = 0
    blocks = cap is not None and count >= int(cap)
    return {
        "cap": cap,
        "paper_orders_today": count,
        "counts": "recorded paper orders",
        "notifications_count": False,
        "broker_executions": 0,
        "blocks_new_paper_order": blocks,
        "blocks_notification": False,
    }


def observe_levels(side, stop, target, bar):
    """A candle that reaches both prices does not say which came first."""
    if side not in {"BUY", "SELL"} or stop is None or target is None or not bar:
        return None
    try:
        high = float(bar["high"])
        low = float(bar["low"])
        stop = float(stop)
        target = float(target)
    except (KeyError, TypeError, ValueError):
        return None
    if side == "BUY":
        stop_hit = low <= stop
        target_hit = high >= target
    else:
        stop_hit = high >= stop
        target_hit = low <= target
    if stop_hit and target_hit:
        return {
            "state": "ambiguous",
            "note": "This candle reached both the stop and the target. Finer prices were not available, so neither is treated as first. This is not a fill.",
        }
    if stop_hit:
        return {"state": "stop_touched", "note": "The candle range reached the stop. Bid and ask were not used. This is not a fill."}
    if target_hit:
        return {"state": "target_touched", "note": "The candle range reached the target. Bid and ask were not used. This is not a fill."}
    return None
