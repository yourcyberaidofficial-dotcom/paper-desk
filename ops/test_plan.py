"""Personal plan, evidence grade, and closed-candle handling. No network."""

from ops.delivery import authorize
from ops.kline import closed_bar
from ops.plan import evidence_grade, normalize, propose_size, visible_to_user, week_status
from ops.registry import catalog
from ops.users import get, register, save_plan, update_profile


def test_registry_keeps_every_strategy_unapproved():
    body = catalog()
    assert body["promoted_count"] == 0
    assert {row["id"] for row in body["strategies"]} >= {"E1-donchian-20", "xau-session-20261027"}
    assert all(row["promoted"] is False and row["research_status"] in {"FAIL", "BLOCKED"} for row in body["strategies"])


def test_evidence_grade_is_a_checklist_not_a_probability():
    grade = evidence_grade({"completed_bar": True, "fresh": True, "enough_history": True, "rule_checked": True, "explained": True, "promoted": False})
    assert grade["evidence_grade"] == 90
    assert grade["calibrated"] is False
    assert "probability" in grade["label"]
    assert evidence_grade({})["evidence_grade"] == 0


def test_apex_request_above_the_cap_is_rejected_and_does_not_approve(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    user = register("plan-user", "password-s")
    update_profile(user["id"], {"signal_style": "apex_momentum", "capital": 1000, "currency": "USD"})
    saved = save_plan(user["id"], {"mode": "auto", "risk_per_trade_percent": 4, "min_evidence_grade": 10, "weekly_aim_percent": 5})
    assert saved["plan"]["risk_per_trade_percent"] == 2.5
    assert any("2.5" in note for note in saved["plan_notes"])
    assert get(user["id"])["profile"]["currency"] == "USD"
    assert get(user["id"])["profile"]["capital"] == 1000
    size = propose_size(1000, saved["plan"]["risk_per_trade_percent"], 100, 99)
    assert size["ok"] is True
    assert size["quantity"] == 25
    assert size["order"] is False
    assert propose_size(1000, 2.5, 100, 100)["ok"] is False
    event = {"strategy": "E1-donchian-20", "symbol": "BTCUSDT", "state": "RESEARCH_OBSERVATION", "evidence_grade": 5}
    decision = visible_to_user(event, saved["plan"])
    assert decision["reason"] == "below_threshold"
    assert decision.get("trade_alert") is not True
    week = week_status(saved["plan"], 1_760_000_000_000, recorded=[])
    assert week["paper_pnl"] is None
    assert week["forces_signals"] is False
    blocked = authorize({"state": "RESEARCH_OBSERVATION", "text": "research note", "symbol": "BTCUSDT", "interval": "15m"}, {"alerts_on": True, "markets": ["BTCUSDT"], "timeframes": {"BTCUSDT": "15m"}, "telegram": {"verified": True, "revoked": False, "chat_id": "1"}}, registry=[])
    assert blocked["send"] is False


def test_closed_kline_rejects_a_forming_candle():
    forming = {"k": {"x": False, "s": "BTCUSDT", "i": "15m", "t": 1, "T": 2, "o": "1", "h": "2", "l": "1", "c": "1.5"}}
    assert closed_bar(forming, "BTCUSDT", "15m") is None
    closed = {"k": {"x": True, "s": "BTCUSDT", "i": "15m", "t": 900000, "T": 1799999, "o": "100", "h": "110", "l": "90", "c": "105"}}
    bar = closed_bar(closed, "BTCUSDT", "15m")
    assert bar["complete"] is True
    assert bar["close"] == 105


def test_two_plans_do_not_share_a_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    first = register("ada", "password-s")
    second = register("bea", "password-s")
    update_profile(first["id"], {"signal_style": "orion_precision"})
    update_profile(second["id"], {"signal_style": "aegis_shield"})
    save_plan(first["id"], {"min_evidence_grade": 80, "mode": "selected", "strategies": ["E1-donchian-20"]})
    save_plan(second["id"], {"min_evidence_grade": 20, "mode": "auto"})
    assert get(first["id"])["plan"]["min_evidence_grade"] == 80
    assert get(second["id"])["plan"]["min_evidence_grade"] == 20
    assert get(second["id"])["plan"]["risk_per_trade_percent"] == 0.8
    assert normalize({"risk_per_trade_percent": 9}, {}, 1.5)["risk_per_trade_percent"] == 1.5
