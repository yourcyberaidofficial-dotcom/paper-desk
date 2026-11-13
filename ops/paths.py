"""One data root for web and worker.

Compose sets AUREON_DATA to /app/data and mounts nine directories under it.
A path that is not inside one of those directories is lost when the
container is replaced, and it is not in the volume backup.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# Directory name under the data root, and the Compose volume that mounts it.
VOLUME_DIRS = (
    ("paper", "desk-data"),
    ("users", "desk-users"),
    ("shadow", "desk-shadow"),
    ("signals", "desk-signals"),
    ("activity", "desk-activity"),
    ("rights", "desk-rights"),
    ("cache", "desk-cache"),
    ("canonical", "desk-canonical"),
    ("ai", "desk-ai"),
)


def data_root():
    configured = os.environ.get("AUREON_DATA", "").strip()
    if configured:
        return Path(configured)
    return _REPO / "data"


def on_volume(path):
    """True when path is inside one of the nine mounted directories."""
    path = Path(path)
    root = data_root()
    for name, _volume in VOLUME_DIRS:
        base = root / name
        if path == base or base in path.parents:
            return True
    return False


def ledger_path():
    return data_root() / "paper" / "ledger.jsonl"


def shadow_observations_path():
    return data_root() / "shadow" / "observations.jsonl"


def promotions_path():
    """Promotion registry. Empty means no send. It lives on desk-data."""
    return data_root() / "paper" / "promotions.json"


def telegram_offset_path():
    return data_root() / "paper" / "telegram_offset.txt"


def telegram_seen_path():
    return data_root() / "paper" / "telegram_updates.jsonl"


def claims_root():
    return data_root() / "canonical" / "claims"


def runtime_state_path():
    return data_root() / "canonical" / "runtime.json"


def imports_root(account_id):
    safe = "".join(ch for ch in str(account_id or "") if ch.isalnum())
    if not safe:
        return None
    return data_root() / "users" / "imports" / safe


def bot_root():
    return data_root() / "users" / "bot"
