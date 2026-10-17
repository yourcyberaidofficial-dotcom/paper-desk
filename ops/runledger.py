"""Durable research ledger. New runs only."""

import json
from pathlib import Path

from ops.history import fetch_history
from ops.deepboard import _trades, _metrics


def write_run(path, run_id, symbol, interval, strategy, bars, cost):
    trades = _trades(bars, strategy, cost)
    rows = []
    for i, trade in enumerate(trades):
        rows.append({
            "run_id": run_id,
            "trade_id": f"{run_id}:{i}",
            "symbol": symbol,
            "interval": interval,
            "strategy": strategy,
            "net": trade["net"],
            "side": trade["side"],
            "cost_bps_per_fill": cost * 10000,
            "validated": False,
        })
    payload = {
        "run_id": run_id,
        "symbol": symbol,
        "interval": interval,
        "strategy": strategy,
        "bars": len(bars),
        "ledger_complete": True,
        "validated": False,
        "trades": rows,
        "engine_metrics": _metrics(trades),
    }
    Path(path).write_text(json.dumps(payload))
    return payload


def reconcile(path):
    data = json.loads(Path(path).read_text())
    trades = data["trades"]
    nets = [t["net"] for t in trades]
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for n in nets:
        equity *= (1 + n)
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak if peak else 0)
    independent = {
        "trades": len(trades),
        "sum_unit_return": sum(nets),
        "compounded_unit_equity": equity,
        "max_drawdown": mdd,
    }
    engine = data["engine_metrics"]
    agree = abs(independent["sum_unit_return"] - engine["sum_unit_return"]) < 1e-12
    return {"status": "RECONCILED" if agree else "DISCREPANCY_FOUND", "independent": independent, "engine": engine}
