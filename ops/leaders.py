"""Frozen on 2026-10-28 before this run was scored.

These rules are not parameter edits of E1, the Gate 3 families, spot-tsmom,
or tight-range-long. Spot shorts are not simulated. The last 20 percent of
each crypto series is a sealed holdout and is not passed to the simulator.
A market leader is the highest median walk-forward mean among rules that are
not blocked. That rank is not an approval. Approval still requires the
existing judge to return PASS on the pre-holdout trades. Gold is scored only
on Dukascopy bid/ask hours, with the spread paid by buying the ask and selling
the bid, plus 0.10 USD slippage per side (0.30 under stress).
"""

from datetime import datetime, timezone

from ops.hypotheses import _atr

SWEEP = "sweep-reclaim-4h-20261028"
COMPRESS = "compress-break-4h-20261028"
LONDON = "london-reclaim-1h-20261028"


def sweep_reclaim(bars, index, higher, symbol):
    del higher
    if symbol not in {"BTCUSDT", "ETHUSDT"} or bars[index].get("interval") != "4h" or index < 7:
        return None
    prior = bars[index - 6 : index]
    prior_low = min(bar["low"] for bar in prior)
    prior_high = max(bar["high"] for bar in prior)
    bar = bars[index]
    if not (bar["low"] < prior_low and bar["close"] > prior_low) or prior_high <= prior_low:
        return None
    return {
        "strategy": SWEEP,
        "version": SWEEP,
        "direction": "LONG",
        "anchor_open_ms": bar["open_time_ms"],
        "target_mode": "level",
        "stop_price": bar["low"],
        "target_price": (prior_high + prior_low) / 2,
        "hold_bars": 6,
        "reward_risk": 1.0,
    }


def compress_break(bars, index, higher, symbol):
    del higher
    if symbol not in {"BTCUSDT", "ETHUSDT"} or bars[index].get("interval") != "4h" or index < 42:
        return None
    quiet = _atr(bars, index - 1, 10)
    slow = _atr(bars, index - 1, 40)
    if quiet is None or slow is None or slow <= 0 or quiet >= 0.6 * slow:
        return None
    ceiling = max(bar["high"] for bar in bars[index - 10 : index])
    if bars[index]["close"] <= ceiling:
        return None
    width = _atr(bars, index, 14)
    if width is None or width <= 0:
        return None
    return {
        "strategy": COMPRESS,
        "version": COMPRESS,
        "direction": "LONG",
        "anchor_open_ms": bars[index]["open_time_ms"],
        "target_mode": "atr",
        "atr": width,
        "stop_multiple": 1.0,
        "target_multiple": 2.0,
        "hold_bars": 12,
        "reward_risk": 2.0,
    }


def london_reclaim(bars, index, higher, symbol):
    del higher
    if symbol != "XAUUSD" or bars[index].get("interval") != "1h" or index < 5:
        return None
    hour = datetime.fromtimestamp(bars[index]["open_time_ms"] / 1000, timezone.utc).hour
    if hour not in {7, 8, 9, 10}:
        return None
    prior = bars[index - 4 : index]
    prior_low = min(bar["low"] for bar in prior)
    prior_high = max(bar["high"] for bar in prior)
    bar = bars[index]
    if not (bar["low"] < prior_low and bar["close"] > prior_low) or prior_high <= prior_low:
        return None
    return {
        "strategy": LONDON,
        "version": LONDON,
        "direction": "LONG",
        "anchor_open_ms": bar["open_time_ms"],
        "target_mode": "level",
        "stop_price": bar["low"],
        "target_price": (prior_high + prior_low) / 2,
        "hold_bars": 4,
        "reward_risk": 1.0,
    }


CRYPTO_RULES = {SWEEP: sweep_reclaim, COMPRESS: compress_break}
GOLD_RULES = {LONDON: london_reclaim}


def choose_leader(rows):
    """rows are pre-holdout summaries. A FAIL can rank first and still stay unapproved."""
    ranked = []
    for row in rows:
        folds = row.get("folds") or []
        if row.get("blocked"):
            continue
        if any((fold.get("trades") or 0) < 10 for fold in folds) or len(folds) < 3:
            continue
        means = sorted(fold["base_mean"] for fold in folds)
        ranked.append((means[1], row))
    if not ranked:
        return {"strategy": None, "status": "none", "approved": False}
    ranked.sort(key=lambda item: item[0], reverse=True)
    winner = ranked[0][1]
    approved = winner.get("judgment") == "PASS"
    return {
        "strategy": winner["strategy"],
        "median_fold_mean": ranked[0][0],
        "judgment": winner.get("judgment"),
        "status": "approved" if approved else "research_leader_failed",
        "approved": approved,
    }
