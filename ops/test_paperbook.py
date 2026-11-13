"""Paper orders are explicit, per user, and never filled from an ambiguous candle."""

import json
import time

from ops.inbox import deliver_evaluation, expire_stale
from ops.paperbook import load, migrate, observe, open_order, summary
from ops.users import register, save_inbox_delivery, update_profile


def _account(tmp_path, monkeypatch, style="apex_momentum", capital=1000):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = register("ada", "password-s")
    other = register("bea", "password-s")
    update_profile(owner["id"], {"signal_style": style, "capital": capital, "currency": "USD"})
    update_profile(other["id"], {"signal_style": style, "capital": capital, "currency": "USD"})
    settings = {"experimental": True, "markets": ["BTCUSDT", "ETHUSDT", "XAUUSD"], "timeframes": ["15m", "1h"], "buy": True, "sell": True}
    save_inbox_delivery(owner["id"], settings)
    save_inbox_delivery(other["id"], settings)
    return users, owner, other


def _plan(**changes):
    base = {
        "symbol": "BTCUSDT", "interval": "15m", "decision": "SELL", "entry": 100.0, "stop": 101.0, "target": 97.0,
        "strategy": "interval-reading", "rule": "Trend pullback", "fresh": True, "reference_price": 100.0,
        "bar_close_ms": 1_700_000_000_000, "approved": False, "reward_risk": 3.0,
    }
    base.update(changes)
    return base


def test_a_saved_plan_can_be_opened_and_does_not_rewrite_its_prices(tmp_path, monkeypatch):
    users, owner, other = _account(tmp_path, monkeypatch)
    delivered = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    assert delivered["stored"] is True
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    from ops.paperbook import opportunity_row
    row = opportunity_row(owner["id"], delivered["opportunity_id"])
    opened = open_order(user, row, 1_700_000_100_000)
    assert opened["ok"] is True
    assert opened["order"]["executable"] is False
    assert opened["order"]["entry"] == 100.0
    assert summary(owner["id"])["trades"] == 0
    assert summary(owner["id"])["pnl_usd"] is None
    again = open_order(user, row, 1_700_000_200_000)
    assert again["reason"] == "already_open"
    from ops.paperbook import opportunity_row as lookup
    assert lookup(other["id"], delivered["opportunity_id"]) is None
    assert summary(other["id"])["empty"] is True


def test_a_live_flag_does_not_send_before_the_risk_check(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch)
    delivered = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    user["profile"]["live_trading"] = True
    calls = []
    monkeypatch.setattr("ops.live_broker.execute", lambda *args, **kwargs: calls.append(args) or {"ok": True, "sent": True, "reason": "opened"})
    from ops.paperbook import opportunity_row
    opened = open_order(user, opportunity_row(owner["id"], delivered["opportunity_id"]), 1_700_000_100_000)
    assert calls == []
    assert opened["ok"] is True
    assert opened["order"]["venue"] == "paper"
    assert opened["order"]["executable"] is False



def test_stop_target_and_ambiguous_candles(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch)
    delivered = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(decision="BUY", entry=100, stop=99, target=103))
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    from ops.paperbook import opportunity_row
    opened = open_order(user, opportunity_row(owner["id"], delivered["opportunity_id"]), 1_700_000_100_000)
    assert opened["ok"] is True
    both = observe(owner["id"], "BTCUSDT", "15m", {"high": 104, "low": 98}, 1_700_000_200_000)
    assert both["updated"] == 1
    assert summary(owner["id"])["ambiguous"][0]["pnl_usd"] is None
    assert summary(owner["id"])["trades"] == 0
    delivered_sell = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    opened_sell = open_order(users.get(owner["id"]) | {"id": owner["id"]}, opportunity_row(owner["id"], delivered_sell["opportunity_id"]), 1_700_000_300_000)
    assert opened_sell["ok"] is True
    observe(owner["id"], "BTCUSDT", "15m", {"high": 100.2, "low": 96}, 1_700_000_400_000)
    closed = summary(owner["id"])["closed"]
    assert len(closed) == 1
    assert closed[0]["status"] == "target"
    assert closed[0]["entry"] == 100.0
    assert closed[0]["pnl_usd"] is not None
    assert closed[0]["cost_usd"] > 0


def test_persona_floor_daily_loss_and_gold_refuse_the_order(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch, style="aegis_shield")
    weak = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(target=98.2))
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    from ops.paperbook import opportunity_row
    refused = open_order(user, opportunity_row(owner["id"], weak["opportunity_id"]), 1_700_000_100_000)
    assert refused["reason"] == "below_persona_reward"
    strong = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(bar_close_ms=1_700_000_900_000, target=97))
    assert open_order(user, opportunity_row(owner["id"], strong["opportunity_id"]), 1_700_000_900_000)["ok"] is True
    book = load(owner["id"])
    book["orders"][0]["status"] = "stopped"
    book["orders"][0]["pnl_usd"] = -20
    book["orders"][0]["closed_ms"] = 1_700_000_900_000
    from ops.paperbook import save
    save(owner["id"], book)
    another = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(bar_close_ms=1_700_001_800_000, target=97))
    blocked = open_order(users.get(owner["id"]) | {"id": owner["id"]}, opportunity_row(owner["id"], another["opportunity_id"]), 1_700_000_950_000)
    assert blocked["reason"] == "daily_loss"
    gold = {
        "opportunity_id": "opp:XAUUSD:1h:Trend pullback:SELL:1",
        "symbol": "XAUUSD", "interval": "1h", "direction": "SELL", "family": "Trend pullback",
        "entry": 2000, "stop": 2010, "target": 1970, "lifecycle": "active",
    }
    opened_gold = open_order(user, gold, 1_700_000_950_000 + 3 * 86_400_000)
    assert opened_gold.get("reason") != "contract_unverified"


def test_a_legacy_list_is_readable_and_a_new_bar_is_not_expired_with_it(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch)
    path = users.ROOT / "paper" / f"{owner['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"id": "old", "status": "target", "entry": 10, "pnl_usd": 1, "symbol": "BTCUSDT"}]), encoding="utf-8")
    migrated = load(owner["id"])
    assert migrated["schema"] == 1
    assert migrated["orders"][0]["entry"] == 10
    assert migrate({"orders": [{"entry": 10}]})["orders"][0]["entry"] == 10
    delivered = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    from ops.inbox import items
    far = 1_700_000_000_000 + 10 * 15 * 60 * 1000
    assert expire_stale(owner["id"], "BTCUSDT", "15m", far, protect_bar_ms=1_700_000_000_000) == 0
    assert items(owner["id"])[0]["lifecycle"] == "active"
    assert expire_stale(owner["id"], "BTCUSDT", "15m", far) == 1


def test_paper_route_is_private(tmp_path, monkeypatch):
    users, owner, other = _account(tmp_path, monkeypatch)
    delivered = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    from ops.app import app
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.get("/api/paper/book").status_code == 401
    with client.session_transaction() as sess:
        sess["user_id"] = other["id"]
        sess["user_exp"] = time.time() + 3600
    missing = client.post("/api/paper/orders", json={"opportunity_id": delivered["opportunity_id"]})
    assert missing.status_code == 404
    assert client.get("/api/paper/book").get_json()["empty"] is True
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["user_exp"] = time.time() + 3600
    opened = client.post("/api/paper/orders", json={"opportunity_id": delivered["opportunity_id"]})
    assert opened.status_code == 200
    assert opened.get_json()["order"]["entry"] == 100.0
    closed = client.post("/api/paper/close", json={"order_id": opened.get_json()["order"]["id"], "exit_price": 98})
    assert closed.status_code == 200
    assert closed.get_json()["order"]["entry"] == 100.0
    assert client.get("/api/paper/book").get_json()["performance"]["trades"] == 1
    page = client.get("/portfolio").get_data(as_text=True)
    assert "No completed paper trade" in page or "paper" in page.lower()


def test_a_manual_close_is_the_only_new_pnl_and_ambiguous_is_excluded(tmp_path, monkeypatch):
    users, owner, other = _account(tmp_path, monkeypatch)
    delivered = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(decision="BUY", entry=100, stop=99, target=103))
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    from ops.paperbook import close_order, opportunity_row, performance
    opened = open_order(user, opportunity_row(owner["id"], delivered["opportunity_id"]), 1_700_000_100_000)
    assert performance(owner["id"])["win_rate"] is None
    missing = close_order(owner["id"], opened["order"]["id"], None, 1_700_000_200_000)
    assert missing["reason"] == "missing_exit"
    closed = close_order(owner["id"], opened["order"]["id"], 102, 1_700_000_200_000)
    assert closed["ok"] is True
    assert closed["order"]["entry"] == 100.0
    assert closed["order"]["stop"] == 99.0
    assert closed["order"]["cost_usd"] > 0
    figures = performance(owner["id"])
    assert figures["trades"] == 1
    assert figures["win_rate"] == 1
    second = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    opened_sell = open_order(users.get(owner["id"]) | {"id": owner["id"]}, opportunity_row(owner["id"], second["opportunity_id"]), 1_700_000_300_000)
    observe(owner["id"], "BTCUSDT", "15m", {"high": 102, "low": 96}, 1_700_000_400_000)
    assert summary(owner["id"])["ambiguous"]
    assert performance(owner["id"])["trades"] == 1
    assert close_order(other["id"], opened["order"]["id"], 102, 1_700_000_500_000)["reason"] == "missing"
    saved = users.get(owner["id"])
    assert saved["paper_orders_today"] == 2
    assert opened_sell["ok"] is True


def test_public_chart_covers_gold_without_inventing_minutes():
    from ops.worker import pair_availability
    rows = pair_availability()
    assert len(rows) == 12
    gold = [row for row in rows if row["symbol"] == "XAUUSD"]
    assert {row["interval"] for row in gold} == {"1m", "3m", "15m", "1h"}
    minutes = [row for row in gold if row["interval"] in {"1m", "3m"}]
    assert all(row["status"] == "unsupported" and row["reason"] == "xau_minute_unsupported" for row in minutes)
    offered = [row for row in gold if row["interval"] in {"15m", "1h"}]
    assert all(row["feed"] == "xaus_public_chart" and row["status"] == "ready" for row in offered)


def test_a_completed_candle_exit_is_not_an_account_exit(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch)
    delivered = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan(decision="BUY", entry=100, stop=99, target=103))
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    from ops.paperbook import opportunity_row
    opened = open_order(user, opportunity_row(owner["id"], delivered["opportunity_id"]), 1_700_000_100_000)
    bar = {"high": 104, "low": 100.2, "close": 103.2, "close_time_ms": 1_700_000_200_000, "provider": "binance", "quote_semantics": "last_trade"}
    observe(owner["id"], "BTCUSDT", "15m", bar, 1_700_000_200_000, {"name": "binance", "bar_close_ms": bar["close_time_ms"], "quote": "last_trade"})
    done = summary(owner["id"])["closed"][0]
    assert done["exit_kind"] == "market_target"
    assert done["entry"] == 100
    assert done["stop"] == 99
    assert done["target"] == 103
    assert done["planned_exit"] == 103
    assert done["exit_price"] < 103
    assert done["slippage_bps"] == 2
    assert done["events"][-1]["source"] == "binance"
    assert "broker" in done["events"][-1]["note"]


def test_personas_share_the_setup_and_aegis_does_not_paper_a_one_minute_scalp(tmp_path, monkeypatch):
    from ops.terminal_signal import apply_persona
    from ops.users import update_profile
    users, owner, _other = _account(tmp_path, monkeypatch, style="aegis_shield")
    users_mod = users
    users_mod.save_inbox_delivery = save_inbox_delivery
    save_inbox_delivery(owner["id"], {"experimental": True, "markets": ["BTCUSDT"], "timeframes": ["1m", "15m", "1h"], "buy": True, "sell": True})
    buy = {"decision": "BUY", "reward_risk": 1.8, "symbol": "BTCUSDT", "interval": "15m", "entry": 100, "stop": 99, "target": 102, "rule": "Trend pullback"}
    sell = {"decision": "SELL", "reward_risk": 1.8, "symbol": "BTCUSDT", "interval": "15m", "entry": 100, "stop": 101, "target": 97, "rule": "Trend pullback"}
    apex = {"profile": {"signal_style": "apex_momentum", "capital": 1000, "currency": "USD"}, "plan": {"risk_per_trade_percent": 2.5}}
    shield = {"profile": {"signal_style": "aegis_shield", "capital": 1000, "currency": "USD"}, "plan": {"risk_per_trade_percent": 0.8}}
    assert apply_persona(buy, apex)["decision"] == "BUY"
    assert apply_persona(sell, apex)["decision"] == "SELL"
    assert apply_persona(buy, apex)["persona_policy"]["entry_rule"] == "shared"
    assert apply_persona(sell, shield)["persona_policy"]["entry_rule"] == "shared"
    assert apply_persona(buy, shield)["account_status"] == "visible_unsized"
    assert apply_persona(sell, shield)["account_status"] == "visible_unsized"
    assert apply_persona(buy, apex)["persona_release"] is True
    assert apply_persona(sell, apex)["persona_release"] is True
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    minute = {"opportunity_id": "opp:BTCUSDT:1m:Trend pullback:SELL:1", "symbol": "BTCUSDT", "interval": "1m", "direction": "SELL", "entry": 100, "stop": 101, "target": 97, "lifecycle": "active", "family": "Trend pullback"}
    assert open_order(user, minute, 1_700_000_100_000)["reason"] == "persona_timeframe"
    update_profile(owner["id"], {"signal_style": "apex_momentum", "capital": 1000, "currency": "USD"})
    apex_user = users.get(owner["id"])
    apex_user["id"] = owner["id"]
    assert open_order(apex_user, minute, 1_700_000_100_000)["ok"] is True


def test_gold_minute_bars_do_not_become_a_plan():
    from ops.terminal_signal import decide
    now = 1_700_000_060_000
    bars = [{
        "high": 2001, "low": 1999, "close": 2000, "complete": True, "close_time_ms": now - 1000,
        "provider": "dukascopy", "quote_semantics": "dukascopy_xauusd_bid_ask",
    }] * 80
    result = decide("XAUUSD", "1m", "auto", bars, now, None)
    assert result["decision"] == "WAIT"
    assert result.get("entry") is None
    assert result["blocked"] in {"quote_not_bid_ask", "timeframe", "incomplete_candle"}
