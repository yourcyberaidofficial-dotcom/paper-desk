"""Model-provider boundary.

The desk builds the evidence. A provider may only phrase it. Ollama is the
first provider. Replacing it means implementing ask_model with the same
return shape. One inference runs at a time. Offline answers still return
the stored facts.
"""

from __future__ import annotations

import threading

_LOCK = threading.Lock()

TASKS = (
    "explain_signal",
    "compare",
    "market_watch",
    "why_quiet",
    "explain_invalidated",
    "portfolio",
    "risk",
    "journal",
)


def _text(user_id, task, symbol, interval):
    from ops.paperbook import summary
    from ops.signal_ledger import read

    rows = [row for row in read() if symbol in (None, "", row.get("symbol")) and interval in (None, "", row.get("interval"))]
    latest = rows[-1] if rows else None
    book = summary(user_id) if user_id else {"open": [], "closed": [], "orders": [], "performance": {}}
    performance = book.get("performance") or {}
    lines = [
        f"task {task}",
        f"stored observations {len(rows)}",
        f"latest observation {(latest or {}).get('observation') or 'none'}",
        f"latest research {(latest or {}).get('research') or 'not_promoted'}",
        f"latest execution {(latest or {}).get('execution') or 'not_eligible'}",
        f"open paper positions {len(book.get('open') or [])}",
        f"closed paper trades {performance.get('trades') or 0}",
        "broker false",
        "approved false",
    ]
    if task == "why_quiet":
        lines.append("No new confirmed signal is claimed when the stored observation is data_unavailable or research_failed.")
    if task == "explain_invalidated":
        lines.append("Invalidated and expired rows stay in the history.")
    if task == "compare":
        symbols = sorted({row.get("symbol") for row in rows if row.get("symbol")})
        lines.append("symbols " + (", ".join(symbols) if symbols else "none"))
    return lines


def deterministic(lines):
    return " ".join(lines) + " This is the stored record. It is not a new signal and not an order."


def ask(user_id, task, symbol=None, interval=None, transport=None, now_ms=None):
    """Answer from stored records. The model cannot approve or trade."""
    import time

    stamp = int(now_ms if now_ms is not None else time.time() * 1000)
    if task not in TASKS:
        return {"ok": False, "reason": "unknown_task", "approved": False, "order_opened": False, "broker": False}
    lines = _text(user_id, task, symbol, interval)
    fallback = deterministic(lines)
    evidence = {
        "symbol": symbol or "desk",
        "interval": interval or "desk",
        "observation": lines[2],
        "research": lines[3],
        "execution": lines[4],
        "paper_status": lines[5] + ". " + lines[6],
        "note": fallback[:400],
        "lifecycle": task,
    }
    base = {
        "ok": True,
        "task": task,
        "approved": False,
        "order_opened": False,
        "broker": False,
        "created_ms": stamp,
        "fallback": fallback,
        "evidence": {key: value for key, value in evidence.items() if isinstance(value, str)},
        "model_status": "offline",
        "explanation": None,
    }
    if not _LOCK.acquire(blocking=False):
        base["model_status"] = "busy"
        base["reason"] = "busy"
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
        base["model_status"] = "online"
        base["model"] = status.get("model")
        base["reason"] = None if phrased.get("ok") else phrased.get("reason")
        base["explanation"] = phrased.get("explanation")
        if summary and any(token in summary.lower() for token in ("approve", "order", "buy now", "sell now")):
            base["explanation"]["summary"] = fallback
            base["explanation"]["approved"] = False
        base["approved"] = False
        base["order_opened"] = False
        return base
    finally:
        _LOCK.release()
