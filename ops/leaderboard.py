"""Strategy leaderboard. Unit returns, not dollars. Not validated."""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ops.rules import rule_states

BASE = 11 / 10000
STRESS = 15 / 10000


def _bars(symbol, interval, limit=1000):
    from ops.data_rights import network_block

    blocked = network_block("binance_spot_rest_klines", "research")
    if blocked:
        raise PermissionError("rights_unconfirmed")
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    request = urllib.request.Request(
        f"https://data-api.binance.vision/api/v3/klines?{query}",
        headers={"User-Agent": "paper-desk"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        rows = json.loads(response.read().decode())
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    bars = []
    for row in rows:
        if int(row[6]) >= now:
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
        trades.append(gross - cost * 2)
        i = min(i + 8, len(bars) - 1)
    return trades


def _metrics(trades):
    if not trades:
        return {"trades": 0, "net_unit_return": 0, "expectancy": 0, "profit_factor": None, "win_rate": 0, "max_drawdown": 0}
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    eq = peak = mdd = 0
    for t in trades:
        eq += t
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) else None
    return {
        "trades": len(trades),
        "net_unit_return": sum(trades),
        "expectancy": sum(trades) / len(trades),
        "profit_factor": pf,
        "win_rate": len(wins) / len(trades),
        "max_drawdown": mdd,
    }


def leaderboard():
    from ops.data_rights import MESSAGE, network_block

    blocked = network_block("binance_spot_rest_klines", "research")
    if blocked:
        return {
            "ok": False,
            "rows": [],
            "validated": False,
            "reason": "commercial_use_unverified",
            "rights_status": blocked.get("rights_status"),
            "message": MESSAGE,
            "label": "RESEARCH WITHHELD — COMMERCIAL USE NOT APPROVED",
        }
    rows = []
    coverage = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for interval in ("15m", "1h", "4h", "1d"):
            bars = _bars(symbol, interval)
            if not bars:
                continue
            coverage.append({
                "symbol": symbol,
                "interval": interval,
                "bars": len(bars),
                "start": datetime.fromtimestamp(bars[0]["open_time_ms"] / 1000, timezone.utc).date().isoformat(),
                "end": datetime.fromtimestamp(bars[-1]["open_time_ms"] / 1000, timezone.utc).date().isoformat(),
                "source": "binance-public",
            })
            for name in ("E1-donchian-20", "SMA20-cross", "RSI14-band"):
                base = _metrics(_trades(bars, name, BASE))
                stress = _metrics(_trades(bars, name, STRESS))
                rows.append({
                    "symbol": symbol,
                    "interval": interval,
                    "strategy": name,
                    "unit": "fractional return per 1 unit, not dollars",
                    "base": base,
                    "stress": stress,
                    "validated": False,
                })
    return {
        "label": "RESEARCH LEADERBOARD — NOT VALIDATED",
        "coverage": coverage,
        "rows": rows,
        "gold": "no reliable XAUUSD feed",
    }
