"""Canonical desk snapshots, explainable readings, and manual paper continuity."""

from ops.desk_snapshot import (
    READING_VERSION,
    archive_restrictions,
    assemble,
    classify,
    observe,
    permission_for,
    quote_alignment,
)


def _bar(index, price, step, start, interval="15m", complete=True, native=None):
    open_ms = start + index * step
    return {
        "symbol": "BTCUSDT",
        "interval": native or interval,
        "native_interval": native,
        "open_time_ms": open_ms,
        "close_time_ms": open_ms + step - 1,
        "open": price - 0.2,
        "high": price + 0.3,
        "low": price - 0.3,
        "close": price,
        "complete": complete,
        "fresh": True,
        "provider": "binance-public",
        "quote_semantics": "last_trade",
        "source_type": "fixture",
    }


def _breakout(now=None):
    step = 15 * 60 * 1000
    start = 1_700_006_400_000
    bars = [_bar(index, 100.0, step, start) for index in range(59)]
    bars.append(_bar(59, 100.8, step, start))
    bars[-1]["high"] = 101.0
    bars[-1]["low"] = 100.5
    bars[-1]["open"] = 100.55
    close_ms = bars[-1]["close_time_ms"]
    return bars, close_ms + 1000


def test_quote_is_not_written_into_the_candle_and_the_boundary_stays_exact():
    aligned, gap = quote_alignment(100.08, 100.0)
    assert aligned == "aligned" and abs(gap - 0.0008) < 1e-12
    wider, wide_gap = quote_alignment(100.0801, 100.0)
    assert wider == "diverged" and wide_gap > 0.0008
    bars, now = _breakout()
    quote = {"ok": True, "bid": 2500, "ask": 2502, "timestamp_ms": now}
    snap = observe("BTCUSDT", "15m", now, bars=bars, quote=quote)
    assert snap["candle"]["close"] == 100.8
    assert snap["display"]["price"] == 100.8
    assert snap["display"]["close"] == 100.8
    assert snap["quote"] is None
    assert "2500" not in str(snap["candle"])
    gold = observe("XAUUSD", "1h", now, bars=[{**bars[-1], "symbol": "XAUUSD", "interval": "1h"}], quote=quote)
    assert gold["candle"]["close"] != gold["quote"]["price"]
    assert gold["quote"]["not_a_candle"] is True
    assert gold["display"]["quote"]["not_a_candle"] is True
    assert gold["display"]["price"] == gold["candle"]["close"]


def test_gold_minutes_and_substituted_timeframes_do_not_invent_candles(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("feed")

    monkeypatch.setattr("ops.terminal_route.load_gold_ohlc", explode)
    monkeypatch.setattr("ops.terminal_route.load_crypto_bars", explode)
    minute = observe("XAUUSD", "1m", 1_700_000_000_000)
    assert minute["quality"] == "unavailable"
    assert minute["candle"] is None
    assert minute["_bars"] == []
    assert minute["permission"]["display"]["allowed"] is True
    foreign = [_bar(0, 100, 60_000, 1_700_006_400_000, interval="1m", native="5m")]
    foreign[0]["native_interval"] = "5m"
    refused = assemble("BTCUSDT", "1m", foreign[0]["close_time_ms"] + 1000, bars=foreign)
    assert refused["quality"] == "degraded"
    assert refused["candle"] is None
    assert refused["_bars"] == []


def test_stale_incomplete_and_gapped_series_keep_the_real_close():
    bars, _now = _breakout()
    stale_now = bars[-1]["close_time_ms"] + 4 * 60 * 60 * 1000
    stale = assemble("BTCUSDT", "15m", stale_now, bars=bars)
    assert stale["quality"] == "stale"
    assert stale["candle"]["close"] == 100.8
    assert stale["_bars"] == []
    forming = [dict(bar) for bar in bars]
    forming[-1]["complete"] = False
    forming[-1]["close_time_ms"] = forming[-1]["open_time_ms"] + 60_000
    incomplete = assemble("BTCUSDT", "15m", forming[-1]["close_time_ms"] + 1000, bars=forming)
    assert incomplete["quality"] == "incomplete"
    assert incomplete["_bars"] == []
    gapped = [bars[0], bars[2], bars[-1]]
    gapped[1] = dict(bars[2])
    report = assemble("BTCUSDT", "15m", bars[-1]["close_time_ms"] + 1000, bars=gapped)
    assert report["series"]["gaps"] >= 1
    assert report["candle"]["close"] == bars[-1]["close"]
    duplicated = list(bars)
    duplicated.append(dict(bars[-1]))
    broken = assemble("BTCUSDT", "15m", bars[-1]["close_time_ms"] + 1000, bars=duplicated)
    assert broken["quality"] == "degraded"
    assert broken["_bars"] == []


def test_the_same_snapshot_classifies_the_same_reading_without_a_probability():
    bars, now = _breakout()
    first = observe("BTCUSDT", "15m", now, bars=bars)
    second = observe("BTCUSDT", "15m", now, bars=bars)
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["reading_version"] == READING_VERSION
    card = {"decision": "WAIT", "decision_label": "WAIT", "message": "No setup on this candle.", "approved": False, "evaluated": True}
    left = classify(card, first)
    right = classify(dict(card), second)
    assert left["reading_class"] == right["reading_class"] == "observational"
    assert left["direction_label"] == "neutral"
    assert left["probability"] is None
    assert left["autopilot_eligible"] is False
    assert left["manual_paper"] is False
    assert "probability" not in (left["explanation"] or "").lower() or left["probability"] is None
    withheld = classify({"decision": "BUY", "entry": 1, "stop": 0.9, "target": 1.2, "approved": False}, first)
    stale = assemble("BTCUSDT", "15m", now + 4 * 60 * 60 * 1000, bars=bars)
    blocked = classify({"decision": "BUY", "entry": 1, "stop": 0.9, "target": 1.2, "approved": True}, stale)
    assert blocked["entry"] is None and blocked["reading_class"] == "insufficient"
    assert withheld["reading_class"] == "manual_plan"
    assert withheld["autopilot_eligible"] is False
    watch = classify({"decision": "WAIT", "decision_label": "WATCH", "runtime_status": "watch", "direction": "WAIT", "message": "The shorter average is below the longer one. A short idea is not an entry.", "approved": False}, first)
    assert watch["reading_class"] == "developing"
    assert watch["direction_label"] == "neutral"
    assert watch["manual_paper"] is False
    assert permission_for("BTCUSDT", "15m")["display"]["allowed"] is True
    assert permission_for("BTCUSDT", "15m")["retention"]["allowed"] is False
    assert permission_for("BTCUSDT", "15m")["research"]["allowed"] is False
    assert archive_restrictions()[0]["status"] == "prohibited"


def test_a_real_reading_can_be_confirmed_manually_and_autopilot_stays_shut(tmp_path, monkeypatch):
    from ops.autopilot import act, consider
    from ops.inbox import items
    from ops.paperbook import open_order, opportunity_row, summary
    from ops.terminal_signal import decide
    from ops.test_paperbook import _account

    users, owner, other = _account(tmp_path, monkeypatch)
    bars, now = _breakout()
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    reading = decide("BTCUSDT", "15m", "auto", bars, now, user)
    assert reading["decision"] == "BUY"
    assert reading["approved"] is False
    assert reading["entry"] == bars[-1]["close"]
    snap = observe("BTCUSDT", "15m", now, bars=bars)
    labeled = classify(reading, snap)
    assert labeled["reading_class"] == "manual_plan"
    assert labeled["autopilot_eligible"] is False
    assert labeled["snapshot_id"] == snap["snapshot_id"]
    delivered = __import__("ops.inbox", fromlist=["deliver_evaluation"]).deliver_evaluation(owner["id"], user, reading)
    assert delivered["stored"] is True
    again = __import__("ops.inbox", fromlist=["deliver_evaluation"]).deliver_evaluation(owner["id"], user, {**reading, "entry": 999})
    assert again["duplicate"] is True
    stored = opportunity_row(owner["id"], delivered["opportunity_id"])
    assert stored.get("entry") == reading["entry"]
    enabled = act(owner["id"], "enable", now, confirm=True)
    assert enabled["ok"] is True
    fresh = users.get(owner["id"])
    fresh["id"] = owner["id"]
    opened = consider(fresh, reading, now + 3000, delivered["opportunity_id"])
    assert opened["ok"] is True
    assert summary(owner["id"])["open"]
    assert open_order(fresh, stored, now + 1000).get("reason") != "paper_ledger_persistence"
    from ops.inbox import build_user_plan, record_desk_plan
    built = build_user_plan(labeled, {"decision": "BUY", "entry": 100, "stop": 98, "target": 104})
    authored = record_desk_plan(owner["id"], fresh, built["plan"])
    assert authored["levels_persisted"] is True
    opened = open_order(fresh, opportunity_row(owner["id"], authored["opportunity_id"]), now + 1500)
    assert opened["ok"] is True
    assert opened["order"]["opened_by"] == "account"
    assert opened["order"]["executable"] is False
    assert opened["order"]["entry"] == 100
    assert open_order(fresh, opportunity_row(owner["id"], authored["opportunity_id"]), now + 2000)["reason"] == "already_open"
    assert opportunity_row(other["id"], delivered["opportunity_id"]) is None
    assert summary(other["id"])["empty"] is True
    blocked_again = consider(fresh, reading, now + 4000, delivered["opportunity_id"])
    assert blocked_again["ok"] is False
    assert len([row for row in summary(owner["id"])["open"] if row.get("opened_by") == "autopilot"]) == 1
    assert items(owner["id"])


def test_desk_routes_remain_present():
    from ops.app import app

    paths = {
        "/", "/login", "/register", "/overview", "/signals", "/trading", "/strategies",
        "/indicators", "/research", "/portfolio", "/risk", "/activity", "/live", "/system",
        "/settings", "/scanner", "/learn", "/plan", "/lab", "/notifications", "/onboarding",
    }
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert paths <= rules
    assert len(paths) == 21
