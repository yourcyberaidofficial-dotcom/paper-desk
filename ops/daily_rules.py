"""Frozen on 2026-10-28 before this run was scored.

These are daily spot rules. They are not edits of the 4h compression
breakout or the 4h failed-breakdown reclaim. Those two stay FAIL.
The saved reason they failed is cost and instability: the BTC reclaim
was positive before 11 bps per fill and negative after, and neither
rule beat buy-and-hold or cleared both chronological halves.
Spot shorts are not simulated. The last 20 percent of daily bars is sealed.
"""

DIP = "dip-in-trend-1d-20261028"
WEEK = "quiet-week-reversal-1d-20261028"


def _sma(bars, index, length):
    if index + 1 < length:
        return None
    return sum(bar["close"] for bar in bars[index + 1 - length : index + 1]) / length


def dip_in_trend(bars, index, higher, symbol):
    del higher
    if symbol not in {"BTCUSDT", "ETHUSDT"} or bars[index].get("interval") != "1d" or index < 100:
        return None
    close = bars[index]["close"]
    average = _sma(bars, index, 100)
    if average is None or close <= average or close >= bars[index - 1]["close"] * 0.98:
        return None
    if bars[index]["low"] >= close:
        return None
    return {
        "strategy": DIP,
        "version": DIP,
        "direction": "LONG",
        "anchor_open_ms": bars[index]["open_time_ms"],
        "target_mode": "rr",
        "stop_price": bars[index]["low"],
        "reward_risk": 1.5,
        "hold_bars": 5,
    }


def quiet_week(bars, index, higher, symbol):
    del higher
    if symbol not in {"BTCUSDT", "ETHUSDT"} or bars[index].get("interval") != "1d" or index < 6:
        return None
    if (index - 5) % 5 != 0:
        return None
    window = bars[index - 4 : index + 1]
    previous = bars[index - 5]["close"]
    close = bars[index]["close"]
    if close >= previous or close <= 0:
        return None
    high = max(bar["high"] for bar in window)
    low = min(bar["low"] for bar in window)
    if (high - low) / close >= 0.06:
        return None
    return {
        "strategy": WEEK,
        "version": WEEK,
        "direction": "LONG",
        "anchor_open_ms": bars[index]["open_time_ms"],
        "target_mode": "level",
        "stop_price": low,
        "target_price": previous,
        "hold_bars": 5,
        "reward_risk": 1.0,
    }


RULES = {DIP: dip_in_trend, WEEK: quiet_week}


def daily_from_4h(bars):
    """One daily bar only when all six UTC 4h bars exist. Missing hours are not filled."""
    from ops.bars import make_bar

    groups = {}
    for bar in bars:
        day = bar["open_time_ms"] - (bar["open_time_ms"] % 86_400_000)
        groups.setdefault(day, []).append(bar)
    out = []
    step = 14_400_000
    for day in sorted(groups):
        chunk = sorted(groups[day], key=lambda item: item["open_time_ms"])
        if len(chunk) != 6:
            continue
        if any(chunk[i]["open_time_ms"] != day + i * step for i in range(6)):
            continue
        out.append(make_bar(
            symbol=chunk[-1]["symbol"],
            instrument=chunk[-1]["symbol"],
            interval="1d",
            open_time_ms=day,
            close_time_ms=day + 86_400_000 - 1,
            open=chunk[0]["open"],
            high=max(item["high"] for item in chunk),
            low=min(item["low"] for item in chunk),
            close=chunk[-1]["close"],
            volume=sum(item.get("volume") or 0 for item in chunk),
            provider=chunk[-1].get("provider"),
            source_type="resampled_4h",
            quote_semantics="last_trade",
            complete=True,
            fresh=False,
        ))
    return out
