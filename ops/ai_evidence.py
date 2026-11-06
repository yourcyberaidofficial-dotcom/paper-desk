"""Server-built evidence. Client text is not a market fact."""

from __future__ import annotations

from ops.ai_safety import PROMPT_VERSION, redact_numbers, scrub_untrusted


def _rows(symbol, interval):
    from ops.signal_ledger import read

    found = []
    for row in read():
        if symbol not in (None, "", row.get("symbol")):
            continue
        if interval not in (None, "", row.get("interval")):
            continue
        found.append(row)
    return found


def _paper(user_id):
    from ops.paperbook import summary

    book = summary(user_id) if user_id else {"open": [], "closed": [], "orders": [], "performance": {}}
    performance = book.get("performance") or {}
    return {
        "open": len(book.get("open") or []),
        "closed": int(performance.get("trades") or 0),
        "ambiguous": len(book.get("ambiguous") or []),
    }


def _profile(user_id):
    if not user_id:
        return {}
    from ops.users import get

    user = get(user_id) or {}
    profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
    lab = user.get("lab") if isinstance(user.get("lab"), dict) else {}
    notes = []
    for row in lab.get("journal_notes") or []:
        if isinstance(row, dict) and row.get("text"):
            notes.append(scrub_untrusted(row.get("text")))
    return {
        "persona": profile.get("signal_style_name") or "not set",
        "risk_per_trade": profile.get("max_risk_pct"),
        "daily_loss": profile.get("max_daily_loss_percent"),
        "journal_notes": len([item for item in notes if item]),
        "lessons_completed": len(lab.get("completed_lessons") or []),
    }


def build(user_id, task, symbol=None, interval=None, signal_id=None, lesson_id=None):
    rows = _rows(symbol, interval)
    if signal_id:
        rows = [row for row in rows if row.get("opportunity_id") == signal_id]
        if not rows:
            return {"ok": False, "reason": "unknown_signal"}
    latest = rows[-1] if rows else None
    paper = _paper(user_id)
    profile = _profile(user_id)
    refs = []
    unavailable = []
    for index, row in enumerate(rows[-8:]):
        ref = f"ledger:{index}:{row.get('symbol')}:{row.get('interval')}:{row.get('observation')}"
        refs.append(ref)
        if row.get("observation") == "data_unavailable" or row.get("freshness") in {"stale", "not_retrieved"}:
            unavailable.append(ref)
    if not rows:
        unavailable.append("no_stored_observation")
    facts = [
        f"task {task}",
        f"stored observations {len(rows)}",
        f"latest observation {(latest or {}).get('observation') or 'none'}",
        f"latest research {(latest or {}).get('research') or 'not_promoted'}",
        f"latest execution {(latest or {}).get('execution') or 'not_eligible'}",
        f"open paper positions {paper['open']}",
        f"closed paper trades {paper['closed']}",
        f"journal notes {profile.get('journal_notes') or 0}",
        f"persona {profile.get('persona') or 'not set'}",
        "broker false",
        "approved false",
    ]
    if task in {"why_quiet", "why_no_setup", "explain_missing"}:
        facts.append("No new confirmed signal is claimed when the stored observation is data_unavailable or research_failed.")
    if task == "explain_invalidated":
        facts.append("Invalidated and expired rows stay in the history.")
    if task == "compare":
        symbols = sorted({row.get("symbol") for row in rows if row.get("symbol")})
        facts.append("symbols " + (", ".join(symbols) if symbols else "none"))
    if task == "research":
        from ops.qualification import catalog

        body = catalog()
        facts.append(f"approved for paper {body.get('approved_for_paper') or 0}")
        facts.append("A research failure does not delete a stored observation.")
    if task == "academy":
        from ops.academy import catalog as lessons

        known = {item.get("id"): item.get("title") for item in lessons()}
        title = known.get(lesson_id) if lesson_id else None
        facts.append("lesson " + (title or "not selected"))
        facts.append(f"completed lessons {profile.get('lessons_completed') or 0}")
        if lesson_id and lesson_id not in known:
            unavailable.append("unknown_lesson")
    model_view = {
        "symbol": symbol or (latest or {}).get("symbol") or "not_selected",
        "interval": interval or (latest or {}).get("interval") or "not_selected",
        "task": task,
        "observation": facts[2],
        "research": facts[3],
        "execution": facts[4],
        "paper_status": facts[5] + ". " + facts[6],
        "lifecycle": (latest or {}).get("observation") or "none",
        "freshness": redact_numbers((latest or {}).get("freshness") or "not_stored"),
        "source": redact_numbers((latest or {}).get("source_id") or "none"),
        "signal_ref": redact_numbers((latest or {}).get("opportunity_id") or "none"),
        "conditions": redact_numbers((latest or {}).get("conditions") or "none"),
        "note": redact_numbers((latest or {}).get("note") or "none"),
    }
    return {
        "ok": True,
        "prompt_version": PROMPT_VERSION,
        "task": task,
        "facts": facts,
        "refs": refs,
        "unavailable": unavailable,
        "model_view": {key: value for key, value in model_view.items() if isinstance(value, str)},
        "account_scope": user_id or "",
    }
