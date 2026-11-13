"""Lab, academy save, and qualification. Learning does not approve a strategy."""

from flask import Blueprint, jsonify, request, session

bp = Blueprint("research_api", __name__)


def _account_learning(user_id):
    """Local paper diagnostics. This does not call Ollama and does not approve."""
    from ops.learning import for_account

    report = for_account(user_id)
    report["changes_approval"] = False
    report["promotes"] = False
    report["confidence"] = None
    return report


def _empty_research():
    return {
        "sample": "not_enough_evidence",
        "closed_trades": 0,
        "hypotheses": [{
            "statement": "Not enough evidence. No account paper book was read.",
            "sample": "not_enough_evidence",
            "n": 0,
            "promotes": False,
            "confidence": None,
            "changes_approval": False,
        }],
        "promotes": False,
        "confidence": None,
        "changes_approval": False,
        "model": {"called": False, "required": False},
        "simulation": {"ran": False, "reason": "bars_not_supplied", "promotes": False, "confidence": None},
        "note": "Qualification is the registry. This request did not read a paper book.",
    }


@bp.get("/api/lab")
def lab_state():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    user_id, user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    if not user:
        return jsonify({"error": "not_found"}), 404
    from ops.academy import catalog, courses, public_rules, suggestions
    from ops.autopilot import presentation, view
    from ops.desk_state import product_gates
    from ops.paperbook import summary
    from ops.profiles import canonical_style, get_profile
    lab = user.get("lab") if isinstance(user.get("lab"), dict) else {}
    book = summary(user_id)
    persona = get_profile(canonical_style((user.get("profile") or {}).get("signal_style")))
    auto = view(user)
    opened = sum(1 for row in (book.get("orders") or []) if row.get("opened_by") == "autopilot" and row.get("status") == "open")
    auto.update(presentation(auto, _worker_public().get("healthy") is True, open_positions=opened, gates=product_gates()))
    trades = (book.get("performance") or {}).get("trades") or 0
    journal = []
    for row in (book.get("orders") or [])[-8:]:
        journal.append({
            "id": row.get("id"),
            "symbol": row.get("symbol"),
            "opened_by": row.get("opened_by") or "account",
            "status": row.get("status"),
            "exit_kind": row.get("exit_kind"),
            "note": (row.get("events") or [{}])[-1].get("note") or row.get("note"),
        })
    return jsonify({
        "profile": user.get("profile") or {},
        "experience": lab.get("experience") or "not_stated",
        "objective": lab.get("objective") or "",
        "focus": lab.get("focus") or [],
        "completed_lessons": lab.get("completed_lessons") or [],
        "persona": {"name": persona.get("name"), "min_rr": persona.get("min_rr"), "risk_per_trade_percent": persona.get("risk_per_trade_percent"), "paper_timeframes": persona.get("paper_timeframes")} if persona else None,
        "autopilot": auto,
        "performance": book.get("performance"),
        "lessons": catalog(),
        "courses": courses(),
        "rules": public_rules(user),
        "journal": journal,
        "journal_notes": lab.get("journal_notes") or [],
        "improvement": suggestions(lab, book.get("performance")),
        "preferences": {"markets": (user.get("prefs") or {}).get("markets") or [], "plan_markets": (user.get("plan") or {}).get("markets")},
        "observation": "Not enough closed paper trades to describe a strength or a weakness." if trades < 5 else "Counts below are closed paper trades only. They are not a skill score and not a profitable strategy.",
        "note": "This page reads this account only. It does not create a strategy.",
        "learning": _account_learning(user_id),
    })


@bp.post("/api/lab")
def lab_save():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.academy import catalog
    from ops.files import update_json
    from ops.users import ROOT
    body = request.json or {}
    experience = body.get("experience") if body.get("experience") in {"new", "developing", "independent"} else None
    objective = str(body.get("objective") or "")[:160]
    focus = [item for item in (body.get("focus") or []) if item in {"candles", "risk", "psychology", "prop"}][:4]
    completed = [str(item)[:40] for item in (body.get("completed_lessons") or [])][:40]
    rule = str(body.get("custom_rule") or "")[:400]
    reflection = str(body.get("journal_note") or "")[:500]
    known = {lesson["id"] for lesson in catalog()}

    def apply(user):
        if not isinstance(user, dict):
            return {"unreadable": True}
        lab = user.get("lab") if isinstance(user.get("lab"), dict) else {}
        if experience:
            lab["experience"] = experience
        if "objective" in body:
            lab["objective"] = objective
        if "focus" in body:
            lab["focus"] = focus
        if "completed_lessons" in body:
            lab["completed_lessons"] = [item for item in completed if item in known]
        if rule:
            rows = list(lab.get("custom_rules") or [])
            rows.append({"text": rule, "verified": False})
            lab["custom_rules"] = rows[-10:]
        if reflection:
            notes = list(lab.get("journal_notes") or [])
            notes.append({"text": reflection, "inferred_behaviour": False})
            lab["journal_notes"] = notes[-20:]
        user["lab"] = lab
        return user

    update_json(ROOT / f"{user_id}.json", apply, None)
    return jsonify({"ok": True})


@bp.get("/api/qualification")
def qualification_api():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    if not _gate():
        return jsonify({"error": "unauthorized"}), 401
    from ops.qualification import catalog, paper_research
    body = catalog()
    user_id = session.get("user_id")
    if user_id:
        body["paper_research"] = paper_research(user_id)
    else:
        body["paper_research"] = _empty_research()
    body["paper_research"]["changes_approval"] = False
    body["paper_research"]["promotes"] = False
    body["paper_research"]["confidence"] = None
    return jsonify(body)
