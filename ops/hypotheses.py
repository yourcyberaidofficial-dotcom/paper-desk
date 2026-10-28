"""Frozen Gate 3 rules. See docs/GATE3_SPEC.md. No parameter search."""

from datetime import datetime, timezone

from ops.e1 import e1_side
from ops.indicators import rsi, sma
from ops.sessions import gold_market_open, gold_signal_session

VERSIONS = {
    "E1-donchian-20": "e1-20261016",
    "tf-pullback-20261027": "tf-pullback-20261027",
    "vol-break-20261027": "vol-break-20261027",
    "mr-range-20261027": "mr-range-20261027",
    "xau-session-20261027": "xau-session-20261027",
}

# Gates frozen before holdout results. Not an industry standard.
GATES = {
    "min_trades": 30,
    "min_half_trades": 10,
    "max_drawdown": 0.25,
    "max_loss_streak": 12,
    "gold_requires_measured_spread": True,
}

CRYPTO_COST = {"base_bps_per_fill": 11, "stress_bps_per_fill": 15, "fills": 2, "kind": "bps"}
GOLD_COST = {
    "base_usd_per_side": 0.50,
    "stress_usd_per_side": 1.50,
    "kind": "usd_per_oz",
    "measured_bid_ask": False,
}


def event_id(strategy, symbol, interval, direction, anchor_open_ms):
    return f"{strategy}:{symbol}:{interval}:{direction}:{int(anchor_open_ms)}"


def _atr(bars, index, length=14):
    if index < length + 1:
        return None
    total = 0.0
    for cursor in range(index - length, index):
        previous = bars[cursor - 1]["close"]
        high = bars[cursor]["high"]
        low = bars[cursor]["low"]
        total += max(high - low, abs(high - previous), abs(low - previous))
    return total / length


def _true_range(bars, index):
    previous = bars[index - 1]["close"]
    high = bars[index]["high"]
    low = bars[index]["low"]
    return max(high - low, abs(high - previous), abs(low - previous))


def _sma_at(bars, index, length):
    if index + 1 < length:
        return None
    return sum(bars[cursor]["close"] for cursor in range(index + 1 - length, index + 1)) / length


def _break(bars, index):
    if index < 20:
        return None
    prior = bars[index - 20:index]
    high = max(bar["high"] for bar in prior)
    low = min(bar["low"] for bar in prior)
    close = bars[index]["close"]
    if close > high:
        return "LONG"
    if close < low:
        return "SHORT"
    return None


def _cutoff(higher, close_time_ms):
    lo, hi = 0, len(higher)
    while lo < hi:
        mid = (lo + hi) // 2
        if higher[mid]["close_time_ms"] <= close_time_ms:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _asof(higher, close_time_ms):
    end = _cutoff(higher, close_time_ms)
    if end == 0:
        return None
    return higher[end - 1]


def _higher_tail(higher, close_time_ms, length):
    end = _cutoff(higher, close_time_ms)
    if end < length:
        return higher[:end]
    return higher[end - length:end]


def _regime(higher, close_time_ms, length):
    tail = _higher_tail(higher, close_time_ms, length)
    if len(tail) < length:
        return None, tail
    value = sum(bar["close"] for bar in tail) / length
    close = tail[-1]["close"]
    if close > value:
        return "LONG", tail
    if close < value:
        return "SHORT", tail
    return None, tail


def _session_ok(symbol, strategy, bar):
    if symbol != "XAUUSD":
        return True, None
    moment = datetime.fromtimestamp(bar["open_time_ms"] / 1000, timezone.utc)
    if not gold_market_open(moment):
        return False, "MARKET_CLOSED"
    if strategy == "xau-session-20261027" and not gold_signal_session(moment):
        return False, "OUTSIDE_SESSION"
    return True, None


def e1_observation(bars, index):
    window = [{"high": bar["high"], "low": bar["low"], "close": bar["close"]} for bar in bars[: index + 1]]
    side = e1_side(window)
    if side == "WAIT":
        return None
    return {
        "strategy": "E1-donchian-20",
        "version": VERSIONS["E1-donchian-20"],
        "direction": "LONG" if side == "LONG_BIAS" else "SHORT",
        "anchor_open_ms": bars[index]["open_time_ms"],
        "benchmark_failed": True,
    }


def tf_pullback_setup(bars, index, higher, symbol, strategy="tf-pullback-20261027"):
    allowed, reason = _session_ok(symbol, strategy, bars[index])
    if not allowed:
        return {"rejected": reason}
    length = 48 if symbol != "XAUUSD" else 12
    regime, _window = _regime(higher, bars[index]["close_time_ms"], length)
    if regime is None or index < 20:
        return None
    if _pullback_fires(bars, index, regime):
        previous = _pullback_fires(bars, index - 1, regime) if index else False
        if previous:
            return None
        window = bars[max(0, index - 5): index + 1]
        stop = min(bar["low"] for bar in window) if regime == "LONG" else max(bar["high"] for bar in window)
        return {
            "strategy": strategy,
            "version": VERSIONS[strategy],
            "direction": regime,
            "anchor_open_ms": bars[index]["open_time_ms"],
            "stop_price": stop,
            "reward_risk": 2.0,
            "hold_bars": 16,
            "target_mode": "rr",
        }
    return None


def _pullback_fires(bars, index, regime):
    if index < 20:
        return False
    sma_now = _sma_at(bars, index, 20)
    if sma_now is None:
        return False
    touched = False
    for cursor in range(max(19, index - 6), index):
        level = _sma_at(bars, cursor, 20)
        if level is None:
            continue
        if regime == "LONG" and bars[cursor]["close"] <= level:
            touched = True
        if regime == "SHORT" and bars[cursor]["close"] >= level:
            touched = True
    if not touched:
        return False
    close = bars[index]["close"]
    previous = bars[index - 1]["close"]
    if regime == "LONG":
        return close > sma_now and close > previous
    return close < sma_now and close < previous


def vol_break_setup(bars, index, higher, symbol, strategy="vol-break-20261027"):
    del higher
    allowed, reason = _session_ok(symbol, strategy, bars[index])
    if not allowed:
        return {"rejected": reason}
    if index < 21:
        return None
    side = _break(bars, index)
    if side is None:
        return None
    if _break(bars, index - 1) == side:
        return None
    width = _atr(bars, index, 14)
    if width is None or width <= 0:
        return None
    if _true_range(bars, index) < width:
        return None
    return {
        "strategy": strategy,
        "version": VERSIONS[strategy],
        "direction": side,
        "anchor_open_ms": bars[index]["open_time_ms"],
        "atr": width,
        "stop_multiple": 1.5,
        "target_multiple": 3.0,
        "reward_risk": 2.0,
        "hold_bars": 24,
        "target_mode": "atr",
    }


def mr_range_setup(bars, index, higher, symbol, strategy="mr-range-20261027"):
    allowed, reason = _session_ok(symbol, strategy, bars[index])
    if not allowed:
        return {"rejected": reason}
    if index < 21:
        return None
    window = _higher_tail(higher, bars[index]["close_time_ms"], 40)
    if len(window) < 35:
        return None
    last = len(window) - 1
    prior = window[last - 20:last]
    high = max(bar["high"] for bar in prior)
    low = min(bar["low"] for bar in prior)
    if not (low < window[last]["close"] < high):
        return None
    width = _atr(window, last, 14)
    if width is None or window[last]["close"] <= 0 or width / window[last]["close"] >= 0.004:
        return None
    entry_prior = bars[index - 20:index]
    entry_high = max(bar["high"] for bar in entry_prior)
    entry_low = min(bar["low"] for bar in entry_prior)
    close = bars[index]["close"]
    if not (entry_low < close < entry_high):
        return None
    tail = bars[index - 20: index + 1]
    closes = [bar["close"] for bar in tail]
    value = rsi(closes, 14)
    previous = rsi(closes[:-1], 14)
    if value is None or previous is None:
        return None
    if previous > 30 and value <= 30:
        side = "LONG"
    elif previous < 70 and value >= 70:
        side = "SHORT"
    else:
        return None
    local = _atr(bars, index, 14)
    if local is None or local <= 0:
        return None
    mean = sma(closes, 20)
    if mean is None:
        return None
    stop = bars[index]["low"] - 0.5 * local if side == "LONG" else bars[index]["high"] + 0.5 * local
    return {
        "strategy": strategy,
        "version": VERSIONS[strategy],
        "direction": side,
        "anchor_open_ms": bars[index]["open_time_ms"],
        "stop_price": stop,
        "target_price": mean,
        "reward_risk": None,
        "hold_bars": 12,
        "target_mode": "mean",
        "rsi_exit": 50,
    }


SETUP = {
    "tf-pullback-20261027": tf_pullback_setup,
    "vol-break-20261027": vol_break_setup,
    "mr-range-20261027": mr_range_setup,
    "xau-session-20261027": lambda bars, index, higher, symbol: tf_pullback_setup(bars, index, higher, symbol, "xau-session-20261027"),
}

FAMILIES = ("tf-pullback-20261027", "vol-break-20261027", "mr-range-20261027")
GOLD_ONLY = ("xau-session-20261027",)
CRYPTO = ("BTCUSDT", "ETHUSDT")
