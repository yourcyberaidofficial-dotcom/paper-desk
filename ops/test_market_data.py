"""Rights gate, candle store and sealed-holdout checks. No vendor download."""

import json
from pathlib import Path

import pytest

from ops.data_rights import coverage_rows, ingestion_allowed, register_public
from ops.history import fetch_history
from ops.market_data import (
    ARCHIVE_MS_START,
    ARCHIVE_US_START,
    DatasetStore,
    MarketDataError,
    backoff,
    holdout_status,
    normalise_candle,
    open_holdout,
    promote_from_dataset,
    public_report,
    research_readiness,
)
from ops.qualification import summary


NOW = 1_739_145_600_000
STEP = 60_000


def _candle(open_ms, *, close="100", instrument="BTCUSDT", native="1m", unit="ms", source_format="fixture", volume="1"):
    return {
        "provider": "fixture",
        "source_id": "fixture-1",
        "instrument": instrument,
        "market_type": "spot",
        "native_interval": native,
        "interval": native,
        "open_time": open_ms if unit == "ms" else open_ms * 1000,
        "close_time": (open_ms + STEP * {"1m": 1, "3m": 3, "15m": 15, "1h": 60}[native] - 1) if unit == "ms" else (open_ms + STEP * {"1m": 1, "3m": 3, "15m": 15, "1h": 60}[native] - 1) * 1000,
        "open": "100",
        "high": "101",
        "low": "99",
        "close": close,
        "volume": volume,
        "quote_volume": None,
        "trade_count": None,
        "timestamp_unit": unit,
        "source_record_id": None,
        "retrieved_at_ms": NOW - 1000,
        "complete": True,
        "source_format": source_format,
    }


def test_register_has_no_commercial_approval():
    rows = register_public()
    assert rows
    assert all(row["commercial_use"] is False for row in rows)
    assert all(row["historical_research"] is False for row in rows)
    assert all(row["written_approval"] is None for row in rows)
    by_id = {row["id"]: row for row in rows}
    assert by_id["binance_vision_klines"]["status"] == "prohibited"
    assert by_id["binance_spot_rest_klines"]["status"] == "rights_unconfirmed"
    assert by_id["dukascopy_datafeed_bi5"]["status"] == "rights_unconfirmed"
    assert by_id["swissquote_public_bbo"]["status"] == "restricted"
    assert "CC BY-NC-SA" in by_id["binance_vision_klines"]["note"]
    assert ingestion_allowed("binance_vision_klines", "historical_research")["allowed"] is False
    assert ingestion_allowed("binance_spot_rest_klines", "historical_research")["reason"] == "rights_unconfirmed"
    assert ingestion_allowed("missing", "historical_research")["reason"] == "unknown_source"
    assert ingestion_allowed("deterministic_fixture", "historical_research")["allowed"] is False
    assert ingestion_allowed("deterministic_fixture", "fixture_test")["research_eligible"] is False


def test_coverage_is_twelve_rows_and_not_research_ready():
    rows = coverage_rows()
    assert len(rows) == 12
    assert [(row["market"], row["timeframe"]) for row in rows].count(("BTCUSDT", "1m")) == 1
    assert all(row["historical_retained"] is False and row["bar_count"] == 0 for row in rows)
    assert all(row["research_usable"] is False for row in rows)
    gold_minutes = [row for row in rows if row["market"] == "XAUUSD" and row["timeframe"] in ("1m", "3m")]
    assert [row["rights_status"] for row in gold_minutes] == ["xau_minute_unlicensed", "xau_minute_unlicensed"]


def test_vendor_ingestion_does_not_write(tmp_path):
    store = DatasetStore(tmp_path)
    for rights_id, purpose in (
        ("binance_vision_klines", "historical_research"),
        ("binance_spot_rest_klines", "historical_research"),
        ("dukascopy_datafeed_bi5", "historical_research"),
        ("swissquote_public_bbo", "historical_research"),
    ):
        result = store.ingest([_candle(NOW - STEP * 3)], dataset_id="should-not-exist", rights_id=rights_id, purpose=purpose, provider="fixture", symbol="BTCUSDT", interval="1m", now_ms=NOW, source_format="fixture")
        assert result["ok"] is False
        assert result["wrote"] is False
    assert not (tmp_path / "datasets").exists()


def test_history_fetch_is_blocked_before_network(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    with pytest.raises(PermissionError, match="rights_unconfirmed"):
        fetch_history("BTCUSDT", "1m", years=1)


def test_normalise_units_and_reject_bad_candles():
    candle = normalise_candle(_candle(1_704_067_200_000), now_ms=NOW)
    assert candle["open_time_ms"] == 1_704_067_200_000
    assert candle["volume"] == "1"
    assert candle["quote_volume"] is None
    micro = _candle(ARCHIVE_MS_START, unit="us", source_format="binance_spot_archive")
    assert normalise_candle(micro, now_ms=NOW)["open_time_ms"] == ARCHIVE_MS_START
    early_archive = _candle(ARCHIVE_MS_START - 60_000, unit="us", source_format="binance_spot_archive")
    with pytest.raises(MarketDataError, match="timestamp_unit_mismatch"):
        normalise_candle(early_archive, now_ms=NOW)
    late_ms = _candle(ARCHIVE_MS_START, unit="ms", source_format="binance_spot_archive")
    with pytest.raises(MarketDataError, match="timestamp_unit_mismatch"):
        normalise_candle(late_ms, now_ms=NOW)
    assert normalise_candle(_candle(ARCHIVE_US_START // 1000), now_ms=NOW)["timestamp_unit"] == "ms"
    substituted = _candle(1_704_067_200_000)
    substituted["native_interval"] = "5m"
    with pytest.raises(MarketDataError, match="unexpected_interval_substitution"):
        normalise_candle(substituted, now_ms=NOW)
    gold = _candle(1_704_067_200_000, instrument="XAUUSD")
    with pytest.raises(MarketDataError, match="xau_minute_unlicensed"):
        normalise_candle(gold, now_ms=NOW)
    broken = _candle(1_704_067_200_000, close="120")
    with pytest.raises(MarketDataError, match="invalid_ohlc"):
        normalise_candle(broken, now_ms=NOW)
    negative = _candle(1_704_067_200_000, volume="-1")
    with pytest.raises(MarketDataError, match="invalid_volume"):
        normalise_candle(negative, now_ms=NOW)
    future = _candle(NOW)
    with pytest.raises(MarketDataError, match="future_or_incomplete"):
        normalise_candle(future, now_ms=NOW)


def test_store_is_idempotent_reports_gaps_and_withholds_revisions(tmp_path):
    store = DatasetStore(tmp_path)
    sentinel = tmp_path / "paper-book.json"
    sentinel.write_text("keep", encoding="utf-8")
    first = 1_704_067_200_000
    second = first + STEP * 2
    kwargs = dict(dataset_id="fixture-btc-1m", rights_id="deterministic_fixture", purpose="fixture_test", provider="fixture", symbol="BTCUSDT", interval="1m", now_ms=NOW, source_format="fixture")
    saved = store.ingest([_candle(first), _candle(second)], **kwargs)
    assert saved["ok"] is True
    assert saved["manifest"]["accepted"] == 2
    assert saved["manifest"]["gaps"] == 1
    assert saved["manifest"]["validation"] == "gaps_reported"
    assert saved["manifest"]["research_eligible"] is False
    again = store.ingest([_candle(first)], **kwargs)
    assert again["manifest"]["accepted"] == 2
    assert again["manifest"]["duplicates"] == 1
    assert again["manifest"]["sha256"] == saved["manifest"]["sha256"]
    changed = _candle(first, close="100.5")
    revised = store.ingest([changed], **kwargs)
    assert revised["manifest"]["corrections"][0]["applied"] is False
    loaded = store.load_verified("fixture-btc-1m")
    assert loaded["ok"] is True
    assert loaded["candles"][0]["close"] == "100"
    assert sentinel.read_text() == "keep"
    state = json.loads((tmp_path / "datasets" / "fixture-btc-1m" / "state.json").read_text())
    assert state["batches"] == 3
    assert state["cursor_ms"] == second


def test_checksum_and_promotion_block(tmp_path):
    store = DatasetStore(tmp_path)
    store.ingest([_candle(1_704_067_200_000)], dataset_id="fixture-btc-1m", rights_id="deterministic_fixture", purpose="fixture_test", provider="fixture", symbol="BTCUSDT", interval="1m", now_ms=NOW, source_format="fixture")
    path = tmp_path / "datasets" / "fixture-btc-1m" / "candles.jsonl"
    path.write_bytes(path.read_bytes() + b" ")
    assert store.load_verified("fixture-btc-1m")["reason"] == "checksum_mismatch"
    manifest = {"research_eligible": True, "rights_status": "approved", "evidence_class": "fixture"}
    with pytest.raises(MarketDataError, match="promotion_not_authorised"):
        promote_from_dataset(manifest)
    ready = research_readiness(manifest)
    assert ready["search_authorised"] is False
    assert ready["dataset_eligible"] is True


def test_backoff_and_holdout_and_registry():
    limited = backoff(1, status=429, retry_after="2")
    assert limited == {"retry": True, "reason": "retry_after", "wait_seconds": 2}
    assert backoff(1, status=418, retry_after="1")["reason"] == "ip_ban"
    assert backoff(1, status=429, retry_after=None)["reason"] == "missing_retry_after"
    assert backoff(9)["reason"] == "backoff_exhausted"
    assert backoff(3)["wait_seconds"] == 8
    assert backoff(6)["reason"] == "backoff_exhausted"
    assert holdout_status()["opened"] is False
    with pytest.raises(MarketDataError, match="holdout_sealed"):
        open_holdout()
    assert summary()["approved_for_paper"] == 0
    report = public_report()
    assert report["collected_bytes"] == 0
    assert report["strategy"]["approved_for_paper"] == 0
    assert report["holdout"]["opened"] is False
    assert report["storage"]["total_bytes"] > 0
    assert all(row["collected"] is False for row in report["storage"]["rows"])
    assert {note["read_for_this_review"] for note in report["retained_files"]} == {False}


def test_native_three_minute_is_not_a_one_minute_aggregate():
    raw = _candle(1_704_067_200_000, native="3m")
    raw["interval"] = "1m"
    with pytest.raises(MarketDataError, match="unexpected_interval_substitution"):
        normalise_candle(raw, now_ms=NOW)
    stored = normalise_candle(_candle(1_704_067_200_000, native="3m"), now_ms=NOW)
    assert stored["native_interval"] == "3m"
    assert stored["close_time_ms"] - stored["open_time_ms"] + 1 == 180_000


def test_every_live_path_fails_closed_before_the_network(monkeypatch, tmp_path):
    def explode(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    from datetime import date

    from ops.app import _remember
    from ops.data_rights import MESSAGE, USES, audit_log, open_market_stream, screen_bars, use_permission
    from ops.feeds import binance_bars, dukascopy_hour, xaus_spot
    from ops.gold_live import swissquote_xau
    from ops.market import fetch_klines, fetch_last_closed
    from ops.terminal_route import _BAR_CACHE, load_crypto_bars, load_gold_ohlc
    from ops.xau_pull import fetch_day

    last = fetch_last_closed("BTCUSDT", "15m", now_ms=NOW)
    assert last["reason"] == "commercial_use_unverified"
    assert last.get("close") is None
    assert last["source_reachable"] == "not_checked"
    candles = fetch_klines("ETHUSDT", "1h", now_ms=NOW)
    assert candles["candles"] == []
    assert candles.get("price") is None
    bars = binance_bars("BTCUSDT", "15m", NOW - 60_000, NOW, NOW)
    assert bars["ok"] is False and bars["bars"] == []
    spot = xaus_spot(NOW)
    assert spot.get("price") is None
    hour = dukascopy_hour(2024, 0, 1, 0)
    assert hour["ok"] is False and hour.get("ticks") == []
    quote = swissquote_xau(NOW)
    assert quote.get("bid") is None and quote.get("ask") is None
    day = fetch_day(date(2024, 1, 2), "BID", tmp_path)
    assert day["ok"] is False and day["body"] is None
    stream = open_market_stream()
    assert stream["stream"] is False and stream["reason"] == "commercial_use_unverified"
    _BAR_CACHE[("BTCUSDT", "15m")] = (NOW, [{"close": 99999}])
    loaded = load_crypto_bars("BTCUSDT", "15m", NOW)
    assert loaded == (None, "commercial_use_unverified")
    poisoned = _remember(("xaus", "spot"), 30, lambda: {"ok": True, "price": 2500})
    assert poisoned.get("price") is None
    assert "2500" not in json.dumps(poisoned)
    assert load_gold_ohlc("1h", NOW) == (None, "commercial_use_unverified")
    assert load_gold_ohlc("1m", NOW)[1] == "xau_minute_unlicensed"
    assert screen_bars("binance_spot_rest_klines", [{"close": 1}]) == []
    assert screen_bars("deterministic_fixture", [{"close": 1}], "research") == []
    evidence = {
        "provider": "Example",
        "product": "Example feed",
        "data_type": "spot kline",
        "permitted_purpose": "connection only",
        "terms_version": "example-1",
        "clause": "1",
        "verified_by": "test",
        "verified_on": "2026-11-03",
        "review_due": "2026-12-01",
    }
    record = {"id": "binance_spot_rest_klines", "status": "rights_unconfirmed", "uses": {use: "rights_unconfirmed" for use in USES}, "use_evidence": {"connection": evidence}}
    record["uses"]["connection"] = "approved"
    assert use_permission("binance_spot_rest_klines", "connection", record=record)["allowed"] is True
    assert use_permission("binance_spot_rest_klines", "display", record=record)["allowed"] is False
    expired = {"id": "binance_spot_rest_klines", "status": "approved", "uses": {"display": "approved"}, "use_evidence": {"display": {**evidence, "review_due": "2020-01-01"}}}
    assert use_permission("binance_spot_rest_klines", "display", record=expired)["reason"] == "rights_review_expired"
    assert use_permission("missing", "display")["allowed"] is False
    assert use_permission("binance_spot_rest_klines", "not-a-use")["reason"] == "missing_or_malformed_rights"
    bare = {"id": "binance_spot_rest_klines", "status": "approved"}
    assert use_permission("binance_spot_rest_klines", "strategy", record=bare)["reason"] == "approval_without_evidence"
    assert any(row["source"] == "binance_spot_rest_klines" for row in audit_log())
    assert MESSAGE.startswith("Market data access unavailable")


def test_rights_block_does_not_feed_decisions_or_the_scanner():
    from ops.autopilot import consider
    from ops.data_rights import MESSAGE
    from ops.inbox import deliver_evaluation
    from ops.scanner import present_window
    from ops.shadow_bridge import load_live_windows

    window = {
        "symbol": "BTCUSDT",
        "interval": "15m",
        "ok": True,
        "reason": "commercial_use_unverified",
        "rights_status": "rights_unconfirmed",
        "bars": [{"close": 100, "complete": True, "fresh": True, "close_time_ms": NOW}],
        "source_kind": "prospective",
    }
    card = present_window(window, NOW)
    assert card["price"] is None
    assert card["evaluated"] is False
    assert card["scanner_state"] == "RIGHTS"
    assert card["entry"] is None
    assert MESSAGE in card["message"]
    live = load_live_windows(NOW)
    assert len(live) == 12
    assert all(not row.get("bars") for row in live)
    assert {row["reason"] for row in live} == {"commercial_use_unverified", "xau_minute_unlicensed"}
    refused = deliver_evaluation("nobody", {}, {"decision": "BUY", "symbol": "BTCUSDT", "interval": "15m", "rights_status": "rights_unconfirmed", "entry": 1, "stop": 1, "target": 2, "reference_price": 1, "approved": True})
    assert refused["stored"] is False and refused["reason"] == "commercial_use_unverified"
    opened = consider({"id": "nobody"}, {"decision": "BUY", "entry": 1, "stop": 1, "target": 2, "rights_status": "prohibited"}, NOW, "opp")
    assert opened["ok"] is False and opened["reason"] == "commercial_use_unverified"


def test_empty_and_partial_restart(tmp_path):
    store = DatasetStore(tmp_path)
    empty = store.ingest([], dataset_id="fixture-btc-1m", rights_id="deterministic_fixture", purpose="fixture_test", provider="fixture", symbol="BTCUSDT", interval="1m", now_ms=NOW, source_format="fixture")
    assert empty["reason"] == "empty_batch"
    first = store.ingest([_candle(1_704_067_200_000)], dataset_id="fixture-btc-1m", rights_id="deterministic_fixture", purpose="fixture_test", provider="fixture", symbol="BTCUSDT", interval="1m", now_ms=NOW, source_format="fixture")
    assert first["manifest"]["accepted"] == 1
    nxt = 1_704_067_200_000 + STEP
    second = store.ingest([_candle(1_704_067_200_000), _candle(nxt)], dataset_id="fixture-btc-1m", rights_id="deterministic_fixture", purpose="fixture_test", provider="fixture", symbol="BTCUSDT", interval="1m", now_ms=NOW, source_format="fixture")
    assert second["manifest"]["accepted"] == 2
    assert second["manifest"]["duplicates"] == 1
    assert second["manifest"]["gaps"] == 0
    assert Path(tmp_path / "datasets" / "fixture-btc-1m" / "manifest.json").exists()
