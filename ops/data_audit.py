"""Fingerprint retained history. Missing desk series stay missing."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ops.bars import validate_series
from ops.history_store import ROOT, load_csv, load_jsonl, validate_bars
from ops.research_cli import _hash, _iso
from ops.worker import COVERAGE, pair_availability

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _span(bars):
    if not bars:
        return {"bars": 0}
    return {
        "bars": len(bars),
        "start": _iso(bars[0]["open_time_ms"]),
        "end": _iso(bars[-1]["close_time_ms"]),
        "first_open_time_ms": bars[0]["open_time_ms"],
        "last_close_time_ms": bars[-1]["close_time_ms"],
    }


def _series_report(path, bars, interval, kind):
    quality = validate_bars(bars, interval) if bars else {"ok": False, "bars": 0, "gaps": 0, "duplicates": 0, "invalid": 0, "forming": 0, "errors": ["missing"]}
    structural = validate_series(bars, interval) if bars else {"ok": False}
    repo = Path(__file__).resolve().parents[1]
    return {
        "path": str(path.relative_to(repo)) if path.is_relative_to(repo) else str(path),
        "kind": kind,
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "file_sha256": _file_sha(path) if path.exists() else None,
        "ohlc_sha256": _hash(bars) if bars else None,
        "interval": interval,
        "span": _span(bars),
        "quality": quality,
        "timestamp_step_ok": bool(structural.get("ok")),
        "gaps": quality.get("gaps"),
        "duplicates": quality.get("duplicates"),
        "invalid_ohlc_or_alignment": quality.get("invalid"),
        "unsorted": structural.get("unsorted"),
        "forming_bars_stored": quality.get("forming"),
        "synthetic": False,
        "used_for_approval": False,
    }


def retained_history():
    rows = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        path = ROOT / f"{symbol}-4h.csv"
        bars = load_csv(path, symbol, "4h", "binance-public", "last_trade") if path.exists() else []
        report = _series_report(path, bars, "4h", "retained_research_csv")
        report.update({
            "symbol": symbol,
            "provider": "binance-public",
            "quote_semantics": "last_trade",
            "desk_timeframe": False,
            "limitation": "Retained research file. 4h is not one of the twelve desk coverage pairs. The last 20 percent is the sealed holdout used by earlier 4h studies and must not be opened to choose a rule.",
        })
        rows.append(report)
    gold_path = ROOT / "XAUUSD-1h.jsonl"
    manifest_path = ROOT / "XAUUSD-1h.manifest.json"
    gold = load_jsonl(gold_path) if gold_path.exists() and gold_path.stat().st_size else []
    report = _series_report(gold_path, gold, "1h", "retained_research_jsonl")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    report.update({
        "symbol": "XAUUSD",
        "provider": (gold[0].get("provider") if gold else None) or "dukascopy",
        "quote_semantics": (gold[0].get("quote_semantics") if gold else None),
        "measured_bid_ask_fields": bool(gold) and all(key in gold[0] for key in ("bid_open", "ask_open", "bid_close", "ask_close")),
        "manifest_bars": manifest.get("bars"),
        "manifest_bars_sha256": manifest.get("bars_sha256"),
        "file_matches_manifest_sha256": bool(manifest.get("bars_sha256")) and report["file_sha256"] == manifest.get("bars_sha256"),
        "desk_timeframe": False,
        "limitation": "Short Dukascopy bid/ask hour file already used by the 4h-leader gold check. Weekend or closed-market steps can appear as gaps. It is not a fresh sample, not a 15m spot sample, and not a licence for 1m or 3m gold. A longer Gate 4 Dukascopy pull was not retained in this checkout.",
    })
    rows.append(report)
    return rows


def desk_matrix():
    """Twelve production pairs. None of them has a retained research candle file in this checkout."""
    availability = {(row["symbol"], row["interval"]): row for row in pair_availability()}
    retained = {("BTCUSDT", "4h"), ("ETHUSDT", "4h"), ("XAUUSD", "1h")}
    rows = []
    for symbol, interval in COVERAGE:
        live = availability[(symbol, interval)]
        rows.append({
            "symbol": symbol,
            "interval": interval,
            "retained_research_file": False,
            "classification": "missing_retained_history",
            "live_feed_class": live["status"],
            "live_feed": live["feed"],
            "reason": live["reason"],
            "can_support_a_new_holdout_study_from_files_in_this_checkout": False,
            "note": "A live scan is not a historical sample. Fixture and synthetic bars are not a source for approval.",
        })
    rows.append({
        "symbol": "BTCUSDT",
        "interval": "4h",
        "retained_research_file": ("BTCUSDT", "4h") in retained,
        "classification": "retained_not_a_desk_timeframe",
        "live_feed_class": "not_in_desk_coverage",
        "can_support_a_new_holdout_study_from_files_in_this_checkout": True,
        "note": "Usable for one pre-registered 4h study. Not a substitute for 1m, 3m, 15m or 1h history.",
    })
    rows.append({
        "symbol": "ETHUSDT",
        "interval": "4h",
        "retained_research_file": True,
        "classification": "retained_not_a_desk_timeframe",
        "live_feed_class": "not_in_desk_coverage",
        "can_support_a_new_holdout_study_from_files_in_this_checkout": True,
        "note": "Same file family as BTCUSDT 4h.",
    })
    return rows


def live_probe():
    """One public kline request. The rows are not stored and are not a research dataset."""
    from ops.feeds import _binance_rows

    probed = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for interval in ("15m", "1h"):
            try:
                page = _binance_rows(symbol, interval, limit=2, timeout=8, attempts=1)
            except Exception as exc:
                probed.append({"symbol": symbol, "interval": interval, "ok": False, "reason": type(exc).__name__, "stored": False})
                continue
            rows = page.get("rows") or []
            last = rows[-1] if rows else None
            probed.append({
                "symbol": symbol,
                "interval": interval,
                "ok": bool(page.get("ok")),
                "reason": page.get("reason"),
                "returned_rows": len(rows),
                "last_open_time": _iso(int(last[0])) if last else None,
                "stored": False,
                "note": "Freshness probe only. These candles were not written into research/history and were not scored.",
            })
    return probed


def build_audit(include_live_probe=False):
    history = retained_history()
    return {
        "generated_by": "ops/data_audit.py",
        "synthetic_data_can_approve": False,
        "paper_ledger_is_not_market_history": "data/paper/ledger.jsonl",
        "desk_pairs": list(COVERAGE),
        "retained": history,
        "coverage": desk_matrix(),
        "not_retained": [
            "BTCUSDT and ETHUSDT 1m, 3m, 15m and 1h candles used in earlier gates were downloaded for those studies and are not in this checkout.",
            "Gate 4 Dukascopy XAUUSD hours (about 6,264 bars, 2025-10-28 to 2026-10-27) are not in this checkout. The recorded Gate 4 result stands. This file is not re-fetched.",
            "XAUUSD 1m and 3m remain xau_minute_unlicensed. No 5m candle is split and no quote is stored as a candle.",
        ],
        "live_probe": live_probe() if include_live_probe else {"status": "not_requested", "stored": False},
    }


def write_audit(include_live_probe=False):
    report = build_audit(include_live_probe=include_live_probe)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "DATA_AUDIT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
