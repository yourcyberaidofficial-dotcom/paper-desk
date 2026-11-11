"""A daily reading can be reviewed and confirmed. AutoPilot stays shut."""

import threading
import time

from ops.desk_snapshot import reading_for
from ops.inbox import deliver_evaluation, items
from ops.paperbook import load, open_order, opportunity_row, summary
from ops.test_desk_snapshot import _breakout
from ops.test_paperbook import _account
from ops.users import save_inbox_delivery


def test_gold_minutes_are_not_a_plan_and_do_not_call_the_feed(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("feed")

    monkeypatch.setattr("ops.terminal_route.load_gold_ohlc", explode)
    monkeypatch.setattr("ops.terminal_route.load_crypto_bars", explode)
    card = reading_for("XAUUSD", "1m", 1_700_000_000_000)
    assert card["reading_class"] == "unavailable"
    assert card["manual_paper"] is False
    assert card["autopilot_eligible"] is False
    assert card.get("entry") is None
    assert card["quality"] == "unavailable"
    assert reading_for("BTCUSDT", "4h", 1_700_000_000_000) is None


def test_an_observation_is_not_saved_and_a_plan_keeps_its_snapshot(tmp_path, monkeypatch):
    from ops.autopilot import act, consider
    from ops.inbox import record_desk_plan

    users, owner, other = _account(tmp_path, monkeypatch)
    save_inbox_delivery(owner["id"], {"experimental": False, "markets": ["BTCUSDT"], "timeframes": ["15m"], "buy": True, "sell": True})
    bars, now = _breakout()
    quiet = [dict(bar, close=100.0, high=100.2, low=99.8) for bar in bars]
    observed = reading_for("BTCUSDT", "15m", now, bars=quiet)
    assert observed["manual_paper"] is False
    assert observed["probability"] is None
    refused = record_desk_plan(owner["id"], users.get(owner["id"]), observed)
    assert refused["reason"] == "not_a_manual_plan"
    assert refused["order_opened"] is False
    assert items(owner["id"]) == []
    labeled = reading_for("BTCUSDT", "15m", now, bars=bars)
    assert labeled["decision"] == "BUY"
    assert labeled["reading_class"] == "manual_plan"
    assert labeled["autopilot_eligible"] is False
    assert labeled["approved"] is False
    assert labeled["snapshot_id"]
    again = reading_for("BTCUSDT", "15m", now, bars=bars)
    assert again["snapshot_id"] == labeled["snapshot_id"]
    assert again["entry"] == labeled["entry"]
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    saved = record_desk_plan(owner["id"], user, labeled)
    assert saved["stored"] is True
    assert saved["order_opened"] is False
    assert saved["levels_persisted"] is True
    blocked = deliver_evaluation(owner["id"], user, labeled)
    assert blocked["reason"] == "experimental_off"
    stored = opportunity_row(owner["id"], saved["opportunity_id"])
    assert stored["entry"] == labeled["entry"]
    assert stored["stop"] == labeled["stop"]
    assert stored["target"] == labeled["target"]
    assert stored["levels_persisted"] is True
    assert stored["snapshot_id"] == labeled["snapshot_id"]
    assert stored["plan_version"].startswith("plan:")
    assert str(labeled["entry"]) in stored["plan_version"]
    repeat = record_desk_plan(owner["id"], user, {**labeled, "entry": 999})
    assert repeat["duplicate"] is True
    assert opportunity_row(owner["id"], saved["opportunity_id"])["entry"] == labeled["entry"]
    later = dict(labeled)
    later["bar_close_ms"] = int(labeled["bar_close_ms"]) + 15 * 60 * 1000
    later["snapshot_id"] = labeled["snapshot_id"] + ":next"
    second = record_desk_plan(owner["id"], user, later)
    assert second["stored"] is True
    assert second["levels_persisted"] is True
    assert second["opportunity_id"] != saved["opportunity_id"]
    from ops.inbox import build_user_plan, retire_opportunity
    opened = open_order(user, stored, now + 1000)
    assert opened.get("reason") != "paper_ledger_persistence"
    copied = build_user_plan(labeled, {"decision": "BUY", "entry": labeled["entry"], "stop": labeled["stop"], "target": labeled["target"]})
    assert copied["reason"] == "feed_copy"
    built = build_user_plan(labeled, {"decision": "BUY", "entry": 100, "stop": 98, "target": 104})
    assert built["ok"] is True
    authored = record_desk_plan(owner["id"], user, built["plan"])
    assert authored["stored"] is True
    assert authored["levels_persisted"] is True
    assert retire_opportunity(owner["id"], saved["opportunity_id"], now, note="one setup") == 1
    assert opportunity_row(owner["id"], second["opportunity_id"])["lifecycle"] == "active"
    assert opportunity_row(other["id"], second["opportunity_id"]) is None
    enabled = act(owner["id"], "enable", now, confirm=True)
    assert enabled["ok"] is True
    fresh = users.get(owner["id"])
    fresh["id"] = owner["id"]
    opened_bot = consider(fresh, labeled, now + 3000, authored["opportunity_id"])
    assert opened_bot["ok"] is True
    assert [row for row in summary(owner["id"])["orders"] if row.get("opened_by") == "autopilot"]
    row = opportunity_row(owner["id"], authored["opportunity_id"])
    assert row["entry"] == 100
    assert row["source_id"] == "user_authored"
    assert row["provenance"] == "user_authored"
    results = []

    def confirm():
        account = users.get(owner["id"])
        account["id"] = owner["id"]
        results.append(open_order(account, row, now + 5000))

    threads = [threading.Thread(target=confirm) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    opened = [item for item in results if item.get("ok")]
    assert len(opened) <= 1
    orders = load(owner["id"])["orders"]
    assert len(orders) == len({row.get("opportunity_id") for row in orders})
    assert summary(other["id"])["empty"] is True


def test_the_plan_route_reviews_without_opening(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch)
    save_inbox_delivery(owner["id"], {"experimental": False, "markets": ["BTCUSDT"], "timeframes": ["15m"], "buy": True, "sell": True})
    bars, now = _breakout()
    card = reading_for("BTCUSDT", "15m", now, bars=bars)
    monkeypatch.setattr("ops.desk_snapshot.reading_for", lambda *_args, **_kwargs: card)
    from ops.app import app
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/api/desk/plan", json={"symbol": "BTCUSDT", "interval": "15m"}).status_code == 401
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["user_exp"] = time.time() + 3600
    quiet = dict(card)
    quiet["reading_class"] = "observational"
    quiet["manual_paper"] = False
    monkeypatch.setattr("ops.desk_snapshot.reading_for", lambda *_args, **_kwargs: quiet)
    blocked = client.post("/api/desk/plan", json={"symbol": "BTCUSDT", "interval": "15m"})
    assert blocked.status_code == 200
    assert blocked.get_json()["order_opened"] is False
    assert blocked.get_json()["reason"] == "reading_unavailable"
    assert blocked.get_json()["entry"] is None
    assert blocked.get_json()["stop"] is None
    assert blocked.get_json()["target"] is None
    assert items(owner["id"]) == []
    monkeypatch.setattr("ops.desk_snapshot.reading_for", lambda *_args, **_kwargs: card)
    reviewed = client.post("/api/desk/plan", json={"symbol": "BTCUSDT", "interval": "15m"})
    body = reviewed.get_json()
    assert reviewed.status_code == 200
    assert body["reason"] == "reading_unavailable"
    assert body.get("opportunity_id") in {None, ""}
    assert body["entry"] is None
    assert str(card["entry"]) not in reviewed.get_data(as_text=True)
    assert items(owner["id"]) == []
    copied = client.post("/api/desk/plan", json={"symbol": "BTCUSDT", "interval": "15m", "authored": True, "decision": "BUY", "entry": card["entry"], "stop": card["stop"], "target": card["target"]})
    copied_body = copied.get_json()
    assert copied_body["reason"] == "feed_copy"
    assert copied_body["entry"] is None
    assert str(card["entry"]) not in copied.get_data(as_text=True)
    authored = client.post("/api/desk/plan", json={"symbol": "BTCUSDT", "interval": "15m", "authored": True, "decision": "BUY", "entry": 100, "stop": 98, "target": 104}).get_json()
    assert authored["levels_persisted"] is True
    assert authored["provenance"] == "user_authored"
    assert authored["source_id"] == "user_authored"
    assert authored["entry"] == 100
    assert authored["snapshot_id"] in {None, ""}
    assert authored["order_opened"] is False
    stored = opportunity_row(owner["id"], authored["opportunity_id"])
    assert stored["entry"] == 100
    assert stored["provenance"] == "user_authored"
    assert stored.get("snapshot_id") in {None, ""}
    assert card.get("snapshot_id") not in (stored.get("snapshot_id"), stored.get("bar_close_ms"))
    if authored["paper"]["allowed"]:
        opened = client.post("/api/paper/orders", json={"opportunity_id": authored["opportunity_id"]})
        assert opened.status_code == 200
        assert opened.get_json()["order"]["executable"] is False
        assert opened.get_json()["order"]["opened_by"] == "account"
        assert opened.get_json()["order"]["entry"] == 100
