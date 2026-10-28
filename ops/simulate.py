"""Deterministic paper simulation. Does not write portfolios or send alerts."""

import math
import statistics

from ops.hypotheses import CRYPTO_COST, GOLD_COST, SETUP


def _cost_return(symbol, entry, stress):
    if symbol == "XAUUSD":
        side_cost = GOLD_COST["stress_usd_per_side"] if stress else GOLD_COST["base_usd_per_side"]
        return (2 * side_cost) / entry
    bps = CRYPTO_COST["stress_bps_per_fill"] if stress else CRYPTO_COST["base_bps_per_fill"]
    return 2 * bps / 10000


def _prices(setup, entry):
    side = setup["direction"]
    sign = 1 if side == "LONG" else -1
    if setup["target_mode"] == "atr":
        stop = entry - sign * setup["stop_multiple"] * setup["atr"]
        target = entry + sign * setup["target_multiple"] * setup["atr"]
    elif setup["target_mode"] == "rr":
        stop = setup["stop_price"]
        risk = (entry - stop) if side == "LONG" else (stop - entry)
        if risk <= 0:
            return None
        target = entry + sign * setup["reward_risk"] * risk
    elif setup["target_mode"] == "distance":
        stop = setup["stop_price"]
        distance = setup.get("target_distance")
        if distance is None or distance <= 0:
            return None
        target = entry + sign * float(distance)
        risk = (entry - stop) if side == "LONG" else (stop - entry)
        reward = distance if side == "LONG" else distance
        if risk <= 0 or reward / risk < 1:
            return None
    else:
        stop = setup["stop_price"]
        target = setup["target_price"]
        risk = (entry - stop) if side == "LONG" else (stop - entry)
        reward = (target - entry) if side == "LONG" else (entry - target)
        if risk <= 0 or reward <= 0 or reward / risk < 1:
            return None
    if side == "LONG" and not (stop < entry < target):
        return None
    if side == "SHORT" and not (target < entry < stop):
        return None
    return stop, target


def _exit(bars, entry_index, side, stop, target, hold, rsi_exit=False):
    from ops.indicators import rsi

    last = min(len(bars) - 1, entry_index + hold - 1)
    for cursor in range(entry_index, last + 1):
        bar = bars[cursor]
        if cursor > entry_index and bar["open_time_ms"] <= bars[cursor - 1]["open_time_ms"]:
            return bars[cursor - 1]["close"], "invalid_sequence", cursor - 1
        if side == "LONG":
            if bar["open"] <= stop:
                return bar["open"], "stop_gap", cursor
            if bar["low"] <= stop:
                return stop, "stop", cursor
            if bar["high"] >= target:
                return target, "target", cursor
        else:
            if bar["open"] >= stop:
                return bar["open"], "stop_gap", cursor
            if bar["high"] >= stop:
                return stop, "stop", cursor
            if bar["low"] <= target:
                return target, "target", cursor
        if rsi_exit and cursor > entry_index:
            closes = [item["close"] for item in bars[: cursor + 1]]
            value = rsi(closes, 14)
            previous = rsi(closes[:-1], 14)
            if value is not None and previous is not None:
                crossed = (side == "LONG" and previous < 50 <= value) or (side == "SHORT" and previous > 50 >= value)
                if crossed:
                    return bar["close"], "rsi_mean", cursor
        if cursor == last:
            return bar["close"], "time", cursor
    return None, None, None


def _side_view(bar, side):
    if side == "LONG":
        prices = (bar.get("bid_open"), bar.get("bid_high"), bar.get("bid_low"), bar.get("bid_close"))
    else:
        prices = (bar.get("ask_open"), bar.get("ask_high"), bar.get("ask_low"), bar.get("ask_close"))
    if any(price is None for price in prices):
        return None
    view = dict(bar)
    view["open"], view["high"], view["low"], view["close"] = prices
    return view


def simulate(symbol, bars, higher, strategy, stress=False, execution="last_trade", slippage_usd=0.0, setup_map=None):
    """One position at a time. Future bars are not visible to the setup call."""
    table = setup_map if setup_map is not None else SETUP
    if strategy not in table:
        raise KeyError(strategy)
    fn = table[strategy]
    trades = []
    index = 30
    long_view = short_view = None
    if execution == "bid_ask":
        long_view = [_side_view(bar, "LONG") for bar in bars]
        short_view = [_side_view(bar, "SHORT") for bar in bars]
        if any(item is None for item in long_view) or any(item is None for item in short_view):
            return []
    while index < len(bars) - 2:
        setup = fn(bars, index, higher, symbol)
        if not setup or setup.get("rejected") or setup.get("benchmark_failed"):
            index += 1
            continue
        entry_bar = bars[index + 1]
        if entry_bar["open_time_ms"] <= bars[index]["open_time_ms"]:
            index += 1
            continue
        if execution == "bid_ask":
            entry = entry_bar.get("ask_open") if setup["direction"] == "LONG" else entry_bar.get("bid_open")
            view = long_view if setup["direction"] == "LONG" else short_view
            if entry is None:
                index += 1
                continue
            levels = _prices(setup, entry)
            if levels is None:
                index += 1
                continue
            stop, target = levels
            price, reason, exit_index = _exit(
                view,
                index + 1,
                setup["direction"],
                stop,
                target,
                setup["hold_bars"],
                rsi_exit=setup.get("target_mode") == "mean",
            )
            if price is None:
                break
            sign = 1 if setup["direction"] == "LONG" else -1
            gross = sign * (price - entry) / entry
            cost = (2 * slippage_usd) / entry
            entry_price = entry
        else:
            levels = _prices(setup, entry_bar["open"])
            if levels is None:
                index += 1
                continue
            stop, target = levels
            price, reason, exit_index = _exit(
                bars,
                index + 1,
                setup["direction"],
                stop,
                target,
                setup["hold_bars"],
                rsi_exit=setup.get("target_mode") == "mean",
            )
            if price is None:
                break
            sign = 1 if setup["direction"] == "LONG" else -1
            gross = sign * (price - entry_bar["open"]) / entry_bar["open"]
            cost = _cost_return(symbol, entry_bar["open"], stress)
            entry_price = entry_bar["open"]
        trades.append({
            "strategy": strategy,
            "symbol": symbol,
            "direction": setup["direction"],
            "event_id": f"{strategy}:{symbol}:{bars[index]['interval']}:{setup['direction']}:{bars[index]['open_time_ms']}",
            "signal_open_time_ms": bars[index]["open_time_ms"],
            "entry_open_time_ms": entry_bar["open_time_ms"],
            "exit_close_time_ms": bars[exit_index]["close_time_ms"],
            "entry": entry_price,
            "exit": price,
            "stop": stop,
            "target": target,
            "reason": reason,
            "gross": gross,
            "net": gross - cost,
            "stress": stress,
            "execution": execution,
        })
        index = exit_index
    return trades


def metrics(trades):
    if not trades:
        return {"trades": 0, "base_mean": None, "equity": 1.0, "max_drawdown": 0.0, "worst_loss_streak": 0}
    nets = [trade["net"] for trade in trades]
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    streak = worst = 0
    for net in nets:
        equity *= 1 + net
        peak = max(peak, equity)
        if peak:
            max_dd = max(max_dd, (peak - equity) / peak)
        if net <= 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    mean = statistics.fmean(nets)
    stdev = statistics.stdev(nets) if len(nets) > 1 else None
    lower = None if stdev is None else mean - 1.96 * stdev / math.sqrt(len(nets))
    return {
        "trades": len(nets),
        "base_mean": mean,
        "normal_95_lower": lower,
        "sum": sum(nets),
        "equity": equity,
        "max_drawdown": max_dd,
        "worst_loss_streak": worst,
        "win_rate": sum(net > 0 for net in nets) / len(nets),
    }


def halves(trades):
    if not trades:
        return {"first": metrics([]), "second": metrics([])}
    start = min(trade["entry_open_time_ms"] for trade in trades)
    end = max(trade["entry_open_time_ms"] for trade in trades)
    mid = start + (end - start) / 2
    first = [trade for trade in trades if trade["entry_open_time_ms"] < mid]
    second = [trade for trade in trades if trade["entry_open_time_ms"] >= mid]
    return {"first": metrics(first), "second": metrics(second), "mid": mid}
