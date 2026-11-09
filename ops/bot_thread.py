"""In-product Aureon Bot thread. One account cannot read another's messages."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def _path(user_id):
    root = Path(os.environ.get("AUREON_DATA") or "data") / "bot"
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in str(user_id) if ch.isalnum())
    return root / f"{safe}.jsonl"


def append(user_id, role, text, *, now_ms=None):
    if not user_id or role not in {"customer", "aureon"}:
        return {"stored": False, "reason": "unauthorized"}
    line = str(text or "").replace("\n", " ").strip()[:1200]
    if not line:
        return {"stored": False, "reason": "empty"}
    row = {
        "account_id": str(user_id),
        "role": role,
        "text": line,
        "created_ms": int(now_ms if now_ms is not None else time.time() * 1000),
    }
    with _path(user_id).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return {"stored": True, "message": row}


def history(user_id, *, limit=40):
    path = _path(user_id)
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
        if isinstance(row, dict) and row.get("account_id") == str(user_id):
            rows.append(row)
    return rows[-int(limit):]
