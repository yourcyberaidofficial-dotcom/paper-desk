"""Per-user paper orders. A notification is not an order, and a touch is not a fill."""

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
COST_BPS_PER_FILL = 11


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
    path.parent.mkdir(parents=True, exist_ok=True)
    body = migrate(book)
    path.write_text(json.dumps(body), encoding="utf-8")
    return True


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


def open_order(user, opportunity, now_ms, commit=True):
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
    book = load(user_id)
    if book.get("unreadable"):
        return {"ok": False, "reason": "record_unreadable"}
    orders = book["orders"]
    opportunity_id = row.get("opportunity_id")
    if any(item.get("opportunity_id") == opportunity_id and item.get("status") == "open" for item in orders):
        return {"ok": False, "reason": "already_open"}
    day = _day(now_ms)
    opened_today = [item for item in orders if _day(item.get("opened_ms") or 0) == day and item.get("status") != "refused"]
    if len(opened_today) >= int(spec["max_trades_per_day"]):
        return {"ok": False, "reason": "daily_count"}
    capital = float(profile.get("capital"))
    closed_today = [item for item in orders if item.get("status") in {"stopped", "target"} and _day(item.get("closed_ms") or 0) == day]
    loss_today = -sum(float(item.get("pnl_usd") or 0) for item in closed_today if float(item.get("pnl_usd") or 0) < 0)
    if loss_today >= capital * float(spec["max_daily_loss_percent"]) / 100.0:
        return {"ok": False, "reason": "daily_loss"}
    week = _week(now_ms)
    week_pnl = sum(float(item.get("pnl_usd") or 0) for item in orders if item.get("status") in {"stopped", "target"} and item.get("week") == week)
    loss_limit = plan.get("weekly_loss_limit_percent")
    if loss_limit not in (None, "") and week_pnl <= -capital * float(loss_limit) / 100.0:
        return {"ok": False, "reason": "weekly_loss"}
    open_risk = sum(float(item.get("risk_budget_usd") or 0) for item in orders if item.get("status") == "open")
    budget = float(sized["risk_budget_usd"])
    if open_risk + budget > capital * float(spec["max_open_risk_percent"]) / 100.0:
        return {"ok": False, "reason": "open_risk"}
    if not commit:
        return {"ok": True, "reason": "allowed", "committed": False}
    quantity = budget / abs(float(entry) - float(stop))
    order = {
        "id": f"paper:{opportunity_id}:{int(now_ms)}",
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
        "quantity_basis": "unrounded_spot_estimate",
        "executable": False,
        "venue_step_verified": False,
        "status": "open",
        "opened_ms": int(now_ms),
        "week": week,
        "persona": spec["key"],
        "cost_bps_per_fill": COST_BPS_PER_FILL,
        "pnl_usd": None,
        "exit_price": None,
        "note": "Paper estimate. The venue quantity step was not verified, so this is not an exchange order.",
        "events": [{"state": "opened", "created_ms": int(now_ms), "note": "Opened by the account. Not opened by a notification."}],
    }
    orders.append(order)
    save(user_id, book)
    return {"ok": True, "reason": "opened", "order": order}


def observe(user_id, symbol, interval, bar, now_ms):
    """Update open paper orders from one completed bar. Both prices in one bar stay unresolved."""
    from ops.plan import observe_levels
    book = load(user_id)
    if book.get("unreadable"):
        return {"updated": 0}
    changed = 0
    for order in book["orders"]:
        if order.get("status") != "open":
            continue
        if order.get("symbol") != symbol or order.get("interval") != interval:
            continue
        reading = observe_levels(order.get("direction"), order.get("stop"), order.get("target"), bar)
        if not reading:
            continue
        state = reading["state"]
        if state == "ambiguous":
            order["status"] = "ambiguous"
            order["pnl_usd"] = None
            order["exit_price"] = None
            order["events"].append({"state": "ambiguous", "created_ms": int(now_ms), "note": reading["note"]})
            changed += 1
            continue
        if state not in {"stop_touched", "target_touched"}:
            continue
        exit_price = float(order["stop"] if state == "stop_touched" else order["target"])
        pnl, cost = _pnl(order["direction"], float(order["entry"]), exit_price, float(order["quantity"]))
        order["status"] = "stopped" if state == "stop_touched" else "target"
        order["exit_price"] = exit_price
        order["pnl_usd"] = pnl
        order["cost_usd"] = cost
        order["closed_ms"] = int(now_ms)
        order["events"].append({
            "state": order["status"],
            "created_ms": int(now_ms),
            "note": "Closed from the completed candle. This is not a broker fill.",
            "exit_price": exit_price,
        })
        changed += 1
    if changed:
        save(user_id, book)
    return {"updated": changed}


def summary(user_id):
    book = load(user_id)
    orders = book.get("orders") or []
    closed = [row for row in orders if row.get("status") in {"stopped", "target"}]
    pnl = sum(float(row.get("pnl_usd") or 0) for row in closed)
    return {
        "schema": book.get("schema") or SCHEMA,
        "open": [row for row in orders if row.get("status") == "open"],
        "ambiguous": [row for row in orders if row.get("status") == "ambiguous"],
        "closed": closed,
        "orders": orders,
        "pnl_usd": pnl if closed else None,
        "trades": len(closed),
        "empty": not orders,
        "note": "Closed paper trades use an unrounded spot estimate and 11 bps per side. Ambiguous candles are not fills and are not counted. Nothing here is a broker result.",
    }


def as_fills(user_id):
    return [{"kind": "paper_fill", "pnl": row.get("pnl_usd")} for row in summary(user_id)["closed"]]
