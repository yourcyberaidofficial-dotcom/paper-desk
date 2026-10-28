"""Gate 4 hypotheses. Frozen in docs/GATE4_SPEC.md before any score.

These rules are not registered in the live snapshot. E1 is not retuned.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ops.hypotheses import _atr, _regime, _true_range

NY = ZoneInfo("America/New_York")

# Adverse slippage on top of the measured bid/ask. Not a spread guess.
SLIPPAGE_USD = {"base_per_fill": 0.10, "stress_per_fill": 0.30, "fills": 2}

CRYPTO = ("fail-break-20261028", "quiet-expand-20261028", "hour-close-drive-20261028")
GOLD = ("xau-london-range-20261028", "xau-session-day-20261028", "xau-climax-fade-20261028")


def _pack(name, side, anchor, stop, hold, reward_risk=None, target=None, mode="rr", distance=None):
    return {
        "strategy": name,
        "version": name,
        "direction": side,
        "anchor_open_ms": anchor,
        "stop_price": stop,
        "target_price": target,
        "target_distance": distance,
        "reward_risk": reward_risk,
        "hold_bars": hold,
        "target_mode": mode,
    }


def _fail_side(bars, index):
    if index < 20:
        return None
    prior = bars[index - 20:index]
    high = max(bar["high"] for bar in prior)
    low = min(bar["low"] for bar in prior)
    bar = bars[index]
    up = bar["high"] > high and bar["close"] <= high and bar["close"] < bar["open"]
    down = bar["low"] < low and bar["close"] >= low and bar["close"] > bar["open"]
    if up and not down:
        return "SHORT"
    if down and not up:
        return "LONG"
    return None


def fail_break_setup(bars, index, higher, symbol):
    del higher
    if symbol not in {"BTCUSDT", "ETHUSDT"} or index < 21:
        return None
    side = _fail_side(bars, index)
    if side is None or _fail_side(bars, index - 1) == side:
        return None
    stop = bars[index]["high"] if side == "SHORT" else bars[index]["low"]
    return _pack("fail-break-20261028", side, bars[index]["open_time_ms"], stop, 12, reward_risk=1.5)


def _quiet_expand_side(bars, index, atr):
    if atr is None or atr <= 0 or index < 9:
        return None
    if any(_true_range(bars, index - 8 + offset) > 0.70 * atr for offset in range(8)):
        return None
    if _true_range(bars, index) < 1.80 * atr:
        return None
    bar = bars[index]
    previous = bars[index - 1]
    if bar["close"] > bar["open"] and bar["close"] > previous["high"]:
        return "LONG"
    if bar["close"] < bar["open"] and bar["close"] < previous["low"]:
        return "SHORT"
    return None


def quiet_expand_setup(bars, index, higher, symbol):
    if symbol not in {"BTCUSDT", "ETHUSDT"} or index < 24:
        return None
    atr = _atr(bars, index - 8, 14)
    side = _quiet_expand_side(bars, index, atr)
    if side is None:
        return None
    regime, _tail = _regime(higher, bars[index]["close_time_ms"], 48)
    if regime != side or _quiet_expand_side(bars, index - 1, atr) == side:
        return None
    stop = bars[index]["low"] if side == "LONG" else bars[index]["high"]
    return _pack("quiet-expand-20261028", side, bars[index]["open_time_ms"], stop, 16, reward_risk=2.0)


def _hour_bar(higher, close_time_ms):
    chosen = None
    for bar in higher:
        if bar["close_time_ms"] <= close_time_ms:
            chosen = bar
        else:
            break
    return chosen


def _hour_drive_side(decision, hour):
    if hour is None or hour["high"] <= hour["low"]:
        return None
    if decision["open_time_ms"] % 3_600_000 != 45 * 60 * 1000:
        return None
    location = (hour["close"] - hour["low"]) / (hour["high"] - hour["low"])
    if location >= 0.75 and hour["close"] > hour["open"]:
        return "LONG"
    if location <= 0.25 and hour["close"] < hour["open"]:
        return "SHORT"
    return None


def hour_close_drive_setup(bars, index, higher, symbol):
    if symbol not in {"BTCUSDT", "ETHUSDT"}:
        return None
    bar = bars[index]
    hour = _hour_bar(higher, bar["close_time_ms"])
    side = _hour_drive_side(bar, hour)
    if side is None:
        return None
    regime, _tail = _regime(higher, bar["close_time_ms"], 48)
    if regime != side:
        return None
    previous_open = bar["open_time_ms"] - 3_600_000
    previous = next((item for item in bars if item["open_time_ms"] == previous_open), None)
    if previous is not None:
        previous_hour = _hour_bar(higher, previous["close_time_ms"])
        if _hour_drive_side(previous, previous_hour) == side:
            return None
    stop = hour["low"] if side == "LONG" else hour["high"]
    return _pack("hour-close-drive-20261028", side, bar["open_time_ms"], stop, 8, reward_risk=2.0)


def _utc_parts(bar):
    return datetime.fromtimestamp(bar["open_time_ms"] / 1000, timezone.utc)


def _bid(bar, field):
    return bar.get(f"bid_{field}", bar.get(field))


def _ask(bar, field):
    return bar.get(f"ask_{field}", bar.get(field))


def _london_core(bars, index):
    moment = _utc_parts(bars[index])
    if moment.hour not in {7, 8, 9}:
        return None
    wanted = []
    for hour in range(6):
        stamp = int(datetime(moment.year, moment.month, moment.day, hour, tzinfo=timezone.utc).timestamp() * 1000)
        match = next((bar for bar in bars if bar["open_time_ms"] == stamp), None)
        if match is None:
            return {"rejected": "overnight_incomplete"}
        wanted.append(match)
    high = max(_bid(bar, "high") for bar in wanted)
    low = min(_bid(bar, "low") for bar in wanted)
    close = _bid(bars[index], "close")
    if close > high:
        return {"direction": "LONG", "stop": low}
    if close < low:
        return {"direction": "SHORT", "stop": max(_ask(bar, "high") for bar in wanted)}
    return None


def xau_london_range_setup(bars, index, higher, symbol):
    del higher
    if symbol != "XAUUSD":
        return None
    core = _london_core(bars, index)
    if core is None or core.get("rejected"):
        return core
    if index:
        previous = _london_core(bars, index - 1)
        if isinstance(previous, dict) and previous.get("direction") == core["direction"]:
            return None
    return _pack("xau-london-range-20261028", core["direction"], bars[index]["open_time_ms"], core["stop"], 6, reward_risk=2.0)


def _session_start(moment):
    local = moment.astimezone(NY)
    start = local.replace(hour=17, minute=0, second=0, microsecond=0)
    if local < start:
        start = start - timedelta(days=1)
    return start


def _session_core(bars, index):
    moment = _utc_parts(bars[index])
    current = _session_start(moment)
    previous_start = _session_start(current - timedelta(hours=1))
    start_ms = int(previous_start.timestamp() * 1000)
    end_ms = int(current.timestamp() * 1000)
    window = [bar for bar in bars if start_ms <= bar["open_time_ms"] < end_ms]
    if len(window) < 18:
        return {"rejected": "session_incomplete"}
    window.sort(key=lambda bar: bar["open_time_ms"])
    if any(window[i + 1]["open_time_ms"] - window[i]["open_time_ms"] != 3_600_000 for i in range(len(window) - 1)):
        return {"rejected": "session_incomplete"}
    high = max(_bid(bar, "high") for bar in window)
    low = min(_bid(bar, "low") for bar in window)
    if high <= low:
        return None
    close = _bid(bars[index], "close")
    if close > high:
        side = "LONG"
    elif close < low:
        side = "SHORT"
    else:
        return None
    return {"direction": side, "stop": (high + low) / 2, "distance": high - low}


def xau_session_day_setup(bars, index, higher, symbol):
    del higher
    if symbol != "XAUUSD":
        return None
    core = _session_core(bars, index)
    if not isinstance(core, dict) or core.get("rejected") or "direction" not in core:
        return core
    if index:
        previous = _session_core(bars, index - 1)
        if isinstance(previous, dict) and previous.get("direction") == core["direction"]:
            return None
    return _pack(
        "xau-session-day-20261028",
        core["direction"],
        bars[index]["open_time_ms"],
        stop=core["stop"],
        hold=8,
        mode="distance",
        distance=core["distance"],
    )


def _climax_core(bars, index):
    if index < 21:
        return None
    atr = _atr(bars, index, 14)
    if atr is None or atr <= 0:
        return None
    bar = bars[index]
    span = bar["high"] - bar["low"]
    if span <= 0:
        return None
    prior = bars[index - 10:index]
    location = (bar["close"] - bar["low"]) / span
    if bar["low"] < min(item["low"] for item in prior) - atr and bar["close"] > bar["open"] and location >= 0.5:
        return {"direction": "LONG", "stop": _bid(bar, "low")}
    if bar["high"] > max(item["high"] for item in prior) + atr and bar["close"] < bar["open"] and location <= 0.5:
        return {"direction": "SHORT", "stop": _ask(bar, "high")}
    return None


def xau_climax_fade_setup(bars, index, higher, symbol):
    del higher
    if symbol != "XAUUSD":
        return None
    core = _climax_core(bars, index)
    if core is None:
        return None
    if index:
        previous = _climax_core(bars, index - 1)
        if isinstance(previous, dict) and previous.get("direction") == core["direction"]:
            return None
    closes = [item["close"] for item in bars[index - 9:index + 1]]
    target = sum(closes) / 10
    return _pack("xau-climax-fade-20261028", core["direction"], bars[index]["open_time_ms"], core["stop"], 8, target=target, mode="fixed")


SETUP = {
    "fail-break-20261028": fail_break_setup,
    "quiet-expand-20261028": quiet_expand_setup,
    "hour-close-drive-20261028": hour_close_drive_setup,
    "xau-london-range-20261028": xau_london_range_setup,
    "xau-session-day-20261028": xau_session_day_setup,
    "xau-climax-fade-20261028": xau_climax_fade_setup,
}
