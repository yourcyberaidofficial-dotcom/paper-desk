"""Strategies the live evaluator can name. Recorded research status is not approval."""

STRATEGIES = (
    {
        "id": "E1-donchian-20",
        "version": "e1-20261016",
        "name": "E1 Donchian-20",
        "instruments": ["BTCUSDT", "ETHUSDT"],
        "timeframe": "15m",
        "entry": "Close beyond the prior 20 completed bars.",
        "invalidation": "The other side of that 20-bar channel.",
        "research_status": "FAIL",
        "evidence": "BTC and ETH 15m validation failed the frozen gates. docs/GATE2_RESULTS.md",
        "promoted": False,
        "live": True,
    },
    {
        "id": "tf-pullback-20261027",
        "version": "tf-pullback-20261027",
        "name": "Trend pullback",
        "instruments": ["BTCUSDT", "ETHUSDT", "XAUUSD"],
        "timeframe": "15m or 1h",
        "entry": "Pullback in the direction of the higher-timeframe regime.",
        "invalidation": "The setup's stop, or the next bar if levels cannot be placed.",
        "research_status": "FAIL",
        "evidence": "Validation failed on BTC, ETH and XAUUSD. docs/GATE3_RESULTS.md",
        "promoted": False,
        "live": True,
    },
    {
        "id": "vol-break-20261027",
        "version": "vol-break-20261027",
        "name": "Volatility breakout",
        "instruments": ["BTCUSDT", "ETHUSDT", "XAUUSD"],
        "timeframe": "15m or 1h",
        "entry": "Break of a quiet range after a volatility filter.",
        "invalidation": "The setup stop. Gold was not scored with measured bid/ask.",
        "research_status": "FAIL",
        "evidence": "Validation failed. Gold rows are also blocked for measured spread. docs/GATE3_RESULTS.md",
        "promoted": False,
        "live": True,
    },
    {
        "id": "mr-range-20261027",
        "version": "mr-range-20261027",
        "name": "Range reversion",
        "instruments": ["BTCUSDT", "ETHUSDT", "XAUUSD"],
        "timeframe": "15m or 1h",
        "entry": "Fade of a range extreme when the regime filter allows it.",
        "invalidation": "Beyond the range extreme.",
        "research_status": "FAIL",
        "evidence": "Crypto validation failed. Gold had no sample. docs/GATE3_RESULTS.md",
        "promoted": False,
        "live": True,
    },
    {
        "id": "xau-session-20261027",
        "version": "xau-session-20261027",
        "name": "Gold session pullback",
        "instruments": ["XAUUSD"],
        "timeframe": "1h",
        "entry": "Pullback during the defined gold signal session.",
        "invalidation": "Outside the session, or the setup stop.",
        "research_status": "FAIL",
        "evidence": "Validation sample was too small and had no measured bid/ask. docs/GATE3_RESULTS.md",
        "promoted": False,
        "live": True,
    },
)

BY_ID = {row["id"]: row for row in STRATEGIES}


def catalog():
    return {"strategies": list(STRATEGIES), "promoted_count": 0, "selection": "deterministic"}


def compatible(symbol):
    return [row for row in STRATEGIES if symbol in row["instruments"]]
