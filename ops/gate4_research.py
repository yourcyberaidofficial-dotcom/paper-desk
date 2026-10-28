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


def gap_report(bars):
    from ops.sessions import expected_gold_gap

    holes = []
    unexpected = 0
    for left, right in zip(bars, bars[1:]):
        delta = right["open_time_ms"] - left["open_time_ms"]
        if delta == 3_600_000:
            continue
        closed = expected_gold_gap(left["open_time_ms"], right["open_time_ms"])
        if not closed:
            unexpected += 1
        holes.append({
            "from": _iso(left["open_time_ms"]),
            "to": _iso(right["open_time_ms"]),
            "hours": delta / 3_600_000,
            "weekly_close": closed,
        })
    return {"gaps": len(holes), "unexpected_gaps": unexpected, "largest": holes[:8]}


def _coverage(symbol, bars, provider, interval):
    if not bars:
        return {"symbol": symbol, "interval": interval, "bars": 0, "provider": provider}
    return {
        "symbol": symbol,
        "interval": interval,
        "provider": provider,
        "bars": len(bars),
        "start": _iso(bars[0]["open_time_ms"]),
        "end": _iso(bars[-1]["close_time_ms"]),
        "sha256": _hash(bars),
        "quote_semantics": bars[0].get("quote_semantics"),
        "fresh": bars[-1].get("fresh"),
    }


# Recorded Gate 3 endpoints. A later clock must not slide this window.
CRYPTO_15M_START = "2025-10-28T00:45:00+00:00"
CRYPTO_15M_END = "2026-10-28T00:29:59.999000+00:00"
CRYPTO_1H_START = "2025-10-23T01:00:00+00:00"
CRYPTO_1H_END = "2026-10-27T23:59:59.999000+00:00"


def _ms(text):
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def score_crypto(now_ms=None):
    from ops.hypotheses import SETUP as GATE3_SETUP
    from ops.research_cli import _evaluate_symbol

    start_15 = _ms(CRYPTO_15M_START)
    end_15 = _ms(CRYPTO_15M_END)
    start_1h = _ms(CRYPTO_1H_START)
    end_1h = _ms(CRYPTO_1H_END)
    clock = end_15 if now_ms is None else now_ms
    report = {"coverage": [], "rows": [], "selection": {}, "gate3_replay": [], "gate3_selection": {}, "gate3_engine": {}}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        entry_page, higher_page = crypto_bundle(symbol, start_15, end_15, clock)
        if not entry_page.get("ok") or not higher_page.get("ok"):
            reason = entry_page.get("reason") or higher_page.get("reason") or "missing_bars"
            report["selection"][symbol] = {"selected": None, "holdout": "NOT_OPENED", "reason": reason}
            report["coverage"].append({"symbol": symbol, "ok": False, "reason": reason})
            continue
        higher = [bar for bar in higher_page["bars"] if start_1h <= bar["open_time_ms"] and bar["close_time_ms"] <= end_1h]
        entry = [bar for bar in entry_page["bars"] if bar["close_time_ms"] <= end_15]
        report["coverage"].append(_coverage(symbol, entry, "binance-public", "15m"))
        report["coverage"].append(_coverage(symbol, higher, "binance-public", "1h"))
        rows, selection = score_symbol(symbol, entry, higher, new_names(symbol), "last_trade", False, selectable=True)
        report["rows"].extend(rows)
        report["selection"][symbol] = selection
        replay_rows, replay_selection = score_symbol(
            symbol, entry, higher, replay_names(symbol), "last_trade", False, selectable=False, setup_map=GATE3_SETUP,
        )
        report["gate3_replay"].extend(replay_rows)
        report["gate3_selection"][symbol] = replay_selection
        report["gate3_engine"][symbol] = _evaluate_symbol(symbol, entry, higher)[1]
    return report


def score_gold(bars):
    from ops.hypotheses import SETUP as GATE3_SETUP

    ordered = sorted(bars, key=lambda bar: bar["open_time_ms"])
    higher = gold_higher(ordered)
    measured_rows, measured_selection = score_symbol(
        "XAUUSD", ordered, higher, new_names("XAUUSD"), "bid_ask", True, selectable=True,
    )
    replay_rows, replay_selection = score_symbol(
        "XAUUSD", ordered, higher, replay_names("XAUUSD"), "bid_ask", True, selectable=False, setup_map=GATE3_SETUP,
    )
    assumed_rows, _assumed_selection = score_symbol(
        "XAUUSD", ordered, higher, list(new_names("XAUUSD")) + list(replay_names("XAUUSD")),
        "last_trade", False, selectable=False, setup_map={**GATE3_SETUP, **SETUP},
    )
    for row in assumed_rows:
        row["cost_label"] = "assumed_0.50_1.50_usd_per_side_on_bid_ohlc_not_measured"
        if row["judgment"] == "PASS":
            row["judgment"] = "BLOCKED"
            row["blocked"] = list(row["blocked"]) + ["assumed_cost_cannot_pass"]
    return {
        "coverage": [
            _coverage("XAUUSD", ordered, "dukascopy", "1h"),
            _coverage("XAUUSD", higher, "dukascopy", "4h"),
        ],
        "gaps": gap_report(ordered),
        "measured": {"rows": measured_rows, "selection": measured_selection},
        "gate3_replay_measured": {"rows": replay_rows, "selection": replay_selection},
        "assumed_cost_comparison": {"rows": assumed_rows, "selection": {"selected": None, "holdout": "NOT_OPENED", "reason": "assumed_cost_cannot_pass"}, "can_pass": False},
    }


def main():
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--crypto-out", default="/tmp/gate4-data/crypto-score.json")
    parser.add_argument("--gold", default="")
    parser.add_argument("--gold-out", default="/tmp/gate4-data/gold-score.json")
    parser.add_argument("--skip-crypto", action="store_true")
    args = parser.parse_args()
    if not args.skip_crypto:
        crypto = score_crypto()
        path = Path(args.crypto_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(crypto, indent=2, sort_keys=True))
        print(json.dumps({"crypto": str(path), "selection": crypto.get("selection")}, sort_keys=True))
    if args.gold:
        bars = load_bars(args.gold)
        gold = score_gold(bars)
        path = Path(args.gold_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(gold, indent=2, sort_keys=True))
        print(json.dumps({"gold": str(path), "bars": len(bars), "selection": gold["measured"]["selection"]}, sort_keys=True))


if __name__ == "__main__":
    main()
