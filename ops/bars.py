"""One candle schema. Invalid bars are rejected, never repaired."""

INTERVAL_MS = {"15m": 15 * 60 * 1000, "1h": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000}


def interval_ms(interval):
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported_interval:{interval}")
    return INTERVAL_MS[interval]


def make_bar(**fields):
    bar = {
        "symbol": fields["symbol"],
        "instrument": fields.get("instrument") or fields["symbol"],
        "interval": fields["interval"],
        "open_time_ms": int(fields["open_time_ms"]),
        "close_time_ms": int(fields["close_time_ms"]),
        "open": fields.get("open"),
        "high": fields.get("high"),
        "low": fields.get("low"),
        "close": fields.get("close"),
        "volume": fields.get("volume"),
        "bid": fields.get("bid"),
        "ask": fields.get("ask"),
        "provider": fields.get("provider") or "unknown",
        "source_type": fields.get("source_type") or "unspecified",
        "quote_semantics": fields.get("quote_semantics") or "unspecified",
        "retrieved_at_ms": int(fields.get("retrieved_at_ms") or 0),
        "complete": bool(fields.get("complete")),
        "fresh": bool(fields.get("fresh")),
    }
    return bar


def ohlc_ok(bar):
    values = (bar.get("open"), bar.get("high"), bar.get("low"), bar.get("close"))
    if any(value is None or isinstance(value, bool) or not isinstance(value, (int, float)) for value in values):
        return False
    open_, high, low, close = values
    if min(open_, high, low, close) <= 0:
        return False
    if high < low or open_ > high or open_ < low or close > high or close < low:
        return False
    if bar["close_time_ms"] <= bar["open_time_ms"]:
        return False
    return True


def validate_series(bars, interval):
    """Return a quality report. Does not invent missing prices."""
    step = interval_ms(interval)
    errors = []
    if not bars:
        return {"ok": False, "bars": 0, "errors": ["empty"], "duplicates": 0, "gaps": 0, "unsorted": 0}
    seen = set()
    duplicates = unsorted = gaps = invalid = 0
    previous = None
    for bar in bars:
        if bar.get("interval") != interval:
            invalid += 1
            errors.append("interval_mismatch")
        if not bar.get("complete") or not ohlc_ok(bar):
            invalid += 1
        stamp = bar.get("open_time_ms")
        if stamp in seen:
            duplicates += 1
        seen.add(stamp)
        if previous is not None:
            if stamp < previous:
                unsorted += 1
            elif stamp - previous != step:
                gaps += 1
        if stamp % step != 0:
            invalid += 1
            errors.append("unaligned")
        previous = stamp
    ok = invalid == 0 and duplicates == 0 and unsorted == 0
    return {
        "ok": ok,
        "bars": len(bars),
        "invalid": invalid,
        "duplicates": duplicates,
        "unsorted": unsorted,
        "gaps": gaps,
        "errors": errors[:8],
    }


def to_chart_candles(bars):
    """Chart points keep the provider open. Close is never copied into open."""
    points = []
    for bar in bars:
        if not ohlc_ok(bar):
            continue
        points.append({
            "t": bar["open_time_ms"],
            "o": bar["open"],
            "h": bar["high"],
            "l": bar["low"],
            "c": bar["close"],
            "v": bar.get("volume"),
        })
    return points


def drop_forming(bars, now_ms):
    """A bar is complete only after its close time. The forming bar is not repaired."""
    kept = []
    dropped = 0
    for bar in bars:
        if bar["close_time_ms"] <= now_ms and bar.get("complete") and ohlc_ok(bar):
            kept.append(bar)
        else:
            dropped += 1
    return kept, dropped


def aggregate(bars, source_interval, target_interval):
    """Build higher bars only from complete aligned groups. Missing children are not filled."""
    source = interval_ms(source_interval)
    target = interval_ms(target_interval)
    if target % source != 0 or target < source:
        raise ValueError("interval_not_aligned")
    width = target // source
    groups = {}
    order = []
    for bar in bars:
        if not bar.get("complete") or not ohlc_ok(bar):
            continue
        if bar["open_time_ms"] % source != 0:
            continue
        bucket = bar["open_time_ms"] - (bar["open_time_ms"] % target)
        if bucket not in groups:
            groups[bucket] = []
            order.append(bucket)
        groups[bucket].append(bar)
    out = []
    for bucket in order:
        children = groups[bucket]
        if len(children) != width:
            continue
        children.sort(key=lambda item: item["open_time_ms"])
        if any(children[i + 1]["open_time_ms"] - children[i]["open_time_ms"] != source for i in range(width - 1)):
            continue
        if children[0]["open_time_ms"] != bucket:
            continue
        out.append(make_bar(
            symbol=children[0]["symbol"],
            instrument=children[0]["instrument"],
            interval=target_interval,
            open_time_ms=children[0]["open_time_ms"],
            close_time_ms=children[-1]["close_time_ms"],
            open=children[0]["open"],
            high=max(item["high"] for item in children),
            low=min(item["low"] for item in children),
            close=children[-1]["close"],
            volume=None if any(item.get("volume") is None for item in children) else sum(item["volume"] for item in children),
            provider=children[0]["provider"],
            source_type=children[0]["source_type"],
            quote_semantics=children[0]["quote_semantics"],
            retrieved_at_ms=children[-1]["retrieved_at_ms"],
            complete=True,
            fresh=False,
        ))
    return out
