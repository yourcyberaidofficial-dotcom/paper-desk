"""Per-user store with password hashing. Isolation is by session user id."""

import hashlib
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
    """A typed chat id is not verification. The bot update path is the only one."""
    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def update_prefs(user_id: str, prefs: dict) -> dict | None:
    path = _path(user_id)
    if not path.exists():
        return None
    user = json.loads(path.read_text())
    markets = [m for m in prefs.get("markets", []) if m in {"BTCUSDT", "ETHUSDT", "XAUUSD"}]
    user["prefs"] = {
        "markets": markets or ["BTCUSDT"],
        "timeframes": {"BTCUSDT": "15m", "ETHUSDT": "15m", "XAUUSD": "1h"},
    }
    path.write_text(json.dumps(user))
    return get(user_id)


def update_profile(user_id: str, profile: dict) -> dict | None:
    from ops.profiles import CURRENCIES, get_profile, risk_cap
    path = _path(user_id)
    if not path.exists():
        return None
    user = json.loads(path.read_text())
    current = user.get("profile") or {}
    mode = profile.get("mode") if profile.get("mode") in {"research", "paper", "decision"} else current.get("mode", "research")
    capital = profile.get("capital") if "capital" in profile else current.get("capital")
    try:
        capital = float(capital) if capital not in (None, "") else None
    except Exception:
        capital = current.get("capital")
    style = profile.get("signal_style", current.get("signal_style"))
    if style is not None and not get_profile(style):
        style = current.get("signal_style")
    currency = profile.get("currency", current.get("currency"))
    if currency not in (None, ""):
        currency = str(currency).upper()[:8]
        if currency not in CURRENCIES:
            currency = current.get("currency")
    else:
        currency = current.get("currency")
    cap = risk_cap(style)
    if style and style != current.get("signal_style"):
        risk = cap
    elif "max_risk_pct" in profile and profile.get("max_risk_pct") not in (None, ""):
        try:
            risk = float(profile.get("max_risk_pct"))
        except Exception:
            risk = current.get("max_risk_pct")
    else:
        risk = current.get("max_risk_pct", cap)
    if cap is not None and risk is not None:
        risk = min(cap, max(0.0, float(risk)))
    spec = get_profile(style) or {}
    user["profile"] = {
        "mode": mode,
        "capital": capital,
        "currency": currency,
        "capital_type": profile.get("capital_type") if profile.get("capital_type") in {"virtual", "declared"} else current.get("capital_type", "virtual"),
        "signal_style": style,
        "signal_style_name": spec.get("name"),
        "risk_mode": spec.get("risk_mode"),
        "max_risk_pct": risk,
        "max_daily_loss_percent": spec.get("max_daily_loss_percent", current.get("max_daily_loss_percent")),
        "max_open_risk_percent": spec.get("max_open_risk_percent", current.get("max_open_risk_percent")),
        "min_rr": spec.get("min_rr", current.get("min_rr")),
        "max_trades_per_day": spec.get("max_trades_per_day", current.get("max_trades_per_day")),
        "experimental_alerts": bool(profile.get("experimental_alerts", current.get("experimental_alerts", False))),
        "daily_report": bool(profile.get("daily_report", current.get("daily_report", True))),
        "timezone": str(profile.get("timezone") or current.get("timezone") or "Africa/Lagos")[:64],
    }
    path.write_text(json.dumps(user))
    return get(user_id)


def start_telegram_link(user_id: str, claimed_id: str | None = None) -> dict | None:
    """One-time token. A typed id is ignored and the raw token is not stored."""
    path = _path(user_id)
    if not path.exists():
        return None
    user = json.loads(path.read_text())
    token = secrets.token_urlsafe(24)
    user["telegram_pending"] = {
        "token_hash": _token_hash(token),
        "expires": time.time() + 600,
    }
    path.write_text(json.dumps(user))
    return {"token": token, "expires_in": 600}


def confirm_telegram_link(token: str, telegram_id: str) -> dict:
    return {"error": "typed_id_not_accepted"}


def process_start_command(token: str, telegram_id: str, chat_id: str) -> dict:
    if not token or not telegram_id or not chat_id:
        return {"error": "incomplete_update"}
    root = Path(os.environ.get("AUREON_DATA", "data")) / "users"
    digest = _token_hash(token)
    owner = None
    for path in root.glob("*.json"):
        user = json.loads(path.read_text())
        pending = user.get("telegram_pending") or {}
        if pending.get("token_hash") != digest:
            continue
        if time.time() > pending.get("expires", 0):
            user.pop("telegram_pending", None)
            path.write_text(json.dumps(user))
            return {"error": "expired"}
        owner = (path, user)
        break
    if owner is None:
        return {"error": "not_found"}
    path, user = owner
    for other_path in root.glob("*.json"):
        other = json.loads(other_path.read_text())
        current = other.get("telegram") or {}
        if other.get("id") != user.get("id") and current.get("verified") and str(current.get("chat_id")) == str(chat_id):
            return {"error": "destination_in_use"}
    user["telegram"] = {
        "id": str(telegram_id),
        "chat_id": str(chat_id),
        "verified": True,
        "revoked": False,
    }
    user.pop("telegram_pending", None)
    path.write_text(json.dumps(user))
    return {"ok": True, "user_id": user["id"]}


def unlink_telegram(user_id: str) -> bool:
    path = _path(user_id)
    if not path.exists():
        return False
    user = json.loads(path.read_text())
    current = user.get("telegram") or {}
    if current:
        current["verified"] = False
        current["revoked"] = True
        user["telegram"] = current
    user.pop("telegram_pending", None)
    path.write_text(json.dumps(user))
    return True


def record_digest(user_id: str, day: str, status: str) -> None:
    path = _path(user_id)
    if not path.exists():
        return
    user = json.loads(path.read_text())
    profile = user.get("profile") or {}
    profile["last_digest_day"] = day
    profile["last_digest_status"] = status[:80]
    user["profile"] = profile
    path.write_text(json.dumps(user))


def list_users() -> list[dict]:
    root = Path(os.environ.get("AUREON_DATA", "data")) / "users"
    if not root.exists():
        return []
    return [json.loads(path.read_text()) for path in root.glob("*.json")]
