"""Provider permissions are enforced. Reachability is not approval."""

import os
from pathlib import Path

from ops.entitlements import CAPABILITIES, decide_use, is_feed_derived, legacy_decision
from ops.provider_adapter import CONTRACT_FIELDS, current_reference_adapter, describe


def test_no_environment_flag_can_verify_a_source(monkeypatch):
    monkeypatch.setenv("AUREON_DESK_LIVE", "1")
    monkeypatch.setenv("DESK_LIVE", "binance_spot_rest_klines")
    monkeypatch.setenv("PAPER_DESK_LIVE", "1")
    import ops.data_rights as rights
    import ops.entitlements as entitlements

    assert not hasattr(rights, "DESK_LIVE")
    assert "os.environ" not in Path(entitlements.__file__).read_text(encoding="utf-8")
    shown = decide_use("binance_spot_rest_klines", "candle_display")
    assert shown["verified"] is True
    assert shown["reason"] == "public_completed_candle"
    assert legacy_decision("binance_spot_rest_klines", "display")["verified"] is False
    assert legacy_decision("binance_spot_rest_klines", "retention")["allowed"] is False
    assert os.environ["AUREON_DESK_LIVE"] == "1"


def test_binance_rest_is_not_the_vision_archive_and_is_not_approved():
    rest = decide_use("binance_spot_rest_klines", "candle_display")
    vision = decide_use("binance_vision_klines", "candle_display")
    assert rest["status"] == "verified"
    assert rest["verified"] is True
    assert rest["reason"] == "public_completed_candle"
    assert vision["status"] == "restricted"
    assert vision["allowed"] is False
    assert vision["reason"] == "prohibited"
    assert decide_use("binance_spot_rest_klines", "raw_data_retention")["allowed"] is False
    assert decide_use("binance_spot_rest_klines", "paper_ledger_persistence")["allowed"] is True
    assert decide_use("binance_vision_klines", "research_backtest")["allowed"] is False
    assert rest["source"] != vision["source"]


def test_swissquote_is_restricted_and_no_active_path_opens_it():
    for capability in CAPABILITIES:
        row = decide_use("swissquote_public_bbo", capability)
        assert row["status"] == "restricted"
        assert row["allowed"] is False
        assert row["verified"] is False
        assert row["operational_observation"] is False
    root = Path(__file__).resolve().parent
    for path in root.glob("*.py"):
        if path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8")
        if "urlopen" in text and ("swissquote" in text.lower() or "bboquotes" in text):
            raise AssertionError(path.name)
    from ops.gold_live import swissquote_xau
    quote = swissquote_xau(1_700_000_000_000)
    assert quote["reason"] == "reference_quote_unavailable"
    assert quote["bid"] is None and quote["ask"] is None
    assert quote["source_reachable"] == "not_checked"


def test_xaus_samples_are_not_a_quote_and_minutes_stay_unavailable():
    sampled = decide_use("xaus_spot_samples", "sampled_reference_display")
    native = decide_use("xaus_spot_samples", "candle_display")
    quote = decide_use("xaus_spot_samples", "quote_display")
    assert sampled["status"] == "unverified"
    assert sampled["operational_observation"] is True
    assert sampled["verified"] is False
    assert native["status"] == "unavailable"
    assert quote["status"] == "unavailable"
    assert decide_use("xaus_public_chart", "quote_display", symbol="XAUUSD", interval="1m")["status"] == "unavailable"
    assert decide_use("xaus_public_chart", "quote_display", symbol="XAUUSD", interval="3m")["reason"] == "xau_minute_unlicensed"


def test_user_authored_levels_are_not_feed_prices():
    feed = {"source_id": "binance_spot_rest_klines", "entry": 10, "stop": 9, "target": 12}
    authored = {"source_id": "user_authored", "provenance": "user_authored", "entry": 10, "stop": 9, "target": 12}
    assert is_feed_derived(feed) is True
    assert is_feed_derived(authored) is False
    assert is_feed_derived({"entry": 10, "stop": 9, "target": 12}) is False
    adapter = current_reference_adapter()
    assert describe(adapter)["ok"] is True
    assert set(CONTRACT_FIELDS).issubset(adapter)
    assert adapter["failure_mode"] == "reference_quote_unavailable"
    assert adapter["quote_threshold"] == 0.0008


def test_existing_paper_bytes_stay_put_when_a_feed_plan_is_reviewed(tmp_path, monkeypatch):
    from ops.inbox import record_desk_plan
    from ops.paperbook import load
    from ops.test_desk_snapshot import _breakout
    from ops.test_paperbook import _account
    from ops.desk_snapshot import reading_for

    users, owner, _other = _account(tmp_path, monkeypatch)
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    book = load(owner["id"])
    book["orders"].append({"id": "kept", "status": "open", "entry": 1, "symbol": "BTCUSDT"})
    from ops.paperbook import save
    save(owner["id"], book)
    path = tmp_path / "users" / owner["id"] / "paper.json"
    # paper path is under AUREON_DATA. Locate the file load just wrote.
    from ops import paperbook
    written = paperbook._path(owner["id"])
    before = written.read_bytes()
    bars, now = _breakout()
    card = reading_for("BTCUSDT", "15m", now, bars=bars)
    assert card["manual_paper"] is True
    saved = record_desk_plan(owner["id"], user, card)
    assert saved["levels_persisted"] is True
    assert written.read_bytes() == before
    assert b'"id": "kept"' in before or b'"id":"kept"' in before or b"kept" in before


def test_the_twenty_one_pages_resolve_without_a_rights_wall():
    from ops.app import app
    pages = [
        "/", "/login", "/register", "/overview", "/signals", "/trading", "/strategies",
        "/indicators", "/research", "/portfolio", "/risk", "/activity", "/live", "/system",
        "/settings", "/scanner", "/learn", "/plan", "/lab", "/notifications", "/onboarding",
    ]
    assert len(pages) == 21
    client = app.test_client()
    for path in pages:
        response = client.get(path)
        assert response.status_code in {200, 302}, path
        body = response.get_data(as_text=True)
        assert "global-rights-wall" not in body
        if response.status_code == 200 and path not in {"/", "/login", "/register"}:
            assert "Market data access unavailable — commercial use permissions are being verified." not in body.split("<script>", 1)[0]
