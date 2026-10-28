"""Score the frozen Gate 4 hypotheses. Holdout stays closed unless validation passes.

Gate 3 families can be replayed and cannot be selected. Production is not changed.
"""

import hashlib
import json
import statistics
from datetime import datetime, timezone

from ops.bars import aggregate
from ops.gate4_hypotheses import CRYPTO, GOLD, SETUP, SLIPPAGE_USD
from ops.hypotheses import FAMILIES, GOLD_ONLY, _regime
from ops.research_select import judge, select_candidate
from ops.simulate import simulate

PRODUCTION = "WAIT_DEFAULT"


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _hash(bars):
    payload = "\n".join(
        f"{bar['open_time_ms']},{bar.get('bid_open', bar['open'])},{bar.get('bid_high', bar['high'])},{bar.get('bid_low', bar['low'])},{bar.get('bid_close', bar['close'])},{bar.get('ask_open','')},{bar.get('ask_close','')}"
        for bar in bars
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def split_bars(bars):
    count = len(bars)
    dev_end = int(count * 0.60)
    val_end = int(count * 0.80)
    return bars[:dev_end], bars[dev_end:val_end], bars[val_end:]


def _between(trades, start_ms, end_ms):
    return [trade for trade in trades if start_ms <= trade["signal_open_time_ms"] < end_ms]


def _profit_factor(trades):
    wins = sum(trade["net"] for trade in trades if trade["net"] > 0)
    losses = sum(-trade["net"] for trade in trades if trade["net"] < 0)
    if losses == 0:
        return None
    return wins / losses


def _means(trades, key):
    groups = {}
    for trade in trades:
        groups.setdefault(trade.get(key) or "NONE", []).append(trade["net"])
    return {name: {"n": len(values), "mean": statistics.fmean(values)} for name, values in sorted(groups.items())}


def _tag(trades, bars, higher, symbol):
    by_open = {bar["open_time_ms"]: bar for bar in bars}
    length = 12 if symbol == "XAUUSD" else 48
    tagged = []
    for trade in trades:
        bar = by_open.get(trade["signal_open_time_ms"])
        regime = None
        if bar is not None:
            regime, _tail = _regime(higher, bar["close_time_ms"], length)
        copy = dict(trade)
        copy["regime"] = regime or "FLAT"
        tagged.append(copy)
    return tagged


def _row(symbol, strategy, split, trades, stress_trades, start_ms, end_ms, measured):
    from ops.simulate import metrics, halves
    summary = metrics(trades)
    stress = metrics(stress_trades)
    summary["stress_mean"] = stress.get("base_mean")
    judgment, failed, blocked = judge(summary, halves(trades), symbol, measured_bid_ask=measured)
    return {
        "symbol": symbol,
        "strategy": strategy,
        "split": split,
        "start": _iso(start_ms),
        "end": _iso(end_ms),
        "judgment": judgment,
        "failed": failed,
        "blocked": blocked,
        "base_mean": summary.get("base_mean"),
        "stress_mean": summary.get("stress_mean"),
        "trades": summary.get("trades"),
        "normal_95_lower": summary.get("normal_95_lower"),
        "equity": summary.get("equity"),
        "max_drawdown": summary.get("max_drawdown"),
        "worst_loss_streak": summary.get("worst_loss_streak"),
        "win_rate": summary.get("win_rate"),
        "profit_factor": _profit_factor(trades),
        "by_direction": _means(trades, "direction"),
        "by_regime": _means(trades, "regime"),
        "measured_bid_ask": measured,
    }


def score_symbol(symbol, entry, higher, names, execution, measured, selectable=True, setup_map=None):
    """Development and validation only, unless a selectable validation row passes."""
    table = setup_map or SETUP
    dev, val, hold = split_bars(entry)
    if not dev or not val or not hold:
        return [], {"selected": None, "holdout": "NOT_OPENED", "reason": "split_too_small"}
    prefix_end = val[-1]["close_time_ms"]
    prefix = [bar for bar in entry if bar["close_time_ms"] <= prefix_end]
    higher_prefix = [bar for bar in higher if bar["open_time_ms"] <= prefix_end]
    hold_start = hold[0]["open_time_ms"]
    if any(bar["open_time_ms"] >= hold_start for bar in prefix):
        raise RuntimeError("holdout_leak")
    rows = []
    cached = {}
    for strategy in names:
        base_slip = 0.0 if execution != "bid_ask" else SLIPPAGE_USD["base_per_fill"]
        stress_slip = 0.0 if execution != "bid_ask" else SLIPPAGE_USD["stress_per_fill"]
        base = _tag(simulate(symbol, prefix, higher_prefix, strategy, stress=False, execution=execution, slippage_usd=base_slip, setup_map=table), prefix, higher_prefix, symbol)
        stress = _tag(simulate(symbol, prefix, higher_prefix, strategy, stress=True, execution=execution, slippage_usd=stress_slip, setup_map=table), prefix, higher_prefix, symbol)
        cached[strategy] = (base, stress)
        windows = (
            ("development", dev[0]["open_time_ms"], val[0]["open_time_ms"]),
            ("validation", val[0]["open_time_ms"], hold_start),
        )
        for split, start_ms, end_ms in windows:
            rows.append(_row(symbol, strategy, split, _between(base, start_ms, end_ms), _between(stress, start_ms, end_ms), start_ms, end_ms, measured))
    if not selectable:
        return rows, {"selected": None, "holdout": "NOT_OPENED", "reason": "replay_not_selectable"}
    chosen = select_candidate(rows).get(symbol)
    if chosen is None:
        return rows, {"selected": None, "holdout": "NOT_OPENED", "reason": "no_validation_pass"}
    strategy = chosen["strategy"]
    base_slip = 0.0 if execution != "bid_ask" else SLIPPAGE_USD["base_per_fill"]
    stress_slip = 0.0 if execution != "bid_ask" else SLIPPAGE_USD["stress_per_fill"]
    base = _tag(simulate(symbol, entry, higher, strategy, stress=False, execution=execution, slippage_usd=base_slip, setup_map=table), entry, higher, symbol)
    stress = _tag(simulate(symbol, entry, higher, strategy, stress=True, execution=execution, slippage_usd=stress_slip, setup_map=table), entry, higher, symbol)
    end_ms = entry[-1]["close_time_ms"] + 1
    rows.append(_row(symbol, strategy, "holdout", _between(base, hold_start, end_ms), _between(stress, hold_start, end_ms), hold_start, end_ms, measured))
    return rows, {"selected": strategy, "holdout": "SCORED", "validation_mean": chosen.get("base_mean")}


def load_bars(path):
    bars = [json.loads(line) for line in Path_read(path) if line.strip()]
    bars.sort(key=lambda bar: bar["open_time_ms"])
    return bars


def Path_read(path):
    from pathlib import Path
    return Path(path).read_text().splitlines()


def crypto_bundle(symbol, start_ms, end_ms, now_ms):
    from ops.feeds import binance_bars
    entry = binance_bars(symbol, "15m", start_ms, end_ms, now_ms=now_ms)
    higher = binance_bars(symbol, "1h", start_ms - 5 * 24 * 60 * 60 * 1000, end_ms, now_ms=now_ms)
    return entry, higher


def gold_higher(bars):
    return aggregate(bars, "1h", "4h")


def new_names(symbol):
    if symbol == "XAUUSD":
        return list(GOLD)
    return list(CRYPTO)


def replay_names(symbol):
    names = list(FAMILIES)
    if symbol == "XAUUSD":
        names.extend(GOLD_ONLY)
    return names
