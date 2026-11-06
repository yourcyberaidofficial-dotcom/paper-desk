"""Phase 3 checks. Fixtures are labelled. They are not live market evidence."""

import json
import threading
from pathlib import Path


def test_rate_limit_identity_expiry_and_a_normal_account_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.delenv("DESK_TRUST_PROXY", raising=False)
    from ops.app import AUTH_LIMITER, LIMITER, app
    from ops.auth import RateLimit, client_identity, limits_apply

    assert limits_apply(False, False) is True
    assert limits_apply(True, False) is False
    assert limits_apply(True, True) is True
    assert client_identity("203.0.113.5", "198.51.100.9", trust_proxy=False) == "203.0.113.5"
    assert client_identity("203.0.113.5", "198.51.100.9", trust_proxy=True) == "203.0.113.5"
    assert client_identity("10.0.0.4", "203.0.113.20, 10.0.0.4", trust_proxy=True) == "10.0.0.4"
    monkeypatch.setenv("DESK_TRUSTED_PROXIES", "10.0.0.0/8")
    assert client_identity("10.0.0.4", "203.0.113.20", trust_proxy=True) == "203.0.113.20"
    assert client_identity("10.0.0.4", "198.51.100.1, 203.0.113.9", trust_proxy=True) == "203.0.113.9"
    assert client_identity("127.0.0.1", "198.51.100.1, 203.0.113.9", trust_proxy=True) == "203.0.113.9"

    now = {"t": 1_000.0}
    monkeypatch.setattr("ops.auth.time.time", lambda: now["t"])
    window = RateLimit(2)
    assert window.allow("ada") is True
    assert window.allow("ada") is True
    assert window.allow("ada") is False
    assert window.retry_after("ada") >= 1
    now["t"] = 1_061.0
    assert window.allow("ada") is True
    assert window.retry_after("ada") == 0

    limiter = RateLimit(25)
    results = []

    def hammer():
        for _ in range(10):
            results.append(limiter.allow("same"))

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for item in results if item) == 25

    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    source = Path("ops/app.py").read_text(encoding="utf-8")
    assert "127.0.0.1:8080:8080" in compose
    assert "DESK_TRUST_PROXY" not in compose
    assert "11434" not in compose
    assert 'os.environ.get("DESK_BIND", "127.0.0.1")' in source
    assert LIMITER.per_minute == 300
    assert AUTH_LIMITER.per_minute == 20

    app.config["TESTING"] = True
    app.config["ENFORCE_RATE_LIMIT"] = True
    previous_auth = AUTH_LIMITER.per_minute
    previous_general = LIMITER.per_minute
    AUTH_LIMITER.per_minute = 6
    LIMITER.per_minute = 1
    AUTH_LIMITER.hits.clear()
    LIMITER.hits.clear()
    try:
        client = app.test_client()
        spoofed = client.get(
            "/version",
            headers={"X-Forwarded-For": "198.51.100.10"},
            environ_base={"REMOTE_ADDR": "203.0.113.5"},
        )
        assert spoofed.status_code == 200
        blocked = client.get(
            "/health",
            headers={"X-Forwarded-For": "198.51.100.99"},
            environ_base={"REMOTE_ADDR": "203.0.113.5"},
        )
        assert blocked.status_code == 429
        assert blocked.get_json()["error"] == "rate_limited"
        assert blocked.get_json()["scope"] == "general"
        assert int(blocked.headers["Retry-After"]) >= 1
        other = client.get("/version", environ_base={"REMOTE_ADDR": "203.0.113.6"})
        assert other.status_code == 200
        LIMITER.hits.clear()
        monkeypatch.setenv("DESK_TRUST_PROXY", "1")
        first = client.get(
            "/version",
            headers={"X-Forwarded-For": "203.0.113.20"},
            environ_base={"REMOTE_ADDR": "10.0.0.4"},
        )
        second = client.get(
            "/version",
            headers={"X-Forwarded-For": "203.0.113.21"},
            environ_base={"REMOTE_ADDR": "10.0.0.4"},
        )
        third = client.get(
            "/health",
            headers={"X-Forwarded-For": "203.0.113.20"},
            environ_base={"REMOTE_ADDR": "10.0.0.4"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert third.status_code == 429
        LIMITER.hits.clear()
        AUTH_LIMITER.hits.clear()
        AUTH_LIMITER.per_minute = 2
        LIMITER.per_minute = 30
        assert client.post("/api/login", json={"name": "nobody", "password": "not-the-password"}).status_code == 401
        assert client.post("/api/login", json={"name": "nobody", "password": "not-the-password"}).status_code == 401
        login_blocked = client.post("/api/login", json={"name": "nobody", "password": "not-the-password"})
        assert login_blocked.status_code == 429
        assert login_blocked.get_json()["scope"] == "auth"
        assert "not-the-password" not in login_blocked.get_data(as_text=True)
        assert client.get("/version").status_code == 200
        AUTH_LIMITER.hits.clear()
        LIMITER.hits.clear()
        AUTH_LIMITER.per_minute = 8
        import ops.users as users

        previous_root = users.ROOT
        users.ROOT = tmp_path / "users"
        users.ROOT.mkdir(parents=True, exist_ok=True)
        try:
            created = client.post("/api/register", json={"name": "ada", "password": "password-s"})
            assert created.status_code == 200
            signed = client.post("/api/login", json={"name": "ada", "password": "password-s"})
            assert signed.status_code == 200
            for path in (
                "/overview",
                "/signals",
                "/orders",
                "/history",
                "/live",
                "/api/me",
                "/api/activity",
                "/api/ai",
                "/api/autopilot",
                "/api/signals/lifecycle",
            ):
                response = client.get(path)
                assert response.status_code != 429
                assert response.status_code < 500
        finally:
            users.ROOT = previous_root
        activity_path = tmp_path / "activity" / "events.jsonl"
        activity = activity_path.read_text(encoding="utf-8") if activity_path.is_file() else ""
        assert "password-s" not in activity
    finally:
        AUTH_LIMITER.per_minute = previous_auth
        LIMITER.per_minute = previous_general
        AUTH_LIMITER.hits.clear()
        LIMITER.hits.clear()
        app.config["ENFORCE_RATE_LIMIT"] = False


def test_user_files_are_not_world_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users

    previous = users.ROOT
    users.ROOT = tmp_path / "users"
    users.ROOT.mkdir(parents=True, exist_ok=True)
    try:
        owner = users.register("ada", "password-s")
        path = users.ROOT / f"{owner['id']}.json"
        assert path.stat().st_mode & 0o077 == 0
        body = json.loads(path.read_text(encoding="utf-8"))
        assert "password_hash" in body
        assert "password-s" not in path.read_text(encoding="utf-8")
    finally:
        users.ROOT = previous


def test_fixture_ai_suite_and_restart_do_not_touch_signals(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setenv("OLLAMA_MODEL", "qwen-test")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    import inspect

    import ops.signal_engine as signal_engine
    import ops.signal_ledger as signal_ledger
    import ops.users as users
    from ops.ai_eval import run_fixtures, summarise
    from ops.ai_monitor import note, read
    from ops.ai_runtime import host_facts
    from ops.app import DASHBOARD
    from ops.ollama import explain

    source = inspect.getsource(signal_engine)
    assert "ollama" not in source
    assert "ai_provider" not in source
    previous = users.ROOT
    users.ROOT = tmp_path / "users"
    users.ROOT.mkdir(parents=True, exist_ok=True)
    try:
        owner = users.register("ada", "password-s")
        other = users.register("bea", "password-s")
        path = users.ROOT / f"{owner['id']}.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["profile"] = {"signal_style_name": "secret-persona-ADA"}
        path.write_text(json.dumps(stored), encoding="utf-8")
        calls = {"signals": 0}

        def boom(*_args, **_kwargs):
            calls["signals"] += 1
            raise AssertionError("signal ledger write")

        monkeypatch.setattr(signal_ledger, "record_observations", boom)
        rows = run_fixtures(owner["id"])
        score = summarise(rows, live_model="NOT TESTED")
        assert score["failed"] == [], score
        assert score["passed"] == score["cases"]
        assert score["cases"] >= 15
        assert score["hello_world_accepted"] is False
        assert calls["signals"] == 0
        from ops.ai_provider import ask

        other_view = ask(
            other["id"],
            "portfolio",
            transport=lambda *_args: (_ for _ in ()).throw(AssertionError("offline model")),
            now_ms=20,
        )
        assert "secret-persona-ADA" not in json.dumps(other_view)
        assert other_view["order_opened"] is False
        offline = note(owner["id"], {"available": False, "reason": "offline", "model": "qwen-test"})
        online = note(owner["id"], {"available": True, "reason": None, "model": "qwen-test"})
        assert offline["event"] == "offline"
        assert online["event"] == "model_restarted"
        assert online["signals_modified"] is False
        assert online["orders_modified"] is False
        assert online["rss_bytes"] > 0
        assert read()[-1]["event"] == "model_restarted"
        assert calls["signals"] == 0
    finally:
        users.ROOT = previous

    captured = {}

    def transport(method, url, payload):
        captured["payload"] = payload
        if method == "GET":
            return 200, {"models": [{"name": "qwen-test"}]}
        return 200, {"message": {"content": json.dumps({"summary": "Stored record.", "evidence_used": ["observation"]})}}

    explained = explain(
        {key: "n" * 500 for key in ("symbol", "interval", "observation", "research", "execution", "decision", "note", "strategy", "lifecycle", "paper_status")},
        transport=transport,
    )
    assert explained["ok"] is True
    assert explained["approved"] is False
    assert len(json.dumps(captured["payload"])) < 6000
    facts = host_facts()
    assert facts["model_installed"] is False
    assert facts["benchmark_status"] == "NOT TESTED"
    assert facts["private_inference"] == "not_operational"
    assert facts["weights_on_this_host"] is False
    assert facts["inference_concurrency_limit"] == 1
    assert "Permission" in DASHBOARD
    assert "Freshness" in DASHBOARD
    assert "Forming setup" in DASHBOARD
    assert "Local AI status is separate" in DASHBOARD


def test_session_cookie_is_httponly():
    from ops.app import app

    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
