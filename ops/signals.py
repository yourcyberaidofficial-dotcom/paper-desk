"""Independent research strategy states. Not production. Not validated."""

from ops.e1 import e1_side
from ops.indicators import sma, rsi


def research_states(bars):
    closes = [b["close"] for b in bars]
    states = []
    states.append(_donchian(bars))
    states.append(_sma(closes))
    states.append(_rsi(closes))
    return states


def _donchian(bars):
    side = e1_side(bars)
    return {
        "strategy": "E1-donchian-20",
        "version": "e1-20261016",
        "direction": side,
        "classification": "research_observation",
        "validated": False,
        "evidence": "negative after costs on two-year development data",
    }


def _sma(closes):
    value = sma(closes, 20)
    direction = "WAIT"
    if value is not None:
        direction = "LONG_BIAS" if closes[-1] > value else "SHORT_BIAS"
    return {
        "strategy": "SMA20-state",
        "version": "research-20261017",
        "direction": direction,
        "sma20": value,
        "classification": "research_observation",
        "validated": False,
        "evidence": "state only; not a promoted entry rule",
    }


def _rsi(closes):
    value = rsi(closes, 14)
    direction = "WAIT"
    if value is not None:
        if value >= 70:
            direction = "SHORT_BIAS"
        elif value <= 30:
            direction = "LONG_BIAS"
    return {
        "strategy": "RSI14-state",
        "version": "research-20261017",
        "direction": direction,
        "rsi14": value,
        "classification": "research_observation",
        "validated": False,
        "evidence": "state only; not a promoted entry rule",
    }
