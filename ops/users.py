"""Per-user store with password hashing. Isolation is by session user id."""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None

from werkzeug.security import generate_password_hash, check_password_hash

from ops.files import update_json

ROOT = Path(os.environ.get("AUREON_DATA", "data")) / "users"
ROOT.mkdir(parents=True, exist_ok=True)


def _path(user_id: str) -> Path:
    return ROOT / f"{user_id}.json"


def _root_lock():
    ROOT.mkdir(parents=True, exist_ok=True)
    handle = open(ROOT / ".write.lock", "a+")
    if fcntl is not None:
        fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def _root_unlock(handle):
    if handle is None:
        return
    if fcntl is not None:
        fcntl.flock(handle, fcntl.LOCK_UN)
    handle.close()


def _commit(user_id, mutator):
    """Apply one profile change under the file lock. A conflict does not write."""
    path = _path(user_id)
    if not path.exists():
        return None
    holder = {}

    def apply(current):
        if not isinstance(current, dict):
            holder["bad"] = True
            return {"unreadable": True}
        draft = mutator(current)
        if not isinstance(draft, dict):
            return None
        if draft.get("__skip__") == "conflict":
            holder["conflict"] = int(draft.get("revision") or current.get("revision") or 0)
            return None
        if draft.get("__skip__"):
            return None
        draft.pop("__skip__", None)
        draft["revision"] = int(current.get("revision") or 0) + 1
        holder["ok"] = True
        return draft

    updated = update_json(path, apply)
    if "conflict" in holder:
        return {"conflict": True, "revision": holder["conflict"]}
    if holder.get("bad") or (isinstance(updated, dict) and updated.get("unreadable") and not holder.get("ok")):
        return None
    if not holder.get("ok"):
        return None
    return get(user_id)


def _by_name(name: str) -> dict | None:
    if not ROOT.exists():
        return None
    for path in ROOT.glob("*.json"):
        try:
            user = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(user, dict) and user.get("name") == name:
            return user
    return None


def register(name: str, password: str) -> dict | None:
    if not name or not password or len(password) < 8:
        return None
    handle = _root_lock()
    try:
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
            "revision": 1,
        }
        update_json(_path(user_id), lambda _current: user, user)
        return {"id": user_id, "name": user["name"]}
    finally:
        _root_unlock(handle)


def login(name: str, password: str) -> dict | None:
    user = _by_name(name)
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return None
    return {"id": user["id"], "name": user["name"]}


def get(user_id: str) -> dict | None:
    path = _path(user_id)
    if not path.exists():
        return None
    try:
        user = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(user, dict):
        return None
    user.pop("password_hash", None)
    return user


def save_inbox_delivery(user_id: str, incoming: dict) -> dict | None:
    """Store inbox filters only. Existing plan, profile, and history stay as they are."""

    def mutator(user):
        current = user.get("inbox_delivery") if isinstance(user.get("inbox_delivery"), dict) else {}
        incoming_local = incoming or {}
        if "markets" in incoming_local:
            markets = [item for item in incoming_local.get("markets") or [] if item in {"BTCUSDT", "ETHUSDT", "XAUUSD"}]
        else:
            markets = [item for item in current.get("markets", ["BTCUSDT", "ETHUSDT", "XAUUSD"]) if item in {"BTCUSDT", "ETHUSDT", "XAUUSD"}]
        if "timeframes" in incoming_local:
            timeframes = [item for item in incoming_local.get("timeframes") or [] if item in {"1m", "3m", "15m", "1h", "4h", "1d"}]
        else:
            timeframes = [item for item in current.get("timeframes", ["15m", "1h", "4h", "1d"]) if item in {"1m", "3m", "15m", "1h", "4h", "1d"}]
        user["inbox_delivery"] = {
            "enabled": bool(incoming_local["enabled"]) if "enabled" in incoming_local else bool(current.get("enabled", True)),
            "markets": markets,
            "timeframes": timeframes,
            "buy": bool(incoming_local["buy"]) if "buy" in incoming_local else bool(current.get("buy", True)),
            "sell": bool(incoming_local["sell"]) if "sell" in incoming_local else bool(current.get("sell", True)),
            "experimental": bool(incoming_local["experimental"]) if "experimental" in incoming_local else bool(current.get("experimental", False)),
            "wait_notices": bool(incoming_local["wait_notices"]) if "wait_notices" in incoming_local else bool(current.get("wait_notices", False)),
        }
        return user

    return _commit(user_id, mutator)


def link_telegram(user_id: str, chat_id: str) -> dict | None:
    """A typed chat id is not verification. The bot update path is the only one."""
    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def update_prefs(user_id: str, prefs: dict) -> dict | None:
    def mutator(user):
        markets = [m for m in (prefs or {}).get("markets", []) if m in {"BTCUSDT", "ETHUSDT", "XAUUSD"}]
        user["prefs"] = {
            "markets": markets or ["BTCUSDT"],
            "timeframes": {"BTCUSDT": "15m", "ETHUSDT": "15m", "XAUUSD": "1h"},
        }
        return user

    return _commit(user_id, mutator)


def update_profile(user_id: str, profile: dict, expected_revision=None) -> dict | None:
    from ops.profiles import CURRENCIES, get_profile, risk_cap

    def mutator(user):
        if expected_revision is not None and int(user.get("revision") or 0) != int(expected_revision):
            return {"__skip__": "conflict", "revision": int(user.get("revision") or 0)}
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
        return user

    return _commit(user_id, mutator)


def save_plan(user_id: str, incoming: dict) -> dict | None:
    from ops.plan import normalize
    from ops.profiles import risk_cap

    notes = {}

    def mutator(user):
        profile = user.get("profile") or {}
        cap = risk_cap(profile.get("signal_style"))
        if cap is not None and profile.get("max_risk_pct") is not None:
            cap = min(cap, float(profile["max_risk_pct"]))
        saved = normalize(incoming, user.get("plan"), cap)
        notes["notes"] = saved.pop("notes")
        user["plan"] = saved
        return user

    public = _commit(user_id, mutator)
    if not public or public.get("conflict"):
        return public
    public["plan_notes"] = notes.get("notes") or []
    return public


def start_telegram_link(user_id: str, claimed_id: str | None = None) -> dict | None:
    """One-time token. A typed id is ignored and the raw token is not stored."""
    minted = {}

    def mutator(user):
        token = secrets.token_urlsafe(24)
        minted["token"] = token
        user["telegram_pending"] = {
            "token_hash": _token_hash(token),
            "expires": time.time() + 600,
        }
        return user

    saved = _commit(user_id, mutator)
    if not saved or saved.get("conflict"):
        return None
    return {"token": minted.get("token"), "expires_in": 600}


def confirm_telegram_link(token: str, telegram_id: str) -> dict:
    return {"error": "typed_id_not_accepted"}


def process_start_command(token: str, telegram_id: str, chat_id: str) -> dict:
    if not token or not telegram_id or not chat_id:
        return {"error": "incomplete_update"}
    handle = _root_lock()
    try:
        digest = _token_hash(token)
        owner = None
        for path in ROOT.glob("*.json"):
            try:
                user = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            pending = user.get("telegram_pending") or {}
            if pending.get("token_hash") != digest:
                continue
            if time.time() > pending.get("expires", 0):
                def clear(current, path=path):
                    current.pop("telegram_pending", None)
                    return current
                _commit(user.get("id"), clear)
                return {"error": "expired"}
            owner = user
            break
        if owner is None:
            return {"error": "not_found"}
        for path in ROOT.glob("*.json"):
            try:
                other = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            current = other.get("telegram") or {}
            if other.get("id") != owner.get("id") and current.get("verified") and str(current.get("chat_id")) == str(chat_id):
                return {"error": "destination_in_use"}

        def link(current):
            current["telegram"] = {
                "id": str(telegram_id),
                "chat_id": str(chat_id),
                "verified": True,
                "revoked": False,
            }
            current.pop("telegram_pending", None)
            return current

        saved = _commit(owner.get("id"), link)
        if not saved or saved.get("conflict"):
            return {"error": "not_found"}
        return {"ok": True, "user_id": owner.get("id")}
    finally:
        _root_unlock(handle)


def unlink_telegram(user_id: str) -> bool:
    def mutator(user):
        current = user.get("telegram") or {}
        if current:
            current["verified"] = False
            current["revoked"] = True
            user["telegram"] = current
        user.pop("telegram_pending", None)
        return user

    saved = _commit(user_id, mutator)
    return bool(saved) and not saved.get("conflict")


def record_digest(user_id: str, day: str, status: str) -> None:
    def mutator(user):
        profile = user.get("profile") or {}
        profile["last_digest_day"] = day
        profile["last_digest_status"] = status[:80]
        user["profile"] = profile
        return user

    _commit(user_id, mutator)


def list_users() -> list[dict]:
    if not ROOT.exists():
        return []
    found = []
    for path in ROOT.glob("*.json"):
        try:
            user = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(user, dict) and user.get("id"):
            found.append(user)
    return found
