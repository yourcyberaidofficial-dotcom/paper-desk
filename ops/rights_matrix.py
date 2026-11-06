"""Per-instrument rights view.

A successful socket is not a row in this matrix. Each desk pair is judged
on its own source. Nothing here writes a grant or opens a connection.
"""

from __future__ import annotations

from ops.data_rights import DESK, source
from ops.entitlements import decide_use

# Native vendor intervals. 3m crypto is derived only from a complete 1m grant.
NATIVE = {
    ("BTCUSDT", "1m"): ("kraken_public_ohlc", "1"),
    ("BTCUSDT", "15m"): ("kraken_public_ohlc", "15"),
    ("BTCUSDT", "1h"): ("kraken_public_ohlc", "60"),
    ("ETHUSDT", "1m"): ("kraken_public_ohlc", "1"),
    ("ETHUSDT", "15m"): ("kraken_public_ohlc", "15"),
    ("ETHUSDT", "1h"): ("kraken_public_ohlc", "60"),
    ("XAUUSD", "1m"): ("twelve_data", "1min"),
    ("XAUUSD", "15m"): ("twelve_data", "15min"),
    ("XAUUSD", "1h"): ("twelve_data", "1h"),
}

USES = {
    "retrieval": "candle_display",
    "internal_research": "research_backtest",
    "customer_display": "customer_reading",
    "derived_indicators": "indicator_calculation",
    "derived_signals": "opportunity_generation",
    "historical_storage": "raw_data_retention",
    "redistribution": "notifications",
}


def _cell(source_id, symbol, interval, use):
    decision = decide_use(source_id, use, symbol=symbol, interval=interval)
    return {
        "allowed": decision.get("verified") is True,
        "status": decision.get("status"),
        "reason": decision.get("reason"),
    }


def matrix():
    rows = []
    for symbol, interval in DESK:
        if symbol == "XAUUSD" and interval == "3m":
            source_id = "twelve_data"
            native = None
            derived = False
            note = "No native 3-minute gold candle. It is not built from another product."
        elif interval == "3m":
            source_id = "kraken_public_ohlc"
            native = None
            derived = True
            note = "Kraken has no native 3-minute candle. Derivation needs a recorded 1-minute grant."
        else:
            source_id, native = NATIVE[(symbol, interval)]
            derived = False
            note = "XBT/USDT maps to BTCUSDT and ETH/USDT maps to ETHUSDT." if source_id == "kraken_public_ohlc" else "XAUUSD stays on its own adapter. Indicative spot is not a tradable quote."
        record = source(source_id) or {}
        uses = {name: _cell(source_id, symbol, interval, capability) for name, capability in USES.items()}
        uses["local_ai_processing"] = {
            "allowed": False,
            "status": "unverified",
            "reason": "no_market_text_grant",
        }
        rows.append({
            "symbol": symbol,
            "interval": interval,
            "source_id": source_id,
            "native_interval": native,
            "derived": derived,
            "territory": None,
            "expires": None,
            "attribution": record.get("attribution"),
            "agreement": record.get("written_approval"),
            "customer_live_signal": uses["customer_display"]["allowed"] is True and uses["derived_signals"]["allowed"] is True,
            "uses": uses,
            "note": note,
        })
    return {
        "rows": rows,
        "customer_live_signals": "blocked" if not any(row["customer_live_signal"] for row in rows) else "partial",
        "note": "An API response cannot move a cell to allowed. A missing display grant blocks the customer signal and does not invent a price.",
    }
