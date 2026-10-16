"""E1 Donchian. Frozen. No parameter search."""

LOOKBACK = 20


def e1_side(bars):
    if len(bars) < LOOKBACK + 1:
        return "WAIT"
    prior = bars[-(LOOKBACK + 1):-1]
    decision = bars[-1]
    high = max(b["high"] for b in prior)
    low = min(b["low"] for b in prior)
    if decision["close"] > high:
        return "LONG_BIAS"
    if decision["close"] < low:
        return "SHORT_BIAS"
    return "WAIT"
