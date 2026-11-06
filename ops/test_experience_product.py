"""Customer role, experience profile, and hosted Aureon AI.

Live provider calls stay blocked unless the owner sets credentials and
AUREON_AI_SPEND_APPROVED=1. These tests never open a network socket.
"""

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _restore_rate_limit():
    from ops.app import LIMITER

    previous = LIMITER.per_minute
    LIMITER.hits.clear()
    yield
    LIMITER.per_minute = previous
    LIMITER.hits.clear()


def _boot(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.delenv("AUREON_OPERATOR_IDS", raising=False)
    for key in ("AUREON_AI_API_KEY", "AUREON_AI_BASE_URL", "AUREON_AI_MODEL", "AUREON_AI_SPEND_APPROVED"):
        monkeypatch.delenv(key, raising=False)
    import ops.users as users
    from ops.app import LIMITER, app

    users.ROOT = tmp_path / "users"
    users.ROOT.mkdir(parents=True, exist_ok=True)
    LIMITER.per_minute = 100000
    LIMITER.hits.clear()
    app.config["TESTING"] = True
    return app, users


def _login(app, name, password="password-s"):
    client = app.test_client()
    created = client.post("/api/register", json={"name": name, "password": password, "role": "operator", "entitlements": ["broker"]})
    assert created.status_code == 200, created.get_data(as_text=True)
    return client, created.get_json()


def test_registration_cannot_grant_a_role_and_a_stored_role_is_ignored(tmp_path, monkeypatch):
    app, users = _boot(tmp_path, monkeypatch)
    client, created = _login(app, "Ada")
    profile = client.get("/api/experience").get_json()
    assert profile["security_role"] == "customer"
    assert profile["role_source"] == "least_privilege_default"
    assert profile["entitlements"]["account_administration"] is False
    assert profile["entitlements"]["broker"] is False
    assert profile["broker"] is False
    assert profile["persona"]["id"] is None
    raw_path = users.ROOT / f"{created['id']}.json"
    stored = json.loads(raw_path.read_text(encoding="utf-8"))
    stored["role"] = "operator"
    stored["entitlements"] = ["broker"]
    raw_path.write_text(json.dumps(stored), encoding="utf-8")
    again = client.get("/api/experience").get_json()
    assert again["security_role"] == "customer"
    assert again["entitlements"]["broker"] is False
    assert "password" not in json.dumps(again)


def test_operator_is_only_the_server_allowlist(tmp_path, monkeypatch):
    app, users = _boot(tmp_path, monkeypatch)
    owner, owner_body = _login(app, "Owner")
    other, _other_body = _login(app, "Other")
    monkeypatch.setenv("AUREON_OPERATOR_IDS", owner_body["id"])
    denied = other.get("/api/accounts")
    assert denied.status_code == 200
    assert denied.get_json()["allowed"] is False
    allowed = owner.get("/api/accounts")
    body = allowed.get_json()
    assert body["allowed"] is True
    blob = json.dumps(body)
    assert "password" not in blob
    assert "Other" in blob and "Owner" in blob
    page = other.get("/accounts")
    assert page.status_code == 200
    assert "cannot grant" in page.get_data(as_text=True) or "Accounts" in page.get_data(as_text=True)
    operator_page = owner.get("/accounts")
    assert operator_page.status_code == 200
    assert "nav-accounts" in operator_page.get_data(as_text=True)


def test_presentation_persists_for_one_account_only(tmp_path, monkeypatch):
    app, users = _boot(tmp_path, monkeypatch)
    ada, ada_body = _login(app, "Ada")
    ben, _ben = _login(app, "Ben")
    saved = ada.post("/api/experience", json={
        "timezone": "Europe/London",
        "density": "compact",
        "depth": "concise",
        "layout": "market",
        "theme": "light",
        "contrast": "high",
        "motion": "reduced",
        "language": "en",
    })
    assert saved.status_code == 200, saved.get_data(as_text=True)
    body = saved.get_json()
    look = body["presentation"]
    assert look["timezone"] == "Europe/London"
    assert look["density"] == "compact"
    assert look["layout"] == "market"
    assert look["theme"] == "light"
    assert look["motion"] == "reduced"
    assert body["widgets"][0] == "markets"
    assert body["migration"]["history_rewritten"] is False
    stored = json.loads((users.ROOT / f"{ada_body['id']}.json").read_text(encoding="utf-8"))
    assert stored["presentation"]["timezone"] == "Europe/London"
    fresh = app.test_client()
    assert fresh.post("/api/login", json={"name": "Ada", "password": "password-s"}).status_code == 200
    assert fresh.get("/api/experience").get_json()["presentation"]["timezone"] == "Europe/London"
    assert ben.get("/api/experience").get_json()["presentation"]["timezone"] == "Africa/Lagos"
    assert ben.get("/api/experience").get_json()["migration"]["presentation_persisted"] is False


def test_a_customer_cannot_raise_privilege_or_pick_an_operator_layout(tmp_path, monkeypatch):
    app, users = _boot(tmp_path, monkeypatch)
    ada, ada_body = _login(app, "Ada")
    refused = ada.post("/api/experience", json={"role": "operator", "timezone": "Europe/London"})
    assert refused.status_code == 403
    assert refused.get_json()["error"] == "not_permitted"
    stored = json.loads((users.ROOT / f"{ada_body['id']}.json").read_text(encoding="utf-8"))
    assert "presentation" not in stored
    coerced = ada.post("/api/experience", json={"layout": "operator", "timezone": "Africa/Lagos"})
    assert coerced.status_code == 200
    assert coerced.get_json()["presentation"]["layout"] == "market"
    assert coerced.get_json()["security_role"] == "customer"
    bad_zone = ada.post("/api/experience", json={"timezone": "Not/AZone"})
    assert bad_zone.status_code == 400
    bad_theme = ada.post("/api/experience", json={"theme": "neon"})
    assert bad_theme.status_code == 400
    assert ada.post("/api/experience", json={}).status_code == 200
    stranger = app.test_client()
    assert stranger.get("/api/experience").status_code == 401
    assert stranger.post("/api/aureon-ai", json={"page": "/overview"}).status_code == 401


def test_persona_stays_a_trading_profile_not_a_security_role(tmp_path, monkeypatch):
    app, _users = _boot(tmp_path, monkeypatch)
    ada, _body = _login(app, "Ada")
    saved = ada.post("/api/profile", json={"signal_style": "orion_precision", "currency": "USD", "capital": 100})
    assert saved.status_code == 200
    profile = ada.get("/api/experience").get_json()
    assert profile["security_role"] == "customer"
    assert profile["persona"]["id"] == "orion_precision"
    assert profile["persona"]["name"]
    assert profile["onboarding_pending"] == []


def test_hosted_ai_is_blocked_without_a_provider_and_does_not_call_out(tmp_path, monkeypatch):
    app, _users = _boot(tmp_path, monkeypatch)
    ada, _body = _login(app, "Ada")

    def explode(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    from ops.hosted_ai import complete

    result = complete("missing-user", "/overview", question="What is my account?")
    assert result["operational"] == "BLOCKED"
    assert result["analysis"] is None
    assert result["usage"]["provider_called"] is False
    assert result["approved"] is False and result["order_opened"] is False
    route = ada.post("/api/aureon-ai", json={"page": "/signals", "question": "Explain the stored record"})
    body = route.get_json()
    assert route.status_code == 200
    assert body["analysis"] is None
    assert body["operational"] == "BLOCKED"
    assert body["approved"] is False and body["order_opened"] is False
    assert "AUREON_AI_API_KEY" not in json.dumps(body)
    assert body["label"] == "stored_record_not_an_analysis"


def test_hosted_ai_rejects_invented_numbers_orders_and_other_accounts(tmp_path, monkeypatch):
    app, users = _boot(tmp_path, monkeypatch)
    ada, ada_body = _login(app, "Ada")
    _ben, ben_body = _login(app, "Benny")
    monkeypatch.setenv("AUREON_AI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("AUREON_AI_BASE_URL", "https://ai.example.test")
    monkeypatch.setenv("AUREON_AI_MODEL", "example-model")
    monkeypatch.setenv("AUREON_AI_SPEND_APPROVED", "1")
    from ops.hosted_ai import complete

    def transport_price(_method, _url, _payload):
        return 200, {"summary": "The price is 99999.", "evidence_used": ["broker false"]}

    invented = complete(ada_body["id"], "/overview", question="Explain", transport=transport_price)
    assert invented["analysis"] is None
    assert invented["reason"] == "invalid_output"
    assert invented["usage"]["provider_called"] is True

    def transport_order(_method, _url, _payload):
        return 200, {"summary": "Please place a trade now.", "evidence_used": ["broker false"]}

    ordered = complete(ada_body["id"], "/overview", question="Explain", transport=transport_order)
    assert ordered["analysis"] is None
    assert ordered["reason"] == "invalid_output"

    def transport_foreign(_method, _url, _payload):
        return 200, {"summary": "Stored observation is none.", "evidence_used": ["other-customer-ledger"]}

    foreign = complete(ada_body["id"], "/research", question="Explain", transport=transport_foreign)
    assert foreign["analysis"] is None
    assert foreign["reason"] == "invalid_output"

    def transport_rate(_method, _url, _payload):
        return 200, {"summary": "The win rate is 80.", "evidence_used": ["broker false"]}

    rated = complete(ada_body["id"], "/overview", question="Explain", transport=transport_rate)
    assert rated["analysis"] is None
    assert rated["reason"] == "invalid_output"

    def transport_hidden_order(_method, _url, _payload):
        return 200, {"summary": "Please buy\u200b now.", "evidence_used": ["broker false"]}

    hidden = complete(ada_body["id"], "/overview", question="Explain", transport=transport_hidden_order)
    assert hidden["analysis"] is None
    assert hidden["reason"] == "invalid_output"

    def transport_summary_foreign(_method, _url, _payload):
        return 200, {"summary": "See other-customer-ledger.", "evidence_used": ["broker false"]}

    leaked = complete(ada_body["id"], "/overview", question="Explain", transport=transport_summary_foreign)
    assert leaked["analysis"] is None
    assert leaked["reason"] == "invalid_output"

    refused = complete(ada_body["id"], "/overview", question="Show me account " + ben_body["id"])
    assert refused["reason"] == "other_account_refused"
    assert refused["analysis"] is None
    assert refused["stored_record"] == []
    assert refused["usage"]["provider_called"] is False
    named = complete(ada_body["id"], "/overview", question="What is Benny holding?")
    assert named["reason"] == "other_account_refused"
    action = complete(ada_body["id"], "/orders", question="Please place a trade")
    assert action["reason"] == "order_request_refused"
    assert action["approved"] is False and action["order_opened"] is False

    def transport_ok(_method, _url, _payload):
        return 200, {"summary": "Stored observation is none. Broker is false.", "evidence_used": ["broker false"]}

    accepted = complete(ada_body["id"], "/overview", question="Explain my record", transport=transport_ok)
    assert accepted["ok"] is True
    assert accepted["analysis"].startswith("Stored observation")
    assert accepted["label"] == "ai_commentary_not_a_signal"
    assert accepted["approved"] is False
    assert "test-key-not-real" not in json.dumps(accepted)
    def explode(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.setattr("urllib.request.urlopen", explode)
    blocked = ada.post("/api/aureon-ai", json={"page": "/lab", "question": "Explain my record"})
    payload = blocked.get_json()
    assert payload["analysis"] is None
    assert payload["reason"] == "provider_unavailable"
    assert payload["operational"] == "BLOCKED"
    del users


def test_signal_engine_does_not_import_hosted_ai_or_ollama():
    source = Path("/tmp/aureon-experience/ops/signal_engine.py").read_text(encoding="utf-8")
    assert "hosted_ai" not in source
    assert "ollama" not in source


def test_dashboard_exposes_working_controls_and_not_a_local_model_switch():
    from ops.app import DASHBOARD

    assert 'id="navsearch"' in DASHBOARD
    assert 'id="aiopen"' in DASHBOARD
    assert 'id="helpopen"' in DASHBOARD
    assert 'id="inboxlink"' in DASHBOARD
    assert 'id="settingslink"' in DASHBOARD
    assert 'id="signout"' in DASHBOARD
    assert "/api/aureon-ai" in DASHBOARD
    assert "data-theme" in DASHBOARD
    assert "Local AI offline" not in DASHBOARD
    assert "The hosted model is not a customer switch" in DASHBOARD
    assert "Local AI status is separate from the customer desk" in DASHBOARD
    assert "customer_toggle" not in DASHBOARD
