"""Account-private historical candles. Not a live exchange feed.

Rows stay under the signed-in account. Another account cannot read them.
Gold 1-minute and 3-minute stay refused. Nothing here is marked live.
"""

from __future__ import annotations

import csv
import io
import time

from ops.candle_book import CandleBook
from ops.signal_pipeline import SignalBook

INSTRUMENTS = {"BTCUSDT", "ETHUSDT", "XAUUSD"}
INTERVALS = {"1m", "3m", "15m", "1h"}
MAX_ROWS = 500


def _root(account_id):
    safe = "".join(ch for ch in str(account_id) if ch.isalnum())
    if not safe:
        return None
    from ops.paths import imports_root

    return imports_root(account_id)


def _book(account_id):
    root = _root(account_id)
    if root is None:
        return None
    return CandleBook(root)


def parse_csv(text):
    """Return row dicts or a field error. Does not store anything."""
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "reason": "empty", "fields": {"csv": "Paste a CSV with a header row."}}
    if len(text) > 400_000:
        return {"ok": False, "reason": "too_large", "fields": {"csv": "The file is too large."}}
    try:
        reader = csv.DictReader(io.StringIO(text.strip()))
    except csv.Error:
        return {"ok": False, "reason": "invalid_csv", "fields": {"csv": "The CSV could not be read."}}
    if not reader.fieldnames:
        return {"ok": False, "reason": "invalid_csv", "fields": {"csv": "A header row is required."}}
    required = {"instrument", "interval", "open_time_ms", "open", "high", "low", "close"}
    names = {name.strip() for name in reader.fieldnames if name}
    missing = sorted(required - names)
    if missing:
        return {"ok": False, "reason": "invalid_csv", "fields": {"csv": "Missing columns: " + ", ".join(missing) + "."}}
    rows = []
    errors = []
    for index, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            errors.append({"line": index, "reason": "too_many_rows"})
            break
        instrument = str(raw.get("instrument") or "").strip()
        interval = str(raw.get("interval") or "").strip()
        if instrument not in INSTRUMENTS:
            errors.append({"line": index, "field": "instrument", "reason": "unsupported_instrument"})
            continue
        if interval not in INTERVALS:
            errors.append({"line": index, "field": "interval", "reason": "unsupported_interval"})
            continue
        if instrument == "XAUUSD" and interval in {"1m", "3m"}:
            errors.append({"line": index, "field": "interval", "reason": "xau_minute_unlicensed"})
            continue
        rows.append({
            "instrument": instrument,
            "interval": interval,
            "open_time_ms": str(raw.get("open_time_ms") or "").strip(),
            "open": str(raw.get("open") or "").strip(),
            "high": str(raw.get("high") or "").strip(),
            "low": str(raw.get("low") or "").strip(),
            "close": str(raw.get("close") or "").strip(),
            "volume": str(raw.get("volume") or "").strip(),
        })
    if not rows and errors:
        return {"ok": False, "reason": errors[0]["reason"], "fields": {"csv": errors[0]["reason"]}, "errors": errors}
    return {"ok": True, "rows": rows, "errors": errors}


def import_rows(account_id, rows, *, now_ms=None):
    book = _book(account_id)
    if book is None:
        return {"ok": False, "reason": "unauthorized", "stored": 0, "live": False}
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    stored = 0
    duplicates = 0
    rejected = []
    for index, row in enumerate(rows or []):
        raw = {
            "provider": "user_provided",
            "source_id": "account_csv",
            "instrument": row.get("instrument"),
            "market_type": "user_historical",
            "native_interval": row.get("interval"),
            "interval": row.get("interval"),
            "open_time": row.get("open_time_ms"),
            "close_time": int(row["open_time_ms"]) + _step(row.get("interval")) - 1 if str(row.get("open_time_ms") or "").isdigit() else row.get("open_time_ms"),
            "timestamp_unit": "ms",
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "complete": True,
            "retrieved_at_ms": now_ms,
            "source_format": "user_csv",
            "rights_id": "user_provided",
            "dataset_id": "account_private",
        }
        if row.get("volume"):
            raw["volume"] = row["volume"]
        result = book.accept(raw, now_ms=now_ms)
        if result.get("stored"):
            stored += 1
        elif result.get("reason") == "duplicate":
            duplicates += 1
        else:
            rejected.append({"line": index + 1, "reason": result.get("reason") or "rejected"})
    history = _root(account_id) / "import_log.jsonl"
    record = {"stored": stored, "duplicates": duplicates, "rejected": len(rejected), "created_ms": now_ms, "live": False, "source": "user_provided"}
    with history.open("a", encoding="utf-8") as handle:
        import json
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return {
        "ok": True,
        "stored": stored,
        "duplicates": duplicates,
        "rejected": rejected,
        "live": False,
        "source": "user_provided_historical",
        "broker": False,
    }


def _step(interval):
    return {"1m": 60_000, "3m": 180_000, "15m": 900_000, "1h": 3_600_000}.get(interval or "", 0)


def history(account_id):
    root = _root(account_id)
    if root is None or not (root / "import_log.jsonl").is_file():
        return []
    import json
    rows = []
    for line in (root / "import_log.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def candles(account_id, instrument, interval):
    book = _book(account_id)
    if book is None:
        return []
    return book.history(instrument, interval)


def evaluate(account_id, instrument, interval, *, now_ms=None):
    """Run the deterministic pipeline on this account's imported candles only."""
    rows = candles(account_id, instrument, interval)
    if now_ms is None and rows:
        now_ms = max(int(row["close_time_ms"]) for row in rows)
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    root = _root(account_id)
    if root is None:
        return {"ok": False, "reason": "unauthorized", "live": False, "signal": False}
    shaped = []
    for row in rows:
        shaped.append({
            "open_time_ms": row["open_time_ms"],
            "close_time_ms": row["close_time_ms"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "complete": True,
            "source_id": "account_csv",
        })
    step = _step(interval)
    book = SignalBook(root / "signals")
    stored = book.evaluate(shaped, symbol=instrument, interval=interval, now_ms=now_ms, rights="user_provided", step_ms=step, account_id=account_id)
    row = stored.get("row") or {}
    row["live"] = False
    row["approved"] = False
    row["paper_eligible"] = False
    row["label"] = "user_provided_historical"
    return {"ok": True, "stored": stored.get("stored"), "row": row, "live": False, "broker": False}
