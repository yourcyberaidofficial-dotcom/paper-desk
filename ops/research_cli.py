"""Run the frozen Gate 3 split. Holdout is scored only after validation selection."""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ops.bars import aggregate
from ops.feeds import binance_bars, dukascopy_hour, xaus_chart
from ops.hypotheses import FAMILIES, GOLD_ONLY
from ops.research_select import judge, select_candidate
from ops.simulate import halves, metrics, simulate

ROOT = Path(__file__).resolve().parents[1]
YEAR_MS = int(365 * 24 * 60 * 60 * 1000)


def _hash(bars):
    payload = "\n".join(
        f"{bar['open_time_ms']},{bar['open']},{bar['high']},{bar['low']},{bar['close']}" for bar in bars
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def _split(bars):
    count = len(bars)
    dev_end = int(count * 0.60)
    val_end = int(count * 0.80)
    return bars[:dev_end], bars[dev_end:val_end], bars[val_end:]


def _between(trades, start_ms, end_ms):
    return [trade for trade in trades if start_ms <= trade["signal_open_time_ms"] < end_ms]


def _window_row(symbol, strategy, split, trades, stress_trades, start_ms, end_ms):
    summary = metrics(trades)
    stress = metrics(stress_trades)
    summary["stress_mean"] = stress.get("base_mean")
    judgment, failed, blocked = judge(summary, halves(trades), symbol)
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
    }


def _evaluate_symbol(symbol, entry, higher):
    dev, val, hold = _split(entry)
    if not dev or not val or not hold:
        return [], {"selected": None, "holdout": "NOT_OPENED", "reason": "split_too_small"}
    prefix_end = val[-1]["close_time_ms"]
    prefix = [bar for bar in entry if bar["close_time_ms"] <= prefix_end]
    higher_prefix = [bar for bar in higher if bar["open_time_ms"] <= prefix_end]
    names = list(FAMILIES) + (list(GOLD_ONLY) if symbol == "XAUUSD" else [])
    rows = []
    cached = {}
    for strategy in names:
        base = simulate(symbol, prefix, higher_prefix, strategy, stress=False)
        stress = simulate(symbol, prefix, higher_prefix, strategy, stress=True)
        cached[strategy] = (base, stress)
        windows = (
            ("development", dev[0]["open_time_ms"], val[0]["open_time_ms"]),
            ("validation", val[0]["open_time_ms"], hold[0]["open_time_ms"]),
        )
        for split, start_ms, end_ms in windows:
            rows.append(_window_row(symbol, strategy, split, _between(base, start_ms, end_ms), _between(stress, start_ms, end_ms), start_ms, end_ms))
    chosen = select_candidate(rows)
    pick = chosen.get(symbol)
    holdout_rows = []
    if pick is None:
        return rows, {"selected": None, "holdout": "NOT_OPENED", "reason": "no_validation_pass"}
    strategy = pick["strategy"]
    base = simulate(symbol, entry, higher, strategy, stress=False)
    stress = simulate(symbol, entry, higher, strategy, stress=True)
    start_ms = hold[0]["open_time_ms"]
    end_ms = entry[-1]["close_time_ms"] + 1
    holdout_rows.append(_window_row(symbol, strategy, "holdout", _between(base, start_ms, end_ms), _between(stress, start_ms, end_ms), start_ms, end_ms))
    return rows + holdout_rows, {"selected": strategy, "holdout": "SCORED"}


def _coverage(symbol, bars, provider):
    if not bars:
        return {"symbol": symbol, "bars": 0, "provider": provider}
    return {
        "symbol": symbol,
        "provider": provider,
        "bars": len(bars),
        "start": _iso(bars[0]["open_time_ms"]),
        "end": _iso(bars[-1]["close_time_ms"]),
        "sha256": _hash(bars),
        "quote_semantics": bars[0].get("quote_semantics"),
    }


def run():
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - YEAR_MS
    out = {
        "spec": "docs/GATE3_SPEC.md",
        "production": "WAIT_DEFAULT",
        "broker": False,
        "promoted": [],
        "e1_benchmark": "FAIL on BTCUSDT and ETHUSDT 15m for 2024-10-17 to 2026-10-17. Not re-tuned.",
        "dukascopy": dukascopy_hour(2024, 9, 1, 0),
        "coverage": [],
        "rows": [],
        "selection": {},
    }
    out["dukascopy"].pop("ticks", None)
    series = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        print(f"fetch {symbol}", flush=True)
        entry = binance_bars(symbol, "15m", start_ms, now_ms, now_ms)
        higher = binance_bars(symbol, "1h", start_ms - 5 * 24 * 60 * 60 * 1000, now_ms, now_ms)
        out["coverage"].append({**_coverage(symbol, entry.get("bars") or [], "binance-public"), "interval": "15m", "ok": entry.get("ok"), "reason": entry.get("reason")})
        out["coverage"].append({**_coverage(symbol, higher.get("bars") or [], "binance-public"), "interval": "1h", "ok": higher.get("ok")})
        if entry.get("ok") and higher.get("ok") and entry["bars"] and higher["bars"]:
            series.append((symbol, entry["bars"], higher["bars"]))
        else:
            out["selection"][symbol] = {"selected": None, "holdout": "NOT_OPENED", "reason": entry.get("reason") or higher.get("reason") or "missing_bars"}
    print("fetch XAUUSD", flush=True)
    gold = xaus_chart("1h", now_ms)
    gold_bars = gold.get("bars") or []
    gold_higher = aggregate(gold_bars, "1h", "4h") if gold_bars else []
    out["coverage"].append({**_coverage("XAUUSD", gold_bars, "xaus.com"), "interval": "1h", "ok": gold.get("ok"), "reason": gold.get("reason"), "partial_dropped": gold.get("partial_dropped")})
    out["coverage"].append({**_coverage("XAUUSD", gold_higher, "xaus.com"), "interval": "4h", "ok": bool(gold_higher)})
    if gold.get("ok") and gold_bars and gold_higher:
        series.append(("XAUUSD", gold_bars, gold_higher))
    else:
        out["selection"]["XAUUSD"] = {"selected": None, "holdout": "NOT_OPENED", "reason": gold.get("reason") or "GOLD_FEED_UNAVAILABLE"}
    for symbol, entry, higher in series:
        print(f"simulate {symbol} bars={len(entry)}", flush=True)
        rows, selection = _evaluate_symbol(symbol, entry, higher)
        out["rows"].extend(rows)
        out["selection"][symbol] = selection
    passed = [row for row in out["rows"] if row["split"] == "holdout" and row["judgment"] == "PASS"]
    out["qualified_for_review"] = [row["strategy"] + ":" + row["symbol"] for row in passed]
    out["approved"] = []
    return out


def _markdown(report):
    lines = [
        "# Gate 3 results",
        "",
        "Production remains WAIT_DEFAULT. No strategy is approved. No Telegram message was sent.",
        "E1 was not re-optimized. The prior BTC and ETH 15-minute result stays FAIL.",
        "",
        "## Coverage",
        "",
    ]
    for row in report["coverage"]:
        lines.append(f"- {row.get('symbol')} {row.get('interval')}: bars {row.get('bars')} ok {row.get('ok')} {row.get('start')} → {row.get('end')} sha256 {row.get('sha256')} {row.get('reason') or ''}")
    lines.extend(["", "## Windows", ""])
    for row in report["rows"]:
        mean = row["base_mean"]
        mean_text = "n/a" if mean is None else f"{mean:.6f}"
        lines.append(
            f"- {row['symbol']} {row['strategy']} {row['split']}: {row['judgment']} n={row['trades']} mean={mean_text} failed={row['failed']} blocked={row['blocked']}"
        )
    lines.extend(["", "## Selection", ""])
    for symbol, selection in report["selection"].items():
        lines.append(f"- {symbol}: {json.dumps(selection, sort_keys=True)}")
    lines.extend([
        "",
        f"Qualified for review: {report['qualified_for_review'] or 'none'}.",
        "Approved for production: none.",
        f"Dukascopy probe: {report['dukascopy'].get('reason') or report['dukascopy'].get('ok')}.",
        "",
    ])
    return "\n".join(lines)


def main():
    report = run()
    path = ROOT / "docs" / "GATE3_RESULTS.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True))
    (ROOT / "docs" / "GATE3_RESULTS.md").write_text(_markdown(report))
    print(path)
    print(json.dumps(report["selection"], sort_keys=True))


if __name__ == "__main__":
    main()
