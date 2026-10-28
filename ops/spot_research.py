"""Score the two frozen spot rules. The holdout slice is not read."""

import json
from pathlib import Path

from ops.feeds import binance_bars
from ops.research_cli import _hash, _iso, _split
from ops.research_select import judge
from ops.simulate import halves, metrics, simulate
from ops.spot_momentum import RULES

ROOT = Path(__file__).resolve().parents[1]


def _benchmark(bars):
    if len(bars) < 2 or bars[0]["close"] <= 0:
        return None
    gross = bars[-1]["close"] / bars[0]["close"] - 1
    cost = 2 * 11 / 10000
    return {"gross": gross, "net_of_one_round_turn": gross - cost, "cost_bps_per_fill": 11}


def evaluate(symbol, bars):
    dev, val, hold = _split(bars)
    if not dev or not val or not hold:
        return {"symbol": symbol, "judgment": "BLOCKED", "reason": "split_too_small", "holdout": "NOT_OPENED"}
    prefix = dev + val
    rows = []
    for name in RULES:
        base = simulate(symbol, prefix, [], name, stress=False, setup_map=RULES)
        stress = simulate(symbol, prefix, [], name, stress=True, setup_map=RULES)
        summary = metrics(base)
        summary["stress_mean"] = metrics(stress).get("base_mean")
        judgment, failed, blocked = judge(summary, halves(base), symbol, measured_bid_ask=False)
        gross = sum(trade["gross"] for trade in base) if base else 0
        net = sum(trade["net"] for trade in base) if base else 0
        rows.append({
            "strategy": name,
            "split": "development_plus_validation",
            "judgment": judgment,
            "failed": failed,
            "blocked": blocked,
            "trades": summary["trades"],
            "gross_sum": gross,
            "net_sum": net,
            "cost_drag": gross - net,
            "base_mean": summary.get("base_mean"),
            "stress_mean": summary.get("stress_mean"),
            "normal_95_lower": summary.get("normal_95_lower"),
            "profit_factor_note": "not a probability",
            "win_rate": summary.get("win_rate"),
            "equity": summary.get("equity"),
            "max_drawdown": summary.get("max_drawdown"),
            "worst_loss_streak": summary.get("worst_loss_streak"),
            "directions": "LONG only. Spot short was not simulated.",
            "promoted": False,
        })
    return {
        "symbol": symbol,
        "bars": len(bars),
        "sha256": _hash(bars),
        "start": _iso(bars[0]["open_time_ms"]),
        "validation_end": _iso(val[-1]["close_time_ms"]),
        "holdout_bars": len(hold),
        "holdout": "NOT_OPENED",
        "benchmark_same_prefix": _benchmark(prefix),
        "rows": rows,
    }


def run(now_ms, days=400):
    start = int(now_ms) - days * 24 * 60 * 60 * 1000
    report = {"promoted": [], "holdout": "NOT_OPENED", "costs": "11 bps per fill, 15 bps stress, two fills", "symbols": []}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        loaded = binance_bars(symbol, "1h", start, now_ms, now_ms)
        if not loaded.get("ok") or len(loaded.get("bars") or []) < 200:
            report["symbols"].append({"symbol": symbol, "judgment": "BLOCKED", "reason": loaded.get("reason") or "insufficient_bars", "holdout": "NOT_OPENED"})
            continue
        report["symbols"].append(evaluate(symbol, loaded["bars"]))
    report["symbols"].append({
        "symbol": "XAUUSD",
        "judgment": "BLOCKED",
        "reason": "no_measured_bid_ask",
        "holdout": "NOT_OPENED",
        "note": "These two rules are spot-crypto rules. Gold was not scored on an assumed spread.",
    })
    path = ROOT / "docs" / "SPOT_RESEARCH_RESULTS.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
