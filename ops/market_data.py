"""Provider-independent candle store.

Real vendor ingestion stays closed unless data_rights marks that source
approved. Fixture rows can exercise persistence. They are never research
evidence. Missing candles are reported, not invented. The 4h holdout is not
read or opened here.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ops.bars import interval_ms
from ops.data_rights import ingestion_allowed

ARCHIVE_US_START = 1735689600000000  # 2025-01-01T00:00:00Z in microseconds
ARCHIVE_MS_START = 1735689600000
QUOTE_DIVERGENCE_LIMIT = Decimal("0.0008")
COST_BPS_PER_SIDE = 11
SLIPPAGE_BPS = 2
STRESS_COST_MULTIPLE = 2
HOLDOUT_START = "2026-01-22T00:00:00+00:00"
RESEARCH_REQUIREMENTS = (
    "immutable_strategy_version",
    "dataset_fingerprint",
    "chronological_training_and_validation",
    "untouched_holdout",
    "walk_forward",
    "embargo",
    "no_lookahead",
    "trading_cost_assumptions",
    "stress_costs",
    "ambiguous_exit_treatment",
    "multiple_testing_safeguards",
    "sample_size_and_uncertainty",
)


class MarketDataError(PermissionError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _decimal(value):
    if isinstance(value, bool) or value is None:
        raise InvalidOperation
    return Decimal(str(value))


def to_milliseconds(value, unit):
    if isinstance(value, bool):
        raise MarketDataError("timestamp_unit_mismatch")
    try:
        raw = int(value)
    except (TypeError, ValueError):
        raise MarketDataError("timestamp_unit_mismatch")
    if unit == "ms":
        if raw >= 10**14:
            raise MarketDataError("timestamp_unit_mismatch")
        return raw
    if unit == "us":
        if raw < 10**14 or raw % 1000:
            raise MarketDataError("timestamp_unit_mismatch")
        return raw // 1000
    raise MarketDataError("timestamp_unit_mismatch")


def archive_timestamp_ok(open_time, unit, source_format):
    """Binance spot archives switch to microseconds on 2025-01-01. REST stays milliseconds unless asked."""
    if source_format != "binance_spot_archive":
        return True
    if unit == "us":
        return int(open_time) >= ARCHIVE_US_START
    if unit == "ms":
        return int(open_time) < ARCHIVE_MS_START
    return False


def normalise_candle(raw, *, now_ms):
    provider = raw.get("provider")
    instrument = raw.get("instrument")
    native = raw.get("native_interval")
    requested = raw.get("interval") or native
    if native == "5m" or requested == "5m":
        raise MarketDataError("unexpected_interval_substitution")
    if native != requested:
        raise MarketDataError("unexpected_interval_substitution")
    if instrument == "XAUUSD" and native in ("1m", "3m"):
        raise MarketDataError("xau_minute_unlicensed")
    if not archive_timestamp_ok(raw.get("open_time"), raw.get("timestamp_unit"), raw.get("source_format")):
        raise MarketDataError("timestamp_unit_mismatch")
    open_ms = to_milliseconds(raw.get("open_time"), raw.get("timestamp_unit"))
    close_ms = to_milliseconds(raw.get("close_time"), raw.get("timestamp_unit"))
    step = interval_ms(native)
    if open_ms % step != 0 or close_ms - open_ms + 1 != step:
        raise MarketDataError("interval_alignment")
    if open_ms > now_ms or close_ms >= now_ms:
        raise MarketDataError("future_or_incomplete")
    if raw.get("complete") is not True:
        raise MarketDataError("incomplete_candle")
    try:
        prices = {name: _decimal(raw.get(name)) for name in ("open", "high", "low", "close")}
    except InvalidOperation:
        raise MarketDataError("invalid_ohlc")
    if min(prices.values()) <= 0:
        raise MarketDataError("invalid_ohlc")
    if prices["high"] < prices["low"] or prices["open"] > prices["high"] or prices["open"] < prices["low"]:
        raise MarketDataError("invalid_ohlc")
    if prices["close"] > prices["high"] or prices["close"] < prices["low"]:
        raise MarketDataError("invalid_ohlc")
    volume = raw.get("volume", None)
    quote_volume = raw.get("quote_volume", None)
    trades = raw.get("trade_count", None)
    if volume is not None:
        try:
            volume_value = _decimal(volume)
        except InvalidOperation:
            raise MarketDataError("invalid_volume")
        if volume_value < 0:
            raise MarketDataError("invalid_volume")
        volume = format(volume_value, "f")
    if quote_volume is not None:
        try:
            quote_value = _decimal(quote_volume)
        except InvalidOperation:
            raise MarketDataError("invalid_volume")
        if quote_value < 0:
            raise MarketDataError("invalid_volume")
        quote_volume = format(quote_value, "f")
    if trades is not None:
        if isinstance(trades, bool) or not isinstance(trades, int) or trades < 0:
            raise MarketDataError("invalid_trade_count")
    retrieved = raw.get("retrieved_at_ms")
    if isinstance(retrieved, bool) or not isinstance(retrieved, int):
        raise MarketDataError("missing_retrieved_timestamp")
    if retrieved > now_ms:
        raise MarketDataError("future_or_incomplete")
    candle = {
        "provider": provider,
        "source_id": raw.get("source_id"),
        "instrument": instrument,
        "market_type": raw.get("market_type"),
        "native_interval": native,
        "open_time_ms": open_ms,
        "close_time_ms": close_ms,
        "open": format(prices["open"], "f"),
        "high": format(prices["high"], "f"),
        "low": format(prices["low"], "f"),
        "close": format(prices["close"], "f"),
        "volume": volume,
        "quote_volume": quote_volume,
        "trade_count": trades,
        "timestamp_unit": raw.get("timestamp_unit"),
        "source_record_id": raw.get("source_record_id"),
        "retrieved_at_ms": retrieved,
        "complete": True,
        "rights_id": raw.get("rights_id"),
        "dataset_id": raw.get("dataset_id"),
        "source_format": raw.get("source_format"),
    }
    return candle


def candle_fingerprint(candle):
    body = json.dumps(candle, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def backoff(attempt, *, status=None, retry_after=None):
    if status == 418:
        return {"retry": False, "reason": "ip_ban", "wait_seconds": None}
    if status == 429:
        try:
            wait = float(retry_after)
        except (TypeError, ValueError):
            return {"retry": False, "reason": "missing_retry_after", "wait_seconds": None}
        if wait < 0 or wait > 120:
            return {"retry": False, "reason": "retry_after_out_of_bounds", "wait_seconds": None}
        return {"retry": True, "reason": "retry_after", "wait_seconds": wait}
    if attempt >= 5:
        return {"retry": False, "reason": "backoff_exhausted", "wait_seconds": None}
    return {"retry": True, "reason": "bounded_backoff", "wait_seconds": min(2 ** attempt, 32)}


def _gaps(candles, interval):
    step = interval_ms(interval)
    missing = 0
    ordered = sorted(candles, key=lambda row: row["open_time_ms"])
    for left, right in zip(ordered, ordered[1:]):
        delta = right["open_time_ms"] - left["open_time_ms"]
        if delta > step:
            missing += (delta // step) - 1
        elif delta == 0:
            continue
        elif delta != step:
            missing += 1
    return missing


class DatasetStore:
    def __init__(self, root):
        self.root = Path(root)

    def dataset_dir(self, dataset_id):
        return self.root / "datasets" / dataset_id

    def ingest(self, raw_rows, *, dataset_id, rights_id, purpose, provider, symbol, interval, now_ms, source_format):
        decision = ingestion_allowed(rights_id, purpose)
        if not decision["allowed"]:
            return {"ok": False, "reason": decision["reason"], "status": decision["status"], "accepted": 0, "wrote": False}
        if not raw_rows:
            return {"ok": False, "reason": "empty_batch", "status": decision["status"], "accepted": 0, "wrote": False}
        folder = self.dataset_dir(dataset_id)
        folder.mkdir(parents=True, exist_ok=True)
        existing = self._read_candles(folder)
        accepted = list(existing)
        known = {(row["provider"], row["instrument"], row["native_interval"], row["open_time_ms"]): row for row in accepted}
        rejected = []
        duplicates = 0
        corrections = []
        for raw in raw_rows:
            raw = dict(raw)
            raw["rights_id"] = rights_id
            raw["dataset_id"] = dataset_id
            if raw.get("provider") != provider or raw.get("instrument") != symbol or raw.get("native_interval") != interval:
                rejected.append("identity_mismatch")
                continue
            if raw.get("rights_id") != rights_id:
                rejected.append("rights_mismatch")
                continue
            try:
                candle = normalise_candle(raw, now_ms=now_ms)
            except MarketDataError as exc:
                rejected.append(exc.reason)
                continue
            if candle["rights_id"] != "deterministic_fixture":
                rejected.append("rights_unconfirmed")
                continue
            identity = (candle["provider"], candle["instrument"], candle["native_interval"], candle["open_time_ms"])
            previous = known.get(identity)
            if previous is None:
                accepted.append(candle)
                known[identity] = candle
            elif candle_fingerprint(previous) == candle_fingerprint(candle):
                duplicates += 1
            else:
                corrections.append({
                    "open_time_ms": candle["open_time_ms"],
                    "original_sha256": candle_fingerprint(previous),
                    "replacement_sha256": candle_fingerprint(candle),
                    "applied": False,
                })
                rejected.append("source_revision_not_applied")
        accepted.sort(key=lambda row: row["open_time_ms"])
        payload = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in accepted)
        data_path = folder / "candles.jsonl"
        temporary = folder / "candles.jsonl.tmp"
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, data_path)
        digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
        if corrections:
            with (folder / "corrections.jsonl").open("a", encoding="utf-8") as handle:
                for row in corrections:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
        state_path = folder / "state.json"
        previous_state = {}
        if state_path.exists():
            previous_state = json.loads(state_path.read_text(encoding="utf-8"))
        cursor = accepted[-1]["open_time_ms"] if accepted else previous_state.get("cursor_ms")
        state = {"cursor_ms": cursor, "batches": int(previous_state.get("batches") or 0) + 1}
        state_path.write_text(json.dumps(state), encoding="utf-8")
        gaps = _gaps(accepted, interval) if accepted else 0
        if not accepted:
            validation = "fail"
        elif any(reason != "source_revision_not_applied" for reason in rejected):
            validation = "rejected_rows"
        elif gaps:
            validation = "gaps_reported"
        elif corrections:
            validation = "correction_withheld"
        else:
            validation = "pass"
        manifest = {
            "dataset_id": dataset_id,
            "provider": provider,
            "symbol": symbol,
            "interval": interval,
            "coverage_start_ms": accepted[0]["open_time_ms"] if accepted else None,
            "coverage_end_ms": accepted[-1]["close_time_ms"] if accepted else None,
            "accepted": len(accepted),
            "rejected": len(rejected),
            "gaps": gaps,
            "duplicates": duplicates,
            "source_format": source_format,
            "timestamp_convention": "milliseconds",
            "sha256": digest,
            "retrieved_start_ms": min(row["retrieved_at_ms"] for row in accepted) if accepted else None,
            "retrieved_end_ms": max(row["retrieved_at_ms"] for row in accepted) if accepted else None,
            "rights_id": rights_id,
            "rights_status": "fixture_only",
            "validation": validation,
            "corrections": corrections,
            "research_eligible": False,
            "evidence_class": "fixture",
            "holdout_opened": False,
            "rejected_reasons": rejected,
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return {"ok": True, "reason": "fixture_stored", "manifest": manifest, "wrote": True}

    def _read_candles(self, folder):
        path = folder / "candles.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def load_verified(self, dataset_id):
        folder = self.dataset_dir(dataset_id)
        manifest_path = folder / "manifest.json"
        data_path = folder / "candles.jsonl"
        if not manifest_path.exists() or not data_path.exists():
            return {"ok": False, "reason": "missing_dataset"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
        if digest != manifest.get("sha256"):
            return {"ok": False, "reason": "checksum_mismatch"}
        if manifest.get("research_eligible") or manifest.get("evidence_class") != "fixture":
            return {"ok": False, "reason": "fixture_promotion_blocked", "candles": []}
        return {"ok": True, "reason": "fixture_only", "manifest": manifest, "candles": self._read_candles(folder)}


def storage_estimate():
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 31, tzinfo=timezone.utc)
    span_ms = int((end - start).total_seconds() * 1000)
    per_candle_bytes = 220
    intervals = ("1m", "3m", "15m", "1h")
    rows = []
    total_bytes = 0
    total_requests = 0
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for interval in intervals:
            count = span_ms // interval_ms(interval)
            size = count * per_candle_bytes
            requests = (count + 999) // 1000
            total_bytes += size
            total_requests += requests
            rows.append({
                "market": symbol,
                "timeframe": interval,
                "candles": count,
                "bytes": size,
                "requests_at_1000": requests,
                "collected": False,
            })
    return {
        "assumption": "Native candles from 2023-01-01 to 2026-10-31, about 220 bytes each, page size 1000. Not downloaded.",
        "rows": rows,
        "total_bytes": total_bytes,
        "total_requests": total_requests,
        "collected_bytes": 0,
    }


def holdout_status():
    return {
        "opened": False,
        "start": HOLDOUT_START,
        "dataset": "Existing BTCUSDT and ETHUSDT 4h files. Not read by this module.",
        "reason": "The final 20 percent beginning 2026-01-22 stays sealed. Desk timeframes are not inferred from it.",
    }


def open_holdout():
    raise MarketDataError("holdout_sealed")


def promote_from_dataset(_manifest):
    raise MarketDataError("promotion_not_authorised")


def retained_file_notes():
    root = Path(__file__).resolve().parents[1] / "research" / "history"
    notes = []
    for name in ("BTCUSDT-4h.csv", "ETHUSDT-4h.csv", "XAUUSD-1h.jsonl", "XAUUSD-1h.manifest.json"):
        path = root / name
        if not path.exists():
            continue
        notes.append({
            "name": name,
            "bytes": path.stat().st_size,
            "read_for_this_review": False,
            "research_cleared": False,
            "desk_substitute": False,
        })
    return notes


def public_report():
    from ops.qualification import summary

    estimate = storage_estimate()
    disk = shutil.disk_usage(Path(__file__).resolve().parents[1])
    qual = summary()
    return {
        "headline": "No source is approved for commercial historical research. Nothing new was downloaded.",
        "reviewed_on": "2026-11-03",
        "coverage": __import__("ops.data_rights", fromlist=["coverage_rows"]).coverage_rows(),
        "sources": __import__("ops.data_rights", fromlist=["register_public"]).register_public(),
        "storage": estimate,
        "disk_free_bytes": disk.free,
        "disk_total_bytes": disk.total,
        "collected_bytes": 0,
        "collector_running": False,
        "forward_collection": "inactive",
        "holdout": holdout_status(),
        "retained_files": retained_file_notes(),
        "strategy": {
            "approved_for_paper": qual["approved_for_paper"],
            "promoted_by_this_change": False,
        },
        "quote_divergence_limit": "0.0008",
        "research": research_readiness(),
    }


def research_readiness(manifest=None):
    eligible = bool(manifest and manifest.get("research_eligible") is True and manifest.get("rights_status") == "approved")
    return {
        "search_authorised": False,
        "dataset_eligible": eligible,
        "reason": "no_rights_cleared_independent_dataset",
        "requirements": list(RESEARCH_REQUIREMENTS),
        "costs": {"bps_per_side": COST_BPS_PER_SIDE, "slippage_bps": SLIPPAGE_BPS, "stress_multiple": STRESS_COST_MULTIPLE},
        "quote_divergence_limit": str(QUOTE_DIVERGENCE_LIMIT),
        "holdout": holdout_status(),
    }
