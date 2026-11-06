"""One server-resolved experience profile for the signed-in account.

Pages read this. They do not invent a second copy of the persona or the role.
"""

from __future__ import annotations

from ops.access import CUSTOMER, entitlements, resolve_role
from ops.hosted_ai import status as ai_status

PAGES = (
    "/", "/register", "/login", "/onboarding", "/overview", "/trading", "/scanner",
    "/signals", "/strategies", "/research", "/plan", "/portfolio", "/orders",
    "/history", "/risk", "/notifications", "/live", "/settings", "/system",
    "/learn", "/lab",
)

CUSTOMER_NAV = (
    "/overview", "/trading", "/scanner", "/signals", "/strategies", "/research",
    "/settings", "/portfolio", "/orders", "/history", "/activity", "/risk", "/plan",
    "/learn", "/lab", "/notifications", "/live", "/system",
)


def _presentation(user):
    stored = user.get("presentation") if isinstance(user.get("presentation"), dict) else {}
    profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
    lab = user.get("lab") if isinstance(user.get("lab"), dict) else {}
    layout = stored.get("layout")
    if layout not in {"guided", "market", "operator"}:
        layout = "market" if lab.get("experience") == "independent" else "guided"
    if layout == "operator" and resolve_role(user) != "operator":
        layout = "market"
    density = stored.get("density") if stored.get("density") in {"comfortable", "compact"} else "comfortable"
    depth = stored.get("depth") if stored.get("depth") in {"guided", "concise"} else "guided"
    language = stored.get("language") if stored.get("language") == "en" else "en"
    theme = stored.get("theme") if stored.get("theme") in {"dark", "light", "system"} else "dark"
    contrast = stored.get("contrast") if stored.get("contrast") in {"standard", "high"} else "standard"
    motion = stored.get("motion") if stored.get("motion") in {"full", "reduced"} else "full"
    timezone = stored.get("timezone") or profile.get("timezone") or "Africa/Lagos"
    return {
        "timezone": timezone,
        "density": density,
        "depth": depth,
        "language": language,
        "language_status": "applied" if language == "en" else "unsupported",
        "layout": layout,
        "theme": theme,
        "contrast": contrast,
        "motion": motion,
    }


def _widgets(layout, role):
    if role == "operator" and layout == "operator":
        return ["accounts", "system", "markets", "account", "ai"]
    if layout == "market":
        return ["markets", "account", "activity", "ai"]
    return ["account", "onboarding", "markets", "activity", "ai"]


def resolve(user):
    """Public profile. Password material is never copied in."""
    user = user or {}
    profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
    lab = user.get("lab") if isinstance(user.get("lab"), dict) else {}
    prefs = user.get("prefs") if isinstance(user.get("prefs"), dict) else {}
    inbox = user.get("inbox_delivery") if isinstance(user.get("inbox_delivery"), dict) else {}
    role = resolve_role(user)
    rights = entitlements(user)
    persona = profile.get("signal_style")
    pending = []
    if not persona:
        pending.append("choose_persona")
    if not profile.get("currency"):
        pending.append("choose_currency")
    look = _presentation(user)
    navigation = list(CUSTOMER_NAV)
    if role == "operator":
        navigation.append("/accounts")
    return {
        "customer_id": user.get("id"),
        "account_id": user.get("id"),
        "name": user.get("name"),
        "membership": "owner",
        "security_role": role,
        "account_status": "active" if user.get("id") else "anonymous",
        "entitlements": rights,
        "persona": {
            "id": persona,
            "name": profile.get("signal_style_name"),
            "risk_mode": profile.get("risk_mode"),
            "max_risk_pct": profile.get("max_risk_pct"),
            "min_rr": profile.get("min_rr"),
            "max_daily_loss_percent": profile.get("max_daily_loss_percent"),
        },
        "markets": list(prefs.get("markets") or ["BTCUSDT", "ETHUSDT", "XAUUSD"]),
        "timeframes": dict(prefs.get("timeframes") or {}),
        "learning_level": lab.get("experience") or "not_stated",
        "onboarding_pending": pending,
        "presentation": look,
        "accessibility": {
            "contrast": look["contrast"],
            "motion": look["motion"],
            "density": look["density"],
        },
        "notifications": {
            "daily_report": bool(profile.get("daily_report", True)),
            "experimental_alerts": bool(profile.get("experimental_alerts", False)),
            "inbox_enabled": bool(inbox.get("enabled", True)),
        },
        "widgets": _widgets(look["layout"], role),
        "navigation": navigation,
        "ai": ai_status(),
        "pages": list(PAGES),
        "timestamps": {"created_at": user.get("created_at")},
        "migration": {
            "mode": "additive_read_time_defaults",
            "history_rewritten": False,
            "presentation_persisted": isinstance(user.get("presentation"), dict),
            "rollback": "Delete only the presentation object on that user. Do not delete history, the ledger, or signal rows. A display save also copies timezone into profile.timezone; restore that one field from backup if needed.",
        },
        "role_source": "server_allowlist" if role != CUSTOMER else "least_privilege_default",
        "broker": False,
    }
