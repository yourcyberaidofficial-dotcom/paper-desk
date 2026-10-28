"""Canonical snapshot. Pure: no Telegram, no user writes, no paper fills."""

from datetime import datetime, timezone

from ops.bars import validate_series
from ops.hypotheses import FAMILIES, GOLD_ONLY, SETUP, VERSIONS, e1_observation, event_id
from ops.sessions import gold_market_open, gold_signal_session
from ops.simulate import _prices

PRODUCTION = "WAIT_DEFAULT"


def _blank(strategy, symbol, interval, state, reason):
    return {
        "strategy": strategy,
        "version": VERSIONS.get(strategy, strategy),
        "symbol": symbol,
        "interval": interval,
        "state": state,
        "reason": reason,
        "direction": "WAIT",
        "production": PRODUCTION,
        "broker": False,
        "validated": False,
        "approved": False,
        "event_id": None,
    }


def _candidate(setup, bars, index, symbol, interval):
    pending = index + 1 >= len(bars)
    anchor = setup["anchor_open_ms"]
    step = bars[index]["close_time_ms"] - bars[index]["open_time_ms"] + 1
    base = {
        "strategy": setup["strategy"],
        "version": setup["version"],
        "symbol": symbol,
        "interval": interval,
        "state": "PAPER_CANDIDATE",
        "reason": "rules_complete_not_approved",
        "direction": setup["direction"],
        "entry": None,
        "entry_rule": "next_completed_bar_open",
        "expires_at_ms": bars[index]["close_time_ms"] + step,
        "event_id": event_id(setup["strategy"], symbol, interval, setup["direction"], anchor),
        "production": PRODUCTION,
        "broker": False,
        "validated": False,
        "approved": False,
        "kind": "paper_candidate",
        "hold_bars": setup.get("hold_bars"),
    }
    if setup.get("target_mode") == "atr":
        base.update(stop_distance=setup["stop_multiple"] * setup["atr"], target_distance=setup["target_multiple"] * setup["atr"], reward_risk=setup["reward_risk"])
    elif setup.get("stop_price") is not None and not pending:
        levels = _prices(setup, bars[index + 1]["open"])
        if levels is None:
            return _blank(setup["strategy"], symbol, interval, "WAIT", "no_executable_levels")
        stop, target = levels
        base.update(entry=bars[index + 1]["open"], stop=stop, target=target, reward_risk=setup.get("reward_risk") or _rr(setup["direction"], bars[index + 1]["open"], stop, target))
    elif setup.get("stop_price") is not None:
        reference = bars[index]["close"]
        levels = _prices(setup, reference)
        if levels is None:
            return _blank(setup["strategy"], symbol, interval, "WAIT", "no_executable_levels")
        base.update(stop=setup["stop_price"], target_rule="set_from_next_open", illustrative_only=True, reward_risk=setup.get("reward_risk"))
    else:
        return _blank(setup["strategy"], symbol, interval, "WAIT", "no_executable_levels")
    return base


def _rr(direction, entry, stop, target):
    risk = (entry - stop) if direction == "LONG" else (stop - entry)
    reward = (target - entry) if direction == "LONG" else (entry - target)
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def evaluate_snapshot(symbol, bars, higher, now_ms, interval):
    """Latest completed bar only. Appending future bars must not change an earlier index."""
    report = validate_series(bars, interval) if bars else {"ok": False, "bars": 0, "invalid": 1}
    if not bars:
        return [_blank("engine", symbol, interval, "DATA_UNAVAILABLE", "no_completed_bars")]
    if report.get("invalid"):
        return [_blank("engine", symbol, interval, "DATA_UNAVAILABLE", "invalid_bars")]
    if symbol == "XAUUSD":
        moment = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
        if not gold_market_open(moment):
            return [_blank("engine", symbol, interval, "WAIT", "MARKET_CLOSED")]
    if len(bars) < 40 or len(higher) < 20:
        return [_blank("engine", symbol, interval, "DATA_UNAVAILABLE", "insufficient_history")]
    index = len(bars) - 1
    if bars[index]["close_time_ms"] > now_ms:
        return [_blank("engine", symbol, interval, "DATA_UNAVAILABLE", "no_completed_bars")]
    age = now_ms - bars[index]["close_time_ms"]
    step = bars[index]["close_time_ms"] - bars[index]["open_time_ms"] + 1
    if age > 2 * step:
        return [_blank("engine", symbol, interval, "DATA_UNAVAILABLE", "stale_bars")]
    results = []
    observation = e1_observation(bars, index)
    if observation is None:
        results.append(_blank("E1-donchian-20", symbol, interval, "WAIT", "e1_inside_channel"))
    else:
        row = _blank("E1-donchian-20", symbol, interval, "RESEARCH_OBSERVATION", "benchmark_failed")
        row["direction"] = observation["direction"]
        row["event_id"] = event_id("E1-donchian-20", symbol, interval, observation["direction"], observation["anchor_open_ms"])
        results.append(row)
    names = list(FAMILIES)
    if symbol == "XAUUSD":
        names.append(GOLD_ONLY[0])
    for name in names:
        if symbol == "XAUUSD" and name == "xau-session-20261027":
            moment = datetime.fromtimestamp(bars[index]["open_time_ms"] / 1000, timezone.utc)
            if not gold_signal_session(moment):
                results.append(_blank(name, symbol, interval, "WAIT", "OUTSIDE_SESSION"))
                continue
        setup = SETUP[name](bars, index, higher, symbol)
        if not setup:
            results.append(_blank(name, symbol, interval, "WAIT", "no_setup"))
            continue
        if setup.get("rejected"):
            results.append(_blank(name, symbol, interval, "WAIT", setup["rejected"]))
            continue
        results.append(_candidate(setup, bars, index, symbol, interval))
    if interval == "1h" and symbol in {"BTCUSDT", "ETHUSDT"}:
        from ops.spot_momentum import RULES
        for name, rule in RULES.items():
            found = rule(bars, index, higher, symbol)
            if not found:
                results.append(_blank(name, symbol, interval, "WAIT", "no_setup"))
                continue
            row = _blank(name, symbol, interval, "RESEARCH_OBSERVATION", "research_failed")
            row["direction"] = "LONG"
            row["event_id"] = event_id(name, symbol, interval, "LONG", found["anchor_open_ms"])
            results.append(row)
    return results


def headline(results):
    if any(row["state"] == "DATA_UNAVAILABLE" and row["strategy"] == "engine" for row in results):
        return results[0]
    for row in results:
        if row["state"] == "PAPER_CANDIDATE":
            return row
    for row in results:
        if row["state"] == "RESEARCH_OBSERVATION":
            return row
    return results[0] if results else _blank("engine", "", "", "WAIT", "empty")
