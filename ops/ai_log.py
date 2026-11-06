"""Append-only inference record. The prompt body is not stored."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path


def _path():
    root = Path(os.environ.get("AUREON_DATA") or "data")
    return root / "ai" / "inferences.jsonl"


def record(entry):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = (path.parent / "inferences.jsonl.lock").open("a+")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")
            handle.flush()
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    return True


def read():
    path = _path()
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
