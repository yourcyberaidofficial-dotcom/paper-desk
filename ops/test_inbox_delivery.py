"""Preference-controlled inbox delivery. Fixtures only. No Telegram."""

import time

from ops.bars import make_bar
from ops.inbox import deliver_evaluation, items
from ops.terminal_signal import decide
from ops.users import register, save_inbox_delivery


def _user(tmp_path, monkeypatch, name):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    return register(name, "password-s")


def _flat(index, close=100, high=100.2, low=99.9, start=1_700_000_000_000):
    step = 14_400_000
    start = start - (start % step)
    open_time = start + index * step
    return make_bar(
        symbol="BTCUSDT", interval="4h", open_time_ms=open_time, close_time_ms=open_time + step - 1,
        open=close, high=high, low=low, close=close, volume=1, complete=True, fresh=True,
        provider="fixture", source_type="fixture", quote_semantics="last_trade",
    )


def _compress():
    bars = []
    for index in range(50):
        if index < 38:
            bars.append(_flat(index, close=100, high=110, low=90))
        else:
            bars.append(_flat(index, close=100, high=100.4, low=99.8))
    bars[-1] = _flat(49, close=106, high=107, low=100)
    return bars


def _account():
    return {"profile": {"capital": 1000, "currency": "USD", "signal_style": "orion_balance"}, "plan": {"risk_per_trade_percent": 1}}


def test_filters_control_delivery_and_stay_private(tmp_path, monkeypatch):
    first = _user(tmp_path, monkeypatch, "ada")
    import ops.users as users
    second = register("bea", "password-s")
    bars = _compress()
    now = bars[-1]["close_time_ms"] + 1000
    match = decide("BTCUSDT", "4h", "compress-break-4h-20261028", bars, now, _account())
    assert match["decision"] == "BUY"
    assert match["approved"] is False
    blocked = deliver_evaluation(first["id"], {}, match)
    assert blocked["reason"] == "experimental_off"
    assert items(first["id"]) == []
    save_inbox_delivery(first["id"], {"experimental": True})
    user = users.get(first["id"])
    delivered = deliver_evaluation(first["id"], user, match)
    assert delivered["stored"] is True
    again = deliver_evaluation(first["id"], user, match)
    assert again["duplicate"] is True
    assert len(items(first["id"])) == 1
    card = items(first["id"])[0]
    assert card["decision"] == "BUY"
    assert card["actionable"] is False
    assert card["approved"] is False
    assert "unapproved" in card["label"].lower()
    assert card["entry"] == match["entry"]
    assert items(second["id"]) == []
    eth_only = save_inbox_delivery(first["id"], {"experimental": True, "markets": ["ETHUSDT"]})
    assert deliver_evaluation(first["id"], eth_only, match)["reason"] == "market"
    no_buy = save_inbox_delivery(first["id"], {"experimental": True, "markets": ["BTCUSDT"], "buy": False})
    assert deliver_evaluation(first["id"], no_buy, match)["reason"] == "buy_off"
    off = save_inbox_delivery(first["id"], {"enabled": False, "experimental": True})
    assert deliver_evaluation(first["id"], off, match)["reason"] == "disabled"
    quiet = decide("BTCUSDT", "4h", "auto", [_flat(i) for i in range(50)], now, _account())
    assert quiet["decision"] == "WAIT"
    assert deliver_evaluation(first["id"], users.get(first["id"]), quiet)["reason"] == "disabled"
    waiting = save_inbox_delivery(first["id"], {"enabled": True, "wait_notices": False})
    assert deliver_evaluation(first["id"], waiting, quiet)["reason"] == "wait_suppressed"
    notices = save_inbox_delivery(first["id"], {"wait_notices": True})
    assert deliver_evaluation(first["id"], notices, quiet)["stored"] is True
    assert items(first["id"])[0]["label"] == "WAIT notice. Not a trade." or any(
        row.get("label") == "WAIT notice. Not a trade." for row in items(first["id"])
    )
    gold = _flat(0, close=2300)
    gold["symbol"] = "XAUUSD"
    gold["interval"] = "1h"
    gold["quote_semantics"] = "ohlc_not_bid_ask"
    blocked_gold = decide("XAUUSD", "1h", "auto", [gold], gold["close_time_ms"] + 1000, _account())
    assert blocked_gold["blocked"] == "quote_not_bid_ask"
    assert deliver_evaluation(first["id"], notices, blocked_gold)["reason"] == "blocked"
    gold["quote_semantics"] = "dukascopy_xauusd_bid_ask"
    gold["ask_open"] = 2301
    gold["complete"] = True
    evaluated = decide("XAUUSD", "1h", "london-reclaim-1h-20261028", [gold], gold["close_time_ms"] + 1000, _account())
    assert evaluated.get("blocked") != "quote_not_bid_ask"
    official = dict(match)
    official["approved"] = True
    official["validation_status"] = "PASS"
    official["eligible_for_alert"] = True
    official["decision"] = "BUY"
    refused = deliver_evaluation(first["id"], save_inbox_delivery(first["id"], {"experimental": True}), official)
    assert refused["stored"] is False
    assert all(row.get("kind") != "official" for row in items(first["id"]))


def test_settings_and_signal_route_keep_users_apart(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    from ops.app import app
    created = users.register("ada", "password-s")
    other = users.register("bea", "password-s")
    users.update_profile(created["id"], {"capital": 1000, "currency": "USD", "signal_style": "orion_balance"})
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.get("/api/inbox/settings").status_code == 401
    with client.session_transaction() as sess:
        sess["user_id"] = created["id"]
        sess["user_exp"] = time.time() + 3600
    saved = client.post("/api/inbox/settings", json={"experimental": True, "markets": ["BTCUSDT"], "timeframes": ["4h"], "wait_notices": False})
    assert saved.status_code == 200
    assert saved.get_json()["settings"]["experimental"] is True
    client.get("/api/logout")
    with client.session_transaction() as sess:
        sess.clear()
    with client.session_transaction() as sess:
        sess["user_id"] = other["id"]
        sess["user_exp"] = time.time() + 3600
    assert client.get("/api/inbox/settings").get_json()["settings"]["experimental"] is False
    assert client.get("/api/notifications").get_json()["items"] == []


def test_a_short_idea_is_delivered_only_when_sell_and_experimental_are_on(tmp_path, monkeypatch):
    owner = _user(tmp_path, monkeypatch, "cara")
    import ops.users as users
    bars = []
    for index in range(80):
        close = 200 - index * 0.15
        bars.append(_flat(index, close=close, high=close + 0.3, low=close - 0.3))
        bars[-1]["interval"] = "15m"
    last = bars[-1]["close"]
    bars[-1] = _flat(79, close=last - 0.05, high=last + 2, low=last - 0.4)
    bars[-1]["interval"] = "15m"
    now = bars[-1]["close_time_ms"] + 1000
    idea = decide("BTCUSDT", "15m", "auto", bars, now, _account())
    assert idea["decision"] == "SELL"
    assert idea["decision_label"] == "SELL · Short idea"
    assert idea["entry"] is not None and idea["stop"] > idea["entry"] > idea["target"]
    assert idea["order"] is False
    hidden = deliver_evaluation(owner["id"], {}, idea)
    assert hidden["stored"] is False
    sell_off = save_inbox_delivery(owner["id"], {"experimental": True, "sell": False, "timeframes": ["15m", "4h"]})
    assert deliver_evaluation(owner["id"], sell_off, idea)["reason"] == "sell_off"
    allowed = save_inbox_delivery(owner["id"], {"experimental": True, "sell": True, "timeframes": ["15m", "4h"]})
    stored = deliver_evaluation(owner["id"], allowed, idea)
    assert stored["stored"] is True
    card = items(owner["id"])[0]
    assert card["decision"] == "SELL"
    assert card["approved"] is False
    assert card["entry"] == idea["entry"]
    assert users.get(owner["id"])["inbox_delivery"]["experimental"] is True
