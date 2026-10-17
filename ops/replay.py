"""Historical replay. Uses only bars closed at the decision time."""

import json
import time
import urllib.parse
import urllib.request

from ops.rules import rule_states

BASE_COST = 11 / 10000


def _klines(symbol, interval, end_ms, limit=80):
    query = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": interval,
        "endTime": int(end_ms),
        "limit": limit,
    })
    request = urllib.request.Request(
        f"https://data-api.binance.vision/api/v3/klines?{query}",
        headers={"User-Agent": "paper-desk"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        rows = json.loads(response.read().decode())
    bars = []
    for row in rows:
        if int(row[6]) > end_ms:
            continue
        bars.append({
            "open_time_ms": int(row[0]),
            "close_time_ms": int(row[6]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
        })
    return bars


def replay(symbol, interval, at_ms):
    bars = _klines(symbol, interval, at_ms)
    if len(bars) < 22:
        return {"error": "insufficient_history", "symbol": symbol, "interval": interval}
    decision = bars[-1]
    known = bars[:-1]
    states = rule_states(known + [decision])
    future = _klines(symbol, interval, at_ms + 20 * 15 * 60 * 1000, limit=25)
    after = [b for b in future if b["open_time_ms"] > decision["open_time_ms"]][:8]
    outcomes = []
    for state in states:
        outcomes.append(_outcome(state, decision, after))
    return {
        "symbol": symbol,
        "interval": interval,
        "decision_close_time_ms": decision["close_time_ms"],
        "decision_close": decision["close"],
        "known_bars": len(known),
        "lookahead_used_for_decision": False,
        "label": "HYPOTHETICAL SIMULATION — NOT A TRADE",
        "states": states,
        "outcomes": outcomes,
    }


def _outcome(state, decision, after):
    direction = state["direction"]
    if direction == "WAIT" or not after:
        return {
            "strategy": state["strategy"],
            "action": "flat",
            "net": 0.0,
            "reason": "no_entry",
        }
    entry = after[0]["open"]
    exit_bar = after[min(7, len(after) - 1)]
    exit_price = exit_bar["close"]
    side = 1 if direction == "LONG_BIAS" else -1
    gross = side * (exit_price - entry) / entry
    path = [b["close"] for b in after]
    mae = min(side * (p - entry) / entry for p in path)
    mfe = max(side * (p - entry) / entry for p in path)
    return {
        "strategy": state["strategy"],
        "action": "hypothetical_entry",
        "entry_price": entry,
        "exit_price": exit_price,
        "exit_time_ms": exit_bar["close_time_ms"],
        "gross": gross,
        "cost": BASE_COST * 2,
        "net": gross - BASE_COST * 2,
        "mae": mae,
        "mfe": mfe,
        "holding_bars": len(after),
        "validated": False,
    }


def yesterday_ms():
    return int(time.time() * 1000) - 24 * 60 * 60 * 1000


def period(symbol, interval, end_ms, bars=200):
    data = _klines(symbol, interval, end_ms, limit=min(bars, 500))
    trades = []
    i = 22
    while i < len(data) - 9:
        window = data[: i + 1]
        states = rule_states(window)
        decision = window[-1]
        after = data[i + 1 : i + 9]
        for state in states:
            out = _outcome(state, decision, after)
            if out["action"] == "hypothetical_entry":
                out["decision_close_time_ms"] = decision["close_time_ms"]
                trades.append(out)
                break
        i += 8
    nets = [t["net"] for t in trades]
    eq = peak = mdd = 0
    for n in nets:
        eq += n
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    wins = [n for n in nets if n > 0]
    return {
        "symbol": symbol,
        "interval": interval,
        "label": "HYPOTHETICAL PERIOD — NOT VALIDATED",
        "trades": trades[-30:],
        "trade_count": len(trades),
        "net": sum(nets),
        "expectancy": (sum(nets) / len(nets)) if nets else 0,
        "win_rate": (len(wins) / len(nets)) if nets else 0,
        "max_drawdown": mdd,
        "validated": False,
    }
