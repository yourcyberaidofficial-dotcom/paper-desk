"""One decision per closed candle.

The lock is per instrument and timeframe. Two passes cannot both decide
the same close. A revised or older candle is recorded and does not replace
the original decision.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import threading
from pathlib import Path

_GUARD = threading.Lock()
_THREADS = {}
_HELD = threading.local()


def fingerprint(bar):
    bar = bar or {}
    return "|".join(str(bar.get(key)) for key in ("open", "high", "low", "close"))


def _root():
    return Path(os.environ.get("AUREON_DATA") or "data") / "claims"


def _state_path(symbol, interval):
    return _root() / f"{symbol}-{interval}.json"


def _held():
    keys = getattr(_HELD, "keys", None)
    if keys is None:
        keys = set()
        _HELD.keys = keys
    return keys


def _thread_lock(key):
    with _GUARD:
        lock = _THREADS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREADS[key] = lock
        return lock


@contextlib.contextmanager
def exclusive(symbol, interval):
    """Yield True when this caller acquired the lock, False when it already holds it."""
    key = (str(symbol), str(interval))
    if key in _held():
        yield False
        return
    thread_lock = _thread_lock(key)
    thread_lock.acquire()
    path = _root() / f"{symbol}-{interval}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        _held().add(key)
        try:
            yield True
        finally:
            _held().discard(key)
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        thread_lock.release()


def _read(symbol, interval):
    path = _state_path(symbol, interval)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(symbol, interval, data):
    path = _state_path(symbol, interval)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def inspect(symbol, interval, bar):
    """Call only while holding exclusive. An empty bar is not a decision."""
    if not isinstance(bar, dict) or bar.get("close_time_ms") is None:
        return {"status": "empty"}
    close_ms = int(bar["close_time_ms"])
    mark = fingerprint(bar)
    state = _read(symbol, interval)
    latest = state.get("latest_close_ms")
    if latest is None:
        return {"status": "new", "close_ms": close_ms, "fingerprint": mark}
    latest = int(latest)
    if close_ms < latest:
        return {"status": "older", "close_ms": close_ms, "fingerprint": mark, "decision": state.get("decision")}
    if close_ms > latest:
        return {"status": "new", "close_ms": close_ms, "fingerprint": mark}
    if state.get("fingerprint") == mark:
        return {"status": "same", "close_ms": close_ms, "fingerprint": mark, "decision": state.get("decision")}
    return {"status": "revised", "close_ms": close_ms, "fingerprint": mark, "decision": state.get("decision")}


def seal(symbol, interval, bar, decision):
    """Call only while holding exclusive, and only after the decision has been stored."""
    if not isinstance(bar, dict) or bar.get("close_time_ms") is None:
        return False
    close_ms = int(bar["close_time_ms"])
    state = _read(symbol, interval)
    latest = state.get("latest_close_ms")
    if latest is not None and int(latest) > close_ms:
        return False
    kept = decision if isinstance(decision, dict) else {}
    state.update({
        "latest_close_ms": close_ms,
        "fingerprint": fingerprint(bar),
        "strategy": kept.get("strategy") or "auto",
        "state": "sealed",
        "decision": {
            "symbol": symbol,
            "interval": interval,
            "decision": kept.get("decision_label") or kept.get("decision"),
            "strategy": kept.get("strategy"),
            "bar_close_ms": close_ms,
            "entry": kept.get("entry"),
            "stop": kept.get("stop"),
            "target": kept.get("target"),
        },
    })
    seen = state.get("seen") if isinstance(state.get("seen"), dict) else {}
    seen[str(close_ms)] = state["fingerprint"]
    state["seen"] = seen
    _write(symbol, interval, state)
    return True


def note_once(symbol, interval, kind, bar, now_ms):
    """Append one correction or late row. The original decision is not rewritten."""
    if not isinstance(bar, dict) or bar.get("close_time_ms") is None:
        return False
    close_ms = int(bar["close_time_ms"])
    mark = fingerprint(bar)
    state = _read(symbol, interval)
    seen = state.get(kind) if isinstance(state.get(kind), list) else []
    token = f"{close_ms}:{mark}"
    if token in seen:
        return False
    from ops.signal_ledger import record_observations

    record_observations(
        [{
            "symbol": symbol,
            "interval": interval,
            "decision": "WAIT",
            "quality": "ok",
            "reading_class": "observational",
            "price": None,
            "entry": None,
            "stop": None,
            "target": None,
            "opportunity_id": f"{kind}:{symbol}:{interval}:{token}",
            "correction": kind,
            "bar_close_ms": close_ms,
        }],
        now_ms=now_ms,
        component="candle_claim",
    )
    seen.append(token)
    state[kind] = seen
    if state.get("latest_close_ms") is not None:
        _write(symbol, interval, state)
    else:
        state["latest_close_ms"] = None
        _write(symbol, interval, state)
    return True
