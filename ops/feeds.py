"""Free market feeds. No API keys. No synthetic prices."""

import json
import lzma
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from ops.bars import drop_forming, interval_ms, make_bar
from ops.sessions import gold_market_open

BINANCE = "https://data-api.binance.vision/api/v3/klines"
XAUS_CHART = "https://xaus.com/api/v1/chart"
XAUS_INTRADAY = "https://xaus.com/api/v1/intraday"
XAUS_SPOT = "https://xaus.com/api/v1/spot"
DUKA = "https://datafeed.dukascopy.com/datafeed/XAUUSD"
USER_AGENT = "aureon-paper-desk"


def _blocked_feed(block, **extra):
    out = {
        "ok": False,
        "bars": [],
        "ticks": [],
        "price": None,
        "reason": "commercial_use_unverified",
        "rights_status": (block or {}).get("rights_status"),
        "message": (block or {}).get("message"),
        "source_reachable": "not_checked",
        "feed_freshness": "not_applicable",
    }
    out.update(extra)
    return out


def _get(url, timeout=20, attempts=3):
    from ops.data_rights import RightsDenied, refuse_url

    blocked = refuse_url(url)
    if blocked:
        raise RightsDenied(blocked)
    delay = 0.4
    last = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code == 429 and attempt + 1 < attempts:
                time.sleep(delay)
                delay = min(delay * 2, 8)
                continue
            body = exc.read()
            return exc.code, body
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(delay)
                delay = min(delay * 2, 8)
                continue
            raise last
    raise last


def _fetch(url, timeout=20, attempts=3):
    from ops.data_rights import RightsDenied

    try:
        return _get(url, timeout=timeout, attempts=attempts), None
    except RightsDenied as exc:
        return None, exc.block


def _binance_rows(symbol, interval, start_ms=None, end_ms=None, limit=1000, timeout=20, attempts=3):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    if end_ms is not None:
        params["endTime"] = int(end_ms)
    got, blocked = _fetch(BINANCE + "?" + urllib.parse.urlencode(params), timeout=timeout, attempts=attempts)
    if blocked:
        return _blocked_feed(blocked)
    status, raw = got
    if status == 429:
        return {"ok": False, "reason": "rate_limited", "bars": []}
    if status != 200:
        return {"ok": False, "reason": f"http_{status}", "bars": []}
    return {"ok": True, "rows": json.loads(raw.decode())}


def binance_bars(symbol, interval, start_ms, end_ms, now_ms=None, timeout=20, attempts=3):
    """Completed Binance spot klines. The forming candle is omitted."""
    if symbol not in {"BTCUSDT", "ETHUSDT"}:
        return {"ok": False, "reason": "symbol_not_allowed", "bars": []}
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    step = interval_ms(interval)
    cursor = int(start_ms)
    collected = []
    pages = 0
    while cursor < end_ms and pages < 80:
        page = _binance_rows(symbol, interval, cursor, end_ms, 1000, timeout=timeout, attempts=attempts)
        pages += 1
        if not page.get("ok"):
            return {"ok": False, "reason": page.get("reason"), "bars": [], "pages": pages}
        rows = page["rows"]
        if not rows:
            break
        for row in rows:
            open_ms = int(row[0])
            close_ms = int(row[6])
            if open_ms < start_ms or close_ms > end_ms or close_ms > now_ms:
                continue
            collected.append(make_bar(
                symbol=symbol,
                instrument=symbol,
                interval=interval,
                open_time_ms=open_ms,
                close_time_ms=close_ms,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                provider="binance-public",
                source_type="spot_kline",
                quote_semantics="last_trade",
                retrieved_at_ms=now_ms,
                complete=True,
                fresh=now_ms - close_ms <= 2 * step,
            ))
        nxt = int(rows[-1][0]) + 1
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(0.05)
    unique = {bar["open_time_ms"]: bar for bar in collected}
    ordered = [unique[key] for key in sorted(unique)]
    kept, dropped = drop_forming(ordered, now_ms)
    return {"ok": True, "bars": kept, "dropped_forming": dropped, "pages": pages, "provider": "binance-public"}


def _chart_range(interval):
    return {"15m": ("1mo", "15m"), "1h": ("1y", "1h"), "1d": ("5y", "1d")}.get(interval)


def xaus_chart(interval, now_ms=None, timeout=30, attempts=3):
    """XAUUSD chart OHLC from xaus.com /api/v1/chart.

    The chart feed returns o/h/l/c/v with data_state.source upstream. That is
    not verified here as an exchange print, a bid/ask, or an execution price.
    Volume is kept only when the payload sends it. The unaligned live tail is dropped.
    """
    spec = _chart_range(interval)
    if spec is None:
        return {"ok": False, "reason": "interval_not_available", "bars": []}
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    step = interval_ms(interval)
    query = urllib.parse.urlencode({"symbol": "xau", "range": spec[0], "interval": spec[1]})
    got, blocked = _fetch(XAUS_CHART + "?" + query, timeout=timeout, attempts=attempts)
    if blocked:
        return _blocked_feed(blocked, provider="xaus.com")
    status, raw = got
    if status != 200:
        return {"ok": False, "reason": f"http_{status}", "bars": [], "provider": "xaus.com"}
    payload = json.loads(raw.decode())
    state = payload.get("data_state") or {}
    bars = []
    partial = 0
    for point in payload.get("points") or []:
        open_ms = int(point["t"]) * 1000 if int(point["t"]) < 10_000_000_000 else int(point["t"])
        if open_ms % step != 0:
            partial += 1
            continue
        close_ms = open_ms + step - 1
        if close_ms > now_ms:
            partial += 1
            continue
        bar = make_bar(
            symbol="XAUUSD",
            instrument="XAUUSD_SPOT",
            interval=interval,
            open_time_ms=open_ms,
            close_time_ms=close_ms,
            open=point.get("o"),
            high=point.get("h"),
            low=point.get("l"),
            close=point.get("c"),
            volume=point.get("v"),
            provider="xaus.com",
            source_type="chart_ohlc",
            quote_semantics="ohlc_not_bid_ask",
            retrieved_at_ms=now_ms,
            complete=True,
            fresh=now_ms - close_ms <= 2 * step and gold_market_open(datetime.fromtimestamp(now_ms / 1000, timezone.utc)),
        )
        if bar["open"] is None:
            partial += 1
            continue
        bars.append(bar)
    kept, dropped = drop_forming(bars, now_ms)
    return {
        "ok": True,
        "bars": kept,
        "partial_dropped": partial + dropped,
        "data_state": state,
        "provider": "xaus.com",
        "quote_semantics": "ohlc_not_bid_ask",
        "range": spec[0],
    }


def aggregate_spot_samples(points, interval, now_ms):
    """Build a sampled indicative reference bar from five-minute spot prints.

    XAUS /intraday is a recorded spot series, not native OHLC. A 15-minute bar
    needs all 3 prints and a 1-hour bar needs all 12. A missing, conflicting,
    duplicated or disordered print drops the interval. No high, low or open is
    filled in, and the source's missing volume is not replaced with a count.
    Prints are not split into 1-minute or 3-minute bars.
    """
    step = interval_ms(interval)
    sample_ms = 300_000
    tolerance = 15_000
    if interval not in {"15m", "1h"} or step < sample_ms or step % sample_ms != 0:
        return []
    expected = step // sample_ms
    buckets = {}
    for point in points or []:
        raw = point.get("p")
        if raw is None:
            continue
        try:
            price = float(raw)
            stamp = int(point["t"])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        open_stamp = stamp if stamp > 10_000_000_000 else stamp * 1000
        bucket = open_stamp - (open_stamp % step)
        seen = buckets.setdefault(bucket, {})
        previous = seen.get(open_stamp)
        if previous is not None and previous != price:
            seen["conflict"] = True
            continue
        seen[open_stamp] = price
    bars = []
    for open_ms in sorted(buckets):
        seen = buckets[open_ms]
        if seen.get("conflict"):
            continue
        ordered = sorted((ts, px) for ts, px in seen.items() if isinstance(ts, int))
        if len(ordered) != expected:
            continue
        spaced = all(
            sample_ms - tolerance <= ordered[index + 1][0] - ordered[index][0] <= sample_ms + tolerance
            for index in range(len(ordered) - 1)
        )
        if not spaced:
            continue
        if ordered[-1][0] >= open_ms + step or ordered[0][0] < open_ms:
            continue
        prices = [px for _, px in ordered]
        close_ms = open_ms + step - 1
        if close_ms > now_ms:
            continue
        bars.append(make_bar(
            symbol="XAUUSD",
            instrument="XAUUSD_SPOT",
            interval=interval,
            open_time_ms=open_ms,
            close_time_ms=close_ms,
            open=ordered[0][1],
            high=max(prices),
            low=min(prices),
            close=ordered[-1][1],
            volume=None,
            provider="xaus.com",
            source_type="spot_sample",
            quote_semantics="spot_sample_not_bid_ask",
            retrieved_at_ms=now_ms,
            complete=True,
            fresh=now_ms - close_ms <= 2 * step and gold_market_open(datetime.fromtimestamp(now_ms / 1000, timezone.utc)),
        ))
    return bars


def xaus_spot_bars(interval="1h", now_ms=None, timeout=8, attempts=1):
    """Derived bars from XAUS five-minute spot samples. Not the Yahoo chart and not a one-minute series."""
    if interval in {"1m", "3m"}:
        return {
            "ok": False,
            "reason": "sample_is_5m",
            "bars": [],
            "provider": "xaus.com",
            "note": "The spot sampler is about five minutes. A 1-minute or 3-minute bar was not created.",
        }
    if interval not in {"15m", "1h"}:
        return {"ok": False, "reason": "interval_not_available", "bars": [], "provider": "xaus.com"}
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    got, blocked = _fetch(XAUS_INTRADAY + "?hours=48", timeout=timeout, attempts=attempts)
    if blocked:
        return _blocked_feed(blocked, provider="xaus.com")
    status, raw = got
    if status != 200:
        return {"ok": False, "reason": f"http_{status}", "bars": [], "provider": "xaus.com"}
    payload = json.loads(raw.decode())
    bars = aggregate_spot_samples(payload.get("points") or [], interval, now_ms)
    return {
        "ok": bool(bars),
        "bars": bars,
        "provider": "xaus.com",
        "quote_semantics": "spot_sample_not_bid_ask",
        "source": "xaus-intraday-spot-sample",
        "note": "Built only from complete five-minute spot samples. A sampled indicative reference bar, not exchange OHLC, not a bid or ask, and not an execution price.",
        "samples": payload.get("count"),
    }


def xaus_spot(now_ms=None):
    """Indicative mid. Never a candle and never a bid or ask."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    got, blocked = _fetch(XAUS_SPOT + "?compact=1", timeout=15)
    if blocked:
        return _blocked_feed(blocked, quote_semantics="indicative_mid", symbol="XAUUSD")
    status, raw = got
    if status != 200:
        return {"ok": False, "reason": f"http_{status}", "quote_semantics": "indicative_mid"}
    payload = json.loads(raw.decode())
    updated = payload.get("updated_at")
    state = payload.get("data_state") or {}
    age = state.get("age_seconds")
    moment = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    fresh = state.get("status") == "fresh" and isinstance(age, (int, float)) and age <= 15 * 60 and gold_market_open(moment)
    return {
        "ok": payload.get("spot_usd_oz") is not None,
        "symbol": "XAUUSD",
        "instrument": "XAUUSD_SPOT",
        "price": payload.get("spot_usd_oz"),
        "updated_at": updated,
        "source": state.get("source") or payload.get("price_source"),
        "quote_semantics": "indicative_mid",
        "kind": "indicative_spot",
        "fresh": fresh,
        "market_open": gold_market_open(moment),
        "not_a_candle": True,
        "not_bid_ask": True,
    }


def decode_dukascopy_bi5(payload, hour_open_ms, point_scale=1000.0):
    """Decode one Dukascopy tick hour. Scale is the feed's point size, not a price guess."""
    raw = lzma.decompress(payload)
    ticks = []
    for offset in range(0, len(raw) - 19, 20):
        millis, ask, bid, ask_vol, bid_vol = struct.unpack(">IIIff", raw[offset:offset + 20])
        ticks.append({
            "time_ms": hour_open_ms + millis,
            "ask": ask / point_scale,
            "bid": bid / point_scale,
            "ask_volume": ask_vol,
            "bid_volume": bid_vol,
        })
    return ticks


def decode_dukascopy_m1(payload, day_open_ms, point_scale=1000.0):
    """Decode one UTC day's Dukascopy 1-minute bid or ask file.

    Record layout is big-endian seconds, open, close, low, high, volume.
    Open is never copied from close. A short or crossed record is rejected.
    """
    raw = lzma.decompress(payload)
    if not raw:
        return []
    if len(raw) % 24 != 0:
        raise ValueError("candle_record_length")
    rows = []
    for offset in range(0, len(raw), 24):
        second, open_i, close_i, low_i, high_i, volume = struct.unpack(">IIIIIf", raw[offset:offset + 24])
        open_ = open_i / point_scale
        close = close_i / point_scale
        low = low_i / point_scale
        high = high_i / point_scale
        if min(open_, high, low, close) <= 0 or high < low or open_ > high or open_ < low or close > high or close < low:
            continue
        if second < 0 or second >= 86400 or second % 60 != 0:
            continue
        rows.append({
            "time_ms": int(day_open_ms) + int(second) * 1000,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
    return rows


def dukascopy_hour(year, month_index, day, hour, timeout=20):
    """month_index is Dukascopy's zero-based month. HTTP 429 stays unavailable."""
    url = f"{DUKA}/{year}/{month_index:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
    got, blocked = _fetch(url, timeout=timeout, attempts=2)
    if blocked:
        return _blocked_feed(blocked, provider="dukascopy")
    status, raw = got
    if status == 429:
        return {"ok": False, "reason": "provider_throttled", "provider": "dukascopy"}
    if status != 200 or not raw or raw[:1] == b"{":
        return {"ok": False, "reason": f"http_{status}", "provider": "dukascopy"}
    hour_open = datetime(year, month_index + 1, day, hour, tzinfo=timezone.utc)
    try:
        ticks = decode_dukascopy_bi5(raw, int(hour_open.timestamp() * 1000))
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "provider": "dukascopy"}
    return {"ok": True, "ticks": ticks, "provider": "dukascopy", "quote_semantics": "bid_ask", "url": url}
