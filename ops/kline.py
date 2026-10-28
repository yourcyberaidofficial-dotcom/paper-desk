"""Binance kline closed-candle rule.

https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md
A kline is closed only when k.x is true. A connection to the stream is valid
for 24 hours and must be reopened. A forming candle is not a strategy input.
"""

STREAM_MAX_AGE_SECONDS = 24 * 60 * 60


def closed_bar(message, symbol, interval):
    candle = (message or {}).get("k") or {}
    if candle.get("x") is not True:
        return None
    if candle.get("s") != symbol or candle.get("i") != interval:
        return None
    try:
        open_ = float(candle["o"])
        high = float(candle["h"])
        low = float(candle["l"])
        close = float(candle["c"])
        open_time = int(candle["t"])
        close_time = int(candle["T"])
    except (KeyError, TypeError, ValueError):
        return None
    if min(open_, high, low, close) <= 0 or high < max(open_, close, low) or low > min(open_, close, high):
        return None
    if close_time <= open_time:
        return None
    return {
        "symbol": symbol,
        "interval": interval,
        "open_time_ms": open_time,
        "close_time_ms": close_time,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "forming": False,
    }
