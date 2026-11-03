"""The 4h follow-up stays reproducible, unapproved, and off the holdout unless validation passes."""

import json
from datetime import datetime, timezone
from pathlib import Path

from ops.data_audit import build_audit
from ops.discovery import EMBARGO_MS, VERSION, protocol_sha256, score_symbol, trend_hold
from ops.history_store import ROOT, load_csv
from ops.plan import observe_levels
from ops.qualification import autopilot_may_open, catalog, find
from ops.research_cli import _hash
from ops.simulate import _exit, simulate

DOCS = Path(__file__).resolve().parents[1] / "docs"
STEP = 4 * 60 * 60 * 1000


def _bar(index, close, high=None, low=None, interval="4h"):
    open_time = 1_672_531_200_000 + index * STEP
    high = close if high is None else high
    low = close if low is None else low
    return {
        "symbol": "BTCUSDT",
        "interval": interval,
        "open_time_ms": open_time,
        "close_time_ms": open_time + STEP - 1,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1,
        "complete": True,
    }


def _breakout_bars():
    bars = [_bar(index, 100, high=101, low=99) for index in range(123)]
    bars[120] = _bar(120, 110, high=110, low=100)
    bars[121] = _bar(121, 120, high=140, low=109)
    return bars


def test_recorded_follow_up_matches_the_frozen_protocol_and_does_not_approve():
    report = json.loads((DOCS / "DISCOVERY_RESULTS.json").read_text(encoding="utf-8"))
    assert report["protocol_sha256"] == protocol_sha256()
    assert report["version"] == VERSION
    assert report["approved_for_paper"] == []
    assert report["promoted"] == []
    assert report["holdout_opened_for"] == []
    assert "follow-up" in report["protocol"]["multiple_testing"]
    for market in report["markets"]:
        assert market["holdout"] == "NOT_OPENED"
        assert market["approved_for_paper"] is False
        assert market["development"]["judgment"] == "FAIL"
        assert "uncertainty" in market["development"]["failed"]
        assert market["validation"]["judgment"] == "BLOCKED"
        assert "sample" in market["validation"]["blocked"]
        assert market["validation"]["short_trades"] == 0
        raw = datetime.fromisoformat(market["validation_start"])
        shown = datetime.fromisoformat(market["validation"]["start"])
        assert int(shown.timestamp()) - int(raw.timestamp()) == EMBARGO_MS // 1000


def test_saved_4h_history_is_the_dataset_that_was_scored_and_desk_minutes_are_missing():
    audit = build_audit(include_live_probe=False)
    assert audit["synthetic_data_can_approve"] is False
    retained = {(row["symbol"], row["interval"]): row for row in audit["retained"]}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        bars = load_csv(ROOT / f"{symbol}-4h.csv", symbol, "4h", "binance-public", "last_trade")
        row = retained[(symbol, "4h")]
        assert row["quality"]["ok"] is True
        assert row["gaps"] == 0 and row["duplicates"] == 0
        assert row["ohlc_sha256"] == _hash(bars)
        assert row["file_sha256"] == build_audit(False)["retained"][0 if symbol == "BTCUSDT" else 1]["file_sha256"]
    missing = [row for row in audit["coverage"] if row["classification"] == "missing_retained_history"]
    assert len(missing) == 12
    assert {row["interval"] for row in missing if row["symbol"] == "XAUUSD"} >= {"1m", "3m", "15m", "1h"}
    gold = retained[("XAUUSD", "1h")]
    assert gold["used_for_approval"] is False
    assert gold["measured_bid_ask_fields"] is True


def test_signal_ignores_the_next_bar_and_the_fill_is_that_next_open():
    bars = _breakout_bars()
    original = trend_hold(bars, 120, [], "BTCUSDT")
    truncated = trend_hold(bars[:121], 120, [], "BTCUSDT")
    assert original == truncated
    assert original["direction"] == "LONG"
    bars[121]["close"] = 1
    bars[121]["high"] = 1
    assert trend_hold(bars, 120, [], "BTCUSDT") == original
    trades = simulate("BTCUSDT", bars, [], VERSION, stress=False, setup_map={VERSION: trend_hold})
    assert len(trades) == 1
    assert trades[0]["entry_open_time_ms"] == bars[121]["open_time_ms"]
    assert trades[0]["signal_open_time_ms"] == bars[120]["open_time_ms"]
    assert abs(trades[0]["net"] - (trades[0]["gross"] - 0.0022)) < 1e-12
    stressed = simulate("BTCUSDT", bars, [], VERSION, stress=True, setup_map={VERSION: trend_hold})
    assert abs(stressed[0]["net"] - (stressed[0]["gross"] - 0.0030)) < 1e-12


def test_round_turn_cost_is_applied_once_on_a_known_price_path():
    def once(bars, index, higher, symbol):
        del bars, higher, symbol
        if index != 30:
            return None
        return {"direction": "LONG", "target_mode": "atr", "atr": 1.0, "stop_multiple": 1.0, "target_multiple": 2.0, "hold_bars": 3, "reward_risk": 2.0}

    bars = [_bar(index, 100, high=100, low=100) for index in range(34)]
    bars[31] = _bar(31, 100, high=100.4, low=99.5)
    bars[31]["open"] = 100
    bars[32] = _bar(32, 100, high=102, low=99.5)
    bars[32]["open"] = 100
    trades = simulate("BTCUSDT", bars, [], "fixture", setup_map={"fixture": once})
    assert len(trades) == 1
    assert trades[0]["exit"] == 102
    assert abs(trades[0]["gross"] - 0.02) < 1e-12
    assert abs(trades[0]["net"] - (0.02 - 0.0022)) < 1e-12
    assert abs((trades[0]["gross"] - trades[0]["net"]) - 0.0022) < 1e-12


def test_research_stop_is_conservative_and_the_paper_book_stays_unresolved():
    bars = [
        {"open": 100, "high": 100, "low": 100, "close": 100, "open_time_ms": 0, "close_time_ms": 1},
        {"open": 100, "high": 110, "low": 90, "close": 100, "open_time_ms": 2, "close_time_ms": 3},
    ]
    price, reason, index = _exit(bars, 1, "LONG", 95, 105, 2)
    assert reason == "stop" and price == 95 and index == 1
    reading = observe_levels("BUY", 95, 105, bars[1])
    assert reading["state"] == "ambiguous"
    assert "not a fill" in reading["note"]


def test_holdout_bars_are_withheld_until_validation_passes_and_still_do_not_approve():
    bars = [_bar(index, 100, high=101, low=99) for index in range(30)]

    def fail(*args, **kwargs):
        del args, kwargs
        return "FAIL", ["expectancy"], []

    def allow(*args, **kwargs):
        del args, kwargs
        return "PASS", [], []

    blocked = score_symbol("BTCUSDT", bars, judge_fn=fail)
    assert blocked["holdout"] == "NOT_OPENED"
    assert max(blocked["bars_simulated_lengths"]) < len(bars)
    opened = score_symbol("BTCUSDT", bars, judge_fn=allow)
    assert opened["holdout"] == "OPENED_ONCE"
    assert len(bars) in opened["bars_simulated_lengths"]
    assert opened["approved_for_paper"] is False


def test_gold_and_minute_bars_are_not_scored_by_the_follow_up():
    gold = score_symbol("XAUUSD", [_bar(0, 2000, interval="1h")])
    assert gold["reason"] == "not_eligible"
    assert gold["holdout"] == "NOT_OPENED"
    assert gold["bars_simulated_lengths"] == []
    minute = score_symbol("BTCUSDT", [_bar(index, 100, interval="1m") for index in range(5)])
    assert minute["reason"] == "not_eligible"
    assert trend_hold([_bar(index, 100) for index in range(130)], 120, [], "XAUUSD") is None


def test_real_prefix_rescore_keeps_the_holdout_closed():
    bars = load_csv(ROOT / "BTCUSDT-4h.csv", "BTCUSDT", "4h", "binance-public", "last_trade")
    scored = score_symbol("BTCUSDT", bars)
    assert scored["holdout"] == "NOT_OPENED"
    assert max(scored["bars_simulated_lengths"]) == int(len(bars) * 0.8)
    assert scored["sha256"] == _hash(bars)
    assert scored["validation"]["trades"] < 30


def test_the_new_version_cannot_be_forged_into_autopilot_or_paper_approval():
    body = catalog()
    assert body["approved_for_paper"] == 0
    row = find(VERSION)
    assert row["research_status"] == "FAIL"
    assert row["lifecycle"] == "backtest_failed"
    assert row["approved_for_paper"] is False
    assert row["live"] is False
    assert autopilot_may_open({"approved": True, "strategy": VERSION, "version": VERSION, "strategy_id": VERSION}) is False


def test_research_page_shows_the_failure_and_not_an_approval():
    from ops.app import app

    payload = app.test_client().get("/api/research-lab").get_json()
    assert payload["promoted_count"] == 0
    assert payload["approved"] == []
    assert payload["discovery"]["version"] == VERSION
    assert payload["discovery"]["holdout_opened_for"] == []
    assert payload["discovery"]["approved_for_paper"] == []
    assert any(item["id"] == VERSION and item["decision"] == "FAIL" for item in payload["experiments"])
    assert len(payload["data_audit"]["desk_pairs_missing_history"]) == 12
    from ops.app import DASHBOARD
    assert "Latest pre-registered study" in DASHBOARD
    assert "not an approved signal" in DASHBOARD
    assert "Latest study, not an approval" in DASHBOARD
