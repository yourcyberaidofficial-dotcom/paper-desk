"""Awuru-style council for Aureon. WAIT when votes disagree or data is incomplete."""

VERSION = "awuru-council-20261018b"


def _kind(direction: str) -> str:
    if direction in {"LONG_BIAS", "SHORT_BIAS"}:
        return "directional"
    if direction == "WAIT":
        return "neutral"
    return "unavailable"


def council(e1: str, sma: str, rsi: str, fresh: bool, candle: str | None = None) -> dict:
    votes = [
        {"name": "E1 Donchian-20", "direction": e1, "weight": 1.2, "rule": "Close outside prior 20-bar high/low", "kind": _kind(e1)},
        {"name": "SMA20 observation", "direction": sma, "weight": 1.0, "rule": "Close vs prior SMA20", "kind": _kind(sma)},
        {"name": "RSI14 observation", "direction": rsi, "weight": 0.9, "rule": "RSI above/below 50", "kind": _kind(rsi)},
    ]
    buy = sum(v["weight"] for v in votes if "LONG" in v["direction"])
    sell = sum(v["weight"] for v in votes if "SHORT" in v["direction"])
    wait = sum(v["weight"] for v in votes if v["direction"] == "WAIT")
    total = buy + sell + wait + 1e-9
    if not fresh:
        state, score = "WAIT", 0.0
        reason = "Stale or missing data. Council blocks directional release."
        next_condition = "Fresh completed candle required."
    elif buy > sell * 1.18 and buy > wait * 0.75:
        state, score = "LONG_BIAS", round(buy / total, 3)
        reason = "Council agrees on bullish bias."
        next_condition = "Agreement would break if E1 or SMA turns against the long."
    elif sell > buy * 1.18 and sell > wait * 0.75:
        state, score = "SHORT_BIAS", round(sell / total, 3)
        reason = "Council agrees on bearish bias."
        next_condition = "Agreement would break if E1 or SMA turns against the short."
    else:
        state, score = "WAIT", round(wait / total, 3)
        sides = sorted({v["direction"] for v in votes})
        reason = "The research states do not agree (" + ", ".join({"LONG_BIAS": "bullish research", "SHORT_BIAS": "bearish research", "WAIT": "no direction"}.get(side, side) for side in sides) + "). This is not a paper order."
        next_condition = "WAIT clears only if E1 and SMA agree and RSI does not contradict."
    return {
        "version": VERSION,
        "state": state,
        "score": score,
        "reason": reason,
        "next_condition": next_condition,
        "candle": candle,
        "votes": votes,
        "note": "Council is research context, not a validated trade signal.",
    }
