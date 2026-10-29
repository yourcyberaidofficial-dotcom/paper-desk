"""A reading of the candles that were requested.

This is not a frozen research rule and it is not an approval.
A 4-hour rule is not relabeled as a 15-minute rule.
"""

PAYOFF = 1.8


def _ema(values, length):
    k = 2 / (length + 1)
    prev = values[0]
    out = []
    for value in values:
        prev = value * k + prev * (1 - k)
        out.append(prev)
    return out


def _atr(bars, length=14):
    trs = []
    for index, bar in enumerate(bars):
        if index == 0:
            trs.append(bar["high"] - bar["low"])
            continue
        prev = bars[index - 1]["close"]
        trs.append(max(bar["high"] - bar["low"], abs(bar["high"] - prev), abs(bar["low"] - prev)))
    seed = sum(trs[:length]) / length
    value = seed
    for item in trs[length:]:
        value = (value * (length - 1) + item) / length
    return value


def _rsi(closes, length=14):
    if len(closes) < length + 1:
        return 50
    gain = 0
    loss = 0
    for index in range(1, length + 1):
        delta = closes[index] - closes[index - 1]
        if delta >= 0:
            gain += delta
        else:
            loss -= delta
    gain /= length
    loss /= length
    for index in range(length + 1, len(closes)):
        delta = closes[index] - closes[index - 1]
        gain = (gain * (length - 1) + max(delta, 0)) / length
        loss = (loss * (length - 1) + max(-delta, 0)) / length
    if loss == 0:
        return 100
    return 100 - 100 / (1 + gain / loss)


def _usable(entry, stop):
    if not entry or stop is None:
        return False
    risk = abs(entry - stop) / entry
    return stop == stop and 0.0015 <= risk <= 0.05


def _pullback(bars):
    closes = [bar["close"] for bar in bars]
    short = _ema(closes, 20)[-1]
    longer = _ema(closes, 50)[-1]
    width = _atr(bars)
    mood = _rsi(closes)
    last = bars[-1]
    recent = bars[-3:]
    recent_high = max(bar["high"] for bar in recent)
    recent_low = min(bar["low"] for bar in recent)
    calm = last["high"] - last["low"] < width * 2.4
    down = short < longer
    if down:
        checks = [
            ("Downtrend", True, f"The shorter average, {short:.2f}, is under the longer one, {longer:.2f}."),
            ("Tagged the average", recent_high >= short * 0.997, f"Price rose to {recent_high:.2f}, into the average."),
            ("Closed back under", last["close"] < short, f"It finished at {last['close']:.2f}, back under the average."),
            ("Not a spike", calm and 32 <= mood <= 62, "The candle is calm, not a blow-off."),
        ]
        stop = max(recent_high, short) + width * 0.15
        side = "SELL"
    else:
        checks = [
            ("Uptrend", short > longer, f"The shorter average, {short:.2f}, is over the longer one, {longer:.2f}."),
            ("Tagged the average", recent_low <= short * 1.003, f"Price dipped to {recent_low:.2f}, into the average."),
            ("Closed back over", last["close"] > short, f"It finished at {last['close']:.2f}, back over the average."),
            ("Not a spike", calm and 40 <= mood <= 68, "The candle is calm, not a blow-off."),
        ]
        stop = min(recent_low, short) - width * 0.15
        side = "BUY"
    if not all(ok for _name, ok, _detail in checks) or not _usable(last["close"], stop):
        return None
    return {"side": side, "entry": last["close"], "stop": stop, "name": "Trend pullback", "checks": checks}


def _reclaim(bars):
    closes = [bar["close"] for bar in bars]
    short = _ema(closes, 20)[-1]
    longer = _ema(closes, 50)[-1]
    width = _atr(bars)
    last = bars[-1]
    window = bars[-11:-1]
    hi = max(bar["high"] for bar in window)
    lo = min(bar["low"] for bar in window)
    down = short < longer
    if down:
        checks = [
            ("Downtrend", True, "The shorter average is below the longer average."),
            ("Failed breakout", last["high"] > hi and last["close"] < hi, f"Price poked above {hi:.2f} and finished back under it."),
        ]
        stop = last["high"] + width * 0.1
        side = "SELL"
    else:
        checks = [
            ("Uptrend", short > longer, "The shorter average is above the longer average."),
            ("Failed breakdown", last["low"] < lo and last["close"] > lo, f"Price poked under {lo:.2f} and finished back over it."),
        ]
        stop = last["low"] - width * 0.1
        side = "BUY"
    if not all(ok for _name, ok, _detail in checks) or not _usable(last["close"], stop):
        return None
    return {"side": side, "entry": last["close"], "stop": stop, "name": "Failed break", "checks": checks}


def _range_break(bars):
    """Close beyond the prior twenty bars. Separate from the failed Donchian research id."""
    if len(bars) < 21:
        return None
    last = bars[-1]
    prior = bars[-21:-1]
    hi = max(bar["high"] for bar in prior)
    lo = min(bar["low"] for bar in prior)
    width = _atr(bars)
    short = _ema([bar["close"] for bar in bars], 20)[-1]
    if last["close"] > hi and last["close"] > short:
        stop = min(last["low"], hi) - width * 0.05
        if stop >= last["close"]:
            stop = last["close"] - max(width * 0.4, last["close"] * 0.004)
        side = "BUY"
        detail = f"The close {last['close']:.2f} is above the prior twenty-bar high {hi:.2f}."
    elif last["close"] < lo and last["close"] < short:
        stop = max(last["high"], lo) + width * 0.05
        if stop <= last["close"]:
            stop = last["close"] + max(width * 0.4, last["close"] * 0.004)
        side = "SELL"
        detail = f"The close {last['close']:.2f} is below the prior twenty-bar low {lo:.2f}."
    else:
        return None
    if not _usable(last["close"], stop):
        return None
    return {"side": side, "entry": last["close"], "stop": stop, "name": "Range expansion", "checks": [("Break", True, detail)]}


def _watch_plan(bars, label):
    """A setup that has not triggered. Not an entry and not an order."""
    closes = [bar["close"] for bar in bars]
    short = _ema(closes, 20)[-1]
    longer = _ema(closes, 50)[-1]
    width = _atr(bars)
    last = bars[-1]
    if short < longer:
        recent_high = max(bar["high"] for bar in bars[-3:])
        stop = max(recent_high, short) + width * 0.15
        entry = short
        if not _usable(entry, stop):
            return None
        target = entry - PAYOFF * abs(stop - entry)
        return {
            "decision": "WAIT",
            "runtime_status": "watch",
            "reason": (
                f"Watch on this {label} candle. The shorter average, {short:.2f}, is below the longer one, {longer:.2f}, "
                f"but the close {last['close']:.2f} has not completed a short trigger. "
                f"A short idea is not an entry until a close back through {entry:.2f}. "
                f"If that happens, the plan would use a stop near {stop:.2f} and a target near {target:.2f}. "
                "No broker order is sent."
            ),
            "entry": None,
            "stop": None,
            "target": None,
            "watch_entry": entry,
            "watch_stop": stop,
            "watch_target": target,
            "reward_risk": None,
            "rule": "Trend pullback",
            "watch_side": "SELL",
        }
    if short <= longer:
        return None
    recent_low = min(bar["low"] for bar in bars[-3:])
    stop = min(recent_low, short) - width * 0.15
    entry = short
    if not _usable(entry, stop):
        return None
    target = entry + PAYOFF * abs(entry - stop)
    return {
        "decision": "WAIT",
        "runtime_status": "watch",
        "reason": (
            f"Watch on this {label} candle. The shorter average, {short:.2f}, is above the longer one, {longer:.2f}, "
            f"but the close {last['close']:.2f} has not completed the pullback. "
            f"A long is not an entry until a close back through {entry:.2f}. "
            f"If that happens, the plan would use a stop near {stop:.2f} and a target near {target:.2f}."
        ),
        "entry": None,
        "stop": None,
        "target": None,
        "watch_entry": entry,
        "watch_stop": stop,
        "watch_target": target,
        "reward_risk": None,
        "rule": "Trend pullback",
    }


def read_spot_sample(interval, bars):
    """Gold hours built from spot samples. Shorter averages, because about two days are available."""
    label = interval or "1h"
    if len(bars) < 24:
        return {
            "decision": "WAIT",
            "reason": f"There are not enough completed {label} spot samples to judge gold. The Yahoo chart was not substituted.",
            "entry": None,
            "stop": None,
            "target": None,
            "reward_risk": None,
            "rule": None,
        }
    closes = [bar["close"] for bar in bars]
    short = _ema(closes, 8)[-1]
    longer = _ema(closes, 21)[-1]
    width = _atr(bars)
    last = bars[-1]
    recent_high = max(bar["high"] for bar in bars[-3:])
    recent_low = min(bar["low"] for bar in bars[-3:])
    down = short < longer
    if down:
        triggered = recent_high >= short * 0.999 and last["close"] < short
        stop = max(recent_high, short) + max(width * 0.15, last["close"] * 0.0015)
        side = "SELL"
    else:
        triggered = short > longer and recent_low <= short * 1.001 and last["close"] > short
        stop = min(recent_low, short) - max(width * 0.15, last["close"] * 0.0015)
        side = "BUY"
    if not triggered or not _usable(last["close"], stop):
        if down and _usable(short, max(recent_high, short) + last["close"] * 0.0015):
            entry = short
            watch_stop = max(recent_high, short) + max(width * 0.15, last["close"] * 0.0015)
            watch_target = entry - PAYOFF * abs(watch_stop - entry)
            return {
                "decision": "WAIT",
                "runtime_status": "watch",
                "reason": (
                    f"Watch on this {label} spot sample. The 8-sample average {short:.2f} is below the 21-sample average {longer:.2f}, "
                    f"but the close {last['close']:.2f} has not finished back under {entry:.2f}. That is not an entry. "
                    f"If it does, the plan would use a stop near {watch_stop:.2f} and a target near {watch_target:.2f}."
                ),
                "entry": None,
                "stop": None,
                "target": None,
                "watch_entry": entry,
                "watch_stop": watch_stop,
                "watch_target": watch_target,
                "reward_risk": None,
                "rule": "Spot-sample pullback",
                "watch_side": "SELL",
            }
        return {
            "decision": "WAIT",
            "reason": f"No setup on this {label} spot sample. The 8-sample and 21-sample averages did not complete a pullback.",
            "entry": None,
            "stop": None,
            "target": None,
            "reward_risk": None,
            "rule": None,
        }
    risk = abs(last["close"] - stop)
    target = last["close"] - PAYOFF * risk if side == "SELL" else last["close"] + PAYOFF * risk
    if side == "SELL":
        return {
            "decision": "SELL",
            "sell_meaning": "short_idea",
            "reason": (
                f"Short idea on this {label} spot sample. Spot-sample pullback. "
                f"The 8-sample average {short:.2f} is below the 21-sample average {longer:.2f}, "
                f"and the close {last['close']:.2f} finished back under it. "
                f"Entry {last['close']:.2f}, stop {stop:.2f}, target {target:.2f}. "
                "No broker order is sent. This is not an exit of a long, and it is not approved."
            ),
            "entry": last["close"],
            "stop": stop,
            "target": target,
            "reward_risk": PAYOFF,
            "rule": "Spot-sample pullback",
        }
    return {
        "decision": "BUY",
        "reason": (
            f"Buy on this {label} spot sample. Spot-sample pullback. "
            f"The 8-sample average {short:.2f} is above the 21-sample average {longer:.2f}, "
            f"and the close {last['close']:.2f} finished back over it. "
            "This is not an approved strategy, and no order was sent."
        ),
        "entry": last["close"],
        "stop": stop,
        "target": target,
        "reward_risk": PAYOFF,
        "rule": "Spot-sample pullback",
    }


def read_interval(interval, bars):
    """Judge this exact candle series. Returns a match or the failed checks."""
    label = interval or "requested"
    if bars:
        stamped = bars[-1].get("interval")
        if stamped and stamped != interval:
            return {
                "decision": "WAIT",
                "reason": f"The candles returned were {stamped}, not {label}, so they were not used as this request.",
                "entry": None,
                "stop": None,
                "target": None,
                "reward_risk": None,
                "rule": None,
                "rejected_bars": True,
            }
    if len(bars) < 60:
        return {
            "decision": "WAIT",
            "reason": f"There are not enough completed {label} candles to judge this request.",
            "entry": None,
            "stop": None,
            "target": None,
            "reward_risk": None,
            "rule": None,
        }
    found = _pullback(bars) or _reclaim(bars) or _range_break(bars)
    if not found:
        watch = _watch_plan(bars, label)
        if watch:
            return watch
        return {
            "decision": "WAIT",
            "reason": f"No setup on this {label} candle. Trend pullback, failed break, and range expansion were checked. None matched. No size follows from that.",
            "entry": None,
            "stop": None,
            "target": None,
            "reward_risk": None,
            "rule": None,
            "families_checked": ["trend_pullback", "failed_break", "range_expansion"],
        }
    risk = abs(found["entry"] - found["stop"])
    target = found["entry"] + PAYOFF * risk if found["side"] == "BUY" else found["entry"] - PAYOFF * risk
    details = " ".join(detail for _name, ok, detail in found["checks"] if ok)
    if found["side"] == "SELL":
        return {
            "decision": "SELL",
            "sell_meaning": "short_idea",
            "reason": (
                f"Short idea on this {label} candle. {found['name']}. {details} "
                f"Entry is the candle close {found['entry']:.2f}, stop {found['stop']:.2f}, target {target:.2f}. "
                "No broker order is sent. This is not an exit of a long, and it is not approved."
            ),
            "entry": found["entry"],
            "stop": found["stop"],
            "target": target,
            "reward_risk": PAYOFF,
            "rule": found["name"],
        }
    return {
        "decision": "BUY",
        "reason": (
            f"Buy on this {label} candle. {found['name']}. {details} "
            "This is a reading of these candles. It is not an approved strategy, and no order was sent."
        ),
        "entry": found["entry"],
        "stop": found["stop"],
        "target": target,
        "reward_risk": PAYOFF,
        "rule": found["name"],
    }
