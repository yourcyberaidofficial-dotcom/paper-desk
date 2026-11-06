"""Local inference watch.

Records whether the private model is up, how much memory the process is
using, and when a model comes back after being offline. It does not write
signals, paper orders, risk settings, or strategy approvals.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None


def _root():
    return Path(os.environ.get("AUREON_DATA") or "data") / "ai"


def memory_sample():
    rss = None
    available = None
    status = Path("/proc/self/status")
    info = Path("/proc/meminfo")
    try:
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError, IndexError):
        rss = None
    try:
        for line in info.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                available = int(line.split()[1]) * 1024
                break
    except (OSError, ValueError, IndexError):
        available = None
    return {"rss_bytes": rss, "mem_available_bytes": available}


def note(user_id, health):
    """Append one watch row. signals_modified and orders_modified stay false."""
    from ops.files import update_json

    health = health if isinstance(health, dict) else {}
    available = health.get("available") is True
    model = health.get("model")
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    holder = {}

    def apply(current):
        current = current if isinstance(current, dict) else {}
        previous = current.get("available")
        previous_model = current.get("model")
        restarted = previous is False and available
        swapped = bool(previous_model) and previous_model != model and available
        event = "model_restarted" if restarted or swapped else ("online" if available else (health.get("reason") or "offline"))
        holder["event"] = event
        return {
            "available": available,
            "model": model,
            "event": event,
            "signals_modified": False,
            "orders_modified": False,
        }

    update_json(root / "watch.json", apply, {})
    sample = memory_sample()
    row = {
        "user_id": user_id,
        "event": holder.get("event") or "offline",
        "model": model,
        "reason": health.get("reason"),
        "available": available,
        "rss_bytes": sample["rss_bytes"],
        "mem_available_bytes": sample["mem_available_bytes"],
        "signals_modified": False,
        "orders_modified": False,
        "created_ms": int(time.time() * 1000),
    }
    path = root / "monitor.jsonl"
    lock = (root / "monitor.jsonl.lock").open("a+")
    try:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            handle.flush()
        os.chmod(path, 0o600)
    finally:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    return row


def read():
    path = _root() / "monitor.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows
