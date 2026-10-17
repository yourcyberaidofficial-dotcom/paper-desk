"""Deeper leaderboard. Sum and compounded unit returns are separate."""

from datetime import datetime, timezone

from ops.history import fetch_history, coverage_status
from ops.rules import rule_states

BASE = 11 / 10000
STRESS = 15 / 10000


def _trades(bars, name, cost):
    trades = []
    i = 22
    while i < len(bars) - 9:
        state = next(s for s in rule_states(bars[: i + 1]) if s["strategy"] == name)
        if state["direction"] == "WAIT":
            i += 1
            continue
        entry = bars[i + 1]["open"]
        exit_bar = bars[min(i + 8, len(bars) - 1)]
        side = 1 if state["direction"] == "LONG_BIAS" else -1
        gross = side * (exit_bar["close"] - entry) / entry
        trades.append({"net": gross - cost * 2, "side": "long" if side > 0 else "short"})
        i = min(i + 8, len(bars) - 1)
    return trades


def _metrics(trades):
    if not trades:
        return {"trades": 0, "sum_unit_return": 0, "compounded_unit_equity": 1, "expectancy": 0, "profit_factor": None, "win_rate": 0, "max_drawdown": 0}
    nets = [t["net"] for t in trades]
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for n in nets:
        equity *= (1 + n)
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak if peak else 0)
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) else None
    return {
        "trades": len(trades),
        "sum_unit_return": sum(nets),
        "compounded_unit_equity": equity,
        "expectancy": sum(nets) / len(nets),
        "profit_factor": pf,
        "win_rate": len(wins) / len(nets),
        "max_drawdown": mdd,
    }


def deep_board():
    rows = []
    coverage = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for interval in ("15m", "1h", "4h", "1d"):
            bars = fetch_history(symbol, interval, years=3)
            if not bars:
                continue
            end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            coverage.append({
                "symbol": symbol,
                "interval": interval,
                "bars": len(bars),
                "start": datetime.fromtimestamp(bars[0]["open_time_ms"] / 1000, timezone.utc).date().isoformat(),
                "end": datetime.fromtimestamp(bars[-1]["open_time_ms"] / 1000, timezone.utc).date().isoformat(),
                "source": "binance-public-paginated",
                "status": coverage_status(bars, end_ms, interval),
                "ceiling": None,
            })
            for name in ("E1-donchian-20", "SMA20-cross", "RSI14-band"):
                base = _metrics(_trades(bars, name, BASE))
                stress = _metrics(_trades(bars, name, STRESS))
                rows.append({"symbol": symbol, "interval": interval, "strategy": name, "base": base, "stress": stress, "validated": False})
    return {
        "label": "DEEP RESEARCH BOARD — NOT VALIDATED",
        "gold": {"status": "NOT_CONFIGURED", "instrument": None, "reason": "No verified XAUUSD provider is configured."},
        "costs": {"base_bps_per_fill": 11, "stress_bps_per_fill": 15, "fills_per_trade": 2, "funding": "not modeled", "extra_spread": "not modeled"},
        "accounting": "sum_unit_return = sum(net_i). compounded_unit_equity = product(1+net_i), start 1. A positive sum can still finish below 1 because losses compound. Not dollars. Base 11 bps per fill, stress 15 bps per fill, applied once on entry and once on exit. No funding, no extra spread.",
        "coverage": coverage,
        "rows": rows,
    }
