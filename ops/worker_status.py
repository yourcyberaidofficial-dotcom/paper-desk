"""Worker heartbeat on the shared canonical volume.

Web does not call the worker over HTTP. It reads this file. The file is
the process heartbeat. It is not a market price.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()


def status_path():
    root = Path(os.environ.get("AUREON_DATA") or "data")
    return root / "canonical" / "worker_status.json"


def read_status():
    path = status_path()
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(body, dict) or body.get("schema") != 1:
        return {}
    return body


def publish_patch(patch):
    path = status_path()
    with _LOCK:
        current = read_status()
        for key, value in (patch or {}).items():
            current[key] = value
        current["schema"] = 1
        current["written_ms"] = int(time.time() * 1000)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")
        temporary.replace(path)
        return dict(current)


def check(max_age_ms=30_000):
    """Process heartbeat only. A missing market reading is not a failed check."""
    alive = int(read_status().get("alive_ms") or 0)
    if alive <= 0:
        return False
    return int(time.time() * 1000) - alive <= int(max_age_ms)


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(0 if check() else 1)
    raise SystemExit("usage: python -m ops.worker_status --check")
