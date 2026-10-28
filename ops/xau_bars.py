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
