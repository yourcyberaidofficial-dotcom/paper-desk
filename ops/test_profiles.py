"""Profile eligibility and currency persistence. No network."""

import json
import os
import tempfile
from pathlib import Path

from ops.profiles import evaluate
from ops.users import login, register, update_profile


def test_three_styles_differ_without_inventing_a_direction():
    only_e1 = evaluate("apex_momentum", "LONG_BIAS", "WAIT", "WAIT", True)
    orion = evaluate("orion_precision", "LONG_BIAS", "WAIT", "WAIT", True)
    aegis = evaluate("aegis_shield", "LONG_BIAS", "WAIT", "WAIT", True)
    assert only_e1["decision"] == "LONG_BIAS" and only_e1["eligible"]
    assert orion["decision"] == "WAIT" and not orion["eligible"]
    assert orion["reason"].startswith("Research check only")
    assert "paper-trade rule" in orion["reason"]
    assert "E1 plus confirming agreement" not in orion["reason"]
    assert aegis["decision"] == "WAIT" and not aegis["eligible"]
    assert only_e1["production"] == "WAIT_DEFAULT"
    assert only_e1["validated"] is False


def test_agreement_and_conflict_and_stale():
    agreed = evaluate("aegis_shield", "SHORT_BIAS", "SHORT_BIAS", "SHORT_BIAS", True)
    assert agreed["decision"] == "SHORT_BIAS"
    conflict = evaluate("aegis_shield", "LONG_BIAS", "SHORT_BIAS", "LONG_BIAS", True)
    assert conflict["decision"] == "WAIT"
    stale = evaluate("apex_momentum", "LONG_BIAS", "LONG_BIAS", "LONG_BIAS", False)
    assert stale["decision"] == "WAIT"
    no_e1 = evaluate("apex_momentum", "WAIT", "LONG_BIAS", "LONG_BIAS", True)
    assert no_e1["decision"] == "WAIT"


def test_wait_and_gold_do_not_invent_a_direction():
    for style in ("apex_momentum", "orion_precision", "aegis_shield"):
        assert evaluate(style, "WAIT", "LONG_BIAS", "SHORT_BIAS", True)["decision"] == "WAIT"
        assert evaluate(style, "LONG_BIAS", "LONG_BIAS", "LONG_BIAS", False)["decision"] == "WAIT"
    gold = evaluate("apex_momentum", "LONG_BIAS", "WAIT", "WAIT", True, "XAUUSD")
    btc = evaluate("apex_momentum", "LONG_BIAS", "WAIT", "WAIT", True, "BTCUSDT")
    assert gold["decision"] == "WAIT" and gold["eligible"] is False
    assert btc["decision"] == "LONG_BIAS" and btc["eligible"] is True
    conflict = evaluate("orion_precision", "LONG_BIAS", "SHORT_BIAS", "LONG_BIAS", True)
    assert conflict["decision"] == "WAIT"


def test_currency_is_not_assumed_and_profiles_are_isolated(monkeypatch=None):
    tmp = tempfile.mkdtemp()
    os.environ["AUREON_DATA"] = tmp
    import ops.users as users
    users.ROOT = Path(tmp) / "users"
    users.ROOT.mkdir(parents=True, exist_ok=True)
    a = register("acct-a", "password-a")
    b = register("acct-b", "password-b")
    update_profile(a["id"], {"signal_style": "aegis_shield", "currency": "NGN", "capital": 1000})
    update_profile(b["id"], {"signal_style": "apex_momentum", "currency": "USD", "capital": 50})
    saved_a = json.loads((users.ROOT / f"{a['id']}.json").read_text())
    saved_b = json.loads((users.ROOT / f"{b['id']}.json").read_text())
    assert saved_a["profile"]["currency"] == "NGN"
    assert saved_a["profile"]["capital"] == 1000
    assert saved_a["profile"]["signal_style"] == "aegis_shield"
    assert saved_a["profile"]["max_risk_pct"] == 0.8
    assert saved_b["profile"]["currency"] == "USD"
    assert saved_b["profile"]["signal_style"] == "apex_momentum"
    assert saved_b["profile"]["max_risk_pct"] == 2.5
    assert saved_a["profile"]["capital"] == 1000
    again = update_profile(a["id"], {"currency": "EUR"})
    assert again["profile"]["capital"] == 1000
    assert again["profile"]["currency"] == "EUR"
    assert again["profile"]["signal_style"] == "aegis_shield"
    switched = update_profile(a["id"], {"signal_style": "apex_momentum", "max_risk_pct": 0.8})
    assert switched["profile"]["max_risk_pct"] == 2.5
    assert switched["profile"]["currency"] == "EUR"
    assert switched["profile"]["capital"] == 1000
    lowered = update_profile(a["id"], {"max_risk_pct": 1.0})
    assert lowered["profile"]["max_risk_pct"] == 1.0
    assert lowered["profile"]["signal_style"] == "apex_momentum"
    assert login("acct-a", "password-a")["id"] == a["id"]
