"""Session isolation and response headers. No live account is used."""

def test_security_headers_and_cross_account_book(tmp_path, monkeypatch):
    from ops.app import app
    from ops.test_paperbook import _account

    _users, owner, other = _account(tmp_path, monkeypatch)
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["user_exp"] = 9_999_999_999
    own = client.get("/api/paper/book")
    assert own.status_code == 200
    assert own.headers["X-Content-Type-Options"] == "nosniff"
    assert own.headers["X-Frame-Options"] == "DENY"
    assert own.headers["X-Request-Id"]
    assert "frame-ancestors 'none'" in own.headers["Content-Security-Policy"]
    with client.session_transaction() as sess:
        sess["user_id"] = other["id"]
        sess["user_exp"] = 9_999_999_999
    theirs = client.get("/api/paper/book").get_json()
    assert theirs["orders"] == []
    public = client.get("/health")
    assert public.status_code == 200
    assert public.get_json()["qualification"]["approved_for_paper"] == 0
    with client.session_transaction() as sess:
        sess.clear()
    assert client.get("/api/qualification").status_code == 401
    assert client.get("/api/paper/book").status_code == 401
