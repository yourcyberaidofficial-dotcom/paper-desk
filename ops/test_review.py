"""Recording regressions: gold divergence, unlicensed minutes, AutoPilot labels."""

from ops.autopilot import consider, presentation
from ops.terminal_route import handle_signal
from ops.terminal_signal import _finish_gold


def _reading():
    return {"decision": "SELL", "entry": 1000.0, "stop": 1012.0, "target": 970.0, "reward_risk": 2.5, "reason": "Short idea."}


def _quote(mid, now=5):
    return {"ok": True, "bid": mid - 0.05, "ask": mid + 0.05, "timestamp_ms": now, "provider": "fixture"}


def test_exact_tolerance_stays_aligned_and_a_wider_gap_withholds_the_plan():
    exact_mid = 1000 / 1.0008
    aligned = _finish_gold(_reading(), {"reference_price": 1000.0, "bar_close_ms": 9}, _quote(exact_mid), "Preface.")
    assert aligned["quote_alignment"] == "aligned"
    assert aligned["quote_threshold"] == 0.0008
    assert aligned["entry"] == 1000.0
    wide_mid = 1000 / 1.0012
    held = _finish_gold(_reading(), {"reference_price": 1000.0, "bar_close_ms": 9}, _quote(wide_mid, now=11), "Preface.")
    assert held["quote_alignment"] == "diverged"
    assert abs(held["quote_gap"] - 0.0012) < 1e-9
    assert held["entry"] is None and held["stop"] is None and held["target"] is None
    assert held["research_levels"]["audit_only"] is True
    assert held["research_levels"]["entry"] == 1000.0
    assert held["size"]["order"] is False
    assert held["quote_time_ms"] == 11
    assert "0.08" in held["reason"]


def test_gold_minutes_stay_unlicensed_even_when_a_loader_has_a_candle():
    called = {"bars": 0, "quote": 0}

    def bars(interval, now):
        called["bars"] += 1
        return [{"close": 3900, "interval": interval}]

    def quote(now):
        called["quote"] += 1
        return {"ok": True, "bid": 3900, "ask": 3901}

    for interval in ("1m", "3m"):
        status, body = handle_signal(
            "user-a", {"symbol": "XAUUSD", "interval": interval, "strategy": "auto"}, 1_700_000_000_000,
            ohlc_loader=bars, quote_loader=quote,
        )
        assert status == 200
        assert body["blocked"] == "xau_minute_unlicensed"
        assert body["strategy"] == "xau-minute-unlicensed"
        assert body.get("entry") is None and body.get("reference_price") is None
        assert "London rule was not used" in body["reason"]
        opened = consider(
            {"id": "review-fixture-not-a-real-account", "autopilot": {"enabled": True, "status": "running"}},
            body, 1_700_000_000_000, "opp:gold",
        )
        assert opened.get("ok") is not True
    assert called == {"bars": 0, "quote": 0}


def test_autopilot_facing_does_not_say_running_when_disabled_or_unhealthy():
    off = presentation({"enabled": False, "status": "off"}, True)
    assert off["facing"] == "Disabled"
    assert off["entries_available"] is False
    assert "running" not in off["facing"].lower()
    paused = presentation({"enabled": True, "status": "paused"}, True)
    assert paused["facing"] == "Paused" and paused["entries_available"] is False
    stopped = presentation({"enabled": True, "status": "stopped"}, True)
    assert stopped["facing"] == "Emergency stop" and "not closed" in stopped["facing_note"]
    stale = presentation({"enabled": True, "status": "running"}, False)
    assert stale["facing"] == "Health not confirmed"
    assert stale["entries_available"] is False
    live = presentation({"enabled": True, "status": "running"}, True)
    assert live["facing"] == "Enabled" and live["entries_available"] is True
    waiting = presentation({"enabled": True, "status": "running"}, True, open_positions=0)
    assert waiting["facing"] == "Waiting"
    assert waiting["entries_available"] is True
    assert "running" not in waiting["facing"].lower()


def test_a_wider_gap_cannot_open_a_paper_order_and_the_boundary_stays_strict():
    from ops.autopilot import consider
    just_over = 1000 / (1 + 0.0008 + 1e-8)
    held = _finish_gold(_reading(), {"reference_price": 1000.0, "bar_close_ms": 9}, _quote(just_over, now=12), "Preface.")
    assert held["quote_alignment"] == "diverged"
    assert held["quote_gap"] > 0.0008
    assert held["entry"] is None and held["size"]["order"] is False
    opened = consider({"id": "review-fixture-not-a-real-account", "autopilot": {"enabled": True, "status": "running"}}, held, 12, "opp:div")
    assert opened.get("ok") is not True
    assert opened["reason"] == "quote_divergence"
    just_under = 1000 / (1 + 0.0008 - 1e-8)
    aligned = _finish_gold(_reading(), {"reference_price": 1000.0, "bar_close_ms": 9}, _quote(just_under), "Preface.")
    assert aligned["quote_alignment"] == "aligned"
    assert aligned["entry"] == 1000.0


def test_scanner_card_withholds_a_divergent_gold_plan(monkeypatch):
    from ops.scanner import _shared_reading

    def fake(*args, **kwargs):
        return {
            "decision": "WAIT",
            "decision_label": "QUOTE DIVERGENCE",
            "runtime_status": "quote_divergence",
            "entry": None,
            "stop": None,
            "target": None,
            "quote_gap": 0.0012,
            "reason": "raw quote_divergence",
            "reference_price": 2650.123456,
        }

    monkeypatch.setattr("ops.terminal_signal.decide", fake)
    card = _shared_reading("XAUUSD", "1h", [], 1, 2650.123456, {"ok": True})
    assert card["decision_label"] == "QUOTE DIVERGENCE"
    assert card["entry"] is None and card["stop"] is None and card["target"] is None
    assert card["eligible_for_alert"] is False
    assert "0.12" in card["message"]
    assert "last_trade" not in card["message"]


def test_worker_does_not_fetch_unlicensed_gold_minutes(monkeypatch, tmp_path):
    from ops.ledger import Ledger
    from ops.worker import Worker

    def crypto(*args, **kwargs):
        return []

    def gold(interval, now):
        if interval in {"1m", "3m"}:
            raise AssertionError(interval)
        return []

    monkeypatch.setattr("ops.terminal_route.load_crypto_bars", crypto)
    monkeypatch.setattr("ops.terminal_route.load_gold_ohlc", gold)
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")
    windows = worker._monitor_windows(1_700_000_000_000)
    minutes = [row for row in windows if row["symbol"] == "XAUUSD" and row["interval"] in {"1m", "3m"}]
    assert [row["interval"] for row in minutes] == ["1m", "3m"]
    assert all(row["blocked"] == "xau_minute_unlicensed" for row in minutes)
    evaluations = []
    assert Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")._monitor_one(1_700_000_000_000, minutes[0], [], evaluations) == 0
    assert evaluations[0]["blocked"] == "xau_minute_unlicensed"
    assert evaluations[0]["decision"] == "UNAVAILABLE"


def test_gold_minute_chart_is_not_a_substituted_candle():
    from ops.app import app
    client = app.test_client()
    for interval in ("1m", "3m"):
        body = client.get(f"/api/gold/candles?interval={interval}").get_json()
        assert body["blocked"] == "xau_minute_unlicensed"
        assert body["candles"] == []
        assert body["interval"] == interval


def test_autopilot_facing_is_shared_and_off_is_not_called_running(tmp_path, monkeypatch):
    from ops.app import app, worker
    from ops.autopilot import act
    from ops.test_paperbook import _account, _plan
    from ops.users import get

    _users, owner, _other = _account(tmp_path, monkeypatch)
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["user_exp"] = 9_999_999_999
    previous = worker.last_beat_ms
    error = worker.last_monitor_error
    worker.last_monitor_error = None
    worker.last_beat_ms = 0
    try:
        off = client.get("/api/autopilot").get_json()
        lab = client.get("/api/lab").get_json()["autopilot"]
        assert off["facing"] == lab["facing"] == "Disabled"
        assert off["entries_available"] is False
        assert off["health"] == "off"
        assert "running" not in (off["facing"] + off["facing_note"]).lower()
        page = client.get("/settings").get_data(as_text=True)
        assert "AutoPilot is running" not in page
        assert "Evaluate market" in page
        assert "Generate Signal" not in page
        act(owner["id"], "enable", 1_700_000_000_000, confirm=True)
        worker.last_beat_ms = int(__import__("time").time() * 1000)
        waiting = client.get("/api/autopilot").get_json()
        assert waiting["status"] == "running"
        assert waiting["facing"] == "Waiting"
        assert waiting["health"] == "confirmed"
        assert waiting["entries_available"] is True
        assert "running" not in waiting["facing"].lower()
        act(owner["id"], "pause", 1_700_000_100_000)
        paused = client.get("/api/autopilot").get_json()
        assert paused["facing"] == "Paused"
        assert paused["entries_available"] is False
        user = get(owner["id"])
        user["id"] = owner["id"]
        blocked = __import__("ops.autopilot", fromlist=["consider"]).consider(user, _plan(), 1_700_000_100_000, "opp:pause")
        assert blocked["attempted"] is False
        assert client.get("/api/paper/book").get_json()["orders"] == []
    finally:
        worker.last_beat_ms = previous
        worker.last_monitor_error = error


def test_inbox_age_and_desk_copy_keep_research_separate_from_orders():
    from ops.app import DASHBOARD
    from ops.inbox import notice_view
    old = notice_view({"id": "n1", "decision": "WAIT", "read": False, "created_ms": 1_000, "message": "wait"}, 1_000 + 5 * 86400000)
    assert old["freshness"] == "historical"
    assert old["read_state"] == "unread"
    assert old["notice_class"] == "WAIT notification"
    assert old["paper_order"] is False
    assert "5 days ago" == old["age_label"]
    fresh = notice_view({"id": "n2", "decision": "SELL", "approved": False, "read": True, "created_ms": 10_000, "validation_status": "FAIL"}, 20_000)
    assert fresh["freshness"] == "current"
    assert fresh["read_state"] == "read"
    assert fresh["notice_class"] == "research observation"
    assert "Checking which prices can be shown" in DASHBOARD
    assert "Scanner unavailable" in DASHBOARD
    assert "No completed paper trades" in DASHBOARD
    assert "Historical research record" in DASHBOARD
    assert "Not approved" in DASHBOARD
    assert 'value="4h"' not in DASHBOARD
    assert "last_trade" not in DASHBOARD.split("function plainReason")[1][:800] or "last completed candle close" in DASHBOARD

