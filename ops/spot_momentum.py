"""Long-only one-hour time-series momentum for spot BTC and ETH.

Frozen before the 2026-10-28 run. Not a rewrite of E1 or the Gate 3 families.
A rising 24-bar close, confirmed by a close above the 20-bar average, enters
long on the next bar's open. Spot shorts are not simulated. The stop is 1.5
times the 14-bar ATR known at the signal bar. The target is twice that risk.
The position times out after 24 completed bars. Costs stay at the existing
11 bps per fill, 15 bps under stress, two fills. Gold is out of scope because
this rule has no measured bid/ask model.
"""

from ops.hypotheses import _atr

STRATEGY = "spot-tsmom-1h-20261028"
LOOKBACK = 24
HOLD = 24


def setup(bars, index, higher, symbol):
    del higher
    if symbol not in {"BTCUSDT", "ETHUSDT"} or bars[index].get("interval") != "1h":
        return None
    if index < LOOKBACK or not bars[index].get("complete", True):
        return None
    closes = [bar["close"] for bar in bars[: index + 1]]
    average = sum(closes[-20:]) / 20
    if closes[-1] <= closes[-1 - LOOKBACK] or closes[-1] <= average:
        return None
    atr = _atr(bars, index)
    if atr is None or atr <= 0:
        return None
    return {
        "strategy": STRATEGY,
        "version": STRATEGY,
        "direction": "LONG",
        "anchor_open_ms": bars[index]["open_time_ms"],
        "target_mode": "atr",
        "stop_multiple": 1.5,
        "target_multiple": 3.0,
        "atr": atr,
        "hold_bars": HOLD,
        "reward_risk": 2.0,
    }


def range_fade(bars, index, higher, symbol):
    """Buy only the bottom of a tight one-hour range. Disabled when the range is wide."""
    del higher
    if symbol not in {"BTCUSDT", "ETHUSDT"} or bars[index].get("interval") != "1h" or index < 20:
        return None
    window = bars[index - 19 : index + 1]
    high = max(bar["high"] for bar in window)
    low = min(bar["low"] for bar in window)
    close = bars[index]["close"]
    if high <= low or close <= 0 or (high - low) / close >= 0.015:
        return None
    if close > low + 0.15 * (high - low):
        return None
    return {
        "strategy": "tight-range-long-1h-20261028",
        "version": "tight-range-long-1h-20261028",
        "direction": "LONG",
        "anchor_open_ms": bars[index]["open_time_ms"],
        "target_mode": "level",
        "stop_price": low,
        "target_price": (high + low) / 2,
        "hold_bars": 12,
        "reward_risk": 1.0,
    }


RULES = {
    STRATEGY: setup,
    "tight-range-long-1h-20261028": range_fade,
}
