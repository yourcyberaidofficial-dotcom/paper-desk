"""One view of what the desk can do right now.

This module does not fetch a price, open a file of candles, or approve a strategy.
The pages render these labels. They do not invent a second decision.
"""

from ops.data_rights import MESSAGE, use_permission


def product_gates():
    from ops.qualification import summary

    qual = summary()
    display = (
        use_permission("binance_spot_rest_klines", "display"),
        use_permission("xaus_public_chart", "display"),
        use_permission("dukascopy_datafeed_bi5", "display"),
        use_permission("swissquote_public_bbo", "display"),
    )
    market = "available" if any(row["allowed"] for row in display) else "rights_withheld"
    approved = qual["approved_for_paper"]
    return {
        "market_data": market,
        "approved_for_paper": approved,
        "historical_research": "unavailable",
        "evaluation": "unavailable" if market != "available" or approved == 0 else "available",
        "message": MESSAGE,
    }


def pair_board():
    from ops.data_rights import coverage_rows

    rows = []
    for row in coverage_rows():
        status = row["rights_status"]
        if status == "xau_minute_unlicensed":
            rights, source = "Gold minute unlicensed", "No licensed minute source"
        elif status == "prohibited":
            rights, source = "Prohibited", "Not permitted"
        elif status == "restricted":
            rights, source = "Restricted", "Not permitted"
        elif status == "approved":
            rights, source = "Approved", "Permitted"
        else:
            rights, source = "Rights unconfirmed", "Withheld"
        rows.append({
            "instrument": row["market"],
            "timeframe": row["timeframe"],
            "rights": rights,
            "source": source,
            "history": "No retained historical data",
            "latest_read": "Not read",
            "evaluation": "Unavailable" if rights != "Approved" else "Not run",
            "approval": "No approved strategy",
        })
    return rows


def platform_state(worker=None):
    gates = product_gates()
    worker = worker or {}
    beating = worker.get("status") == "beating" and worker.get("healthy") is True
    approved = gates["approved_for_paper"]
    return {
        "application": "operational",
        "worker": "operational" if beating else (worker.get("status") or "not_confirmed"),
        "worker_healthy": beating,
        "market_data": gates["market_data"],
        "market_data_technical": "not_checked",
        "historical_research": "unavailable",
        "approved_strategies": approved,
        "qualifying_opportunity": "none",
        "evaluation": gates["evaluation"],
        "paper_trading": "available",
        "education": "available",
        "broker": False,
        "message": MESSAGE,
        "requirement": (
            "A written licence for that exact commercial use, and a strategy approved for paper, "
            "are both required before a candle or an evaluation can be shown."
        ),
        "states": [
            {"id": "application", "label": "Application", "value": "Operational"},
            {"id": "worker", "label": "Worker", "value": "Operational" if beating else "Not confirmed"},
            {"id": "market_data", "label": "Market data", "value": "Rights withheld" if gates["market_data"] == "rights_withheld" else "Permitted"},
            {"id": "market_technical", "label": "Feed health", "value": "Not checked"},
            {"id": "history", "label": "Historical research", "value": "Unavailable"},
            {"id": "strategies", "label": "Approved strategies", "value": str(approved)},
            {"id": "opportunity", "label": "Qualifying opportunity", "value": "None"},
            {"id": "paper", "label": "Paper trading", "value": "Available for eligible account actions"},
            {"id": "education", "label": "Academy and Lab", "value": "Available"},
        ],
        "pairs": pair_board(),
        "gates": gates,
    }
