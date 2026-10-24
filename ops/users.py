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


import secrets
import time

def update_profile(user_id: str, profile: dict) -> dict | None:
    path = _path(user_id)
    if not path.exists():
        return None
    user = json.loads(path.read_text())
    current = user.get("profile") or {}
    mode = profile.get("mode") if profile.get("mode") in {"research", "paper", "decision"} else current.get("mode", "research")
    capital = profile.get("capital")
    try:
        capital = float(capital) if capital is not None else current.get("capital")
    except Exception:
        capital = current.get("capital")
    risk = profile.get("max_risk_pct")
    try:
        risk = min(100.0, max(0.0, float(risk))) if risk is not None else current.get("max_risk_pct", 1.0)
    except Exception:
        risk = current.get("max_risk_pct", 1.0)
    user["profile"] = {
        "mode": mode,
        "capital": capital,
        "currency": str(profile.get("currency") or current.get("currency") or "USD")[:8],
        "capital_type": profile.get("capital_type") if profile.get("capital_type") in {"virtual", "declared"} else current.get("capital_type", "virtual"),
        "max_risk_pct": risk,
        "experimental_alerts": bool(profile.get("experimental_alerts", current.get("experimental_alerts", False))),
        "daily_report": bool(profile.get("daily_report", current.get("daily_report", True))),
        "timezone": str(profile.get("timezone") or current.get("timezone") or "Africa/Lagos")[:64],
    }
    path.write_text(json.dumps(user))
    return get(user_id)


def start_telegram_link(user_id: str, claimed_id: str) -> dict | None:
    path = _path(user_id)
    if not path.exists():
        return None
    user = json.loads(path.read_text())
    token = secrets.token_urlsafe(16)
    user["telegram_pending"] = {
        "token": token,
        "claimed_id": str(claimed_id),
        "expires": time.time() + 600,
    }
    path.write_text(json.dumps(user))
    return {"token": token, "expires_in": 600}


def confirm_telegram_link(token: str, telegram_id: str) -> dict | None:
    root = Path(os.environ.get("AUREON_DATA", "data")) / "users"
    for path in root.glob("*.json"):
        user = json.loads(path.read_text())
        pending = user.get("telegram_pending") or {}
        if pending.get("token") != token:
            continue
        if time.time() > pending.get("expires", 0):
            return {"error": "expired"}
        if str(pending.get("claimed_id")) != str(telegram_id):
            return {"error": "id_mismatch"}
        user["telegram"] = {"id": str(telegram_id), "verified": True}
        user.pop("telegram_pending", None)
        path.write_text(json.dumps(user))
        return {"ok": True, "user_id": user["id"]}
    return {"error": "not_found"}


def process_start_command(token: str, telegram_id: str, chat_id: str) -> dict:
    root = Path(os.environ.get("AUREON_DATA", "data")) / "users"
    for path in root.glob("*.json"):
        user = json.loads(path.read_text())
        pending = user.get("telegram_pending") or {}
        if pending.get("token") != token:
            continue
        if time.time() > pending.get("expires", 0):
            return {"error": "expired"}
        if str(pending.get("claimed_id")) != str(telegram_id):
            return {"error": "id_mismatch"}
        user["telegram"] = {"id": str(telegram_id), "chat_id": str(chat_id), "verified": True}
        user.pop("telegram_pending", None)
        path.write_text(json.dumps(user))
        return {"ok": True, "user_id": user["id"]}
    return {"error": "not_found"}


def unlink_telegram(user_id: str) -> bool:
    path = _path(user_id)
    if not path.exists():
        return False
    user = json.loads(path.read_text())
    user.pop("telegram", None)
    user.pop("telegram_pending", None)
    path.write_text(json.dumps(user))
    return True


def list_users() -> list[dict]:
    root = Path(os.environ.get("AUREON_DATA", "data")) / "users"
    if not root.exists():
        return []
    return [json.loads(path.read_text()) for path in root.glob("*.json")]
