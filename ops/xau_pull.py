"""Download Dukascopy XAUUSD bid and ask minutes and build hour bars.

Raw files stay outside the git repository. The public datafeed is free and
needs no API key. Dukascopy's XAUUSD quote is not every broker's price.
Historical files are not a live feed.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ops.feeds import decode_dukascopy_m1
from ops.sessions import gold_market_open
from ops.xau_bars import hours_from_minutes

FEED = "https://datafeed.dukascopy.com/datafeed/XAUUSD"
POINT_SCALE = 1000.0
USER_AGENT = "aureon-paper-desk"


def day_url(day, side):
    return f"{FEED}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{side}_candles_min_1.bi5"


def fetch_day(day, side, cache, timeout=25, attempts=5):
    path = cache / side / f"{day.isoformat()}.bi5"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        payload = path.read_bytes()
        return {"ok": True, "body": payload, "cached": True, "sha256": hashlib.sha256(payload).hexdigest(), "url": day_url(day, side)}
    url = day_url(day, side)
    delay = 1.0
    last = "not_tried"
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            if not payload:
                return {"ok": False, "reason": "empty", "url": url, "sha256": None}
            path.write_bytes(payload)
            return {"ok": True, "body": payload, "cached": False, "sha256": hashlib.sha256(payload).hexdigest(), "url": url}
        except urllib.error.HTTPError as exc:
            last = f"http_{exc.code}"
            if exc.code == 404:
                return {"ok": False, "reason": last, "url": url, "sha256": None}
            time.sleep(delay)
            delay = min(delay * 2, 20)
        except Exception as exc:
            last = type(exc).__name__
            time.sleep(delay)
            delay = min(delay * 2, 20)
    return {"ok": False, "reason": last, "url": url, "sha256": None}


def _day_open_ms(day):
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def build_day(day, bid_body, ask_body, retrieved_at_ms):
    bid = decode_dukascopy_m1(bid_body, _day_open_ms(day), POINT_SCALE)
    ask = decode_dukascopy_m1(ask_body, _day_open_ms(day), POINT_SCALE)
    built = hours_from_minutes(bid, ask, retrieved_at_ms=retrieved_at_ms)
    kept = []
    closed = 0
    for bar in built["bars"]:
        moment = datetime.fromtimestamp(bar["open_time_ms"] / 1000, timezone.utc)
        if gold_market_open(moment):
            kept.append(bar)
        else:
            closed += 1
    built["bars"] = kept
    built["closed_hours"] = closed
    built["bid_minutes"] = len(bid)
    built["ask_minutes"] = len(ask)
    return built


def pull(start, end, cache, out_path, workers=3):
    from concurrent.futures import ThreadPoolExecutor
    cache = Path(cache)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    days = []
    day = start
    while day <= end:
        days.append(day)
        day += timedelta(days=1)

    def one(day):
        bid = fetch_day(day, "BID", cache)
        ask = fetch_day(day, "ASK", cache)
        row = {"day": day.isoformat(), "bid": {k: bid.get(k) for k in ("ok", "reason", "sha256", "url", "cached")}, "ask": {k: ask.get(k) for k in ("ok", "reason", "sha256", "url", "cached")}}
        built_bars = []
        if bid.get("ok") and ask.get("ok"):
            built = build_day(day, bid["body"], ask["body"], int(time.time() * 1000))
            row["hours"] = len(built["bars"])
            row["skipped_hours"] = built["skipped_hours"]
            row["closed_hours"] = built["closed_hours"]
            row["duplicate_minutes"] = built["duplicate_minutes"]
            row["invalid_minutes"] = built["invalid_minutes"]
            built_bars = built["bars"]
            print(f"{day} hours={len(built_bars)} skipped={built['skipped_hours']}", flush=True)
        else:
            row["hours"] = 0
            print(f"{day} missing bid={bid.get('reason')} ask={ask.get('reason')}", flush=True)
        return day, row, built_bars

    done = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, day) for day in days]
        for future in futures:
            day, row, built_bars = future.result()
            done[day] = (row, built_bars)
    manifest = {
        "provider": "dukascopy-public-datafeed",
        "instrument": "XAUUSD",
        "instrument_note": "Dukascopy XAUUSD bid and ask. Not a claim about any other broker's executable price.",
        "url_template": FEED + "/{year}/{month0}/{day}/{BID|ASK}_candles_min_1.bi5",
        "point_scale": POINT_SCALE,
        "record": "uint32 seconds, open, close, low, high, float32 volume",
        "live_feed": False,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": [],
    }
    bars = []
    for day in days:
        row, built_bars = done[day]
        manifest["days"].append(row)
        bars.extend(built_bars)
    lines = [json.dumps(bar, sort_keys=True) for bar in bars]
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    manifest["bars"] = len(bars)
    manifest["bars_sha256"] = digest
    manifest["bars_path"] = str(out_path)
    manifest_path = out_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps({"bars": len(bars), "sha256": digest, "manifest": str(manifest_path)}), flush=True)
    return manifest


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-10-28")
    parser.add_argument("--end", default="2026-10-27")
    parser.add_argument("--cache", default="/tmp/xau-m1")
    parser.add_argument("--out", default="/tmp/xau-h1.jsonl")
    args = parser.parse_args()
    pull(date.fromisoformat(args.start), date.fromisoformat(args.end), args.cache, args.out)


if __name__ == "__main__":
    main()
