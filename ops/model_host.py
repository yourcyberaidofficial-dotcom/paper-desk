"""OpenAI-compatible hosted model client.

No local model is started. A missing key, URL, model, or spend approval
does not call the network and does not invent a completion.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

_LIMITER = None
_LIMIT = None


def _int_env(name, default, low, high):
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        value = default
    return min(max(value, low), high)


def requirements():
    """Exact configuration still required. The key itself is never returned."""
    key = os.environ.get("AUREON_AI_API_KEY", "").strip()
    base = os.environ.get("AUREON_AI_BASE_URL", "").strip()
    model = os.environ.get("AUREON_AI_MODEL", "").strip()
    fallback = os.environ.get("AUREON_AI_FALLBACK_MODEL", "").strip() or None
    approved = os.environ.get("AUREON_AI_SPEND_APPROVED", "").strip() == "1"
    missing = []
    if not key:
        missing.append("api_key")
    if not base.startswith("https://"):
        missing.append("base_url")
    if not model:
        missing.append("model")
    if not approved:
        missing.append("spend_approval")
    return {
        "provider": "openai-compatible",
        "primary_model": model or None,
        "fallback_model": fallback,
        "base_url_set": bool(base.startswith("https://")),
        "spend_approved": approved,
        "timeout_seconds": _int_env("AUREON_AI_TIMEOUT_SECONDS", 8, 1, 30),
        "concurrency": _int_env("AUREON_AI_CONCURRENCY", 2, 1, 8),
        "missing": missing,
        "settings": {
            "api_key": "AUREON_AI_API_KEY",
            "base_url": "AUREON_AI_BASE_URL",
            "model": "AUREON_AI_MODEL",
            "fallback_model": "AUREON_AI_FALLBACK_MODEL",
            "spend_approval": "AUREON_AI_SPEND_APPROVED=1",
            "timeout_seconds": "AUREON_AI_TIMEOUT_SECONDS",
            "concurrency": "AUREON_AI_CONCURRENCY",
        },
        "configured": not missing,
        "local_model": False,
    }


def _limiter():
    global _LIMITER, _LIMIT
    size = requirements()["concurrency"]
    if _LIMITER is None or _LIMIT != size:
        _LIMITER = threading.BoundedSemaphore(size)
        _LIMIT = size
    return _LIMITER


def health(transport=None, allow_network=False):
    """Connectivity check. The default path does not open a socket."""
    spec = requirements()
    body = {
        "operational": "BLOCKED" if spec["missing"] else "CONFIGURED",
        "reason": "provider_not_configured" if spec["missing"] else None,
        "missing": list(spec["missing"]),
        "primary_model": spec["primary_model"],
        "fallback_model": spec["fallback_model"],
        "model_available": False,
        "live": False,
        "network": False,
        "local_model": False,
    }
    if spec["missing"] or not allow_network:
        if not spec["missing"] and not allow_network:
            body["reason"] = "health_probe_not_requested"
        return body
    base = os.environ.get("AUREON_AI_BASE_URL", "").strip().rstrip("/")
    try:
        status, payload, _headers = _exchange("GET", base + "/v1/models", None, transport)
    except Exception:
        body["operational"] = "BLOCKED"
        body["reason"] = "provider_unavailable"
        body["network"] = True
        return body
    body["network"] = True
    names = []
    if status == 200 and isinstance(payload, dict):
        names = [str(item.get("id")) for item in payload.get("data") or [] if isinstance(item, dict)]
    wanted = spec["primary_model"]
    if status != 200 or wanted not in names:
        body["operational"] = "BLOCKED"
        body["reason"] = "model_unavailable" if status == 200 else "provider_unavailable"
        return body
    body["model_available"] = True
    body["live"] = False
    return body


def chat(messages, prompt_version=None, transport=None):
    """One completion. Primary model, then the optional fallback. No invented text."""
    spec = requirements()
    if spec["missing"]:
        return {"ok": False, "status": 0, "reason": "provider_not_configured", "summary": None, "network": False, "retries": 0}
    started = time.perf_counter()
    primary = spec["primary_model"]
    result = _attempt(messages, primary, transport, spec["timeout_seconds"])
    fallback_used = False
    if not result["ok"] and spec["fallback_model"] and result["reason"] in {"provider_unavailable", "rate_limited", "timeout"}:
        result = _attempt(messages, spec["fallback_model"], transport, spec["timeout_seconds"])
        fallback_used = True
        result["retries"] = result.get("retries", 0) + 1
    result["fallback_used"] = fallback_used
    result["model_id"] = result.get("model_id") or primary
    result["prompt_version"] = prompt_version
    result["latency_ms"] = int((time.perf_counter() - started) * 1000)
    result["summary"] = result["summary"] if result.get("ok") else None
    return result


def _attempt(messages, model, transport, timeout):
    base = os.environ.get("AUREON_AI_BASE_URL", "").strip().rstrip("/")
    payload = {"model": model, "temperature": 0, "messages": messages}
    retries = 0
    last = {"ok": False, "status": 503, "reason": "provider_unavailable", "summary": None, "model_id": model, "retries": 0}
    for _pass in (1, 2):
        try:
            with _limiter():
                status, decoded, headers = _exchange("POST", base + "/v1/chat/completions", payload, transport, timeout)
        except TimeoutError:
            last = {"ok": False, "status": 504, "reason": "timeout", "summary": None, "model_id": model, "retries": retries}
            retries += 1
            continue
        except Exception:
            last = {"ok": False, "status": 503, "reason": "provider_unavailable", "summary": None, "model_id": model, "retries": retries}
            retries += 1
            continue
        if status == 429 or status >= 500:
            last = {
                "ok": False,
                "status": status,
                "reason": "rate_limited" if status == 429 else "provider_unavailable",
                "summary": None,
                "model_id": model,
                "retries": retries,
            }
            retries += 1
            if status == 429 and transport is None:
                delay = headers.get("retry-after") if isinstance(headers, dict) else None
                try:
                    time.sleep(min(max(int(delay), 0), 2))
                except (TypeError, ValueError):
                    pass
            continue
        if status in {401, 403}:
            return {"ok": False, "status": status, "reason": "provider_rejected", "summary": None, "model_id": model, "retries": retries}
        summary = _content(decoded)
        if status != 200 or not summary:
            return {"ok": False, "status": status or 502, "reason": "invalid_output", "summary": None, "model_id": model, "retries": retries}
        return {"ok": True, "status": 200, "reason": None, "summary": summary, "model_id": model, "retries": retries}
    last["retries"] = retries
    return last


def _content(payload):
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
    content = message.get("content")
    return content if isinstance(content, str) and content.strip() else None


def _exchange(method, url, payload, transport, timeout=8):
    if transport is not None:
        status, decoded, headers = transport(method, url, payload)
        return status, decoded, headers or {}
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ.get("AUREON_AI_API_KEY", "").strip(),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode() or "{}"
            return response.status, json.loads(raw), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            decoded = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            decoded = {}
        return exc.code, decoded, dict(exc.headers.items()) if exc.headers else {}
