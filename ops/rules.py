"""Explicit research rules. Not validated."""

from ops.e1 import e1_side
from ops.indicators import sma, rsi

RULES = {
    "E1-donchian-20": "e1-20261016",
    "SMA20-cross": "sma20-cross-20261017",
    "RSI14-band": "rsi14-band-20261017",
}


def rule_states(bars):
    closes = [b["close"] for b in bars]
    return [
        {"strategy": "E1-donchian-20", "version": RULES["E1-donchian-20"], "direction": e1_side(bars), "validated": False},
        _sma(closes),
        _rsi(closes),
    ]


def _sma(closes):
    value = sma(closes, 20)
    prev = sma(closes[:-1], 20) if len(closes) > 21 else None
    direction = "WAIT"
    if value is not None and prev is not None:
        if closes[-2] <= prev and closes[-1] > value:
            direction = "LONG_BIAS"
        elif closes[-2] >= prev and closes[-1] < value:
            direction = "SHORT_BIAS"
    return {"strategy": "SMA20-cross", "version": RULES["SMA20-cross"], "direction": direction, "sma20": value, "validated": False}


def _rsi(closes):
    value = rsi(closes, 14)
    direction = "WAIT"
    if value is not None:
        if value <= 30:
            direction = "LONG_BIAS"
        elif value >= 70:
            direction = "SHORT_BIAS"
    return {"strategy": "RSI14-band", "version": RULES["RSI14-band"], "direction": direction, "rsi14": value, "validated": False}
