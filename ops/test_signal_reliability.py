"""Failure, staleness, lifecycle and concurrency. Fixtures are not live evidence."""

import json
import threading
from datetime import datetime, timedelta, timezone


def test_conditions_name_the_bars_without_a_score():
    from ops.market_conditions import assess

    bars = []
    start = 1_700_000_000_000
    for index in range(6):
        price = 10 + index
        bars.append({
            "complete": True, "close": price, "high": price + 1, "low": price - 0.2,
            "open_time_ms": start + index * 60_000, "close_time_ms": start + (index + 1) * 60_000,
        })
    facts = assess(bars, start + 6 * 60_000, "1m")
    assert facts["trend"] == "rising" and facts["momentum"] == "up" and facts["freshness"] == "fresh"
    assert facts["evidence"].endswith("No probability is assigned.")
    assert not any(character.isdigit() for character in facts["evidence"])


def test_a_stale_candle_is_not_a_current_signal():
    from ops.signal_engine import _observe

    start = 1_700_000_000_000
    step = 900_000
    bars = []
    for index in range(5):
        price = 50 + index
        bars.append({
            "symbol": "BTCUSDT", "interval": "15m", "complete": True, "open": price, "high": price + 1,
            "low": price - 1, "close": price + 0.2, "open_time_ms": start + index * step,
            "close_time_ms": start + (index + 1) * step, "provider": "kraken", "quote_semantics": "ohlc_not_bid_ask",
        })
    card = _observe("BTCUSDT", "15m", bars, "fixture", start + 30 * step)
    assert card["freshness"] == "stale"
    assert card["price"] is None
    assert card["entry"] is None
    assert card["quality"] == "stale"


def test_invalidation_appends_and_keeps_the_original(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.signal_engine import _expire_or_invalidate
    from ops.signal_ledger import read, record_observations

    record_observations([{
        "symbol": "BTCUSDT", "interval": "15m", "quality": "ok", "decision": "BUY",
        "entry": 100, "stop": 98, "target": 104, "price": 100, "validation_status": "FAIL",
        "approved": False, "source_id": "fixture", "opportunity_id": "obs:keep",
    }], now_ms=1_000, component="test")
    follow = _expire_or_invalidate({
        "symbol": "BTCUSDT", "interval": "15m", "quality": "ok", "price": 97, "decision": "WAIT",
    }, 2_000)
    assert follow["observation"] == "invalidated"
    record_observations([follow], now_ms=2_000, component="test")
    rows = read()
    assert [row["observation"] for row in rows] == ["active_signal", "invalidated"]
    assert rows[0]["entry"] == 100 and rows[0]["stop"] == 98
    assert rows[1]["price"] == 97


def test_kraken_timeout_and_malformed_payloads_do_not_switch_source(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    today = datetime.now(timezone.utc).date()
    body = {
        "provider": "Kraken", "product": "ohlc", "instruments": ["BTCUSDT"], "timeframes": ["15m"],
        "capabilities": ["candle_display"], "terms_version": "t", "clause": "unit test",
        "verified_by": "unit-test", "verified_on": today.isoformat(),
        "review_due": (today + timedelta(days=10)).isoformat(), "redistribution": "test-only",
    }
    rights = tmp_path / "rights"
    rights.mkdir()
    (rights / "kraken_public_ohlc.json").write_text(json.dumps(body), encoding="utf-8")
    from ops.kraken_public import authorized_bars

    calls = {"n": 0}

    def explode(url, timeout):
        calls["n"] += 1
        raise TimeoutError("timed out")

    timed = authorized_bars("BTCUSDT", "15m", 1, transport=explode)
    assert timed["called"] is True and timed["reason"] == "timeout" and timed["attempts"] == 2
    assert calls["n"] == 2 and timed["bars"] == []

    def malformed(url, timeout):
        return 200, {"error": [], "result": {"XBTUSDT": "not-rows"}}

    bad = authorized_bars("BTCUSDT", "15m", 1, transport=malformed)
    assert bad["reason"] == "malformed" and bad["bars"] == []
    assert "binance" not in json.dumps(bad)


def test_concurrent_appends_stay_intact(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.activity import read, record

    errors = []

    def write(index):
        try:
            record("paper_plan_created", entity=f"plan:{index}", component="test", detail={"note": "kept"}, now_ms=index + 1)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    rows = read()
    assert len(rows) == 12
    assert len({row["entity"] for row in rows}) == 12


def test_explanation_quotes_the_stored_observation_and_drops_a_client_price(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setenv("OLLAMA_MODEL", "unit-test")
    from ops.ai_provider import ask
    from ops.signal_ledger import record_observations

    record_observations([{
        "symbol": "ETHUSDT", "interval": "1h", "quality": "ok", "reading_class": "observational",
        "decision": "WAIT", "validation_status": "FAIL", "approved": False, "source_id": "fixture",
        "conditions": "Trend rising. Momentum up. Range ordinary. Freshness fresh.",
        "price": 424242.42,
    }], now_ms=5, component="test")
    seen = {}

    def transport(method, url, payload):
        if method == "GET":
            return 200, {"models": [{"name": "unit-test"}]}
        seen["body"] = json.dumps(payload)
        return 200, {"message": {"content": json.dumps({"summary": "The stored observation is data in the evidence.", "evidence_used": ["observation"]})}}

    result = ask("ada", "explain_signal", symbol="ETHUSDT", interval="1h", transport=transport)
    assert "active_signal" in seen["body"] or "market_observation" in seen["body"] or "forming" in seen["body"]
    assert "424242" not in seen["body"]
    assert result["approved"] is False and result["order_opened"] is False
    assert result["explanation"]["not_an_order"] is True
