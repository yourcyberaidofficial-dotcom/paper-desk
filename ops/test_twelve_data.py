"""Twelve Data is a gated XAU/USD candle source. It is not a BTCUSDT or ETHUSDT feed."""

import json
from datetime import datetime, timezone

from ops.desk_snapshot import _CACHE, observe
from ops.entitlements import decide_use, persistence_refusal
from ops.provider_adapter import describe, twelve_data_adapter
from ops.twelve_data import fetch_time_series, parse_quote, parse_time_series

STEP = 3_600_000
NOW = 1_700_010_000_000


def _stamp(open_ms):
    return datetime.fromtimestamp(open_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _payload(symbol="XAU/USD", interval="1h", rows=None):
    if rows is None:
        rows = [
            {"datetime": _stamp(NOW - 3 * STEP), "open": "2000", "high": "2002", "low": "1999", "close": "2001"},
            {"datetime": _stamp(NOW - STEP), "open": "2001", "high": "2004", "low": "2000", "close": "2001.5"},
            {"datetime": _stamp(NOW), "open": "2001.5", "high": "2005", "low": "2001", "close": "424242.42"},
        ]
    return {"meta": {"symbol": symbol, "interval": interval}, "values": rows}


def _grant(root, **changes):
    today = datetime.now(timezone.utc).date().isoformat()
    body = {
        "provider": "Twelve Data",
        "product": "time_series",
        "instruments": ["XAUUSD"],
        "timeframes": ["1m", "15m", "1h"],
        "capabilities": ["candle_display"],
        "terms_version": "public-terms-reviewed-2026-11-04",
        "clause": "external display named in a signed add-on",
        "verified_by": "owner",
        "verified_on": today,
        "review_due": "2099-01-01",
        "redistribution": "named-addon",
    }
    body.update(changes)
    folder = root / "rights"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "twelve_data.json").write_text(json.dumps(body), encoding="utf-8")


def test_rejected_pairs_and_the_missing_3m_interval_do_not_call_transport():
    calls = []
    for symbol in ("BTCUSDT", "ETHUSDT", "BTCUSD", "ETHUSD"):
        result = fetch_time_series(symbol, "1h", NOW, transport=lambda _url: calls.append(_url))
        assert result["called"] is False
        assert result["reason"] == "pair_not_listed"
        assert result["synthesized"] is False
    missing = fetch_time_series("XAUUSD", "3m", NOW, transport=lambda _url: calls.append("3m"))
    assert missing["called"] is False
    assert missing["reason"] == "native_interval_not_supplied"
    assert missing["synthesized"] is False
    assert calls == []


def test_a_native_hour_drops_the_forming_bar_and_counts_gaps_and_duplicates():
    parsed = parse_time_series(_payload(), "XAUUSD", "1h", NOW)
    assert parsed["synthesized"] is False
    assert parsed["dropped_forming"] == 1
    assert [bar["close"] for bar in parsed["bars"]] == [2001.0, 2001.5]
    assert parsed["quality"]["gaps"] == 1
    assert "424242.42" not in json.dumps(parsed["bars"])
    mismatched = parse_time_series(_payload(symbol="BTC/USD"), "XAUUSD", "1h", NOW)
    assert mismatched["reason"] == "symbol_mismatch"
    assert mismatched["bars"] == []
    duplicated = _payload(rows=[
        {"datetime": _stamp(NOW - 2 * STEP), "open": "1", "high": "2", "low": "1", "close": "1.5"},
        {"datetime": _stamp(NOW - 2 * STEP), "open": "1", "high": "2", "low": "1", "close": "1.6"},
    ])
    again = parse_time_series(duplicated, "XAUUSD", "1h", NOW)
    assert again["quality"]["duplicates"] == 1
    assert again["ok"] is False


def test_the_quote_close_is_not_a_bid_or_ask_and_an_unverified_read_does_not_connect():
    quote = parse_quote({"symbol": "XAU/USD", "close": "2001.5"})
    assert quote["ok"] is False
    assert quote["bid"] is None
    assert quote["ask"] is None
    assert quote["last_ohlc_close"] == 2001.5
    assert quote["not_bid_ask"] is True
    calls = []
    blocked = fetch_time_series("XAUUSD", "1h", NOW, api_key="secret", transport=lambda _url: calls.append(_url))
    assert blocked["called"] is False
    assert blocked["reason"] == "unverified"
    assert calls == []
    described = describe(twelve_data_adapter())
    assert described["ok"] is True
    assert "btcusdt" in described["adapter"]["does_not_supply"]
    assert described["adapter"]["capabilities"]["quote_display"]["reason"] == "bid_ask_not_supplied"
    assert described["adapter"]["capabilities"]["candle_display"]["verified"] is False


def test_a_grant_verifies_only_the_named_gold_capability(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    _grant(tmp_path)
    candle = decide_use("twelve_data", "candle_display", symbol="XAUUSD", interval="1h")
    assert candle["verified"] is True and candle["allowed"] is True
    assert decide_use("twelve_data", "customer_reading", symbol="XAUUSD", interval="1h")["verified"] is False
    assert decide_use("twelve_data", "quote_display", symbol="XAUUSD", interval="1h")["reason"] == "bid_ask_not_supplied"
    assert decide_use("twelve_data", "candle_display", symbol="XAUUSD", interval="3m")["reason"] == "native_3m_not_supplied"
    assert decide_use("twelve_data", "candle_display", symbol="BTCUSDT", interval="1h")["reason"] == "pair_not_listed"
    assert decide_use("binance_spot_rest_klines", "candle_display", symbol="BTCUSDT", interval="15m")["reason"] == "public_completed_candle"
    _grant(
        tmp_path,
        product="time_series+derived",
        capabilities=["candle_display", "paper_ledger_persistence"],
        timeframes=["1h"],
    )
    assert decide_use("twelve_data", "paper_ledger_persistence", symbol="XAUUSD", interval="1h")["verified"] is True
    assert decide_use("twelve_data", "customer_reading", symbol="XAUUSD", interval="1h")["verified"] is False
    kept = {
        "source_id": "twelve_data",
        "provider": "twelve-data",
        "symbol": "XAUUSD",
        "interval": "1h",
        "entry": 2001.0,
        "stop": 1990.0,
        "target": 2030.0,
    }
    assert persistence_refusal(kept) is None
    refused = dict(kept, source_id="binance_spot_rest_klines", symbol="BTCUSDT", interval="15m")
    assert persistence_refusal(refused) is None
    (tmp_path / "rights" / "binance_spot_rest_klines.json").write_text((tmp_path / "rights" / "twelve_data.json").read_text(), encoding="utf-8")
    copied = decide_use("binance_spot_rest_klines", "candle_display", symbol="BTCUSDT", interval="1h")
    assert copied["verified"] is True
    assert copied["reason"] == "public_completed_candle"


def test_customer_gold_candles_use_the_injected_source_and_do_not_fail_over(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    _CACHE.clear()
    calls = []

    def transport(url, timeout=None, hook=None):
        calls.append(url)
        now_ms = int(__import__("time").time() * 1000)
        step = STEP
        start = (now_ms // step) * step - 2 * step
        rows = []
        for index in range(2):
            stamp = start + index * step
            rows.append({
                "datetime": _stamp(stamp),
                "open": 2000 + index,
                "high": 2003 + index,
                "low": 1998 + index,
                "close": 2001 + index,
            })
        rows.append({
            "datetime": _stamp((now_ms // step) * step),
            "open": 2002,
            "high": 2004,
            "low": 2001,
            "close": 424242.42,
        })
        return 200, _payload(rows=rows)

    monkeypatch.setattr("ops.twelve_data._request", transport)
    monkeypatch.setattr("ops.terminal_route.load_gold_ohlc", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("xaus")))
    from ops.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    quiet = client.get("/api/gold/candles?interval=1h")
    assert quiet.get_json()["candles"] == []
    assert calls == []
    assert "424242" not in quiet.get_data(as_text=True)
    _grant(tmp_path)
    released = client.get("/api/gold/candles?interval=1h")
    body = released.get_json()
    assert released.status_code == 200
    assert body["source"] == "twelve-data"
    assert body["quote_semantics"] == "ohlc_not_bid_ask"
    assert [row["c"] for row in body["candles"]] == [2001.0, 2002.0]
    assert "424242" not in released.get_data(as_text=True)
    assert "xaus" not in released.get_data(as_text=True).lower()
    assert calls and "XAU%2FUSD" in calls[0] or "XAU/USD" in calls[0]
    assert "BTCUSDT" not in calls[0]
    before = len(calls)
    crypto = client.get("/api/klines?symbol=BTCUSDT&interval=15m").get_json()
    assert crypto["candles"]
    assert "424242" not in str(crypto)
    assert len(calls) == before
    (tmp_path / "rights" / "twelve_data.json").unlink()
    _CACHE.clear()
    blocked = client.get("/api/gold/candles?interval=15m")
    assert blocked.get_json()["candles"] == []
    assert len(calls) == before
    failed = {"ok": False}

    def fail(_url, timeout=None, hook=None):
        failed["ok"] = True
        return 400, {"status": "error", "message": "down"}

    _grant(tmp_path, timeframes=["15m"])
    monkeypatch.setattr("ops.twelve_data._request", fail)
    _CACHE.clear()
    empty = client.get("/api/gold/candles?interval=15m")
    assert empty.status_code == 502
    assert empty.get_json()["candles"] == []
    assert empty.get_json()["source"] == "twelve-data"
    assert failed["ok"] is True
    _CACHE.clear()


def test_a_retention_grant_stores_gold_levels_without_calling_them_user_authored(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = users.register("ada", "password-s")
    _grant(tmp_path, product="time_series+derived", capabilities=["candle_display", "paper_ledger_persistence"], timeframes=["1h"])
    from ops.inbox import record_desk_plan
    from ops.paperbook import opportunity_row

    saved = record_desk_plan(owner["id"], {"id": owner["id"]}, {
        "symbol": "XAUUSD",
        "interval": "1h",
        "reading_class": "manual_plan",
        "manual_paper": True,
        "quality": "ok",
        "decision": "BUY",
        "entry": 2001,
        "stop": 1990,
        "target": 2030,
        "source_id": "twelve_data",
        "provider": "twelve-data",
        "bar_close_ms": 1_700_000_000_000,
        "rule": "native-ohlc",
    })
    assert saved["stored"] is True
    assert saved["levels_persisted"] is True
    row = opportunity_row(owner["id"], saved["opportunity_id"])
    assert row["entry"] == 2001
    assert row["source_id"] == "twelve_data"
    assert row.get("provenance") != "user_authored"



def test_an_authorised_empty_read_does_not_fall_through_to_xaus(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    _grant(tmp_path, timeframes=["1h"])
    monkeypatch.setattr("ops.twelve_data._request", lambda _url, timeout=None, transport=None: (400, {"status": "error"}))
    monkeypatch.setattr("ops.terminal_route.load_gold_ohlc", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("xaus")))
    _CACHE.clear()
    snap = observe("XAUUSD", "1h", NOW)
    assert snap["provider"] == "twelve-data"
    assert snap["source_id"] == "twelve_data"
    assert snap["_bars"] == []
    _CACHE.clear()
