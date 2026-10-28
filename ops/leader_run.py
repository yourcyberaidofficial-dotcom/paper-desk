"""Score the frozen leaders. The holdout slice is never simulated."""

import json
from pathlib import Path

from ops.history_store import ROOT, load_csv, load_jsonl, save_csv, validate_bars
from ops.leaders import COMPRESS, CRYPTO_RULES, GOLD_RULES, LONDON, SWEEP, choose_leader
from ops.research_cli import _hash, _iso, _split
from ops.research_select import judge
from ops.simulate import halves, metrics, simulate

OUT = Path(__file__).resolve().parents[1] / "docs" / "LEADER_RESULTS.json"


def _folds(trades, start_ms, end_ms):
    width = (end_ms - start_ms) / 3 or 1
    rows = []
    for index in range(3):
        left = start_ms + index * width
        right = end_ms if index == 2 else start_ms + (index + 1) * width
        part = [trade for trade in trades if left <= trade["signal_open_time_ms"] < right]
        summary = metrics(part)
        rows.append({"fold": index + 1, "trades": summary["trades"], "base_mean": summary.get("base_mean")})
    return rows


def _score(symbol, bars, rules, execution="last_trade", slippage=0.0, stress_slippage=0.0, measured=False):
    dev, val, hold = _split(bars)
    prefix = dev + val
    if len(prefix) < 80 or not hold:
        return {"symbol": symbol, "judgment": "BLOCKED", "reason": "split_too_small", "holdout": "NOT_OPENED", "rows": []}
    rows = []
    for name in rules:
        kwargs = {"setup_map": rules, "execution": execution}
        if execution == "bid_ask":
            base = simulate(symbol, prefix, [], name, stress=False, slippage_usd=slippage, **kwargs)
            stress = simulate(symbol, prefix, [], name, stress=True, slippage_usd=stress_slippage, **kwargs)
        else:
            base = simulate(symbol, prefix, [], name, stress=False, **kwargs)
            stress = simulate(symbol, prefix, [], name, stress=True, **kwargs)
        summary = metrics(base)
        summary["stress_mean"] = metrics(stress).get("base_mean")
        judgment, failed, blocked = judge(summary, halves(base), symbol, measured_bid_ask=measured or symbol != "XAUUSD")
        folds = _folds(base, prefix[0]["open_time_ms"], prefix[-1]["close_time_ms"] + 1)
        if any((fold.get("trades") or 0) < 10 or fold.get("base_mean") is None for fold in folds):
            if "unstable_folds" not in blocked:
                blocked.append("unstable_folds")
            if judgment == "PASS":
                judgment = "BLOCKED"
        gross = sum(trade["gross"] for trade in base)
        net = sum(trade["net"] for trade in base)
        rows.append({
            "strategy": name,
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
            "win_rate": summary.get("win_rate"),
            "equity": summary.get("equity"),
            "max_drawdown": summary.get("max_drawdown"),
            "worst_loss_streak": summary.get("worst_loss_streak"),
            "folds": folds,
            "promoted": False,
            "directions": "LONG only",
        })
    return {
        "symbol": symbol,
        "bars": len(bars),
        "prefix_bars": len(prefix),
        "holdout_bars": len(hold),
        "holdout": "NOT_OPENED",
        "sha256": _hash(bars),
        "start": _iso(bars[0]["open_time_ms"]),
        "prefix_end": _iso(prefix[-1]["close_time_ms"]),
        "validation": validate_bars(bars, bars[0]["interval"]),
        "leader": choose_leader(rows),
        "benchmark": None if symbol == "XAUUSD" else {
            "name": "buy_and_hold_one_round_turn",
            "gross": prefix[-1]["close"] / prefix[0]["open"] - 1,
            "net": prefix[-1]["close"] / prefix[0]["open"] - 1 - 0.0022,
            "cost": "22 bps for one round turn at the project crypto rate",
        },
        "rows": rows,
    }


def score_saved():
    report = {"holdout": "NOT_OPENED", "promoted": [], "markets": []}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        path = ROOT / f"{symbol}-4h.csv"
        bars = load_csv(path, symbol, "4h", "binance-public", "last_trade")
        report["markets"].append(_score(symbol, bars, CRYPTO_RULES))
    gold_path = ROOT / "XAUUSD-1h.jsonl"
    if gold_path.exists() and gold_path.stat().st_size:
        gold = load_jsonl(gold_path)
        report["markets"].append(_score("XAUUSD", gold, GOLD_RULES, execution="bid_ask", slippage=0.10, stress_slippage=0.30, measured=True))
    else:
        report["markets"].append({"symbol": "XAUUSD", "judgment": "BLOCKED", "reason": "no_bid_ask_file", "holdout": "NOT_OPENED", "leader": {"strategy": None, "approved": False, "status": "none"}})
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def published_leaders():
    if not OUT.exists():
        return []
    report = json.loads(OUT.read_text(encoding="utf-8"))
    rows = []
    for market in report.get("markets") or []:
        leader = market.get("leader") or {}
        rows.append({
            "symbol": market.get("symbol"),
            "strategy": leader.get("strategy"),
            "status": leader.get("status") or "none",
            "approved": bool(leader.get("approved")),
            "judgment": leader.get("judgment"),
        })
    return rows


def download_crypto(now_ms):
    from ops.feeds import binance_bars
    start = 1672531200000  # 2023-01-01 UTC
    saved = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        loaded = binance_bars(symbol, "4h", start, now_ms, now_ms)
        if not loaded.get("ok"):
            raise RuntimeError(loaded.get("reason"))
        path = save_csv(ROOT / f"{symbol}-4h.csv", loaded["bars"])
        saved.append({"symbol": symbol, "bars": len(loaded["bars"]), "path": str(path), "validation": validate_bars(loaded["bars"], "4h")})
    return saved
