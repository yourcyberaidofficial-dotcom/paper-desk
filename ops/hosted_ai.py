"""Hosted Aureon AI. Customers do not install a model and cannot turn this off.

Live inference stays blocked until the owner sets a provider URL, a model
name, an API key, and AUREON_AI_SPEND_APPROVED=1. A missing credential is
not replaced with a fake analysis.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from ops.ai_safety import foreign_evidence, invented_numbers, order_language, question_requests_action

PROMPT_VERSION = "aureon-hosted-1"
_USAGE = {}

PAGE_TASK = {
    "/overview": "portfolio",
    "/": "portfolio",
    "/trading": "market_watch",
    "/scanner": "why_quiet",
    "/signals": "explain_signal",
    "/strategies": "research",
    "/research": "research",
    "/plan": "risk",
    "/portfolio": "portfolio",
    "/orders": "journal",
    "/history": "journal",
    "/activity": "journal",
    "/risk": "risk",
    "/notifications": "why_quiet",
    "/live": "why_quiet",
    "/settings": "risk",
    "/learn": "academy",
    "/indicators": "academy",
    "/lab": "journal",
    "/system": "why_quiet",
    "/onboarding": "risk",
}


def configured():
    key = os.environ.get("AUREON_AI_API_KEY", "").strip()
    base = os.environ.get("AUREON_AI_BASE_URL", "").strip()
    model = os.environ.get("AUREON_AI_MODEL", "").strip()
    approved = os.environ.get("AUREON_AI_SPEND_APPROVED", "").strip() == "1"
    return bool(key and base.startswith("https://") and model and approved)


def status():
    ready = configured()
    return {
        "compulsory": True,
        "customer_toggle": False,
        "operational": "READY" if ready else "BLOCKED",
        "reason": None if ready else "provider_not_configured",
        "provider": "hosted" if ready else None,
        "live_model": "NOT TESTED" if not ready else os.environ.get("AUREON_AI_MODEL", "").strip(),
        "note": (
            "Aureon AI is part of the desk. The hosted model is not configured, so this is not an analysis."
            if not ready else
            "The hosted provider is configured. A reply is still not a signal and not an order."
        ),
    }


def _facts(user_id, task, symbol, interval):
    from ops.ai_evidence import build

    bundle = build(user_id, task, symbol, interval)
    if bundle.get("ok") is False:
        return bundle
    lines = list(bundle.get("facts") or [])
    return {"ok": True, "facts": lines, "refs": list(bundle.get("refs") or [])}


def _foreign_account(user_id, question):
    text = (question or "").lower()
    if not text:
        return False
    from ops.users import ROOT

    if not ROOT.exists():
        return False
    for path in ROOT.glob("*.json"):
        other = path.stem
        name = ""
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(record, dict):
                other = str(record.get("id") or other)
                name = str(record.get("name") or "").strip().lower()
        except (OSError, ValueError):
            name = ""
        if not other or other == user_id:
            continue
        if other.lower() in text:
            return True
        if len(name) >= 4 and re.search(r"\b" + re.escape(name) + r"\b", text):
            return True
    return False


def _account_usage(user_id, called):
    row = _USAGE.setdefault(str(user_id), {"requests": 0, "provider_calls": 0})
    row["requests"] += 1
    if called:
        row["provider_calls"] += 1
    return {"requests": row["requests"], "provider_calls": row["provider_calls"], "durable_billing": False}


def _finish(user_id, body, called):
    body["prompt_version"] = PROMPT_VERSION
    body["usage"] = {
        "provider_called": bool(called),
        "retries": 0,
        "timeout_seconds": 8,
        "prompt_version": PROMPT_VERSION,
        "account": _account_usage(user_id, called),
    }
    try:
        from ops.activity import record

        record(
            "hosted_ai_request",
            account_id=user_id,
            component="hosted_ai",
            detail={
                "page": body.get("page"),
                "called": bool(called),
                "operational": body.get("operational"),
                "reason": body.get("reason"),
            },
        )
    except Exception:
        pass
    return body


_IDENTIFIER = re.compile(r"[A-Za-z0-9]+(?:[-_:][A-Za-z0-9]+){1,}")
_SHORT_NUMBER = re.compile(r"\b\d{1,2}\b")


def _validate(summary, facts, refs, used):
    allowed_lines = list(facts) + list(refs)
    allowed_text = "\n".join(allowed_lines)
    if order_language(summary) or invented_numbers(summary, allowed_lines):
        return False
    known_numbers = set()
    for item in allowed_lines:
        known_numbers.update(re.findall(r"\d+", str(item)))
    for raw in _SHORT_NUMBER.findall(str(summary)):
        if raw not in known_numbers:
            return False
    haystack = allowed_text.lower()
    for token in _IDENTIFIER.findall(str(summary)):
        if token.lower() not in haystack:
            return False
    if foreign_evidence(used, allowed_text):
        return False
    return True


def complete(user_id, page, question=None, symbol=None, interval=None, transport=None):
    """Answer from authorised records. No credential means no model call."""
    task = PAGE_TASK.get(page or "/overview", "ask")
    page = page or "/overview"
    if question and question_requests_action(question):
        return _finish(user_id, _refused("order_request_refused", task, page), False)
    if _foreign_account(user_id, question):
        return _finish(user_id, _refused("other_account_refused", task, page), False)
    evidence = _facts(user_id, task, symbol, interval)
    if evidence.get("ok") is False:
        return _finish(user_id, _refused(evidence.get("reason") or "unknown_signal", task, page), False)
    body = {
        "ok": False,
        "task": task,
        "page": page,
        "approved": False,
        "order_opened": False,
        "broker": False,
        "analysis": None,
        "stored_record": evidence["facts"],
        "evidence_refs": evidence["refs"],
        "label": "stored_record_not_an_analysis",
    }
    body.update(status())
    if not configured():
        return _finish(user_id, body, False)
    payload = {
        "model": os.environ.get("AUREON_AI_MODEL", "").strip(),
        "prompt_version": PROMPT_VERSION,
        "messages": [
            {"role": "system", "content": "Explain only the supplied facts. Do not invent prices, probabilities, or orders. Prompt " + PROMPT_VERSION + "."},
            {"role": "user", "content": json.dumps({"facts": evidence["facts"], "refs": evidence["refs"], "question": (question or "")[:500]})[:4000]},
        ],
    }
    try:
        if transport is not None:
            code, decoded = transport("POST", os.environ.get("AUREON_AI_BASE_URL", ""), payload)
        else:
            code, decoded = _post(payload)
    except Exception:
        body["reason"] = "provider_unavailable"
        body["operational"] = "BLOCKED"
        return _finish(user_id, body, True)
    if code != 200 or not isinstance(decoded, dict):
        body["reason"] = "provider_unavailable"
        body["operational"] = "BLOCKED"
        return _finish(user_id, body, True)
    summary = str(decoded.get("summary") or "")
    used = decoded.get("evidence_used") if isinstance(decoded.get("evidence_used"), list) else []
    if not summary or not _validate(summary, evidence["facts"], evidence["refs"], used):
        body["reason"] = "invalid_output"
        return _finish(user_id, body, True)
    body["ok"] = True
    body["analysis"] = summary
    body["label"] = "ai_commentary_not_a_signal"
    return _finish(user_id, body, True)


def _refused(reason, task, page="/overview"):
    refused = status()
    refused.update({
        "ok": False,
        "reason": reason,
        "task": task,
        "page": page,
        "approved": False,
        "order_opened": False,
        "broker": False,
        "analysis": None,
        "stored_record": [],
    })
    return refused


def _post(payload):
    request = urllib.request.Request(
        os.environ.get("AUREON_AI_BASE_URL", "").rstrip("/") + "/v1/chat",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ.get("AUREON_AI_API_KEY", "").strip(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}
