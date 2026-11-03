"""Recorded research stays unapproved. A forged flag cannot open AutoPilot."""

from ops.autopilot import consider
from ops.qualification import autopilot_may_open, catalog, evidence_chain
from ops.registry import STRATEGIES
from ops.terminal_route import handle_signal


def test_every_registered_strategy_stays_out_of_paper_approval():
    body = catalog()
    assert body["approved_for_paper"] == 0
    assert len(body["strategies"]) == len(STRATEGIES)
    lifecycles = {row["lifecycle"] for row in body["strategies"]}
    assert lifecycles <= {"backtest_failed", "insufficient_data", "research_only"}
    assert "approved_for_paper" not in lifecycles
    failed = [row for row in body["strategies"] if row["research_status"] == "FAIL"]
    blocked = [row for row in body["strategies"] if row["research_status"] == "BLOCKED"]
    assert failed and all(row["lifecycle"] == "backtest_failed" and row["approved_for_paper"] is False for row in failed)
    assert blocked and all(row["lifecycle"] == "insufficient_data" for row in blocked)
    assert all(row["cost_model"]["transaction_cost_bps_per_side"] == 11 for row in body["strategies"])
    assert all(row["holdout_opened"] is False for row in body["strategies"])


def test_a_forged_approved_flag_cannot_open_autopilot(tmp_path, monkeypatch):
    from ops.test_paperbook import _account, _plan
    from ops.users import get

    users, owner, _other = _account(tmp_path, monkeypatch)
    from ops.autopilot import act
    act(owner["id"], "enable", 1_700_000_000_000, confirm=True)
    user = get(owner["id"])
    user["id"] = owner["id"]
    plan = _plan(approved=True, strategy="E1-donchian-20", version="e1-20261016")
    assert autopilot_may_open(plan) is False
    opened = consider(user, plan, 1_700_000_100_000, "opp:forged")
    assert opened["reason"] == "no_approved_strategy"
    assert users  # account fixture stays isolated


def test_terminal_result_carries_an_evidence_chain_without_a_probability():
    status, body = handle_signal(
        "user-a",
        {"symbol": "XAUUSD", "interval": "1m", "strategy": "auto"},
        1_700_000_000_000,
        ohlc_loader=lambda interval, now: [{"close": 1}],
        quote_loader=lambda now: {"ok": True},
    )
    assert status == 200
    chain = body["evidence_chain"]
    assert chain["instrument"] == "XAUUSD"
    assert chain["timeframe"] == "1m"
    assert chain["approved"] is False
    assert chain["calibrated_probability"] is None
    assert body["approved_strategy_available"] is False
    assert evidence_chain({})["calibrated_probability"] is None
