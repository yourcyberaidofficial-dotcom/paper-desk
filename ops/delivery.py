"""The only trade-alert policy. Empty promotions mean no send."""

import json
import logging
from pathlib import Path

log = logging.getLogger("aureon.delivery")

FORBIDDEN_TEXT = (
    "EXPERIMENTAL — NOT VALIDATED",
    "LONG_BIAS",
    "SHORT_BIAS",
    "stale or unavailable",
)
SYMBOLS = {"BTCUSDT", "ETHUSDT", "XAUUSD"}


def load_promotions(path=None):
    from ops.paths import promotions_path

    target = Path(path) if path is not None else promotions_path()
    if not target.exists():
        return []
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if not item.get("strategy") or not item.get("version"):
            continue
        symbols = item.get("symbols") or item.get("scope") or []
        if isinstance(symbols, str):
            symbols = [symbols]
        rows.append({
            "strategy": item["strategy"],
            "version": item["version"],
            "symbols": [symbol for symbol in symbols if symbol in SYMBOLS],
        })
    return rows


def _profile(account):
    if isinstance(account, dict) and isinstance(account.get("profile"), dict):
        return account["profile"]
    return account or {}


def _prefs(account):
    if isinstance(account, dict) and isinstance(account.get("prefs"), dict):
        return account["prefs"]
    if isinstance(account, dict) and isinstance(account.get("profile"), dict):
        nested = account["profile"].get("prefs")
        if isinstance(nested, dict):
            return nested
    return {}


def _telegram(account):
    if not isinstance(account, dict):
        return {}
    if isinstance(account.get("telegram"), dict):
        return account["telegram"]
    profile = account.get("profile") if isinstance(account.get("profile"), dict) else {}
    telegram = profile.get("telegram")
    return telegram if isinstance(telegram, dict) else {}


def _alerts_on(profile):
    if profile.get("notifications_enabled") is False:
        return False
    if profile.get("notifications_enabled") is True:
        return True
    return bool(profile.get("experimental_alerts"))


def _no(reason):
    return {"send": False, "delivered": False, "reason": reason}


def _promoted(event, registry):
    for row in registry:
        if row["strategy"] != event.get("strategy") or row["version"] != event.get("version"):
            continue
        if event.get("symbol") in row["symbols"]:
            return row
    return None


def authorize(event, account, now_ms=0, registry=None, already_sent=None):
    """Reject unless every gate is true. An observation is never approved here."""
    event = event or {}
    text = str(event.get("text") or "")
    if any(part in text for part in FORBIDDEN_TEXT):
        return _no("experimental_message_blocked")
    rows = list(registry) if registry is not None else load_promotions()
    if not rows:
        return _no("production_wait_default")
    if event.get("state") != "APPROVED_SIGNAL":
        return _no("not_approved")
    if _promoted(event, rows) is None:
        return _no("not_promoted")
    if event.get("fresh") is not True or event.get("complete") is False:
        return _no("data_not_live")
    if event.get("symbol") not in SYMBOLS:
        return _no("symbol_not_allowed")
    if event.get("expires_at_ms") is not None and now_ms > event["expires_at_ms"]:
        return _no("expired")
    profile = _profile(account)
    prefs = _prefs(account)
    if not _alerts_on(profile):
        return _no("alerts_off")
    markets = prefs.get("markets")
    if markets is not None and event.get("symbol") not in markets:
        return _no("market_not_selected")
    frames = prefs.get("timeframes") or {}
    wanted = frames.get(event.get("symbol"))
    if wanted and event.get("timeframe") and wanted != event.get("timeframe"):
        return _no("timeframe_not_selected")
    telegram = _telegram(account)
    if telegram.get("revoked") or not telegram.get("verified") or telegram.get("chat_id") in (None, ""):
        return _no("unverified_destination")
    event_id = event.get("event_id")
    if event_id and already_sent and event_id in already_sent:
        return _no("duplicate")
    return {
        "send": True,
        "delivered": False,
        "reason": "eligible_to_attempt",
        "chat_id": str(telegram.get("chat_id")),
        "event_id": event_id,
    }


class DeliveryLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sent = set()
        for row in self.read():
            if row.get("delivered") and row.get("key"):
                self.sent.add(row["key"])

    def read(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def remember(self, key, row):
        if key in self.sent:
            return False
        stored = dict(row)
        stored["key"] = key
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(stored, sort_keys=True) + "\n")
        if stored.get("delivered"):
            self.sent.add(key)
        return True


def dispatch(event, account, sender, already_sent=None, now_ms=0, registry=None, delivery_log=None, user_id=None):
    decision = authorize(event, account, now_ms=now_ms, registry=registry, already_sent=already_sent)
    event_id = (event or {}).get("event_id")
    key = f"{user_id or 'account'}:{event_id}" if event_id else None
    if key and delivery_log and key in delivery_log.sent:
        return _no("duplicate")
    if not decision["send"]:
        log.info("delivery_blocked reason=%s event=%s", decision["reason"], event_id)
        return decision
    text = (event or {}).get("text") or "Aureon approved signal."
    if any(part in text for part in FORBIDDEN_TEXT):
        return _no("experimental_message_blocked")
    try:
        result = sender(text, chat_id=decision["chat_id"]) or {}
    except Exception as exc:
        log.info("delivery_failed reason=%s event=%s", type(exc).__name__, event_id)
        return {"send": False, "delivered": False, "reason": type(exc).__name__, "status": "FAILED"}
    chat_ok = str(result.get("telegram_chat_id")) == str(decision["chat_id"])
    delivered = bool(result.get("delivered")) and result.get("telegram_message_id") is not None and chat_ok
    if delivered and key and delivery_log:
        delivery_log.remember(key, {"delivered": True, "event_id": event_id, "user_id": user_id})
    log.info("delivery_result delivered=%s event=%s", delivered, event_id)
    return {
        "send": True,
        "delivered": delivered,
        "status": "DELIVERED" if delivered else "FAILED",
        "reason": None if delivered else (result.get("reason") or "telegram_not_ok"),
        "event_id": event_id,
        "telegram_message_id": result.get("telegram_message_id") if delivered else None,
        "telegram_chat_id": result.get("telegram_chat_id") if delivered else None,
    }
