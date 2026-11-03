"""One frozen 4h follow-up. Parameters are not searched and the holdout stays sealed unless validation PASSes.

This is a follow-up to the recorded cost-drag result, not an independent discovery.
Paper approval is not granted here, including when a window PASSes the existing judge.
"""

import hashlib
import json
from pathlib import Path

from ops.hypotheses import CRYPTO_COST, GATES, _atr
from ops.history_store import ROOT, load_csv
from ops.research_cli import _hash, _iso, _split
from ops.research_select import judge
from ops.simulate import halves, metrics, simulate

VERSION = "trend-hold-4h-20261103"
LOOKBACK = 60
TREND = 120
ATR_LEN = 14
STOP_ATR = 3.0
TARGET_ATR = 6.0
HOLD_BARS = 42
INTERVAL = "4h"
STEP_MS = 4 * 60 * 60 * 1000
EMBARGO_MS = HOLD_BARS * STEP_MS
DOCS = Path(__file__).resolve().parents[1] / "docs"

# Families already compared before this version was declared. The count is a bias warning, not a new test.
PRIOR_RECORDED = (
    "E1-donchian-20",
    "tf-pullback-20261027",
    "vol-break-20261027",
    "mr-range-20261027",
    "xau-session-20261027",
    "spot-tsmom-1h-20261028",
    "tight-range-long-1h-20261028",
    "sweep-reclaim-4h-20261028",
    "compress-break-4h-20261028",
    "london-reclaim-1h-20261028",
    "dip-in-trend-1d-20261028",
    "quiet-week-reversal-1d-20261028",
    "fail-break-20261028",
    "quiet-expand-20261028",
    "hour-close-drive-20261028",
    "xau-london-range-20261028",
    "xau-session-day-20261028",
    "xau-climax-fade-20261028",
)


def protocol():
    return {
        "version": VERSION,
        "hypothesis": "A slow long-only 4h trend hold may survive 22 bps of round-turn cost where faster positive-gross rules did not. BTC sweep-reclaim and compression-breakout had positive gross sums that costs erased or nearly erased. This rule enters less often and plans a larger move. It is a follow-up, not a fresh claim.",
        "market_behaviour": "Multi-week spot uptrends on BTCUSDT and ETHUSDT.",
        "required_data": "Retained Binance spot 4h CSV only.",
        "eligible": ["BTCUSDT 4h", "ETHUSDT 4h"],
        "ineligible": ["XAUUSD", "1m", "3m", "15m", "1h", "1d", "shorts", "futures"],
        "entry": "On a completed 4h bar, close is above the prior 60 highs and above the 120-bar simple average. The fill is the next bar open. The signal bar is not the fill.",
        "invalidation": "3 times the prior 14-bar ATR below the entry. No trade if ATR is missing or the reward would not exceed the risk.",
        "exit": "6 ATR target, the stop, or 42 bars, whichever the existing simulator reaches first.",
        "hold_bars": HOLD_BARS,
        "expected_turnover": "Much lower than the 300-trade 4h reclaim and the 400-trade 1h momentum rules. Not estimated from this sample before the run.",
        "do_not_trade_when": "The bar is not 4h BTC or ETH, the close has not cleared the prior 60 highs, the close is not above the 120-bar average, or levels cannot be placed.",
        "parameters": {
            "lookback": LOOKBACK,
            "trend": TREND,
            "atr_len": ATR_LEN,
            "stop_atr": STOP_ATR,
            "target_atr": TARGET_ATR,
            "hold_bars": HOLD_BARS,
        },
        "split": "Chronological 60/20/20 by bar count, same helper as Gate 3. No shuffle.",
        "purging": "Development is simulated on development bars only. Validation trades are those whose signal bar opens in validation. Signals inside the first 42 4h bars of validation are embargoed.",
        "holdout_rule": "Open a symbol's final 20 percent only if judge() returns PASS on that symbol's purged validation window. Otherwise record NOT_OPENED. Do not use the holdout to pick a parameter.",
        "approval_rule": "A PASS is not paper approval. This version is a follow-up after the recorded families below, 4h is not a desk coverage timeframe, and no forward paper sample exists. promoted stays false.",
        "gates": dict(GATES),
        "costs": {
            "base_bps_per_fill": CRYPTO_COST["base_bps_per_fill"],
            "stress_bps_per_fill": CRYPTO_COST["stress_bps_per_fill"],
            "fills": 2,
            "research_round_turn_base_bps": 2 * CRYPTO_COST["base_bps_per_fill"],
            "paper_book_adverse_slippage_bps": 2,
            "paper_slippage_in_this_simulator": False,
            "meaning": "Research uses the existing simulator cost once. The paper book's separate 2 bps candle-exit slippage is not added on top. Neither figure is a measured exchange fee.",
        },
        "benchmarks": ["no_trade", "buy_and_hold_one_round_turn_on_the_same_window"],
        "prior_recorded_families": list(PRIOR_RECORDED),
        "multiple_testing": "This candidate was motivated by those earlier results. A pass would still be one follow-up, not an independent discovery.",
    }


def protocol_sha256():
    payload = json.dumps(protocol(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def trend_hold(bars, index, higher, symbol):
    """Completed-bar signal. higher is ignored. Future bars are not indexed."""
    del higher
    if symbol not in {"BTCUSDT", "ETHUSDT"} or bars[index].get("interval") != INTERVAL or index < TREND:
        return None
    prior = bars[index - LOOKBACK : index]
    if len(prior) < LOOKBACK:
        return None
    if bars[index]["close"] <= max(bar["high"] for bar in prior):
        return None
    average = sum(bars[cursor]["close"] for cursor in range(index - TREND + 1, index + 1)) / TREND
    if bars[index]["close"] <= average:
        return None
    width = _atr(bars, index, ATR_LEN)
    if width is None or width <= 0:
        return None
    return {
        "strategy": VERSION,
        "version": VERSION,
        "direction": "LONG",
        "anchor_open_ms": bars[index]["open_time_ms"],
        "target_mode": "atr",
        "atr": width,
        "stop_multiple": STOP_ATR,
        "target_multiple": TARGET_ATR,
        "hold_bars": HOLD_BARS,
        "reward_risk": TARGET_ATR / STOP_ATR,
    }


RULES = {VERSION: trend_hold}


def _profit_factor(trades):
    gains = sum(trade["net"] for trade in trades if trade["net"] > 0)
    losses = -sum(trade["net"] for trade in trades if trade["net"] < 0)
    if losses <= 0:
        return None
    return gains / losses


def _average(trades, positive):
    chosen = [trade["net"] for trade in trades if (trade["net"] > 0) is positive and trade["net"] != 0]
    if not chosen:
        return None
    return sum(chosen) / len(chosen)


def _enrich(trades, summary):
    summary = dict(summary)
    summary["gross_sum"] = sum(trade["gross"] for trade in trades) if trades else 0.0
    summary["net_sum"] = sum(trade["net"] for trade in trades) if trades else 0.0
    summary["cost_drag"] = summary["gross_sum"] - summary["net_sum"]
    summary["profit_factor"] = _profit_factor(trades)
    summary["average_win"] = _average(trades, True)
    summary["average_loss"] = _average(trades, False)
    summary["long_trades"] = sum(trade["direction"] == "LONG" for trade in trades)
    summary["short_trades"] = sum(trade["direction"] == "SHORT" for trade in trades)
    return summary


def _benchmark(bars):
    if len(bars) < 2 or bars[0]["open"] <= 0:
        return None
    gross = bars[-1]["close"] / bars[0]["open"] - 1
    cost = 2 * CRYPTO_COST["base_bps_per_fill"] / 10000
    return {"no_trade": 0.0, "buy_and_hold_gross": gross, "buy_and_hold_net_one_round_turn": gross - cost, "round_turn_bps": 22}


def _folds(trades, start_ms, end_ms):
    width = (end_ms - start_ms) / 3 or 1
    rows = []
    for index in range(3):
        left = start_ms + index * width
        right = end_ms if index == 2 else start_ms + (index + 1) * width
        part = [trade for trade in trades if left <= trade["signal_open_time_ms"] < right]
        summary = _enrich(part, metrics(part))
        rows.append({"fold": index + 1, "trades": summary["trades"], "base_mean": summary.get("base_mean"), "net_sum": summary.get("net_sum")})
    return rows


def _between(trades, start_ms, end_ms):
    return [trade for trade in trades if start_ms <= trade["signal_open_time_ms"] < end_ms]


def _window(symbol, name, trades, stress_trades, start_ms, end_ms):
    summary = _enrich(trades, metrics(trades))
    stress = metrics(stress_trades)
    summary["stress_mean"] = stress.get("base_mean")
    summary["stress_trades"] = stress.get("trades")
    judgment, failed, blocked = judge(summary, halves(trades), symbol, measured_bid_ask=True)
    return {
        "symbol": symbol,
        "strategy": VERSION,
        "split": name,
        "start": _iso(start_ms) if start_ms else None,
        "end": _iso(end_ms) if end_ms else None,
        "judgment": judgment,
        "failed": failed,
        "blocked": blocked,
        "base_mean": summary.get("base_mean"),
        "stress_mean": summary.get("stress_mean"),
        "trades": summary.get("trades"),
        "gross_sum": summary.get("gross_sum"),
        "net_sum": summary.get("net_sum"),
        "cost_drag": summary.get("cost_drag"),
        "normal_95_lower": summary.get("normal_95_lower"),
        "equity": summary.get("equity"),
        "max_drawdown": summary.get("max_drawdown"),
        "worst_loss_streak": summary.get("worst_loss_streak"),
        "win_rate": summary.get("win_rate"),
        "profit_factor": summary.get("profit_factor"),
        "average_win": summary.get("average_win"),
        "average_loss": summary.get("average_loss"),
        "long_trades": summary.get("long_trades"),
        "short_trades": summary.get("short_trades"),
        "normal_interval_assumption": "The 95 percent bound treats trade results as independent draws. Overlapping regimes violate that, so the bound is a screen, not a proof.",
    }


def score_symbol(symbol, bars, simulate_fn=simulate, judge_fn=judge):
    """Score development and validation. Holdout bars are not passed in unless validation PASSes."""
    if symbol == "XAUUSD" or (bars and bars[0].get("interval") in {"1m", "3m"}):
        return {"symbol": symbol, "judgment": "BLOCKED", "reason": "not_eligible", "holdout": "NOT_OPENED", "approved_for_paper": False, "bars_simulated_lengths": []}
    dev, val, hold = _split(bars)
    if not dev or not val or not hold:
        return {"symbol": symbol, "judgment": "BLOCKED", "reason": "split_too_small", "holdout": "NOT_OPENED", "approved_for_paper": False, "bars_simulated_lengths": []}
    lengths = []

    def _sim(source, stress):
        lengths.append(len(source))
        return simulate_fn(symbol, source, [], VERSION, stress=stress, setup_map=RULES)

    dev_base = _sim(dev, False)
    dev_stress = _sim(dev, True)
    prefix = dev + val
    prefix_base = _sim(prefix, False)
    prefix_stress = _sim(prefix, True)
    val_start = val[0]["open_time_ms"]
    hold_start = hold[0]["open_time_ms"]
    dev_row = _window(symbol, "development", dev_base, dev_stress, dev[0]["open_time_ms"], val_start)
    # Replace judge with the injected function so tests can prove the holdout gate.
    dev_row["judgment"], dev_row["failed"], dev_row["blocked"] = judge_fn(metrics(dev_base) | {"stress_mean": metrics(dev_stress).get("base_mean")}, halves(dev_base), symbol, True)
    val_trades = _between(prefix_base, val_start + EMBARGO_MS, hold_start)
    val_stress = _between(prefix_stress, val_start + EMBARGO_MS, hold_start)
    val_row = _window(symbol, "validation", val_trades, val_stress, val_start + EMBARGO_MS, hold_start)
    val_summary = metrics(val_trades)
    val_summary["stress_mean"] = metrics(val_stress).get("base_mean")
    val_row["judgment"], val_row["failed"], val_row["blocked"] = judge_fn(val_summary, halves(val_trades), symbol, True)
    purged = [trade for trade in prefix_base if trade["signal_open_time_ms"] < val_start + EMBARGO_MS and trade["signal_open_time_ms"] >= val_start]
    folds = _folds(prefix_base, prefix[0]["open_time_ms"], hold_start)
    decision = {
        "symbol": symbol,
        "version": VERSION,
        "bars": len(bars),
        "development_bars": len(dev),
        "validation_bars": len(val),
        "holdout_bars": len(hold),
        "development_start": _iso(dev[0]["open_time_ms"]),
        "validation_start": _iso(val_start),
        "holdout_start": _iso(hold_start),
        "series_end": _iso(bars[-1]["close_time_ms"]),
        "sha256": _hash(bars),
        "embargo_ms": EMBARGO_MS,
        "embargoed_validation_signals": len(purged),
        "development": dev_row,
        "validation": val_row,
        "folds_on_prefix_signals": folds,
        "benchmark_development": _benchmark(dev),
        "benchmark_validation": _benchmark(val),
        "benchmark_prefix": _benchmark(prefix),
        "directions": "LONG only. Spot short was not simulated.",
        "promoted": False,
        "approved_for_paper": False,
        "bars_simulated_lengths": lengths,
        "holdout": "NOT_OPENED",
    }
    if val_row["judgment"] != "PASS":
        decision["holdout_reason"] = "validation_not_pass"
        return decision
    full_base = _sim(bars, False)
    full_stress = _sim(bars, True)
    hold_trades = _between(full_base, hold_start + EMBARGO_MS, bars[-1]["close_time_ms"] + 1)
    hold_stress = _between(full_stress, hold_start + EMBARGO_MS, bars[-1]["close_time_ms"] + 1)
    hold_row = _window(symbol, "holdout", hold_trades, hold_stress, hold_start + EMBARGO_MS, bars[-1]["close_time_ms"] + 1)
    hold_summary = metrics(hold_trades)
    hold_summary["stress_mean"] = metrics(hold_stress).get("base_mean")
    hold_row["judgment"], hold_row["failed"], hold_row["blocked"] = judge_fn(hold_summary, halves(hold_trades), symbol, True)
    decision["holdout"] = "OPENED_ONCE"
    decision["holdout_row"] = hold_row
    decision["approved_for_paper"] = False
    decision["bars_simulated_lengths"] = lengths
    return decision


def _git_sha():
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def evaluate_saved(simulate_fn=simulate, judge_fn=judge):
    """Quarantine retained 4h files. Do not read their candles or open the holdout."""
    del simulate_fn, judge_fn
    from ops.data_rights import MESSAGE, retained_research_status

    retained = [retained_research_status(ROOT / f"{symbol}-4h.csv") for symbol in ("BTCUSDT", "ETHUSDT")]
    return {
        "study": "discovery-20261103",
        "version": VERSION,
        "protocol": protocol(),
        "protocol_sha256": protocol_sha256(),
        "software_sha": _git_sha(),
        "quarantined": True,
        "commercial_research": False,
        "evaluation_command": "not run — retained 4h candles were not read",
        "costs_are_assumptions": True,
        "promoted": [],
        "approved_for_paper": [],
        "passed_existing_gates_on_validation_and_holdout": [],
        "holdout_opened_for": [],
        "markets": [],
        "retained": retained,
        "decision": "rights_unconfirmed",
        "note": MESSAGE + " The retained BTC and ETH 4h files were not opened and were not rescored.",
    }


def _fmt(value):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _markdown(report):
    lines = [
        "# Discovery result, trend-hold-4h-20261103",
        "",
        "This file is the scored result of the frozen protocol in `ops/discovery.py`. It is not an approval.",
        f"Protocol sha256: {report['protocol_sha256']}",
        f"Software sha at the run: {report['software_sha']}",
        f"Holdout opened for: {report['holdout_opened_for'] or 'nobody'}.",
        "Approved for paper: none.",
        "",
        "The rule is a follow-up to earlier cost-drag failures. It was not selected by looking at the holdout.",
        "",
    ]
    for market in report["markets"]:
        lines.append(f"## {market['symbol']}")
        lines.append("")
        lines.append(f"- Bars {market.get('bars')}. Development {market.get('development_bars')} from {market.get('development_start')}. Validation from {market.get('validation_start')}. Holdout starts {market.get('holdout_start')} and is {market.get('holdout')}.")
        lines.append(f"- Dataset fingerprint {market.get('sha256')}.")
        lines.append(f"- Embargoed validation signals: {market.get('embargoed_validation_signals')}.")
        for name in ("development", "validation"):
            row = market.get(name) or {}
            lines.append(f"- {name}: {row.get('judgment')} n={row.get('trades')} mean={_fmt(row.get('base_mean'))} stress={_fmt(row.get('stress_mean'))} gross={_fmt(row.get('gross_sum'))} net={_fmt(row.get('net_sum'))} cost={_fmt(row.get('cost_drag'))} drawdown={_fmt(row.get('max_drawdown'))} lower={_fmt(row.get('normal_95_lower'))} profit_factor={_fmt(row.get('profit_factor'))} win_rate={_fmt(row.get('win_rate'))} failed={row.get('failed')} blocked={row.get('blocked')}")
        if market.get("holdout") == "OPENED_ONCE":
            row = market.get("holdout_row") or {}
            lines.append(f"- holdout: {row.get('judgment')} n={row.get('trades')} mean={_fmt(row.get('base_mean'))} failed={row.get('failed')} blocked={row.get('blocked')}")
        else:
            lines.append("- holdout: NOT_OPENED")
        bench = market.get("benchmark_prefix") or {}
        lines.append(f"- Prefix buy-and-hold gross {_fmt(bench.get('buy_and_hold_gross'))}, net of one 22 bps round turn {_fmt(bench.get('buy_and_hold_net_one_round_turn'))}. No-trade baseline is 0.")
        lines.append(f"- Long trades are the only direction. Short trades: 0. Approved for paper: {market.get('approved_for_paper')}.")
        lines.append("")
    lines.append("Production was not changed by writing this file.")
    lines.append("")
    return "\n".join(lines)


def write_report(report=None):
    report = evaluate_saved() if report is None else report
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "DISCOVERY_RESULTS.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    (DOCS / "DISCOVERY_RESULTS.md").write_text(_markdown(report), encoding="utf-8")
    (DOCS / "DISCOVERY_PROTOCOL.md").write_text(_protocol_markdown(report["protocol"]), encoding="utf-8")
    return report


def _protocol_markdown(body):
    lines = [
        "# Frozen protocol, trend-hold-4h-20261103",
        "",
        "This protocol is the `protocol()` value in `ops/discovery.py`. Parameters were not changed after the result was scored.",
        "",
        f"Hypothesis. {body['hypothesis']}",
        "",
        f"Entry. {body['entry']}",
        "",
        f"Invalidation. {body['invalidation']}",
        "",
        f"Exit. {body['exit']}",
        "",
        f"Split. {body['split']}",
        "",
        f"Purging and embargo. {body['purging']}",
        "",
        f"Holdout. {body['holdout_rule']}",
        "",
        f"Approval. {body['approval_rule']}",
        "",
        f"Costs. {body['costs']['meaning']} Base {body['costs']['base_bps_per_fill']} bps per fill, stress {body['costs']['stress_bps_per_fill']} bps per fill, {body['costs']['fills']} fills.",
        "",
        "Gates are the existing `GATES` values: minimum 30 trades, 10 in each half, max drawdown 0.25, max loss streak 12, positive base and stress means, normal 95 percent lower bound above zero, equity above 1. Gold still requires measured bid/ask. This study does not score gold.",
        "",
        "Prior recorded families, which make this a follow-up rather than an independent test:",
        "",
    ]
    for name in body["prior_recorded_families"]:
        lines.append(f"- {name}")
    lines.append("")
    return "\n".join(lines)
