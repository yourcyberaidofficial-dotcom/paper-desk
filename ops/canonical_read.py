"""Customer reads from the worker's stored readings.

These helpers do not open a market connection. A missing row stays empty.
"""

from __future__ import annotations

import os


def web_role():
    return os.environ.get("AUREON_ROLE", "").strip().lower() == "web"


def stored_desk(now_ms):
    from ops.customer_release import reading_released, unavailable_card
    from ops.data_rights import DESK
    from ops.desk_pulse import get, health_label

    markets = []
    for symbol, interval in DESK:
        card = unavailable_card(symbol, interval)
        card["source"] = "canonical"
        stored = get(symbol, interval)
        released = bool(stored and stored.get("snapshot_id") and reading_released(symbol, interval))
        if released:
            price = stored.get("reference_price")
            if price is None:
                price = stored.get("price")
            card.update({
                "decision": stored.get("decision") or "WAIT",
                "decision_label": stored.get("decision_label") or stored.get("decision") or "WAIT",
                "entry": stored.get("entry"),
                "stop": stored.get("stop"),
                "target": stored.get("target"),
                "price": price,
                "close": price,
                "reference_price": stored.get("reference_price"),
                "snapshot_id": stored.get("snapshot_id"),
                "bar_close_ms": stored.get("bar_close_ms"),
                "fresh": stored.get("fresh"),
                "feed_state": stored.get("feed_state") or "live",
                "customer_status": None,
                "evaluated": True,
                "quality": health_label(stored, int(now_ms)),
                "message": "Stored worker reading. This request did not fetch a market.",
            })
        else:
            card["message"] = "No stored worker reading. This request did not fetch a market."
            card["fetched_upstream"] = False
        markets.append(card)
    return {
        "markets": markets,
        "notice": "Read from the worker's stored readings. This request did not fetch a market.",
        "broker": False,
        "source": "canonical",
        "snapshots": [],
        "fetched_upstream": False,
    }
