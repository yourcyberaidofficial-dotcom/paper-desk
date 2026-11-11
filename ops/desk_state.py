"""One view of what the desk can do right now.

This module does not fetch a price, open a file of candles, or approve a strategy.
The pages render these labels. They do not invent a second decision.
"""

from ops.data_rights import MESSAGE, use_permission

OPERATING = "Public completed candles are on for BTC, ETH and gold. Paper orders fill on this desk. They are not sent to a live exchange."


def product_gates():
    from ops.qualification import summary

    qual = summary()
    display = (
        use_permission("binance_spot_rest_klines", "display"),
        use_permission("xaus_public_chart", "display"),
    )
    market = "available" if any(row["allowed"] for row in display) else "rights_withheld"
    approved = qual["approved_for_paper"]
    operating = market == "available"
    return {
        "market_data": market,
        "approved_for_paper": approved,
        "historical_research": "unavailable",
        "evaluation": "available" if operating else "unavailable",
        "message": OPERATING if operating else MESSAGE,
    }


def pair_board():
    from ops.worker import pair_availability

    rows = []
    for row in pair_availability():
        minute = row["symbol"] == "XAUUSD" and row["interval"] in {"1m", "3m"}
        if minute and row["interval"] == "3m":
            rights, source, latest, evaluation = "Public 1-minute candles", "Gold chart, three complete minutes", "Desk", "Paper"
        elif minute:
            rights, source, latest, evaluation = "Public 1-minute chart", "Gold chart", "Desk", "Paper"
        else:
            source = "Gold chart" if row["symbol"] == "XAUUSD" else "Binance spot"
            rights, latest, evaluation = "Public completed candle", "Desk", "Paper"
        rows.append({
            "instrument": row["symbol"],
            "timeframe": row["interval"],
            "rights": rights,
            "source": source,
            "history": "No retained historical data",
            "latest_read": latest,
            "evaluation": evaluation,
            "approval": "Paper signals",
            "observation": "public_candle",
            "research": "not_promoted",
            "execution": "paper",
        })
    return rows


def platform_state(worker=None):
    gates = product_gates()
    worker = worker or {}
    beating = worker.get("status") == "beating" and worker.get("healthy") is True
    approved = gates["approved_for_paper"]
    operating = gates["market_data"] == "available"
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
        "message": gates["message"],
        "requirement": (
            "A public completed candle can be shown. Paper orders fill on this desk. Historical research archives stay closed."
            if operating else
            "A public candle for that market, and a paper plan that passes the account checks, "
            "are both required before a reading or a paper order is shown."
        ),
        "states": [
            {"id": "application", "label": "Application", "value": "Operational"},
            {"id": "worker", "label": "Worker", "value": "Operational" if beating else "Not confirmed"},
            {"id": "market_data", "label": "Market data", "value": "Public candles" if operating else "Not available"},
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