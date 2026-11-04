"""One account can review, confirm, monitor and close a paper trade it typed itself."""


def test_register_review_confirm_close_keeps_the_typed_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "ops.desk_snapshot.reading_for",
        lambda *_args, **_kwargs: {"symbol": "BTCUSDT", "interval": "15m", "entry": 50, "stop": 49, "target": 55, "decision": "BUY"},
    )
    from ops.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    created = client.post("/api/register", json={"name": "ada", "password": "password-s"})
    assert created.status_code == 200
    assert created.get_json()["ok"] is True
    profile = client.post("/api/profile", json={"signal_style": "apex_momentum", "capital": 1000, "currency": "USD"})
    assert profile.status_code == 200
    plan = client.post("/api/desk/plan", json={
        "symbol": "BTCUSDT",
        "interval": "15m",
        "authored": True,
        "decision": "BUY",
        "entry": 100,
        "stop": 98,
        "target": 104,
    }).get_json()
    assert plan["order_opened"] is False
    assert plan["provenance"] == "user_authored"
    assert plan["entry"] == 100
    assert plan["paper"]["allowed"] is True
    opened = client.post("/api/paper/orders", json={"opportunity_id": plan["opportunity_id"]})
    assert opened.status_code == 200
    order = opened.get_json()["order"]
    assert order["executable"] is False
    assert order["opened_by"] == "account"
    assert order["entry"] == 100
    book = client.get("/api/paper/book").get_json()
    assert book["open"][0]["entry"] == 100
    assert book.get("broker") is not True
    closed = client.post("/api/paper/close", json={"order_id": order["id"], "exit_price": 103})
    assert closed.status_code == 200
    assert closed.get_json()["order"]["entry"] == 100
    assert closed.get_json()["order"]["exit_price"] == 103
    after = client.get("/api/paper/book").get_json()
    assert after["open"] == []
    assert after["closed"][0]["entry"] == 100
    assert after["closed"][0]["exit_kind"] == "account_exit"
    assert after["trades"] == 1
    autopilot = client.get("/api/autopilot").get_json()
    assert autopilot["broker"] is False
    assert autopilot["health"] == "off"
    assert autopilot["automated_orders"] == 0
    research = client.get("/api/research-lab").get_json()
    assert research["promoted_count"] == 0
    assert research["approved"] == []
