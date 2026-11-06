"""Facts read off completed candles.

Rising, falling, wide and narrow are descriptions of the bars supplied.
They are not probabilities, confidence scores, or orders.
"""

from __future__ import annotations

from ops.bars import interval_ms


def assess(bars, now_ms, interval):
    completed = [
        bar for bar in (bars or [])
        if isinstance(bar, dict)
        and bar.get("complete") is True
        and bar.get("close") is not None
        and int(bar.get("close_time_ms") or 0) <= int(now_ms)
    ]
    if len(completed) < 2:
        return {
            "trend": "unknown",
            "momentum": "unknown",
            "volatility": "unknown",
            "freshness": "missing",
            "evidence": "Fewer than two completed candles. No signal was formed.",
        }
    window = completed[-21:]
    first_close = window[0]["close"]
    last = completed[-1]
    last_close = last["close"]
    if last_close > first_close:
        trend = "rising"
    elif last_close < first_close:
        trend = "falling"
    else:
        trend = "flat"
    tail = [bar["close"] for bar in completed[-3:]]
    if len(tail) == 3 and tail[0] < tail[1] < tail[2]:
        momentum = "up"
    elif len(tail) == 3 and tail[0] > tail[1] > tail[2]:
        momentum = "down"
    else:
        momentum = "mixed"
    ranges = []
    for bar in window[:-1]:
        high, low = bar.get("high"), bar.get("low")
        if isinstance(high, (int, float)) and isinstance(low, (int, float)) and not isinstance(high, bool):
            ranges.append(high - low)
    last_high, last_low = last.get("high"), last.get("low")
    last_range = None
    if isinstance(last_high, (int, float)) and isinstance(last_low, (int, float)) and not isinstance(last_high, bool):
        last_range = last_high - last_low
    if not ranges or last_range is None:
        volatility = "unknown"
    else:
        ranges.sort()
        mid = ranges[len(ranges) // 2]
        if mid <= 0:
            volatility = "unknown"
        elif last_range > mid * 1.5:
            volatility = "wide"
        elif last_range < mid * 0.5:
            volatility = "narrow"
        else:
            volatility = "ordinary"
    try:
        fresh = int(now_ms) - int(last["close_time_ms"]) <= 2 * interval_ms(interval)
    except ValueError:
        fresh = False
    freshness = "fresh" if fresh else "stale"
    return {
        "trend": trend,
        "momentum": momentum,
        "volatility": volatility,
        "freshness": freshness,
        "evidence": (
            f"Trend {trend}. Momentum {momentum}. Range {volatility}. Freshness {freshness}. "
            "No probability is assigned."
        ),
    }
