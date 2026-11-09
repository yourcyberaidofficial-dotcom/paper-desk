"""Milestone checks.

Unit and fixture tests do not open a socket. The Ollama cases use a transport
double. They are not a live model test.
"""

import json

from ops.ai_evidence import build
from ops.ollama import explain, health
from ops.runtime import DeskRuntime


def test_persona_context_is_account_specific(tmp_path, monkeypatch):
    from ops.app import LIMITER
    from ops.test_experience_product import _boot, _login
    import ops.users as users

    previous = LIMITER.per_minute
    original_root = users.ROOT
    app, _users = _boot(tmp_path, monkeypatch)
    try:
        ada, ada_body = _login(app, "Ada")
        nia, nia_body = _login(app, "Nia")
        assert ada.post("/api/profile", json={"signal_style": "apex_momentum", "currency": "USD", "capital": 100}).status_code == 200
        assert nia.post("/api/profile", json={"signal_style": "aegis_shield", "currency": "USD", "capital": 100}).status_code == 200
        assert ada.post("/api/lab", json={"experience": "new"}).status_code == 200
        assert nia.post("/api/lab", json={"experience": "independent"}).status_code == 200
        ada_facts = " ".join(build(ada_body["id"], "ask")["facts"])
        nia_facts = " ".join(build(nia_body["id"], "ask")["facts"])
        assert "persona context momentum" in ada_facts
        assert "explanation detail beginner" in ada_facts
        assert "persona context protection" in nia_facts
        assert "explanation detail technical" in nia_facts
        assert ada_body["id"] not in nia_facts
        assert nia_body["id"] not in ada_facts
    finally:
        users.ROOT = original_root
        LIMITER.per_minute = previous


def test_bot_thread_and_activity_stay_on_the_account(tmp_path, monkeypatch):
    from ops.activity import present
    from ops.app import LIMITER
    from ops.test_experience_product import _boot, _login
    import ops.users as users

    previous = LIMITER.per_minute
    original_root = users.ROOT
    app, _users = _boot(tmp_path, monkeypatch)
    try:
        ada, ada_body = _login(app, "Ada")
        nia, nia_body = _login(app, "Nia")
        first = ada.post("/api/aureon-ai", json={"page": "/overview", "question": "Explain my desk"})
        body = first.get_json()
        assert body["analysis"] is None
        assert body["approved"] is False and body["order_opened"] is False
        assert body["ollama"]["available"] is False
        assert body["ollama"]["reason"] == "model_not_configured"
        assert body["ollama"]["inference"] is False
        assert "Traceback" not in json.dumps(body)
        assert any(row["role"] == "customer" and "Explain my desk" in row["text"] for row in body["thread"])
        again = ada.post("/api/aureon-ai", json={"page": "/overview", "question": "Explain my desk"})
        assert again.status_code == 200
        ada_events = [row for row in present(ada_body["id"]) if row["event_type"] == "bot_request" and row["account_id"] == ada_body["id"]]
        nia_events = [row for row in present(nia_body["id"]) if row.get("account_id") == nia_body["id"] and row["event_type"] == "bot_request"]
        assert len(ada_events) == 1
        assert nia_events == []
        mark = ada.post("/api/activity/read", json={"event_ids": [ada_events[0]["event_id"]]})
        assert mark.status_code == 200
        reread = [row for row in present(ada_body["id"]) if row["event_id"] == ada_events[0]["event_id"]][0]
        assert reread["read"] is True
        stolen = nia.get("/api/bot/thread").get_json()
        assert stolen["messages"] == []
        assert "Explain my desk" not in json.dumps(stolen)
    finally:
        users.ROOT = original_root
        LIMITER.per_minute = previous


def test_signal_lifecycle_writes_one_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.activity import present
    from ops.signal_pipeline import SignalBook

    book = SignalBook(tmp_path / "signals")
    row = book.evaluate([], symbol="BTCUSDT", interval="1m", now_ms=1, rights="missing", account_id="ada")
    assert row["row"]["lifecycle"] == "UNAVAILABLE" and row["row"]["signal"] is False
    book.evaluate([], symbol="BTCUSDT", interval="1m", now_ms=2, rights="missing", account_id="ada")
    events = [item for item in present("ada") if item["account_id"] == "ada"]
    assert len(events) == 1
    assert events[0]["event_type"] == "source_unavailable"
    assert events[0]["detail"]["opportunity_id"]
    assert present("nia") == [] or all(item.get("account_id") != "ada" for item in present("nia") if item.get("account_id"))


def test_ollama_discovery_and_inference_use_a_double(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen-test")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    calls = []

    def transport(method, url, payload):
        calls.append(method)
        if method == "GET":
            return 200, {"models": [{"name": "qwen-test"}]}
        if payload is None:
            raise TimeoutError("timed out")
        return 200, {"message": {"content": json.dumps({"summary": "The stored observation is none.", "evidence_used": ["observation"]})}}

    found = health(transport=transport)
    assert found["available"] is True
    assert found["installed"] == ["qwen-test"]
    assert found["inference"] is False
    assert found["reachable"] is True
    explained = explain({"observation": "none", "note": "stored observation is none"}, transport=transport)
    assert explained["ok"] is True
    assert explained["explanation"]["approved"] is False
    assert calls.count("POST") == 1


def test_customer_route_accepts_a_validated_ollama_double(tmp_path, monkeypatch):
    """Mocked provider. This does not open a socket and is not a live inference result."""
    from ops.app import LIMITER
    from ops.test_experience_product import _boot, _login
    import ops.users as users

    previous = LIMITER.per_minute
    original_root = users.ROOT
    app, _users = _boot(tmp_path, monkeypatch)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen-test")

    def health(**_kwargs):
        return {"available": True, "reason": None, "model": "qwen-test", "installed": ["qwen-test"], "reachable": True, "inference": False, "broker": False}

    def explain(_evidence, timeout=8, transport=None, now_ms=None):
        return {
            "ok": True,
            "approved": False,
            "explanation": {
                "summary": "Stored observation is none. Broker is false.",
                "evidence_used": ["broker false"],
                "approved": False,
                "model": "qwen-test",
            },
        }

    monkeypatch.setattr("ops.ollama.health", health)
    monkeypatch.setattr("ops.ollama.explain", explain)
    try:
        ada, _body = _login(app, "Ada")
        body = ada.post("/api/aureon-ai", json={"page": "/overview", "question": "Explain my desk"}).get_json()
        assert body["analysis"].startswith("Stored observation")
        assert body["approved"] is False and body["order_opened"] is False
        assert body["ollama"]["inference"] is True
        assert body["reason"] is None
        assert body["ollama"]["available"] is True
        assert body["ollama"]["model"] == "qwen-test"
        assert "Traceback" not in json.dumps(body)
    finally:
        users.ROOT = original_root
        LIMITER.per_minute = previous


def test_worker_state_follows_the_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    runtime = DeskRuntime()
    assert runtime.operational_view()["state"] == "STOPPED"
    runtime.mark_started()
    assert runtime.running() is True
    assert runtime.operational_view()["state"] == "RUNNING"
    runtime.tick_start("scan")
    runtime.tick_end("scan", False)
    assert runtime.operational_view()["state"] == "DEGRADED"


def test_customer_error_hides_the_exception():
    from ops.app import _customer_failure, app

    with app.app_context():
        response = _customer_failure(RuntimeError("Traceback /tmp/aureon/secret"))
    payload = response.get_json()
    assert payload["message"] == "This action could not be completed."
    assert payload["handled"] is True
    assert "Traceback" not in json.dumps(payload)
    assert "/tmp/aureon" not in json.dumps(payload)
    assert payload["analysis"] is None
