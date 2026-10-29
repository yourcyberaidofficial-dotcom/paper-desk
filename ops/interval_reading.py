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


def _watch_plan(bars, label):
    """A long that has not triggered. Spot only. Not an entry."""
    closes = [bar["close"] for bar in bars]
    short = _ema(closes, 20)[-1]
    longer = _ema(closes, 50)[-1]
    if short <= longer:
        return None
    width = _atr(bars)
    last = bars[-1]
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
    found = _pullback(bars) or _reclaim(bars)
    if not found:
        watch = _watch_plan(bars, label)
        if watch:
            return watch
        return {
            "decision": "WAIT",
            "reason": f"Wait on this {label} candle. Price did not tag the average and close back with it, and it did not fail a break. No size follows from that.",
            "entry": None,
            "stop": None,
            "target": None,
            "reward_risk": None,
            "rule": None,
        }
    risk = abs(found["entry"] - found["stop"])
    target = found["entry"] + PAYOFF * risk if found["side"] == "BUY" else found["entry"] - PAYOFF * risk
    if found["side"] == "SELL":
        return {
            "decision": "WAIT",
            "reason": (
                f"A short reading matched on this {label} candle ({found['name']}). "
                f"A stop near {found['stop']:.2f} and a target near {target:.2f} would belong to a short. "
                "This desk is spot-only, so that is not a SELL and no short was opened."
            ),
            "entry": None,
            "stop": None,
            "target": None,
            "reward_risk": None,
            "rule": found["name"],
            "spot_short_refused": True,
        }
    details = " ".join(detail for _name, ok, detail in found["checks"] if ok)
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
