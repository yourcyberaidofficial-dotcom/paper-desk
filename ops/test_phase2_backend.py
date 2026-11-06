"""Phase 2 backend defects. Fixtures are labelled fixtures, not live readings."""

import json
import threading
from pathlib import Path


def _users(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users

    users.ROOT = tmp_path / "users"
    users.ROOT.mkdir(parents=True, exist_ok=True)
    return users


def _login(client, name, password):
    response = client.post("/api/login", json={"name": name, "password": password})
    assert response.status_code == 200
    return response


def test_lifecycle_is_private_and_does_not_write(tmp_path, monkeypatch):
    users = _users(tmp_path, monkeypatch)
    owner = users.register("ada", "password-s")
    other = users.register("bea", "password-s")
    from ops.activity import record
    from ops.app import app
    from ops.signal_ledger import read, record_observations

    record_observations([{
        "symbol": "BTCUSDT",
        "interval": "15m",
        "customer_status": "reading_unavailable",
        "quality": "unavailable",
        "account_id": other["id"],
        "price": 424242,
    }], now_ms=1, component="test")
    record("signal_created", account_id=other["id"], entity="secret-bea", component="test", detail={"note": "bea only"}, now_ms=2)
    record("signal_created", account_id=owner["id"], entity="ada-row", component="test", detail={"note": "ada only"}, now_ms=3)
    before = (tmp_path / "signals" / "history.jsonl").read_text(encoding="utf-8")
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.get("/api/signals/lifecycle").status_code == 401
    assert client.post("/api/signals/lifecycle", json={"price": 1}).status_code == 401
    _login(client, "ada", "password-s")
    denied = client.put("/api/signals/lifecycle", json={"observation": "active_signal", "price": 424242})
    assert denied.status_code == 405
    assert denied.get_json()["modified"] is False
    body = client.get("/api/signals/lifecycle").get_json()
    assert body["read_only"] is True
    assert body["modified"] is False
    assert body["account_id"] == owner["id"]
    dumped = json.dumps(body)
    assert "secret-bea" not in dumped
    assert "ada-row" in dumped
    assert "424242" not in dumped
    assert all(row.get("account_id") in (None, owner["id"]) for row in body["history"])
    assert (tmp_path / "signals" / "history.jsonl").read_text(encoding="utf-8") == before
    assert read()[0]["price"] is None
    with client.session_transaction() as sess:
        sess["user_id"] = other["id"]
        sess["user_exp"] = 9_999_999_999
    theirs = client.get("/api/signals/lifecycle").get_json()
    assert "ada-row" not in json.dumps(theirs)
    assert "secret-bea" in json.dumps(theirs)


def test_inbox_keeps_more_than_200_notices_across_restart(tmp_path, monkeypatch):
    users = _users(tmp_path, monkeypatch)
    owner = users.register("ada", "password-s")
    other = users.register("bea", "password-s")
    from ops.inbox import apply_retention, items, mark_read, offer, page, read_archive, unread_count
    from ops.signal_ledger import note_unavailable, read

    note_unavailable("BTCUSDT", "1h", "reading_unavailable", 1)
    before_signals = read()
    assert before_signals and before_signals[0]["signal"] is False

    for index in range(230):
        saved = offer(owner["id"], {
            "id": f"note-{index}",
            "kind": "status",
            "message": f"notice {index}",
            "created_ms": 1_000 + index,
            "decision": "WAIT",
        })
        assert saved["stored"] is True
    again = offer(owner["id"], {"id": "note-0", "kind": "status", "message": "dup", "created_ms": 5, "decision": "WAIT"})
    assert again["duplicate"] is True
    assert len(items(owner["id"])) == 230
    path = users.ROOT / "inbox" / f"{owner['id']}.jsonl"
    reloaded = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(reloaded) == 230
    assert [row["id"] for row in reloaded] == [f"note-{index}" for index in range(230)]
    window = page(owner["id"], limit=50)
    assert window["total"] == 230
    assert window["truncated"] is False
    assert len(window["items"]) == 50
    seen = []
    before = None
    before_id = None
    while True:
        body = page(owner["id"], limit=80, before_ms=before, before_id=before_id)
        seen.extend(row["id"] for row in body["items"])
        if not body["next_before"]:
            break
        before = body["next_before"]
        before_id = body["next_id"]
    assert len(seen) == 230
    assert len(set(seen)) == 230
    assert seen == sorted(seen, key=lambda item: (-int(item.split("-")[1]), item))
    tied = offer(owner["id"], {"id": "tie-b", "kind": "status", "message": "b", "created_ms": 9000, "decision": "WAIT"})
    assert tied["stored"] is True
    offer(owner["id"], {"id": "tie-a", "kind": "status", "message": "a", "created_ms": 9000, "decision": "WAIT"})
    first = page(owner["id"], limit=1)
    assert first["items"][0]["id"] == "tie-a"
    second = page(owner["id"], limit=1, before_ms=first["next_before"], before_id=first["next_id"])
    assert second["items"][0]["id"] == "tie-b"
    assert mark_read(owner["id"], "tie-a")["unread"] == unread_count(owner["id"])
    assert all(row["id"] != "tie-a" or row["read"] for row in items(owner["id"]))
    assert unread_count(owner["id"]) == 231
    offer(other["id"], {"id": "bea-only", "kind": "status", "message": "private", "created_ms": 9, "decision": "WAIT"})
    assert "bea-only" not in {row["id"] for row in items(owner["id"])}
    apply_retention(owner["id"], now_ms=1_000 + 229, max_age_ms=50)
    assert len(items(owner["id"])) < 230
    assert len(items(owner["id"])) + len(read_archive(owner["id"])) == 232
    archived_id = read_archive(owner["id"])[0]["id"]
    restored = offer(owner["id"], {"id": archived_id, "kind": "status", "message": "again", "created_ms": 9, "decision": "WAIT"})
    assert restored["duplicate"] is True
    assert len(items(owner["id"])) + len(read_archive(owner["id"])) == 232
    archived = page(owner["id"], include_archived=True)
    assert archived["total"] == 232
    after_signals = read()
    assert after_signals[: len(before_signals)] == before_signals
    assert before_signals[0] in after_signals

    errors = []

    def burst(start):
        try:
            for offset in range(10):
                offer(owner["id"], {
                    "id": f"burst-{start}-{offset}",
                    "kind": "status",
                    "message": "concurrent",
                    "created_ms": 5_000 + start * 10 + offset,
                    "decision": "WAIT",
                })
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=burst, args=(slot,)) for slot in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    ids = [row["id"] for row in items(owner["id"])] + [row["id"] for row in read_archive(owner["id"])]
    assert len([item for item in ids if item.startswith("burst-")]) == 80


def test_profile_writes_do_not_drop_fields_or_partial_documents(tmp_path, monkeypatch):
    users = _users(tmp_path, monkeypatch)
    owner = users.register("ada", "password-s")
    other = users.register("bea", "password-s")
    users.update_profile(other["id"], {"capital": 50, "currency": "NGN", "signal_style": "aegis_shield"})
    start = threading.Barrier(2)

    def timezones():
        start.wait()
        for index in range(30):
            users.update_profile(owner["id"], {"timezone": f"Zone/{index}", "capital": 1000, "currency": "USD"})

    def styles():
        start.wait()
        for _index in range(30):
            users.update_profile(owner["id"], {"signal_style": "orion_balance", "max_risk_pct": 1.0})

    threads = [threading.Thread(target=timezones), threading.Thread(target=styles)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    saved = json.loads((users.ROOT / f"{owner['id']}.json").read_text(encoding="utf-8"))
    assert saved["profile"]["capital"] == 1000
    assert saved["profile"]["currency"] == "USD"
    assert saved["profile"]["signal_style"] == "orion_balance"
    assert str(saved["profile"]["timezone"]).startswith("Zone/")
    assert saved["name"] == "ada"
    assert "password_hash" in saved
    other_saved = json.loads((users.ROOT / f"{other['id']}.json").read_text(encoding="utf-8"))
    assert other_saved["profile"]["capital"] == 50
    assert other_saved["profile"]["currency"] == "NGN"
    revision = saved["revision"]
    conflict = users.update_profile(owner["id"], {"currency": "EUR"}, expected_revision=revision - 1)
    assert conflict["conflict"] is True
    assert json.loads((users.ROOT / f"{owner['id']}.json").read_text(encoding="utf-8"))["profile"]["currency"] == "USD"
    path = users.ROOT / f"{owner['id']}.json"
    original = path.read_text(encoding="utf-8")

    def boom(user):
        raise RuntimeError("interrupted")

    try:
        users._commit(owner["id"], boom)
    except RuntimeError:
        pass
    assert path.read_text(encoding="utf-8") == original
    path.write_text("{", encoding="utf-8")
    assert users.update_profile(owner["id"], {"currency": "EUR"}) is None
    assert path.read_text(encoding="utf-8") == "{"


def test_worker_shutdown_records_only_finished_work(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.activity import read
    from ops.runtime import DeskRuntime

    runtime = DeskRuntime(deadline_s=1)
    runtime.mark_started()
    assert runtime.tick_start("desk")
    runtime.tick_end("desk", True)
    done = runtime.shutdown(deadline_s=1)
    assert done["completed"] is True
    assert done["phase"] == "stopped"
    kinds = [row["event_type"] for row in read()]
    assert "worker_stopped" in kinds
    assert "work_interrupted" not in kinds
    restarted = DeskRuntime(deadline_s=1)
    restarted.mark_started()
    assert "worker_restarted" in [row["event_type"] for row in read()]
    assert restarted.read_state()["completed"] is not True or restarted.read_state()["phase"] == "running"

    stuck = DeskRuntime(deadline_s=0.05)
    stuck.mark_started()
    assert stuck.tick_start("slow")
    forced = stuck.shutdown(deadline_s=0.05)
    assert forced["completed"] is False
    assert forced["phase"] == "interrupted"
    assert forced["reason"] == "deadline"
    stopped = [row for row in read() if row["event_type"] == "worker_stopped"]
    interrupted = [row for row in read() if row["event_type"] == "work_interrupted"]
    assert interrupted
    assert all(row["detail"]["note"] for row in interrupted)
    assert len(stopped) == 1
    recovered = DeskRuntime(deadline_s=0.05)
    found = recovered.recover()
    assert found["completed"] is False
    assert recovered.read_state()["completed"] is False
    assert recovered.read_state()["tasks"]["slow"] is False
    stuck.tick_end("slow", False)
    assert stuck.read_state()["tasks"]["slow"] is False
    failed = DeskRuntime(deadline_s=1)
    failed.mark_started()
    assert failed.tick_start("job")
    failed.tick_end("job", False)
    refused = failed.shutdown(deadline_s=1)
    assert refused["completed"] is False
    assert refused["reason"] == "task_failed"
    assert refused["tasks"]["job"] is False
    assert failed.read_state()["completed"] is False


def test_signal_continuity_still_keeps_history(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.signal_engine import canonical_opportunity_id
    from ops.signal_ledger import note_unavailable, read, record_observations

    assert canonical_opportunity_id("BTCUSDT", "15m", {"strategy": "trend pullback", "decision": "BUY", "bar_close_ms": 10}, []) == "opp:BTCUSDT:15m:trend pullback:BUY:10"
    assert canonical_opportunity_id("ETHUSDT", "1h", {"opportunity_id": "obs:ETHUSDT:1h:10", "strategy": "range", "decision": "SELL", "bar_close_ms": 10}, []).startswith("opp:")
    assert note_unavailable("XAUUSD", "3m", "reading_unavailable", 1)["stored"] == 1
    assert note_unavailable("XAUUSD", "3m", "reading_unavailable", 2)["stored"] == 0
    record_observations([{
        "symbol": "BTCUSDT",
        "interval": "15m",
        "quality": "ok",
        "reading_class": "observational",
        "decision": "BUY",
        "entry": 10,
        "stop": 9,
        "target": 12,
        "price": 10,
        "validation_status": "FAIL",
        "approved": False,
        "source_id": "fixture",
        "opportunity_id": "opp:BTCUSDT:15m:fixture:BUY:10",
    }], now_ms=3, component="test")
    rows = read()
    assert rows[0]["signal"] is False
    assert rows[0]["price"] is None
    assert rows[1]["signal"] is True
    assert len(rows) == 2


def test_rate_limit_covers_a_previously_open_route(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.app import LIMITER, app

    app.config["TESTING"] = True
    app.config["ENFORCE_RATE_LIMIT"] = True
    previous = LIMITER.per_minute
    LIMITER.per_minute = 2
    LIMITER.hits.clear()
    try:
        client = app.test_client()
        assert client.get("/api/signal").status_code == 200
        assert client.get("/version").status_code == 200
        blocked = client.get("/health")
        assert blocked.status_code == 429
        assert blocked.get_json()["error"] == "rate_limited"
    finally:
        LIMITER.per_minute = previous
        LIMITER.hits.clear()
        app.config["ENFORCE_RATE_LIMIT"] = False


def test_worker_prefs_post_is_not_registered_twice():
    from ops.app import app

    posts = [rule.rule for rule in app.url_map.iter_rules() if "POST" in rule.methods and rule.rule in {"/api/prefs", "/api/worker/prefs"}]
    assert posts.count("/api/prefs") == 1
    assert "/api/worker/prefs" in posts


def test_local_ai_rejects_hidden_prices_and_public_binds(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setenv("OLLAMA_MODEL", "qwen-test")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    from ops.ai_provider import ask
    from ops.ai_runtime import host_facts
    from ops.ai_safety import endpoint_allowed, listener_allowed, local_model_allowed
    from ops.app import app
    from ops.users import register

    assert endpoint_allowed("http://192.0.2.1:11434") is False
    assert endpoint_allowed("http://8.8.8.8:11434") is False
    assert listener_allowed("0.0.0.0") is False
    assert listener_allowed("127.0.0.1") is True
    assert local_model_allowed("gpt4o") is False
    facts = host_facts()
    assert facts["benchmark_status"] == "NOT TESTED"
    assert facts["model_installed"] is False
    assert facts["private_inference"] == "not_operational"
    calls = {"n": 0}

    def transport(method, url, payload):
        calls["n"] += 1
        if method == "GET":
            return 200, {"models": [{"name": "qwen-test"}]}
        return 200, {"message": {"content": json.dumps({
            "summary": "Spot is 424,242 right now.",
            "evidence_used": ["price 424242 buy now"],
        })}}

    import ops.users as users
    users.ROOT = tmp_path / "users"
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = register("ada", "password-s")
    users.update_profile(owner["id"], {"signal_style": "orion_balance", "currency": "USD", "capital": 1000})
    before = json.loads((users.ROOT / f"{owner['id']}.json").read_text(encoding="utf-8"))
    result = ask(owner["id"], "market_watch", transport=transport, now_ms=5)
    assert result["approved"] is False
    assert result["order_opened"] is False
    assert result["reason"] == "ungrounded"
    assert "424" not in result["explanation"]["summary"]
    assert "buy now" not in " ".join(result["explanation"]["evidence_used"]).lower()
    after = json.loads((users.ROOT / f"{owner['id']}.json").read_text(encoding="utf-8"))
    assert after["profile"]["max_risk_pct"] == before["profile"].get("max_risk_pct")
    assert after["profile"]["capital"] == before["profile"]["capital"]
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.0.2.1:11434")
    refused = {"n": 0}

    def no(method, url, payload):
        refused["n"] += 1
        raise AssertionError("public documentation address was contacted")

    blocked = ask(owner["id"], "explain_signal", transport=no, now_ms=6)
    assert blocked["reason"] == "endpoint_refused"
    assert blocked["approved"] is False
    assert blocked["order_opened"] is False
    assert blocked["explanation"] is None
    assert refused["n"] == 0
    app.config["TESTING"] = True
    client = app.test_client()
    assert client.post("/api/explain", json={"price": 424242}).status_code == 401
    _login(client, "ada", "password-s")
    answered = client.post("/api/ai/ask", json={"task": "why_quiet", "question": "buy\u00a0now"})
    assert answered.status_code == 200
    assert answered.get_json()["reason"] == "order_request_refused"
    assert answered.get_json()["approved"] is False
    assert answered.get_json()["order_opened"] is False
