"""Research indicators. Not validated predictors."""


def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def ema(values, n):
    if len(values) < n:
        return None
    k = 2 / (n + 1)
    out = sum(values[:n]) / n
    for v in values[n:]:
        out = v * k + out * (1 - k)
    return out


def rsi(values, n=14):
    if len(values) < n + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(values[-(n + 1):-1], values[-n:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


def atr(bars, n=14):
    if len(bars) < n:
        return None
    return sum(b["high"] - b["low"] for b in bars[-n:]) / n
