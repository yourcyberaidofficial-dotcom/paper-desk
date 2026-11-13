"""Stage 5: paper excursion learning stays research, and the desk routes are split."""

import pytest
from pathlib import Path

import ops.simulate as simulate_mod

from ops.paperbook import load, observe, open_order, performance, save
from ops.qualification import MIN_COMPLETED_TRADES, catalog, paper_research
from ops.schema_guard import CURRENT
from ops.test_paperbook import _account, _plan


def _user(tmp_path, monkeypatch):
    users, owner, _other = _account(tmp_path, monkeypatch)
    user = users.get(owner["id"])
    user["id"] = owner["id"]
    return users, owner, user


def _completed_bars(now_ms):
    rows = []
    price = 100.0
    for index in range(4):
        rows.append({
            "complete": True,
            "open": price,
            "high": price + 0.4,
            "low": price - 0.1,
            "close": price + 0.2,
            "close_time_ms": now_ms - (4 - index) * 60_000,
        })
        price += 0.2
    return rows


def test_entry_context_is_stored_and_a_quiet_bar_updates_excursion_without_closing(tmp_path, monkeypatch):
    _users, owner, user = _user(tmp_path, monkeypatch)
    from ops.inbox import deliver_evaluation
    from ops.paperbook import opportunity_row

    delivered = deliver_evaluation(owner["id"], _users.get(owner["id"]), _plan(decision="BUY", entry=100, stop=99, target=103))
    opened = open_order(user, opportunity_row(owner["id"], delivered["opportunity_id"]), 1_700_000_100_000)
    assert opened["ok"] is True
    order = opened["order"]
    assert order["schema"] == 1
    assert order["initial_risk"] == 1
    assert order["mae_r"] is None
    assert order["mfe_r"] is None
    assert order["bars_held"] == 0
    assert order["realized_r"] is None
    assert order["excursion"] == "no_bar_yet"
    assert order["regime"]["source"] == "not_supplied"
    assert order["regime"]["trend"] == "unknown"
    assert order["session"] in {"utc_asia", "utc_london", "utc_new_york", "utc_late"}
    assert order.get("confidence") is None
    quiet = observe(
        owner["id"], "BTCUSDT", "15m",
        {"high": 100.4, "low": 99.6, "close": 100.1},
        1_700_000_200_000,
        bars=_completed_bars(1_700_000_200_000),
    )
    assert quiet["updated"] == 0
    assert quiet["excursion"] == 1
    stored = load(owner["id"])["orders"][0]
    assert stored["status"] == "open"
    assert stored["pnl_usd"] is None
    assert stored["mae_r"] == pytest.approx(0.4)
    assert stored["mfe_r"] == pytest.approx(0.4)
    assert stored["bars_held"] == 1
    assert stored["excursion"] == "measured"
    assert stored["regime"]["source"] == "bars_already_in_hand"
    assert stored["regime"]["trend"] != "unknown"
    worse = observe(owner["id"], "BTCUSDT", "15m", {"high": 100.2, "low": 99.2}, 1_700_000_300_000)
    assert worse["updated"] == 0
    followed = load(owner["id"])["orders"][0]
    assert followed["mae_r"] == pytest.approx(0.8)
    assert followed["mfe_r"] == pytest.approx(0.4)
    assert followed["bars_held"] == 2
    missing = observe(owner["id"], "BTCUSDT", "15m", {"close": 100}, 1_700_000_400_000)
    assert missing["excursion"] == 0
    assert load(owner["id"])["orders"][0]["bars_held"] == 2
    assert load(owner["id"])["orders"][0]["mae_r"] == pytest.approx(0.8)


def test_stop_target_and_ambiguous_keep_pnl_rules_and_record_r(tmp_path, monkeypatch):
    _users, owner, user = _user(tmp_path, monkeypatch)
    from ops.inbox import deliver_evaluation
    from ops.paperbook import opportunity_row

    def boom(*_args, **_kwargs):
        raise AssertionError("learning called a simulator or a model")

    monkeypatch.setattr("ops.simulate.simulate", boom)
    monkeypatch.setattr("ops.ollama.health", boom)
    delivered = deliver_evaluation(owner["id"], _users.get(owner["id"]), _plan(decision="BUY", entry=100, stop=99, target=103))
    opened = open_order(user, opportunity_row(owner["id"], delivered["opportunity_id"]), 1_700_000_100_000)
    stopped = observe(owner["id"], "BTCUSDT", "15m", {"high": 100.2, "low": 98.5}, 1_700_000_200_000)
    assert stopped["updated"] == 1
    row = load(owner["id"])["orders"][0]
    assert row["status"] == "stopped"
    assert row["pnl_usd"] is not None
    assert row["realized_r"] is not None
    assert row["realized_r"] < 0
    assert row["mae_r"] >= 1
    figures = performance(owner["id"])
    assert figures["win_rate"] == 0
    assert figures["diagnostics"]["sample"] == "not_enough_evidence"
    assert figures["diagnostics"]["expectancy_r"] is None
    assert figures["diagnostics"]["confidence"] is None
    assert figures["diagnostics"]["promotes"] is False
    second = deliver_evaluation(
        owner["id"], _users.get(owner["id"]),
        _plan(decision="SELL", entry=100, stop=101, target=97, bar_close_ms=1_700_000_900_000),
    )
    opened_sell = open_order(user, opportunity_row(owner["id"], second["opportunity_id"]), 1_700_000_900_000)
    assert opened_sell["ok"] is True
    both = observe(owner["id"], "BTCUSDT", "15m", {"high": 102, "low": 96}, 1_700_000_950_000)
    assert both["updated"] == 1
    ambiguous = [item for item in load(owner["id"])["orders"] if item["status"] == "ambiguous"][0]
    assert ambiguous["pnl_usd"] is None
    assert ambiguous["realized_r"] is None
    assert performance(owner["id"])["trades"] == 1


def test_a_supplied_regime_is_not_replaced_and_gold_uses_the_existing_clock(tmp_path, monkeypatch):
    _users, owner, user = _user(tmp_path, monkeypatch)
    gold = {
        "opportunity_id": "opp:XAUUSD:1h:Trend pullback:SELL:9",
        "symbol": "XAUUSD", "interval": "1h", "direction": "SELL", "family": "Trend pullback",
        "version": "xau-session-20261027", "snapshot_id": "snap-9",
        "entry": 2000, "stop": 2010, "target": 1970, "lifecycle": "active",
        "regime": {"trend": "falling", "momentum": "down", "volatility": "ordinary", "freshness": "fresh"},
    }
    opened = open_order(user, gold, 1_700_000_100_000, bars=[{"complete": True, "close": 1}])
    assert opened["ok"] is True
    order = opened["order"]
    assert order["strategy_version"] == "xau-session-20261027"
    assert order["snapshot_id"] == "snap-9"
    assert order["regime"]["source"] == "supplied"
    assert order["regime"]["trend"] == "falling"
    assert order["session"].startswith("gold_")
    assert order["initial_risk"] == 10
    path = Path(tmp_path) / "users" / "paper" / f"{owner['id']}.json"
    assert path.is_file()
    from ops.paths import on_volume
    assert on_volume(path) is True
    assert CURRENT == 1


def test_small_samples_stay_unenforced_and_a_counted_sample_still_does_not_promote(tmp_path, monkeypatch):
    _users, owner, user = _user(tmp_path, monkeypatch)
    from ops.learning import for_account, stress_comparison

    original = simulate_mod.simulate

    def boom(*_args, **_kwargs):
        raise AssertionError("simulation ran without bars")

    monkeypatch.setattr(simulate_mod, "simulate", boom)
    refused = stress_comparison("BTCUSDT", [], [], "tf-pullback-20261027")
    assert refused["ran"] is False
    assert refused["promotes"] is False
    assert refused["confidence"] is None
    monkeypatch.setattr(simulate_mod, "simulate", original)
    early = for_account(owner["id"])
    assert early["sample"] == "not_enough_evidence"
    assert early["expectancy_r"] is None
    assert early["model"]["called"] is False
    assert early["simulation"]["ran"] is False
    assert all(item["promotes"] is False and item["confidence"] is None for item in early["hypotheses"])
    orders = []
    for index in range(MIN_COMPLETED_TRADES):
        stopped = index < 16
        orders.append({
            "id": f"paper:x:{index}",
            "status": "stopped" if stopped else "target",
            "exit_kind": "market_stop" if stopped else "market_target",
            "pnl_usd": -1.0 if stopped else 2.0,
            "risk_budget_usd": 1.0,
            "realized_r": -1.0 if stopped else 2.0,
            "mae_r": 1.2 if stopped else 0.4,
            "symbol": "BTCUSDT",
            "interval": "15m",
            "family": "Trend pullback",
            "strategy_version": "tf-pullback-20261027",
            "session": "utc_london",
            "regime": {"trend": "rising" if index % 2 == 0 else "falling", "source": "supplied"},
            "direction": "BUY",
        })
    orders.append({"id": "amb", "status": "ambiguous", "pnl_usd": None, "exit_kind": "unresolved"})
    save(owner["id"], {"schema": 1, "orders": orders})
    counted = paper_research(owner["id"])
    assert counted["sample"] == "counted"
    assert counted["closed_trades"] == MIN_COMPLETED_TRADES
    assert counted["ambiguous"] == 1
    assert counted["expectancy_r"] is not None
    assert counted["confidence"] is None
    assert counted["promotes"] is False
    assert counted["changes_approval"] is False
    assert counted["holdout_opened"] is False
    assert counted["registry_approved_for_paper"] == 0
    assert any("Stops were observed before targets" in item["statement"] for item in counted["hypotheses"])
    assert all(item["promotes"] is False for item in counted["hypotheses"])
    body = catalog()
    assert body["approved_for_paper"] == 0
    assert "approved_for_paper" not in {row["lifecycle"] for row in body["strategies"]}
    compared = stress_comparison("BTCUSDT", _completed_bars(1_700_000_000_000), [], "not-a-strategy")
    assert compared["ran"] is False
    assert compared["reason"] == "unknown_strategy"
    assert compared["promotes"] is False
    short = stress_comparison("BTCUSDT", _completed_bars(1_700_000_000_000), [], "tf-pullback-20261027")
    assert short["ran"] is True
    assert short["sample"] == "not_enough_evidence"
    assert short["base_mean"] is None
    assert short["promotes"] is False
    assert short["approved_for_paper"] is False
    assert short["confidence"] is None


def test_lab_and_qualification_show_learning_without_a_model_or_a_new_route(tmp_path, monkeypatch):
    _users, owner, _user_row = _user(tmp_path, monkeypatch)

    def boom(*_args, **_kwargs):
        raise AssertionError("the page called a model")

    monkeypatch.setattr("ops.ollama.health", boom)
    monkeypatch.setattr("ops.ollama.explain", boom)
    from ops.app import DASHBOARD, _digest_loop, _loop, _telegram_loop, app, desk_runtime

    assert _loop and _telegram_loop and _digest_loop and desk_runtime
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["user_exp"] = 9_999_999_999
        sess["csrf"] = "b" * 32
    lab = client.get("/api/lab").get_json()
    assert lab["learning"]["sample"] == "not_enough_evidence"
    assert lab["learning"]["model"]["called"] is False
    assert lab["learning"]["confidence"] is None
    assert lab["learning"]["promotes"] is False
    assert lab["observation"].startswith("Not enough")
    qualification = client.get("/api/qualification").get_json()
    assert qualification["approved_for_paper"] == 0
    assert qualification["paper_research"]["promotes"] is False
    assert qualification["paper_research"]["changes_approval"] is False
    assert "function paperLearning(" in DASHBOARD
    source = Path("ops/app.py").read_text(encoding="utf-8")
    assert "function watchTelegram()" not in source
    assert "def digest(" in source
    assert '_spawn(_digest_loop, "aureon-digest")' in source
    assert len(source.splitlines()) < 4000
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    assert "desk_pages.landing" in endpoints
    assert "paper_api.paper_book" in endpoints
    assert "research_api.lab_state" in endpoints
    assert "research_api.qualification_api" in endpoints
    lab_rules = [rule for rule in app.url_map.iter_rules() if rule.rule == "/api/lab"]
    assert {rule.endpoint for rule in lab_rules} == {"research_api.lab_state", "research_api.lab_save"}
    assert sum(1 for rule in app.url_map.iter_rules() if rule.rule == "/api/qualification") == 1
    assert sum(1 for rule in app.url_map.iter_rules() if rule.rule == "/") == 1
    assert "/api/learning" not in {rule.rule for rule in app.url_map.iter_rules()}
