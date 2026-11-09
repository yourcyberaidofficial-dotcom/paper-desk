"""Security role and product entitlement. A browser cannot grant either.

Trading personas are not roles. A stored ``role`` field is ignored.
Operators are named only by ``AUREON_OPERATOR_IDS`` on the server.
"""

from __future__ import annotations

import os

CUSTOMER = "customer"
OPERATOR = "operator"
ROLES = (CUSTOMER, OPERATOR)


def operator_ids():
    found = []
    for item in os.environ.get("AUREON_OPERATOR_IDS", "").split(","):
        item = item.strip()
        if item and item not in found:
            found.append(item)
    return found


def resolve_role(user):
    """Least privilege unless this account id is on the server allowlist."""
    user_id = (user or {}).get("id")
    if user_id and user_id in operator_ids():
        return OPERATOR
    return CUSTOMER


def entitlements(user):
    """Product capabilities. A preference cannot turn these on."""
    from ops.customer_release import any_customer_display

    role = resolve_role(user)
    live = bool(any_customer_display())
    return {
        "paper_trading": True,
        "academy": True,
        "live_market_display": live,
        "hosted_ai": True,
        "account_administration": role == OPERATOR,
        "broker": False,
    }
