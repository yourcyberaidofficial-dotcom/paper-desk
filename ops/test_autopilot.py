"""AutoPilot opens paper orders only after this account turns it on. Fixtures, not a live feed."""

import json
import threading

from ops.autopilot import act, consider, view
from ops.paperbook import observe, summary
from ops.test_paperbook import _account, _plan
from ops.users import get


def _user(users, owner):
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    return user


def test_autopilot_stays_off_until_this_account_confirms(tmp_path, monkeypatch):
    users, owner, other = _account(tmp_path, monkeypatch)
    assert view(get(owner["id"]))["status"] == "off"
    assert view(get(owner["id"]))["accepts_new_entries"] is False
    assert act(owner["id"], "enable", 1_700_000_000_000, confirm=False)["reason"] == "confirmation_required"
    assert act(other["id"], "enable", 1_700_000_000_000, confirm=True)["ok"] is True
    assert view(get(owner["id"]))["enabled"] is False
    assert act(owner["id"], "enable", 1_700_000_000_000, confirm=True)["autopilot"]["status"] == "running"


def test_pause_blocks_a_new_entry_and_the_open_position_can_still_close(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch)
    act(owner["id"], "enable", 1_700_000_100_000, confirm=True)
    user = _user(users, owner)
    first = consider(user, _plan(), 1_700_000_100_000, "opp:BTCUSDT:15m:Trend pullback:BUY:1")
    assert first["ok"] is True
    assert first["order"]["opened_by"] == "autopilot"
    assert act(owner["id"], "pause", 1_700_000_200_000)["autopilot"]["status"] == "paused"
    user = _user(users, owner)
    second = consider(user, _plan(entry=110, stop=109, target=113), 1_700_000_200_000, "opp:BTCUSDT:15m:Trend pullback:BUY:2")
    assert second["attempted"] is False
    observe(owner["id"], "BTCUSDT", "15m", {"high": 104, "low": 100, "close": 103, "close_time_ms": 1_700_000_300_000, "provider": "binance"}, 1_700_000_300_000, {"name": "binance"})
    closed = summary(owner["id"])["closed"]
    assert closed[0]["exit_kind"] == "market_stop"
    assert len(summary(owner["id"])["orders"]) == 1


def test_a_repeated_opportunity_and_a_low_reward_plan_do_not_open_twice(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch, style="aegis_shield")
    act(owner["id"], "enable", 1_700_000_100_000, confirm=True, max_orders_per_day=1)
    user = _user(users, owner)
    low = consider(user, _plan(target=100.4), 1_700_000_100_000, "opp:low")
    assert low["reason"] == "below_persona_reward"
    assert summary(owner["id"])["orders"] == []
    assert get(owner["id"])["autopilot"]["rejections"][-1]["reason"] == "below_persona_reward"
    act(owner["id"], "disable", 1_700_000_100_000)
    users_mod = users
    from ops.users import update_profile
    update_profile(owner["id"], {"signal_style": "apex_momentum", "capital": 1000, "currency": "USD"})
    act(owner["id"], "enable", 1_700_000_100_000, confirm=True)
    user = _user(users_mod, owner)
    opened = consider(user, _plan(), 1_700_000_100_000, "opp:once")
    assert opened["ok"] is True
    again = consider(_user(users_mod, owner), _plan(), 1_700_000_200_000, "opp:once")
    assert again["reason"] == "already_recorded"
    assert len(summary(owner["id"])["orders"]) == 1


def test_emergency_stop_stale_data_and_gold_minutes_open_nothing(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch)
    act(owner["id"], "enable", 1_700_000_100_000, confirm=True)
    act(owner["id"], "emergency_stop", 1_700_000_100_000)
    user = _user(users, owner)
    assert consider(user, _plan(), 1_700_000_100_000, "opp:stop")["attempted"] is False
    act(owner["id"], "resume", 1_700_000_100_000)
    user = _user(users, owner)
    stale = consider(user, {"decision": "BUY", "blocked": "stale_or_incomplete", "symbol": "BTCUSDT", "interval": "15m"}, 1_700_000_100_000, "opp:stale")
    assert stale["ok"] is False
    assert summary(owner["id"])["orders"] == []
    from ops.terminal_signal import decide
    now = 1_700_000_060_000
    bars = [{"high": 10, "low": 9, "close": 9.5, "complete": True, "close_time_ms": now - 1000, "provider": "dukascopy", "quote_semantics": "dukascopy_xauusd_bid_ask"}] * 80
    gold = decide("XAUUSD", "1m", "auto", bars, now, None)
    assert consider(user, gold, now, "opp:gold")["reason"] == "xau_minute_unlicensed"
    assert summary(owner["id"])["orders"] == []


def test_two_overlapping_attempts_leave_one_order(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch)
    act(owner["id"], "enable", 1_700_000_100_000, confirm=True)
    user = _user(users, owner)
    results = []

    def run():
        results.append(consider(dict(user), _plan(), 1_700_000_100_000, "opp:race"))

    first = threading.Thread(target=run)
    second = threading.Thread(target=run)
    first.start()
    second.start()
    first.join()
    second.join()
    assert sorted(row.get("reason") for row in results) == ["already_recorded", "opened"]
    assert len(summary(owner["id"])["orders"]) == 1


def test_lab_progress_stays_on_one_account_and_a_note_is_not_a_firm_rule(tmp_path, monkeypatch):
    users, owner, other = _account(tmp_path, monkeypatch)
    from ops.app import app
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["user_exp"] = 9_999_999_999
    assert client.get("/api/autopilot").get_json()["status"] == "off"
    assert client.post("/api/autopilot", json={"action": "enable", "confirm": False}).status_code == 409
    saved = client.post("/api/lab", json={"experience": "new", "objective": "Learn risk", "focus": ["risk"], "completed_lessons": ["risk"], "custom_rule": "Daily loss 5%"})
    assert saved.status_code == 200
    lab = client.get("/api/lab").get_json()
    assert lab["experience"] == "new"
    assert lab["completed_lessons"] == ["risk"]
    assert lab["rules"]["verified_firm_rules"] == []
    assert lab["rules"]["custom_rules"][0]["verified"] is False
    assert "Not confirmed" in lab["rules"]["custom_rules"][0]["note"]
    assert lab["observation"].startswith("Not enough")
    assert any(item["lesson_id"] == "journal" for item in lab["improvement"])
    assert "skill score" not in json.dumps(lab["improvement"]).lower()
    from ops.app import worker
    previous = worker.last_beat_ms
    worker.last_beat_ms = 0
    worker.last_monitor_error = None
    try:
        health = client.get("/api/autopilot").get_json()
        assert health["worker"]["healthy"] is False
        assert health["health"] == "off"
    finally:
        worker.last_beat_ms = previous
        worker.last_monitor_error = None
    page = client.get("/settings").get_data(as_text=True)
    assert "Enable AutoPilot" in page
    assert "not a broker" in page.lower() or "Not a broker" in page
    with client.session_transaction() as sess:
        sess["user_id"] = other["id"]
    other_lab = client.get("/api/lab").get_json()
    assert other_lab["completed_lessons"] == []
    assert other_lab["rules"]["custom_rules"] == []
    with client.session_transaction() as sess:
        sess.clear()
    public = client.get("/")
    assert b"not a broker" in public.get_data().lower() or b"Not a broker" in public.get_data()
