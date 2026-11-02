"""Account-authorised paper automation. Off until the account enables it."""

from ops.files import update_json
from ops.profiles import canonical_style, get_profile

STATUSES = {"off", "running", "paused", "stopped"}


def _path(user_id):
    from ops.users import ROOT
    return ROOT / f"{user_id}.json"


def default_state():
    return {
        "enabled": False,
        "status": "off",
        "max_orders_per_day": None,
        "enabled_ms": None,
        "updated_ms": None,
        "last_evaluation_ms": None,
        "last_opportunity_id": None,
        "rejections": [],
        "last_error": None,
    }


def view(user):
    raw = (user or {}).get("autopilot") if isinstance((user or {}).get("autopilot"), dict) else {}
    state = default_state()
    state.update({key: raw.get(key) for key in state if key in raw})
    if state["status"] not in STATUSES or not state["enabled"]:
        state["status"] = "off"
        state["enabled"] = False
    state["accepts_new_entries"] = state["enabled"] and state["status"] == "running"
    state["paper_only"] = True
    state["broker"] = False
    state["note"] = "AutoPilot can open a paper trade only while it is running. Pause and emergency stop block new entries. They do not close an open paper position."
    return state


def _write(user_id, mutator):
    path = _path(user_id)
    if path is None or not path.exists():
        return None

    def apply(current):
        if not isinstance(current, dict):
            return {"unreadable": True}
        mutator(current)
        return current

    updated = update_json(path, apply, None)
    if not isinstance(updated, dict) or updated.get("unreadable"):
        return None
    updated.pop("password_hash", None)
    return updated


def act(user_id, action, now_ms, confirm=False, max_orders_per_day=None):
    if action == "enable" and confirm is not True:
        return {"ok": False, "reason": "confirmation_required"}
    holder = {}

    def mutate(user):
        state = view(user)
        persona = get_profile(canonical_style(((user.get("profile") or {}).get("signal_style"))))
        cap = int(persona["max_trades_per_day"]) if persona else None
        if action == "enable":
            chosen = state.get("max_orders_per_day")
            if max_orders_per_day not in (None, ""):
                try:
                    chosen = int(max_orders_per_day)
                except (TypeError, ValueError):
                    holder["result"] = {"ok": False, "reason": "bad_cap"}
                    return
            if chosen is not None and cap is not None:
                chosen = min(chosen, cap)
            if chosen is not None and chosen < 1:
                holder["result"] = {"ok": False, "reason": "bad_cap"}
                return
            state = default_state()
            state.update({"enabled": True, "status": "running", "max_orders_per_day": chosen, "enabled_ms": int(now_ms)})
        elif action == "pause":
            if not state["enabled"]:
                holder["result"] = {"ok": False, "reason": "not_enabled"}
                return
            state["status"] = "paused"
        elif action == "resume":
            if not state["enabled"] or state["status"] == "off":
                holder["result"] = {"ok": False, "reason": "not_enabled"}
                return
            state["status"] = "running"
        elif action == "emergency_stop":
            if not state["enabled"]:
                holder["result"] = {"ok": False, "reason": "not_enabled"}
                return
            state["status"] = "stopped"
        elif action == "disable":
            state = default_state()
        else:
            holder["result"] = {"ok": False, "reason": "unknown_action"}
            return
        state["updated_ms"] = int(now_ms)
        state["accepts_new_entries"] = state["enabled"] and state["status"] == "running"
        user["autopilot"] = {key: state[key] for key in default_state()}
        holder["result"] = {"ok": True, "autopilot": view(user)}

    written = _write(user_id, mutate)
    if written is None and "result" not in holder:
        return {"ok": False, "reason": "missing_user"}
    return holder.get("result") or {"ok": False, "reason": "missing_user"}


def note(user_id, now_ms, opportunity_id=None, rejection=None, error=None):
    def mutate(user):
        state = view(user)
        state["last_evaluation_ms"] = int(now_ms)
        if opportunity_id:
            state["last_opportunity_id"] = opportunity_id
        if error:
            state["last_error"] = str(error)[:160]
        if rejection:
            rows = list(state.get("rejections") or [])
            rows.append({"ms": int(now_ms), "opportunity_id": opportunity_id, "reason": rejection})
            state["rejections"] = rows[-20:]
        user["autopilot"] = {key: state[key] for key in default_state()}

    _write(user_id, mutate)


def consider(user, result, now_ms, opportunity_id=None):
    """Open one paper order only when this account's bot is running and every existing check passes."""
    user = user or {}
    user_id = user.get("id")
    state = view(user)
    result = result or {}
    if state["enabled"]:
        note(user_id, now_ms, opportunity_id)
    if not state["accepts_new_entries"]:
        return {"attempted": False, "reason": state["status"]}
    decision = result.get("decision")
    if result.get("blocked") or decision not in {"BUY", "SELL"} or result.get("entry") is None:
        reason = result.get("blocked") or "not_a_plan"
        note(user_id, now_ms, opportunity_id, rejection=reason)
        return {"attempted": True, "ok": False, "reason": reason}
    from ops.paperbook import open_order
    row = {
        "opportunity_id": opportunity_id or result.get("id"),
        "symbol": result.get("symbol"),
        "interval": result.get("interval"),
        "direction": decision,
        "entry": result.get("entry"),
        "stop": result.get("stop"),
        "target": result.get("target"),
        "lifecycle": "active",
        "family": result.get("rule") or result.get("strategy"),
    }
    opened = open_order(user, row, now_ms, opened_by="autopilot", automation_cap=state.get("max_orders_per_day"))
    if opened.get("ok"):
        note(user_id, now_ms, row.get("opportunity_id"))
    else:
        note(user_id, now_ms, row.get("opportunity_id"), rejection=opened.get("reason"))
    return {"attempted": True, **opened}
