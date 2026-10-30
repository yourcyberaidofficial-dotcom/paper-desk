"""Account policy. No family-count gate and no invented money."""

from ops.inbox import append_event, deliver_evaluation, items
from ops.plan import observe_levels, paper_cap_status, qualify_size
from ops.terminal_signal import apply_persona
from ops.users import register, save_inbox_delivery


def _plan(decision="SELL"):
    return {
        "symbol": "BTCUSDT",
        "interval": "15m",
        "decision": decision,
        "reward_risk": 1.8,
        "entry": 100.0,
        "stop": 101.0 if decision == "SELL" else 99.0,
        "target": 98.2 if decision == "SELL" else 101.8,
        "strategy": "interval-reading",
        "rule": "Trend pullback",
        "fresh": True,
        "reference_price": 100.0,
        "bar_close_ms": 1_700_000_000_000,
        "version": "interval-reading",
        "approved": False,
        "runtime_status": "experimental",
    }


def _user(style, currency="USD"):
    return {"profile": {"signal_style": style, "capital": 1000, "currency": currency}, "plan": {}, "paper_orders_today": 0}


def test_a_short_uses_the_same_reward_floor_as_a_long():
    withheld = apply_persona(_plan(), _user("orion_precision"))
    assert withheld["decision"] == "SELL"
    assert withheld["account_status"] == "visible_unsized"
    assert withheld["size"]["reason"] == "below_persona_reward"
    assert "2.0" in withheld["persona_note"]
    sized = apply_persona(_plan(), _user("apex_momentum"))
    assert sized["decision"] == "SELL"
    assert sized["size"]["budget_ok"] is True
    assert sized["size"]["quantity_orderable"] is False
    assert sized["size"]["order"] is False
    assert "vote" not in sized["persona_note"].lower()


def test_missing_fx_and_an_unknown_gold_contract_are_not_invented():
    fx = qualify_size("BTCUSDT", 1000, 1, "NGN", 100, 99)
    assert fx["reason"] == "fx_unverified"
    assert fx["budget_ok"] is False
    gold = qualify_size("XAUUSD", 1000, 1, "USD", 2000, 1990)
    assert gold["reason"] == "contract_unverified"
    assert gold["quantity_orderable"] is False
    assert gold["risk_budget_usd"] == 10


def test_a_candle_that_reaches_both_levels_is_ambiguous():
    both = observe_levels("BUY", 99, 102, {"high": 103, "low": 98})
    assert both["state"] == "ambiguous"
    assert "not a fill" in both["note"]
    stop_only = observe_levels("BUY", 99, 110, {"high": 105, "low": 98})
    assert stop_only["state"] == "stop_touched"


def test_the_daily_cap_counts_paper_orders_not_notifications():
    quiet = paper_cap_status(5, 0)
    assert quiet["blocks_notification"] is False
    assert quiet["blocks_new_paper_order"] is False
    full = paper_cap_status(2, 2)
    assert full["blocks_new_paper_order"] is True
    assert full["notifications_count"] is False


def test_a_later_reading_of_the_same_idea_does_not_rewrite_the_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = register("ada", "password-s")
    save_inbox_delivery(owner["id"], {"experimental": True, "markets": ["BTCUSDT"], "timeframes": ["15m"], "sell": True})
    first = deliver_evaluation(owner["id"], users.get(owner["id"]), _plan())
    assert first["stored"] is True
    changed = dict(_plan())
    changed["bar_close_ms"] = 1_700_000_900_000
    changed["entry"] = 105
    changed["stop"] = 106
    changed["target"] = 103
    second = deliver_evaluation(owner["id"], users.get(owner["id"]), changed)
    assert second["stored"] is False
    assert second["reason"] == "same_opportunity"
    saved = items(owner["id"])[0]
    assert saved["entry"] == 100.0
    assert saved["stop"] == 101.0
    assert saved["target"] == 98.2
    assert saved["events"][-1]["observed_entry"] == 105
    touched = append_event(owner["id"], saved["opportunity_id"], {
        "id": "evt-touch",
        "state": "ambiguous",
        "note": "This candle reached both the stop and the target. This is not a fill.",
    })
    assert touched["stored"] is True
    again = items(owner["id"])[0]
    assert again["entry"] == 100.0
    assert again["lifecycle"] == "ambiguous"
