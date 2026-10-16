"""G1-H4 corrected simulator. Same fills across cost paths. Vol-scaled size."""

import math


def trailing_vol(closes, end, lookback):
    if end < lookback or lookback < 2:
        return None
    window = closes[end - lookback:end]
    rets = []
    for a, b in zip(window, window[1:]):
        if a <= 0:
            return None
        rets.append(b / a - 1)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    vol = math.sqrt(var)
    if not math.isfinite(vol) or vol <= 0:
        return None
    return vol


def signal_side(closes, end, lookback):
    if end < lookback:
        return 0
    start = closes[end - lookback]
    last = closes[end - 1]
    if start <= 0:
        return 0
    ret = last / start - 1
    if ret > 0:
        return 1
    if ret < 0:
        return -1
    return 0


def simulate_h4(bars, lookback, fee_bps, spread_bps, risk_cap=0.02):
    closes = [b["close"] for b in bars]
    trades = []
    i = lookback
    while i < len(bars) - 1:
        side = signal_side(closes, i, lookback)
        vol = trailing_vol(closes, i, lookback)
        if side == 0 or vol is None:
            i += 1
            continue
        size = min(risk_cap, 1.0 / vol)
        entry_bar = bars[i]
        exit_bar = bars[min(i + lookback, len(bars) - 1)]
        entry = entry_bar["open"] * (1 + side * spread_bps / 10_000)
        exit_px = exit_bar["open"] * (1 - side * spread_bps / 10_000)
        gross = side * (exit_px - entry) / entry * size
        fee = size * 2 * fee_bps / 10_000
        trades.append({
            "pnl": gross - fee,
            "size": size,
            "vol": vol,
            "entry_t": entry_bar["open_time_ms"],
            "exit_t": exit_bar["open_time_ms"],
        })
        i += lookback
    return trades
