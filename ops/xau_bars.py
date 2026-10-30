"""Build XAUUSD hour bars from separate Dukascopy bid and ask minutes.

Missing minutes are not invented. Bid is not copied into ask.
"""

from ops.bars import make_bar

HOUR_MS = 60 * 60 * 1000
MINUTE_MS = 60 * 1000


def _index(rows):
    found = {}
    duplicate = invalid = 0
    for row in rows:
        stamp = row.get("time_ms")
        if stamp in found:
            duplicate += 1
            found[stamp] = None
            continue
        if row.get("open") is None or row.get("high") is None or row.get("low") is None or row.get("close") is None:
            invalid += 1
            continue
        found[stamp] = row
    return found, duplicate, invalid


def hours_from_minutes(bid_rows, ask_rows, retrieved_at_ms=0):
    """One hour exists only when both sides have all 60 minutes."""
    bid, bid_dups, bid_invalid = _index(bid_rows)
    ask, ask_dups, ask_invalid = _index(ask_rows)
    stamps = set(bid) | set(ask)
    hours = sorted({stamp - (stamp % HOUR_MS) for stamp in stamps})
    bars = []
    skipped = 0
    for hour in hours:
        slots = [hour + minute * MINUTE_MS for minute in range(60)]
        if any(bid.get(slot) is None or ask.get(slot) is None for slot in slots):
            skipped += 1
            continue
        bids = [bid[slot] for slot in slots]
        asks = [ask[slot] for slot in slots]
        crossed = 0
        for left, right in zip(bids, asks):
            if right["open"] < left["open"] or right["close"] < left["close"]:
                crossed += 1
        if crossed:
            skipped += 1
            continue
        bars.append(make_bar(
            symbol="XAUUSD",
            instrument="XAUUSD_DUKASCOPY",
            interval="1h",
            open_time_ms=hour,
            close_time_ms=hour + HOUR_MS - 1,
            open=bids[0]["open"],
            high=max(item["high"] for item in bids),
            low=min(item["low"] for item in bids),
            close=bids[-1]["close"],
            volume=sum(item.get("volume") or 0 for item in bids),
            bid_open=bids[0]["open"],
            bid_high=max(item["high"] for item in bids),
            bid_low=min(item["low"] for item in bids),
            bid_close=bids[-1]["close"],
            ask_open=asks[0]["open"],
            ask_high=max(item["high"] for item in asks),
            ask_low=min(item["low"] for item in asks),
            ask_close=asks[-1]["close"],
            provider="dukascopy",
            source_type="m1_bid_ask",
            quote_semantics="dukascopy_xauusd_bid_ask",
            retrieved_at_ms=retrieved_at_ms,
            complete=True,
            fresh=False,
        ))
    return {
        "bars": bars,
        "skipped_hours": skipped,
        "duplicate_minutes": bid_dups + ask_dups,
        "invalid_minutes": bid_invalid + ask_invalid,
    }


def minutes_from_sides(bid_rows, ask_rows, retrieved_at_ms, now_ms):
    """One minute exists only when that exact minute has both a bid and an ask. Nothing is filled in."""
    bid, _, _ = _index(bid_rows)
    ask, _, _ = _index(ask_rows)
    bars = []
    for stamp in sorted(set(bid) & set(ask)):
        left, right = bid.get(stamp), ask.get(stamp)
        if left is None or right is None:
            continue
        if right["open"] < left["open"] or right["close"] < left["close"]:
            continue
        close_ms = stamp + MINUTE_MS - 1
        if close_ms > now_ms:
            continue
        bars.append(make_bar(
            symbol="XAUUSD",
            instrument="XAUUSD_DUKASCOPY",
            interval="1m",
            open_time_ms=stamp,
            close_time_ms=close_ms,
            open=left["open"],
            high=left["high"],
            low=left["low"],
            close=left["close"],
            volume=left.get("volume"),
            bid=left["close"],
            ask=right["close"],
            provider="dukascopy",
            source_type="m1_bid_ask",
            quote_semantics="dukascopy_xauusd_bid_ask",
            retrieved_at_ms=retrieved_at_ms,
            complete=True,
            fresh=0 <= now_ms - close_ms <= 2 * MINUTE_MS,
        ))
    return bars


def threes_from_minutes(minutes, now_ms):
    """A 3-minute bar exists only when three consecutive completed minutes are present."""
    by = {bar["open_time_ms"]: bar for bar in minutes or []}
    step = 3 * MINUTE_MS
    bars = []
    for start in sorted(by):
        if start % step != 0:
            continue
        slots = [by.get(start + offset * MINUTE_MS) for offset in range(3)]
        if any(slot is None for slot in slots):
            continue
        close_ms = start + step - 1
        if close_ms > now_ms:
            continue
        bars.append(make_bar(
            symbol="XAUUSD",
            instrument="XAUUSD_DUKASCOPY",
            interval="3m",
            open_time_ms=start,
            close_time_ms=close_ms,
            open=slots[0]["open"],
            high=max(slot["high"] for slot in slots),
            low=min(slot["low"] for slot in slots),
            close=slots[-1]["close"],
            volume=sum(slot.get("volume") or 0 for slot in slots),
            bid=slots[-1].get("bid"),
            ask=slots[-1].get("ask"),
            provider="dukascopy",
            source_type="m1_bid_ask",
            quote_semantics="dukascopy_xauusd_bid_ask",
            retrieved_at_ms=slots[-1].get("retrieved_at_ms") or 0,
            complete=True,
            fresh=all(slot.get("fresh") for slot in slots),
        ))
    return bars
