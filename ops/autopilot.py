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


def presentation(state, worker_healthy, open_positions=None, gates=None):
    """One account-facing label. Stored status is unchanged and is not shown as Running.

    Permission, strategy approval, and execution eligibility stay separate.
    """
    status = (state or {}).get("status") or "off"
    enabled = bool((state or {}).get("enabled")) and status != "off"
    updated = (state or {}).get("updated_ms")

    def pack(facing, entries, note, kind, blockers=None, approval="not_checked"):
        body = {
            "facing": facing,
            "entries_available": entries,
            "facing_note": note,
            "state_kind": kind,
            "updated_ms": updated,
            "blockers": list(blockers or []),
            "permission": "granted" if enabled else "not_granted",
            "strategy_approval": approval,
            "execution": "eligible" if entries else "not_eligible",
        }
        return body

    if not enabled:
        return pack("Disabled", False, "Permission is not active. New automated entries are blocked.", "disabled", approval="not_checked")
    if status == "paused":
        return pack("Paused", False, "New entries are blocked. Open paper positions stay open and are not closed.", "paused")
    if status == "stopped":
        return pack("Emergency stop", False, "New entries are blocked. Open paper positions are not closed.", "stopped")
    if worker_healthy is not True:
        return pack(
            "Health not confirmed",
            False,
            "Permission is on, but worker health is not confirmed. New entries are not treated as available.",
            "unhealthy",
        )
    blockers = []
    approved = None
    if isinstance(gates, dict):
        if gates.get("market_data") == "rights_withheld":
            blockers.append("market_data_rights")
        approved = None
        if gates.get("approved_for_paper"):
            approved = "present"
        elif gates.get("approved_for_paper") == 0:
            approved = "paper_signals"
    if blockers:
        parts = []
        if "market_data_rights" in blockers:
            parts.append("Market data rights are unconfirmed.")
        if "no_approved_strategy" in blockers:
            parts.append("No strategy is approved for paper.")
        facing = "Permission on — not operational"
        return pack(
            facing,
            False,
            " ".join(parts) + " Existing paper positions stay monitored. Permission is not execution.",
            "blocked",
            blockers,
            approval=approved or "absent",
        )
    if open_positions == 0:
        if gates is not None:
            return pack(
                "Operational — waiting for an eligible paper opportunity",
                True,
                "Permission and worker health allow a new paper entry. A completed public-candle plan can open one. Nothing is sent to a live exchange.",
                "waiting",
                approval="present",
            )
        return pack(
            "Waiting",
            True,
            "Permission is on and the worker heartbeat is current. No qualifying paper opportunity is open. Nothing is entered until a plan passes every check.",
            "waiting",
        )
    return pack(
        "Operational",
        True,
        "Permission is on and the worker heartbeat is current. Open paper positions stay monitored. A new plan is opened only when it qualifies.",
        "enabled",
        approval="present" if approved == "present" else "not_checked",
    )


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
    state["note"] = "AutoPilot can open a paper trade only while this account has enabled it and the worker heartbeat is current. Pause and emergency stop block new entries. They do not close an open paper position."
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


_RISK_REASONS = frozenset({
    "below_persona_reward",
    "daily_count",
    "daily_loss",
    "weekly_loss",
    "open_risk",
    "automation_cap",
    "no_persona",
    "persona_timeframe",
    "unsized",
    "market",
    "timeframe",
    "incomplete",
    "not_a_plan",
    "opportunity_closed",
    "buy_off",
    "sell_off",
})


def _audit(user_id, now_ms, opportunity_id, reason, result=None):
    """Append the refusal. The account rejection list can drop old rows. This file does not."""
    try:
        from ops.activity import record

        result = result or {}
        reason = str(reason or "")
        if not reason:
            return
        if reason == "no_approved_strategy":
            kind = "strategy_rejected"
            text = "AutoPilot did not open it. No approved strategy. The observation was not removed."
        elif reason == "commercial_use_unverified":
            kind = "source_unavailable"
            text = "No authorised reading. AutoPilot did not open an order."
        elif reason == "quote_divergence":
            kind = "reading_stale"
            text = "The quote did not agree with the candle. No order was opened and no price was stored here."
        else:
            kind = "risk_rejected"
            text = "The paper order was refused. The observation was not removed."
        record(
            kind,
            account_id=user_id,
            entity=opportunity_id or f"{result.get('symbol')}:{result.get('interval')}:{reason}",
            component="autopilot",
            detail={
                "note": text,
                "reason": reason[:80],
                "symbol": result.get("symbol"),
                "interval": result.get("interval"),
            },
            now_ms=int(now_ms),
        )
    except Exception:
        pass


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
    """Open a paper order only when the account allowed automation and the strategy version is approved for paper."""
    user = user or {}
    user_id = user.get("id")
    state = view(user)
    result = result or {}
    from ops.data_rights import is_rights_reason
    if result.get("rights_status") in {"rights_unconfirmed", "prohibited", "restricted", "fixture_only"} or is_rights_reason(result.get("reason")) or is_rights_reason(result.get("blocked")):
        if state["enabled"]:
            note(user_id, now_ms, opportunity_id, rejection="commercial_use_unverified")
        _audit(user_id, now_ms, opportunity_id, "commercial_use_unverified", result)
        return {"attempted": False, "ok": False, "reason": "commercial_use_unverified", "order": False}
    if state["enabled"]:
        note(user_id, now_ms, opportunity_id)
    if not state["accepts_new_entries"]:
        return {"attempted": False, "reason": state["status"]}
    decision = result.get("decision")
    if result.get("runtime_status") == "quote_divergence":
        note(user_id, now_ms, opportunity_id, rejection="quote_divergence")
        _audit(user_id, now_ms, opportunity_id, "quote_divergence", result)
        return {"attempted": True, "ok": False, "reason": "quote_divergence"}
    if result.get("blocked") or decision not in {"BUY", "SELL"} or result.get("entry") is None:
        reason = result.get("blocked") or "not_a_plan"
        note(user_id, now_ms, opportunity_id, rejection=reason)
        _audit(user_id, now_ms, opportunity_id, reason, result)
        return {"attempted": True, "ok": False, "reason": reason}
    from ops.paperbook import open_order
    from ops.qualification import autopilot_may_open
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
    probe = open_order(user, row, now_ms, commit=False, opened_by="autopilot", automation_cap=state.get("max_orders_per_day"))
    if not probe.get("ok"):
        note(user_id, now_ms, row.get("opportunity_id"), rejection=probe.get("reason"))
        _audit(user_id, now_ms, row.get("opportunity_id"), probe.get("reason"), result)
        return {"attempted": True, "ok": False, "reason": probe.get("reason")}
    if not autopilot_may_open(result):
        note(user_id, now_ms, row.get("opportunity_id"), rejection="no_approved_strategy")
        _audit(user_id, now_ms, row.get("opportunity_id"), "no_approved_strategy", result)
        return {"attempted": True, "ok": False, "reason": "no_approved_strategy", "approved_strategy": False}
    opened = open_order(user, row, now_ms, opened_by="autopilot", automation_cap=state.get("max_orders_per_day"))
    if opened.get("ok"):
        note(user_id, now_ms, row.get("opportunity_id"))
    else:
        note(user_id, now_ms, row.get("opportunity_id"), rejection=opened.get("reason"))
        _audit(user_id, now_ms, row.get("opportunity_id"), opened.get("reason"), result)
    return {"attempted": True, **opened}
