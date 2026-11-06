"""Model-provider boundary.

The desk builds the evidence. A provider may only phrase it. Ollama is the
first provider. One inference runs at a time. Offline answers still return
the stored facts. The model cannot approve a strategy or open an order.
"""

from __future__ import annotations

import os
import threading

from ops.ai_safety import PROMPT_VERSION, invented_numbers, local_model_allowed, order_language, question_requests_action

_LOCK = threading.Lock()

TASKS = (
    "ask",
    "explain_signal",
    "compare",
    "market_watch",
    "why_quiet",
    "explain_missing",
    "why_no_setup",
    "explain_invalidated",
    "portfolio",
    "risk",
    "journal",
    "research",
    "academy",
)


def deterministic(lines):
    return " ".join(lines) + " This is the stored record. It is not a new signal and not an order. AI analysis is not a deterministic signal."


def _refuse(reason, stamp):
    return {
        "ok": False,
        "reason": reason,
        "approved": False,
        "order_opened": False,
        "broker": False,
        "created_ms": stamp,
        "prompt_version": PROMPT_VERSION,
        "analysis_label": "ai_analysis_not_a_signal",
        "explanation": None,
        "fallback": None,
        "model_status": "refused",
    }


def ask(user_id, task, symbol=None, interval=None, transport=None, now_ms=None, signal_id=None, lesson_id=None, question=None):
    """Answer from stored records. The model cannot approve or trade."""
    import time

    stamp = int(now_ms if now_ms is not None else time.time() * 1000)
    if task not in TASKS:
        return _refuse("unknown_task", stamp)
    if question:
        from ops.ai_safety import scrub_untrusted

        if not scrub_untrusted(question) and str(question).strip():
            return _refuse("untrusted_input", stamp)
        if question_requests_action(question):
            return _refuse("order_request_refused", stamp)
    if not local_model_allowed(os.environ.get("OLLAMA_MODEL")):
        return _refuse("cloud_model_refused", stamp)
    from ops.ai_evidence import build

    bundle = build(user_id, task, symbol, interval, signal_id=signal_id, lesson_id=lesson_id)
    if bundle.get("ok") is False:
        return _refuse(bundle.get("reason") or "unknown_signal", stamp)
    lines = bundle["facts"]
    fallback = deterministic(lines)
    evidence = dict(bundle["model_view"])
    evidence["note"] = fallback[:400]
    base = {
        "ok": True,
        "task": task,
        "approved": False,
        "order_opened": False,
        "broker": False,
        "created_ms": stamp,
        "prompt_version": PROMPT_VERSION,
        "analysis_label": "ai_analysis_not_a_signal",
        "fallback": fallback,
        "evidence": {key: value for key, value in evidence.items() if isinstance(value, str)},
        "evidence_refs": list(bundle["refs"]),
        "verified_facts": list(lines),
        "unavailable": list(bundle["unavailable"]),
        "uncertainty": ["The model is not a signal. A missing source is not a setup."],
        "interpretation": None,
        "model_status": "offline",
        "explanation": None,
    }
    if not _LOCK.acquire(blocking=False):
        base["model_status"] = "busy"
        base["reason"] = "busy"
        _log(user_id, task, stamp, bundle, "busy", None)
        return base
    try:
        from ops.activity import record
        from ops.ollama import explain, health

        status = health(timeout=1.5, transport=transport)
        record(
            "ollama_status",
            account_id=user_id,
            component="ai",
            entity=f"ollama:{status.get('reason') or ('ready' if status.get('available') else 'offline')}",
            detail={"note": "Local model status. Not a market reading.", "reason": status.get("reason"), "model": status.get("model")},
            now_ms=stamp,
        )
        if status.get("available") is not True:
            base["reason"] = status.get("reason") or "offline"
            _log(user_id, task, stamp, bundle, base["reason"], status.get("model"))
            return base
        phrased = explain(evidence, timeout=8, transport=transport, now_ms=stamp)
        record(
            "ai_inference",
            account_id=user_id,
            component="ai",
            entity=f"ai:{task}:{symbol or 'desk'}:{interval or 'desk'}:{stamp}",
            detail={"note": "Inference used stored labels only. It did not approve a strategy or open an order.", "task": task, "model": status.get("model")},
            now_ms=stamp,
        )
        summary = ((phrased.get("explanation") or {}).get("summary") if phrased.get("ok") else None)
        used = ""
        if isinstance(phrased.get("explanation"), dict):
            used = " ".join(item for item in (phrased["explanation"].get("evidence_used") or []) if isinstance(item, str))
        blob = f"{summary or ''}\n{used}"
        base["model_status"] = "online" if phrased.get("ok") else "rejected"
        base["model"] = status.get("model")
        base["reason"] = None if phrased.get("ok") else phrased.get("reason")
        base["explanation"] = phrased.get("explanation")
        if phrased.get("ok") and (order_language(blob) or invented_numbers(blob, lines)):
            base["explanation"]["summary"] = fallback
            base["explanation"]["evidence_used"] = list(bundle["refs"])
            base["explanation"]["approved"] = False
            base["reason"] = "ungrounded"
            summary = fallback
        base["interpretation"] = summary
        base["approved"] = False
        base["order_opened"] = False
        _log(user_id, task, stamp, bundle, base["reason"] or "ok", status.get("model"))
        return base
    finally:
        _LOCK.release()


def _log(user_id, task, stamp, bundle, status, model):
    try:
        from ops.ai_log import record

        record({
            "user_id": user_id,
            "task": task,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "created_ms": stamp,
            "evidence_refs": list(bundle.get("refs") or []),
            "output_status": status,
            "broker": False,
            "approved": False,
        })
    except Exception:
        return None
