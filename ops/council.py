"""Simplified Awuru-style strategy council for Aureon.

Uses existing E1, SMA20, and RSI14 outputs. Does not invent indicators.
WAIT is the default when votes disagree.
"""

VERSION = "awuru-council-20261018"


def _vote(name: str, direction: str, weight: float) -> dict:
    return {"name": name, "direction": direction, "weight": weight}


def council(e1: str, sma: str, rsi: str, fresh: bool) -> dict:
    votes = [
        _vote("E1 Donchian-20", e1, 1.2),
        _vote("SMA20 observation", sma, 1.0),
        _vote("RSI14 observation", rsi, 0.9),
    ]
    buy = sum(v["weight"] for v in votes if "LONG" in v["direction"])
    sell = sum(v["weight"] for v in votes if "SHORT" in v["direction"])
    wait = sum(v["weight"] for v in votes if v["direction"] == "WAIT")
    total = buy + sell + wait + 1e-9
    if not fresh:
        state, score = "WAIT", 0.0
        reason = "Stale data. Council blocks directional release."
    elif buy > sell * 1.18 and buy > wait * 0.75:
        state, score = "LONG_BIAS", round(buy / total, 3)
        reason = "Council agrees on bullish bias."
    elif sell > buy * 1.18 and sell > wait * 0.75:
        state, score = "SHORT_BIAS", round(sell / total, 3)
        reason = "Council agrees on bearish bias."
    else:
        state, score = "WAIT", round(wait / total, 3)
        reason = "Votes disagree or are weak. WAIT protects capital."
    return {
        "version": VERSION,
        "state": state,
        "score": score,
        "reason": reason,
        "votes": votes,
        "note": "Council is research context, not a validated trade signal.",
    }
