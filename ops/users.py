"""Per-user store with password hashing. Isolation is by session user id."""

import json
import os
import secrets
import time
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(os.environ.get("AUREON_DATA", "data")) / "users"
ROOT.mkdir(parents=True, exist_ok=True)


def _path(user_id: str) -> Path:
    return ROOT / f"{user_id}.json"


def _by_name(name: str) -> dict | None:
    for path in ROOT.glob("*.json"):
        user = json.loads(path.read_text())
        if user.get("name") == name:
            return user
    return None


def register(name: str, password: str) -> dict | None:
    if not name or not password or len(password) < 8:
        return None
    if _by_name(name):
        return None
    user_id = secrets.token_hex(8)
    user = {
        "id": user_id,
        "name": name[:40],
        "password_hash": generate_password_hash(password),
        "created_at": time.time(),
        "telegram": None,
        "prefs": {"markets": ["BTCUSDT", "ETHUSDT", "XAUUSD"]},
    }
    _path(user_id).write_text(json.dumps(user))
    return {"id": user_id, "name": user["name"]}


def login(name: str, password: str) -> dict | None:
    user = _by_name(name)
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return None
    return {"id": user["id"], "name": user["name"]}


def get(user_id: str) -> dict | None:
    path = _path(user_id)
    if not path.exists():
        return None
    user = json.loads(path.read_text())
    user.pop("password_hash", None)
    return user


def link_telegram(user_id: str, chat_id: str) -> dict | None:
    path = _path(user_id)
    if not path.exists():
        return None
    user = json.loads(path.read_text())
    user["telegram"] = {"chat_id": str(chat_id), "linked_at": time.time()}
    path.write_text(json.dumps(user))
    return get(user_id)


def update_prefs(user_id: str, prefs: dict) -> dict | None:
    path = _path(user_id)
    if not path.exists():
        return None
    user = json.loads(path.read_text())
    markets = [m for m in prefs.get("markets", []) if m in {"BTCUSDT", "ETHUSDT", "XAUUSD"}]
    user["prefs"] = {
        "markets": markets or ["BTCUSDT"],
        "timeframes": {"BTCUSDT": "15m", "ETHUSDT": "15m", "XAUUSD": "1d"},
    }
    path.write_text(json.dumps(user))
    return get(user_id)
