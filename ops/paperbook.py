"""Per-user paper orders. A notification is not an order, and a touch is not a fill."""

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
COST_BPS_PER_FILL = 11
SLIPPAGE_BPS = 2
CLOSED = {"stopped", "target", "closed"}


def _safe(user_id):
    text = str(user_id or "")
    if not text or "/" in text or "\\" in text or ".." in text:
        return None
    return text


def _path(user_id):
    from ops.users import ROOT
    safe = _safe(user_id)
    if safe is None:
        return None
    return ROOT / "paper" / f"{safe}.json"


def migrate(raw):
    """Keep any stored orders. Do not invent prices or delete rows."""
    if isinstance(raw, list):
        return {"schema": SCHEMA, "orders": raw}
    if isinstance(raw, dict):
        orders = raw.get("orders")
        if not isinstance(orders, list):
            orders = []
        return {"schema": SCHEMA, "orders": orders}
    return {"schema": SCHEMA, "orders": []}


def load(user_id):
    path = _path(user_id)
    if path is None or not path.exists():
        return {"schema": SCHEMA, "orders": []}
    try:
        return migrate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {"schema": SCHEMA, "orders": [], "unreadable": True}


def save(user_id, book):
    path = _path(user_id)
    if path is None:
        return False
    from ops.files import update_json
    body = migrate(book)
    update_json(path, lambda _current: body, body)
    return True


def _update_orders(user_id, fn):
    path = _path(user_id)
    if path is None:
        return {"ok": False, "reason": "bad_user"}
    from ops.files import update_json
    holder = {}

    def apply(raw):
        book = migrate(raw if raw is not None else {"schema": SCHEMA, "orders": []})
        holder["out"] = fn(book)
        if isinstance(holder["out"], dict) and holder["out"].get("save") is False:
            holder["out"].pop("save", None)
            return None
        return book

    updated = update_json(path, apply, {"schema": SCHEMA, "orders": []})
    if isinstance(updated, dict) and updated.get("unreadable"):
        return {"ok": False, "reason": "record_unreadable"}
    return holder.get("out")


def _day(now_ms):
    return datetime.fromtimestamp(int(now_ms) / 1000, timezone.utc).strftime("%Y-%m-%d")


def _week(now_ms):
    moment = datetime.fromtimestamp(int(now_ms) / 1000, timezone.utc)
    year, week, _day = moment.isocalendar()
    return f"{year}-W{week:02d}"


def _reward(entry, stop, target):
    try:
        distance = abs(float(entry) - float(stop))
        if distance <= 0:
            return None
        return abs(float(target) - float(entry)) / distance
    except (TypeError, ValueError):
        return None


def _pnl(direction, entry, exit_price, quantity):
    gross = quantity * (exit_price - entry) if direction == "BUY" else quantity * (entry - exit_price)
    cost = quantity * entry * (COST_BPS_PER_FILL * 2) / 10000.0
    return gross - cost, cost


def opportunity_row(user_id, opportunity_id):
    from ops.inbox import items
    if not opportunity_id:
        return None
    for row in items(user_id):
        if row.get("opportunity_id") == opportunity_id:
            return row
    return None


def paper_permission(user, result):
    """Whether this account may open a paper order. The market decision is unchanged."""
    result = result or {}
    if result.get("decision") not in {"BUY", "SELL"}:
        return {"allowed": False, "reason": "not_a_plan"}
    probe = {
        "opportunity_id": "probe",
        "symbol": result.get("symbol"),
        "interval": result.get("interval"),
        "direction": result.get("decision"),
        "entry": result.get("entry"),
        "stop": result.get("stop"),
        "target": result.get("target"),
        "lifecycle": "active",
        "family": result.get("rule") or result.get("strategy"),
    }
    verdict = open_order(user, probe, int(result.get("requested_ms") or 0) or 1, commit=False)
    return {"allowed": verdict.get("ok") is True, "reason": verdict.get("reason")}


def plan_preview(user, row):
    """Risk and size for a review. Nothing is written."""
    row = row or {}
    probe = {
        "symbol": row.get("symbol"),
        "interval": row.get("interval"),
        "decision": row.get("decision") or row.get("direction"),
        "entry": row.get("entry"),
        "stop": row.get("stop"),
        "target": row.get("target"),
        "rule": row.get("rule") or row.get("family") or row.get("strategy"),
        "requested_ms": row.get("created_ms") or row.get("requested_ms") or 1,
    }
    verdict = paper_permission(user, probe)
    from ops.plan import qualify_size
    from ops.profiles import canonical_style, get_profile
    profile = (user or {}).get("profile") or {}
    spec = get_profile(canonical_style(profile.get("signal_style"))) or {}
    plan = (user or {}).get("plan") or {}
    risk = plan.get("risk_per_trade_percent")
    cap = spec.get("risk_per_trade_percent")
    if risk is None:
        risk = cap
    if cap is not None and risk is not None:
        risk = min(float(risk), float(cap))
    sized = qualify_size(row.get("symbol"), profile.get("capital"), risk, profile.get("currency"), row.get("entry"), row.get("stop"))
    return {
        "allowed": verdict.get("allowed") is True,
        "reason": verdict.get("reason"),
        "risk_percent": risk,
        "persona": spec.get("name"),
        "min_rr": spec.get("min_rr"),
        "size": sized,
        "order_opened": False,
    }


def open_order(user, opportunity, now_ms, commit=True, opened_by="account", automation_cap=None, bars=None):
    user = user or {}
    user_id = user.get("id")
    row = opportunity or {}
    if _safe(user_id) is None:
        return {"ok": False, "reason": "bad_user"}
    if row.get("lifecycle") in {"superseded", "expired", "invalidated"}:
        return {"ok": False, "reason": "opportunity_closed"}
    direction = row.get("direction") or row.get("decision")
    if direction not in {"BUY", "SELL"}:
        return {"ok": False, "reason": "not_a_plan"}
    from ops.entitlements import persistence_refusal
    refused = persistence_refusal(row)
    if refused:
        return refused
    entry, stop, target = row.get("entry"), row.get("stop"), row.get("target")
    if entry is None or stop is None or target is None:
        return {"ok": False, "reason": "incomplete"}
    from ops.inbox import inbox_settings
    from ops.plan import qualify_size
    from ops.profiles import get_profile, canonical_style

    settings = inbox_settings(user)
    symbol = row.get("symbol")
    interval = str(row.get("interval") or "")
    if symbol not in settings["markets"]:
        return {"ok": False, "reason": "market"}
    if interval and interval not in settings["timeframes"]:
        return {"ok": False, "reason": "timeframe"}
    if direction == "BUY" and not settings["buy"]:
        return {"ok": False, "reason": "buy_off"}
    if direction == "SELL" and not settings["sell"]:
        return {"ok": False, "reason": "sell_off"}
    profile = user.get("profile") or {}
    spec = get_profile(canonical_style(profile.get("signal_style")))
    if not spec:
        return {"ok": False, "reason": "no_persona"}
    reward = _reward(entry, stop, target)
    if reward is None or reward + 1e-9 < float(spec["min_rr"]):
        return {"ok": False, "reason": "below_persona_reward", "reward_risk": reward, "floor": spec["min_rr"]}
    allowed_frames = spec.get("paper_timeframes") or []
    if interval and allowed_frames and interval not in allowed_frames:
        return {"ok": False, "reason": "persona_timeframe", "allowed": allowed_frames}
    plan = user.get("plan") or {}
    if symbol not in (plan.get("markets") or [symbol]):
        return {"ok": False, "reason": "market"}
    risk = plan.get("risk_per_trade_percent")
    if risk is None:
        risk = spec["risk_per_trade_percent"]
    risk = min(float(risk), float(spec["risk_per_trade_percent"]))
    sized = qualify_size(symbol, profile.get("capital"), risk, profile.get("currency"), entry, stop)
    if not sized.get("ok"):
        return {"ok": False, "reason": sized.get("reason") or "unsized", "size": sized}
    # Risk admission is the next step. Live execution is locked off, so no
    # exchange call can run before, or instead of, that admission.
    venue = None
    origin = opened_by if opened_by in {"account", "autopilot"} else "account"
    if not commit:
        book = load(user_id)
        if book.get("unreadable"):
            return {"ok": False, "reason": "record_unreadable"}
        return _admit(book, row, now_ms, spec, sized, reward, _week(now_ms), origin, automation_cap, float(profile.get("capital")), plan.get("weekly_loss_limit_percent"), commit=False, venue=venue, bars=bars)
    admitted = _update_orders(
        user_id,
        lambda book: _admit(book, row, now_ms, spec, sized, reward, _week(now_ms), origin, automation_cap, float(profile.get("capital")), plan.get("weekly_loss_limit_percent"), commit=True, venue=venue, bars=bars),
    )
    if not admitted or not admitted.get("ok"):
        return admitted or {"ok": False, "reason": "record_unreadable"}
    _remember_count(user_id, now_ms)
    if admitted.get("ok") and isinstance(admitted.get("order"), dict):
        try:
            from ops.activity import record
            order = admitted["order"]
            record(
                "paper_opened",
                account_id=user_id,
                entity=order.get("id"),
                component="paperbook",
                detail={
                    "symbol": order.get("symbol"),
                    "direction": order.get("direction"),
                    "entry": order.get("entry"),
                    "opened_by": order.get("opened_by"),
                    "note": "Paper order recorded. Not a broker fill.",
                },
                now_ms=int(now_ms),
            )
        except Exception:
            pass
    return admitted


def _admit(book, row, now_ms, spec, sized, reward, week, origin, automation_cap, capital, loss_limit, commit, venue=None, bars=None):
    if book.get("unreadable"):
        return {"ok": False, "reason": "record_unreadable", "save": False}
    orders = book["orders"]
    opportunity_id = row.get("opportunity_id")
    symbol = row.get("symbol")
    interval = str(row.get("interval") or "")
    direction = row.get("direction") or row.get("decision")
    entry, stop, target = row.get("entry"), row.get("stop"), row.get("target")
    if origin == "autopilot" and any(item.get("opportunity_id") == opportunity_id for item in orders):
        return {"ok": False, "reason": "already_recorded", "save": False}
    if any(item.get("opportunity_id") == opportunity_id and item.get("status") == "open" for item in orders):
        return {"ok": False, "reason": "already_open", "save": False}
    day = _day(now_ms)
    opened_today = [item for item in orders if _day(item.get("opened_ms") or 0) == day and item.get("status") != "refused"]
    if len(opened_today) >= int(spec["max_trades_per_day"]):
        return {"ok": False, "reason": "daily_count", "save": False}
    if origin == "autopilot" and automation_cap is not None:
        automated = [item for item in opened_today if item.get("opened_by") == "autopilot"]
        if len(automated) >= int(automation_cap):
            return {"ok": False, "reason": "automation_cap", "save": False}
    closed_today = [item for item in orders if item.get("status") in CLOSED and _day(item.get("closed_ms") or 0) == day]
    loss_today = -sum(float(item.get("pnl_usd") or 0) for item in closed_today if float(item.get("pnl_usd") or 0) < 0)
    if loss_today >= capital * float(spec["max_daily_loss_percent"]) / 100.0:
        return {"ok": False, "reason": "daily_loss", "save": False}
    week_pnl = sum(float(item.get("pnl_usd") or 0) for item in orders if item.get("status") in CLOSED and item.get("week") == week)
    if loss_limit not in (None, "") and week_pnl <= -capital * float(loss_limit) / 100.0:
        return {"ok": False, "reason": "weekly_loss", "save": False}
    open_risk = sum(float(item.get("risk_budget_usd") or 0) for item in orders if item.get("status") == "open")
    budget = float(sized["risk_budget_usd"])
    if open_risk + budget > capital * float(spec["max_open_risk_percent"]) / 100.0:
        return {"ok": False, "reason": "open_risk", "save": False}
    if not commit:
        return {"ok": True, "reason": "allowed", "committed": False, "save": False}
    quantity = (venue or {}).get("quantity") or budget / abs(float(entry) - float(stop))
    live = bool(venue)
    opened_note = (
        "Opened on Binance spot with a protective stop."
        if live else
        "Opened by AutoPilot as a paper trade. Not a notification and not a broker order." if origin == "autopilot" else "Opened by the account. Not opened by a notification."
    )
    order = {
        "id": f"{'live' if live else 'paper'}:{opportunity_id}:{int(now_ms)}",
        "schema": SCHEMA,
        "opportunity_id": opportunity_id,
        "symbol": symbol,
        "interval": interval,
        "family": row.get("family") or row.get("rule") or row.get("strategy"),
        "direction": direction,
        "entry": float(entry),
        "stop": float(stop),
        "target": float(target),
        "reward_risk": reward,
        "risk_budget_usd": budget,
        "quantity": quantity,
        "quantity_basis": "binance_lot" if live else "unrounded_spot_estimate",
        "executable": live,
        "venue": "binance-spot" if live else "paper",
        "exchange_order_id": (venue or {}).get("order_id"),
        "stop_order_id": (venue or {}).get("stop_order_id"),
        "venue_step_verified": live,
        "status": "open",
        "opened_ms": int(now_ms),
        "opened_by": origin,
        "week": week,
        "persona": spec["key"],
        "cost_bps_per_fill": COST_BPS_PER_FILL,
        "slippage_bps": None,
        "exit_kind": None,
        "pnl_usd": None,
        "exit_price": None,
        "note": "Binance spot market buy. A stop order was accepted." if live else "Paper estimate. The venue quantity step was not verified, so this is not an exchange order.",
        "events": [{"state": "opened", "created_ms": int(now_ms), "opened_by": origin, "note": opened_note}],
    }
    try:
        from ops.learning import attach_entry
        attach_entry(order, row, int(now_ms), bars=bars)
    except Exception:
        order["regime"] = {
            "trend": "unknown",
            "momentum": "unknown",
            "volatility": "unknown",
            "freshness": "missing",
            "source": "not_supplied",
            "evidence": "Entry context was not stored. No regime was fetched.",
        }
        order["mae_r"] = None
        order["mfe_r"] = None
        order["bars_held"] = 0
        order["realized_r"] = None
        order["excursion"] = "no_bar_yet"
    orders.append(order)
    return {"ok": True, "reason": "opened", "order": order}


def _remember_count(user_id, now_ms):
    from ops.files import update_json
    from ops.users import ROOT
    path = ROOT / f"{user_id}.json"
    if not path.exists():
        return
    day = _day(now_ms)

    def apply(user):
        if not isinstance(user, dict):
            return {"unreadable": True}
        count = sum(
            1 for item in load(user_id)["orders"]
            if _day(item.get("opened_ms") or 0) == day and item.get("status") != "refused"
        )
        user["paper_orders_today"] = count
        return user

    update_json(path, apply, None)


def close_order(user_id, order_id, exit_price, now_ms):
    """Close one open paper order at a price the account supplied. No price is invented."""
    if _safe(user_id) is None or not order_id:
        return {"ok": False, "reason": "missing"}
    try:
        exit_price = float(exit_price)
    except (TypeError, ValueError):
        return {"ok": False, "reason": "missing_exit"}
    if exit_price <= 0:
        return {"ok": False, "reason": "missing_exit"}
    book = load(user_id)
    if book.get("unreadable"):
        return {"ok": False, "reason": "record_unreadable"}
    for order in book["orders"]:
        if order.get("id") != order_id:
            continue
        if order.get("status") != "open":
            return {"ok": False, "reason": "not_open"}
        entry = float(order["entry"])
        pnl, cost = _pnl(order["direction"], entry, exit_price, float(order["quantity"]))
        order["status"] = "closed"
        order["exit_kind"] = "account_exit"
        order["exit_price"] = exit_price
        order["pnl_usd"] = pnl
        order["cost_usd"] = cost
        order["slippage_bps"] = 0
        order["slippage_note"] = "No slippage was added. The account supplied this exit price."
        order["closed_ms"] = int(now_ms)
        try:
            from ops.learning import stamp_realized
            stamp_realized(order)
        except Exception:
            order["realized_r"] = None
        order["events"] = list(order.get("events") or [])
        order["events"].append({
            "state": "closed",
            "created_ms": int(now_ms),
            "exit_price": exit_price,
            "note": "Closed by the account at a stated price. The original entry, stop and target were not changed. This is not a broker fill.",
        })
        save(user_id, book)
        try:
            from ops.activity import record
            record(
                "paper_closed",
                account_id=user_id,
                entity=order.get("id"),
                component="paperbook",
                detail={
                    "symbol": order.get("symbol"),
                    "direction": order.get("direction"),
                    "entry": order.get("entry"),
                    "exit_price": exit_price,
                    "note": "Closed by the account. The original entry was not rewritten. Not a broker fill.",
                },
                now_ms=int(now_ms),
            )
        except Exception:
            pass
        return {"ok": True, "reason": "closed", "order": order}
    return {"ok": False, "reason": "missing"}


def _adverse(direction, price):
    slip = float(price) * SLIPPAGE_BPS / 10000.0
    return (float(price) - slip) if direction == "BUY" else (float(price) + slip)


def observe(user_id, symbol, interval, bar, now_ms, source=None, bars=None):
    """Update open paper orders from one completed bar. Both prices in one bar stay unresolved."""
    from ops.plan import observe_levels
    book = load(user_id)
    if book.get("unreadable"):
        return {"updated": 0, "excursion": 0}
    source = source or {}
    changed = 0
    touched = 0
    for order in book["orders"]:
        if order.get("status") != "open":
            continue
        if order.get("symbol") != symbol or order.get("interval") != interval:
            continue
        try:
            from ops.learning import note_bar
            if note_bar(order, bar, bars=bars, now_ms=now_ms, interval=interval):
                touched += 1
        except Exception:
            pass
        reading = observe_levels(order.get("direction"), order.get("stop"), order.get("target"), bar)
        if not reading:
            continue
        state = reading["state"]
        observed = {
            "created_ms": int(now_ms),
            "bar_close_ms": source.get("bar_close_ms") or (bar or {}).get("close_time_ms"),
            "source": source.get("name") or (bar or {}).get("provider") or "completed_candle",
            "quote": source.get("quote") or (bar or {}).get("quote_semantics"),
        }
        if state == "ambiguous":
            order["status"] = "ambiguous"
            order["exit_kind"] = "unresolved"
            order["pnl_usd"] = None
            order["exit_price"] = None
            order["realized_r"] = None
            order["realized_r_price"] = None
            order["events"] = list(order.get("events") or [])
            order["events"].append({**observed, "state": "ambiguous", "note": reading["note"]})
            changed += 1
            continue
        if state not in {"stop_touched", "target_touched"}:
            continue
        planned = float(order["stop"] if state == "stop_touched" else order["target"])
        exit_price = _adverse(order["direction"], planned)
        pnl, cost = _pnl(order["direction"], float(order["entry"]), exit_price, float(order["quantity"]))
        order["status"] = "stopped" if state == "stop_touched" else "target"
        order["exit_kind"] = "market_stop" if state == "stop_touched" else "market_target"
        order["exit_price"] = exit_price
        order["planned_exit"] = planned
        order["pnl_usd"] = pnl
        order["cost_usd"] = cost
        order["slippage_bps"] = SLIPPAGE_BPS
        order["slippage_note"] = "An assumed 2 bps adverse slippage was applied. It was not measured from a broker."
        order["closed_ms"] = int(now_ms)
        try:
            from ops.learning import stamp_realized
            stamp_realized(order)
        except Exception:
            order["realized_r"] = None
        order["events"] = list(order.get("events") or [])
        order["events"].append({
            **observed,
            "state": order["exit_kind"],
            "note": "Estimated paper exit from the completed candle. Not a broker fill. " + reading["note"],
            "exit_price": exit_price,
            "planned_exit": planned,
            "slippage_bps": SLIPPAGE_BPS,
            "cost_bps_per_fill": COST_BPS_PER_FILL,
        })
        changed += 1
    if changed or touched:
        save(user_id, book)
    return {"updated": changed, "excursion": touched}


def performance(user_id):
    """Figures come only from closed paper orders. An empty book stays empty."""
    book = load(user_id)
    orders = book.get("orders") or []
    closed = [row for row in orders if row.get("status") in CLOSED and row.get("pnl_usd") is not None]
    if not closed:
        figures = {
            "trades": 0,
            "pnl_usd": None,
            "costs_usd": None,
            "wins": 0,
            "losses": 0,
            "win_rate": None,
            "note": "No completed paper trade. Ambiguous candles are not counted.",
        }
    else:
        pnl = sum(float(row.get("pnl_usd") or 0) for row in closed)
        costs = sum(float(row.get("cost_usd") or 0) for row in closed)
        wins = sum(1 for row in closed if float(row.get("pnl_usd") or 0) > 0)
        losses = sum(1 for row in closed if float(row.get("pnl_usd") or 0) < 0)
        figures = {
            "trades": len(closed),
            "pnl_usd": pnl,
            "costs_usd": costs,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(closed),
            "note": "Paper estimate after 11 bps per side. Not a broker result and not a validated return.",
        }
    try:
        from ops.learning import report
        figures["diagnostics"] = report(orders)
    except Exception:
        figures["diagnostics"] = {"sample": "not_enough_evidence", "confidence": None, "promotes": False, "changes_approval": False}
    return figures


def summary(user_id):
    book = load(user_id)
    orders = book.get("orders") or []
    closed = [row for row in orders if row.get("status") in CLOSED and row.get("pnl_usd") is not None]
    figures = performance(user_id)
    return {
        "schema": book.get("schema") or SCHEMA,
        "open": [row for row in orders if row.get("status") == "open"],
        "ambiguous": [row for row in orders if row.get("status") == "ambiguous"],
        "closed": closed,
        "orders": orders,
        "pnl_usd": figures["pnl_usd"],
        "performance": figures,
        "trades": len(closed),
        "empty": not orders,
        "note": "Closed paper trades use an unrounded spot estimate and 11 bps per side. Ambiguous candles are not fills and are not counted. Nothing here is a broker result.",
    }


def as_fills(user_id):
    return [{"kind": "paper_fill", "pnl": row.get("pnl_usd")} for row in summary(user_id)["closed"]]
