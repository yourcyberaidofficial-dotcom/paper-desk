"""Opportunity identity. These cases used to merge, drop, or retire the wrong card."""

import json
from pathlib import Path

from ops.inbox import deliver_evaluation, expire_stale, items, notice_id, opportunity_identity, retire_opportunity
from ops.plan import present_size, qualify_size
from ops.users import register, save_inbox_delivery


def _user(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = register("ada", "password-s")
    other = register("bea", "password-s")
    settings = {
        "experimental": True,
        "markets": ["BTCUSDT", "ETHUSDT"],
        "timeframes": ["15m", "1h"],
        "buy": True,
        "sell": True,
    }
    save_inbox_delivery(owner["id"], settings)
    save_inbox_delivery(other["id"], settings)
    return users, owner, other


def _plan(**changes):
    base = {
        "symbol": "BTCUSDT",
        "interval": "15m",
        "decision": "SELL",
        "entry": 100.0,
        "stop": 101.0,
        "target": 98.0,
        "strategy": "interval-reading",
        "rule": "Trend pullback",
        "fresh": True,
        "reference_price": 100.0,
        "bar_close_ms": 1_700_000_000_000,
        "version": "interval-reading",
        "approved": False,
    }
    base.update(changes)
    return base


def test_a_later_bar_is_a_different_opportunity(tmp_path, monkeypatch):
    users, owner, _other = _user(tmp_path, monkeypatch)
    first = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    second = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(bar_close_ms=1_700_000_900_000, entry=130, stop=131, target=128))
    assert first["stored"] is True and second["stored"] is True
    assert first["opportunity_id"] != second["opportunity_id"]
    cards = list(reversed(items(owner["id"])))
    assert len(cards) == 2
    assert cards[0]["entry"] == 100.0
    assert cards[1]["entry"] == 130


def test_a_different_family_does_not_collide(tmp_path, monkeypatch):
    users, owner, _other = _user(tmp_path, monkeypatch)
    first = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    second = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(rule="Failed break", entry=120, stop=121, target=118))
    assert second["stored"] is True
    assert second["id"] != first["id"]
    assert "Failed break" in second["opportunity_id"]
    assert len(items(owner["id"])) == 2


def test_retiring_a_sell_does_not_retire_the_buy(tmp_path, monkeypatch):
    users, owner, _other = _user(tmp_path, monkeypatch)
    sell = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    buy = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(decision="BUY", entry=90, stop=89, target=92))
    assert retire_opportunity(owner["id"], sell["opportunity_id"], 1_700_000_100_000) == 1
    rows = {row["direction"]: row for row in items(owner["id"])}
    assert rows["SELL"]["lifecycle"] == "superseded"
    assert rows["SELL"]["entry"] == 100.0
    assert rows["BUY"]["lifecycle"] == "active"
    assert rows["BUY"]["entry"] == 90


def test_retiring_one_bar_does_not_retire_the_next_bar(tmp_path, monkeypatch):
    users, owner, _other = _user(tmp_path, monkeypatch)
    first = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    second = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(bar_close_ms=1_700_000_900_000, entry=130, stop=131, target=128))
    retire_opportunity(owner["id"], first["opportunity_id"], 1_700_000_900_000)
    rows = {row["bar_close_ms"]: row for row in items(owner["id"])}
    assert rows[1_700_000_000_000]["lifecycle"] == "superseded"
    assert rows[1_700_000_900_000]["lifecycle"] == "active"
    assert rows[1_700_000_900_000]["entry"] == 130


def test_the_same_origin_accumulates_events_without_replacing_levels(tmp_path, monkeypatch):
    users, owner, _other = _user(tmp_path, monkeypatch)
    deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    again = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(entry=104, stop=105, target=102))
    assert again["reason"] == "same_opportunity"
    assert again["appended"] is True
    card = items(owner["id"])[0]
    assert card["entry"] == 100.0
    assert card["stop"] == 101.0
    assert card["target"] == 98.0
    assert card["events"][-1]["state"] == "reevaluated"
    assert card["events"][-1]["observed_entry"] == 104
    identical = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(entry=104, stop=105, target=102))
    assert identical["appended"] is False
    assert len(items(owner["id"])) == 1


def test_instruments_and_timeframes_stay_independent(tmp_path, monkeypatch):
    users, owner, other = _user(tmp_path, monkeypatch)
    btc = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    eth = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(symbol="ETHUSDT", entry=200, stop=201, target=198))
    hour = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(interval="1h", entry=110, stop=111, target=108))
    assert len({btc["opportunity_id"], eth["opportunity_id"], hour["opportunity_id"]}) == 3
    assert len(items(owner["id"])) == 3
    foreign = deliver_evaluation(other["id"], users.get(other["id"]), _plan(entry=50, stop=51, target=48))
    retire_opportunity(owner["id"], btc["opportunity_id"], 1_700_000_100_000)
    assert items(other["id"])[0]["entry"] == 50
    assert items(other["id"])[0]["lifecycle"] == "active"
    assert foreign["opportunity_id"] == btc["opportunity_id"]


def test_notification_ids_use_the_canonical_opportunity(tmp_path, monkeypatch):
    users, owner, _other = _user(tmp_path, monkeypatch)
    saved = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    expected = opportunity_identity("BTCUSDT", "15m", "Trend pullback", "SELL", 1_700_000_000_000)
    assert saved["opportunity_id"] == expected
    assert saved["id"] == notice_id("experimental", expected)
    assert items(owner["id"])[0]["id"] == saved["id"]


def test_an_old_record_keeps_its_prices_and_is_not_merged_with_a_new_bar(tmp_path, monkeypatch):
    users, owner, _other = _user(tmp_path, monkeypatch)
    path = Path(users.ROOT) / "inbox" / f"{owner['id']}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": "experimental:BTCUSDT:15m:interval-reading:1700000000000:SELL",
        "kind": "experimental",
        "symbol": "BTCUSDT",
        "interval": "15m",
        "strategy": "interval-reading",
        "family": "Trend pullback",
        "direction": "SELL",
        "decision": "SELL",
        "entry": 100.0,
        "stop": 101.0,
        "target": 98.0,
        "bar_close_ms": 1_700_000_000_000,
        "lifecycle": "active",
        "events": [{"id": "kept", "state": "active", "entry": 100.0, "stop": 101.0, "target": 98.0}],
    }) + "\n", encoding="utf-8")
    later = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(bar_close_ms=1_700_000_900_000, entry=130, stop=131, target=128))
    assert later["stored"] is True
    same = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(entry=140, stop=141, target=138))
    assert same["reason"] == "same_opportunity"
    rows = {row["bar_close_ms"]: row for row in items(owner["id"])}
    assert rows[1_700_000_000_000]["entry"] == 100.0
    assert rows[1_700_000_000_000]["events"][-1]["observed_entry"] == 140
    assert rows[1_700_000_900_000]["entry"] == 130
    untouched = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert untouched["entry"] == 100.0
    assert untouched["stop"] == 101.0
    assert untouched["target"] == 98.0


def test_a_fresh_card_is_not_expired_because_another_market_was_scanned(tmp_path, monkeypatch):
    users, owner, _other = _user(tmp_path, monkeypatch)
    deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    assert expire_stale(owner["id"], "ETHUSDT", "15m", 1_700_000_100_000) == 0
    assert items(owner["id"])[0]["lifecycle"] == "active"


def test_an_unorderable_crypto_quantity_is_not_shown_as_a_size():
    size = qualify_size("BTCUSDT", 1000, 1, "USD", 100, 93)
    shown = present_size(size)
    assert size["quantity_orderable"] is True
    assert size["live_broker"] is False
    assert size["order"] is False
    shown = present_size(size)
    assert shown["executable_quantity"] == size["quantity"]
    assert shown["risk_budget"] == 10
    eth = present_size(qualify_size("ETHUSDT", 1000, 2.5, "USD", 200, 190))
    assert eth["executable_quantity"] == qualify_size("ETHUSDT", 1000, 2.5, "USD", 200, 190)["quantity"]
    assert "Risk budget" in eth["text"]
    gold = present_size(qualify_size("XAUUSD", 1000, 1, "USD", 2000, 1990))
    assert gold["executable_quantity"] == 1
    assert "troy_ounce" in gold["text"]
    page = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            Path("ops/app.py"),
            Path("ops/ui/dashboard.html"),
            Path("ops/ui/landing.html"),
            Path("ops/routes/pages.py"),
        )
    )
    assert "units, risk" not in page
    assert "account.quantity" not in page
