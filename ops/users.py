"""Minimal per-user store. Not multi-tenant production auth. Isolation is by user id."""

import json
import os
import secrets
import time
from pathlib import Path

ROOT = Path(os.environ.get("AUREON_DATA", "data")) / "users"
ROOT.mkdir(parents=True, exist_ok=True)


def _path(user_id: str) -> Path:
    return ROOT / f"{user_id}.json"


def create(name: str) -> dict:
    user_id = secrets.token_hex(8)
    user = {
        "id": user_id,
        "name": name[:40],
        "created_at": time.time(),
        "telegram": None,
        "prefs": {"markets": ["BTCUSDT", "ETHUSDT", "XAUUSD"], "min_assurance": "purple"},
    }
    _path(user_id).write_text(json.dumps(user))
    return user


def get(user_id: str) -> dict | None:
    path = _path(user_id)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def link_telegram(user_id: str, chat_id: str) -> dict | None:
    user = get(user_id)
    if not user:
        return None
    user["telegram"] = {"chat_id": str(chat_id), "linked_at": time.time()}
    _path(user_id).write_text(json.dumps(user))
    return user


def unlink_telegram(user_id: str) -> dict | None:
    user = get(user_id)
    if not user:
        return None
    user["telegram"] = None
    _path(user_id).write_text(json.dumps(user))
    return user
