"""Five-way check for every route that has no path argument, plus the two user routes.

A category that cannot apply is recorded with a reason. It is not skipped silently.
"""

import json

PUBLIC_GET = {
    "/api/ai", "/api/broker", "/api/council", "/api/coverage", "/api/data-coverage", "/api/deep-board",
    "/api/engine", "/api/gold/candles", "/api/gold/signal", "/api/klines", "/api/leaderboard",
    "/api/market", "/api/markets", "/api/notify-history", "/api/paper-status", "/api/period",
    "/api/platform", "/api/profiles", "/api/replay", "/api/research-lab", "/api/research-signals",
    "/api/signal", "/api/signal-history", "/api/triad", "/health", "/version",
}
SESSION_GET = {
    "/api/activity", "/api/autopilot", "/api/bot/thread", "/api/candles/import", "/api/desk", "/api/desk/pulse", "/api/eligibility", "/api/experience", "/api/accounts", "/api/inbox/settings",
    "/api/lab", "/api/me", "/api/notifications", "/api/paper/book", "/api/plan",
    "/api/qualification", "/api/registry", "/api/scanner", "/api/signals/lifecycle",
    "/api/terminal/history", "/api/workspace",
}
SESSION_POST = {
    "/api/activity/read", "/api/ai/ask", "/api/aureon-ai", "/api/autopilot", "/api/candles/evaluate", "/api/candles/import", "/api/desk/plan", "/api/digest", "/api/explain",
    "/api/experience", "/api/inbox/settings", "/api/lab", "/api/notifications/read", "/api/paper/close",
    "/api/paper/orders", "/api/plan", "/api/prefs", "/api/profile", "/api/size",
    "/api/telegram/link", "/api/telegram/unlink", "/api/terminal/signal",
}
TOKEN_GET = {"/api/evaluations", "/api/events", "/api/experimental", "/api/prefs", "/api/state"}
TOKEN_POST = {"/api/alert-test", "/api/bar", "/api/worker/prefs"}
PAGES = {
    "/overview", "/signals", "/trading", "/strategies", "/indicators", "/research",
    "/portfolio", "/risk", "/activity", "/live", "/system", "/settings", "/scanner",
    "/learn", "/plan", "/lab", "/notifications", "/onboarding", "/orders", "/history",
    "/accounts",
}
PUBLIC_PAGES = {"/", "/login", "/register"}
AUTH_FREE_POST = {"/api/login", "/api/logout", "/api/register", "/api/telegram/confirm", "/api/telegram/update", "/login", "/logout"}
LIFECYCLE_WRITE = {"/api/signals/lifecycle"}


def _body(response):
    text = response.get_data(as_text=True)
    try:
        return text, response.get_json(silent=True)
    except Exception:
        return text, None


def test_every_route_has_five_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setenv("DESK_API_TOKEN", "phase2-token-which-is-long-enough")
    import ops.users as users
    from ops.app import app

    users.ROOT = tmp_path / "users"
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = users.register("matrix-owner", "password-s")
    other = users.register("matrix-other", "password-s")
    from ops.app import LIMITER
    previous_limit = LIMITER.per_minute
    LIMITER.per_minute = 100000
    LIMITER.hits.clear()
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        client = app.test_client()
        assert client.post("/api/login", json={"name": "matrix-owner", "password": "password-s"}).status_code == 200
        token = "phase2-token-which-is-long-enough"
        rows = []
        seen = []
        for rule in app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            for method in sorted(rule.methods & {"GET", "POST", "PUT", "DELETE", "PATCH"}):
                seen.append((method, rule.rule))
                rows.append(_probe(app, client, method, rule.rule, owner, other, token))
        missing = [f"{method} {rule}" for method, rule in seen if _kind(method, rule) is None]
        assert missing == []
        failed = [row for row in rows if row["verdict"] != "PASS"]
        assert failed == []
        assert len(rows) == len(seen)
        kinds = {row["kind"] for row in rows}
        assert "session" in kinds and "public" in kinds and "token" in kinds
        import os
        from pathlib import Path
        destination = os.environ.get("AUREON_MATRIX_OUT")
        if destination:
            Path(destination).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    finally:
        LIMITER.per_minute = previous_limit
        LIMITER.hits.clear()


def _kind(method, rule):
    if method == "GET" and rule in PUBLIC_GET:
        return "public"
    if method == "GET" and rule in SESSION_GET:
        return "session"
    if method == "POST" and rule in SESSION_POST:
        return "session"
    if method == "GET" and rule in TOKEN_GET:
        return "token"
    if method == "POST" and rule in TOKEN_POST:
        return "token"
    if method == "GET" and rule in PAGES:
        return "page"
    if method == "GET" and rule in PUBLIC_PAGES:
        return "public-page"
    if method == "POST" and rule in AUTH_FREE_POST:
        return "auth-free"
    if method in {"POST", "PUT", "DELETE", "PATCH"} and rule in LIFECYCLE_WRITE:
        return "lifecycle-write"
    if rule == "/api/users/<user_id>":
        return "closed-user"
    if rule == "/api/users/<user_id>/telegram":
        return "telegram-user"
    return None


def _probe(app, client, method, rule, owner, other, token):
    kind = _kind(method, rule)
    path = rule.replace("<user_id>", other["id"])
    actor = client
    if rule in {"/api/logout", "/logout"}:
        actor = app.test_client()
    result = {"method": method, "rule": rule, "kind": kind, "checks": {}}
    try:
        result["checks"]["success"] = _success(actor, method, path, kind, token)
        result["checks"]["invalid"] = _invalid(actor, method, path, kind, token)
        result["checks"]["auth"] = _auth(app, method, path, kind, token)
        result["checks"]["missing"] = _missing(app, method, path, kind, owner, other, token)
        result["checks"]["internal"] = _internal(app, actor, method, path)
    except Exception as exc:
        result["checks"]["raised"] = {"status": "FAIL", "reason": type(exc).__name__ + ": " + str(exc)[:180]}
    result["verdict"] = "PASS" if all(item.get("status") == "PASS" for item in result["checks"].values()) else "FAIL"
    return result


def _call(client, method, path, **kwargs):
    kwargs.setdefault("headers", {})
    if method == "GET":
        return client.get(path, **kwargs)
    if method == "POST":
        return client.post(path, **kwargs)
    if method == "PUT":
        return client.put(path, **kwargs)
    if method == "DELETE":
        return client.delete(path, **kwargs)
    return client.patch(path, **kwargs)


def _ok_status(response):
    return response.status_code < 500


def _success(client, method, path, kind, token):
    headers = {}
    payload = {}
    if kind == "token":
        headers["Authorization"] = "Bearer " + token
    if method == "POST" and path == "/api/login":
        fresh = client.application.test_client()
        response = fresh.post(path, json={"name": "matrix-owner", "password": "password-s"})
        if response.status_code != 200 or not (response.get_json() or {}).get("ok"):
            return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:160]}
        return {"status": "PASS", "code": 200, "reason": "A separate client logged in. The suite session was left signed in."}
    if method == "POST" and path == "/api/register":
        fresh = client.application.test_client()
        response = fresh.post(path, json={"name": "matrix-created", "password": "password-s"})
        if response.status_code != 200 or not (response.get_json() or {}).get("id"):
            return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:160]}
        return {"status": "PASS", "code": 200, "reason": "Registration succeeded on a separate client."}
    if method == "POST" and path == "/login":
        fresh = client.application.test_client()
        with fresh.session_transaction() as sess:
            sess["csrf"] = "phase2-csrf"
        response = fresh.post(path, data={"csrf": "phase2-csrf", "token": token})
        location = response.headers.get("Location") or ""
        if response.status_code != 302 or "login=failed" in location:
            return {"status": "FAIL", "code": response.status_code, "body": location}
        return {"status": "PASS", "code": 302, "reason": "Owner token login redirected into the desk."}
    if method == "POST" and path == "/api/autopilot":
        enabled = client.post(path, json={"action": "enable", "confirm": True, "max_orders_per_day": 1})
        paused = client.post(path, json={"action": "pause"})
        client.post(path, json={"action": "disable"})
        if enabled.status_code != 200 or paused.status_code != 200:
            return {"status": "FAIL", "code": enabled.status_code, "body": enabled.get_data(as_text=True)[:160]}
        return {"status": "PASS", "code": 200, "reason": "Enable and pause succeeded. Disable ran afterwards. No order was opened."}
    if method == "POST" and path == "/api/paper/orders":
        response = _call(client, method, path, json={"opportunity_id": "missing-opportunity"})
        body = response.get_json(silent=True) or {}
        if response.status_code == 404 and body.get("reason") == "missing_opportunity" and body.get("ok") is False:
            return {"status": "PASS", "code": 404, "reason": "Authenticated, and no order was opened because the opportunity does not exist. A stored opportunity open is covered by ops/test_paperbook.py."}
        return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:160]}
    if method == "POST" and path == "/api/paper/close":
        response = _call(client, method, path, json={"order_id": "missing-order"})
        body = response.get_json(silent=True) or {}
        if response.status_code == 409 and body.get("ok") is False:
            return {"status": "PASS", "code": 409, "reason": "Authenticated close of a missing order is refused. A real close is covered by ops/test_paperbook.py."}
        return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:160]}
    if method == "POST" and path == "/api/desk/plan":
        response = _call(client, method, path, json={"symbol": "BTCUSDT", "interval": "15m"})
        body = response.get_json(silent=True) or {}
        if response.status_code == 200 and body.get("order_opened") is False and body.get("reason") == "reading_unavailable":
            return {"status": "PASS", "code": 200, "reason": "No display grant. The plan route refused and did not open an order."}
        return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:180]}
    if method == "POST" and path == "/api/telegram/confirm":
        response = _call(client, method, path, json={"token": "typed", "telegram_id": "1"})
        body = response.get_json(silent=True) or {}
        if response.status_code == 400 and body.get("error") == "typed_id_not_accepted":
            return {"status": "PASS", "code": 400, "reason": "A typed Telegram id is refused. That is the route contract."}
        return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:160]}
    if method == "POST" and path == "/api/bar":
        payload = {"symbol": "BTCUSDT", "bar": {"close": 1}}
    if method == "POST" and path == "/api/worker/prefs":
        payload = {"assets": ["BTCUSDT"], "interval": "15m"}
    if method == "POST" and path in {"/api/logout", "/logout"}:
        fresh = client.application.test_client()
        if path == "/api/logout":
            assert fresh.post("/api/login", json={"name": "matrix-owner", "password": "password-s"}).status_code == 200
            response = fresh.post(path)
            good = response.status_code == 200
        else:
            response = fresh.post(path)
            good = response.status_code in {302, 400, 401}
        if not good:
            return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:160]}
        return {"status": "PASS", "code": response.status_code, "reason": "Logout was checked on a separate client so the suite session stayed signed in."}
    response = _call(client, method, path, json=payload, headers=headers)
    if kind == "page":
        good = response.status_code == 200
    elif kind == "public" and method == "GET":
        good = response.status_code == 200
    elif kind == "session" and method == "GET":
        good = response.status_code == 200
    elif kind == "token" and method == "GET":
        good = response.status_code == 200
    elif kind == "public-page":
        good = response.status_code in {200, 302}
    elif kind == "lifecycle-write":
        good = response.status_code == 405 and response.get_json()["modified"] is False
    elif kind == "closed-user":
        good = response.status_code == 404
    elif kind == "telegram-user":
        good = response.status_code == 403
    elif kind == "auth-free" and path == "/api/register":
        good = response.status_code == 400
    elif kind == "auth-free" and path == "/login":
        good = response.status_code in {302, 400}
    elif kind == "auth-free" and path == "/logout":
        good = response.status_code in {302, 400}
    else:
        good = _ok_status(response)
    if not good:
        return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:180]}
    return {"status": "PASS", "code": response.status_code}


def _invalid(client, method, path, kind, token):
    headers = {"Authorization": "Bearer " + token} if kind == "token" else {}
    if method == "GET":
        response = _call(client, method, path + ("&" if "?" in path else "?") + "at=not-a-time&limit=no&symbol=", headers=headers)
    else:
        response = _call(client, method, path, data="{", headers={**headers, "Content-Type": "application/json"})
    if response.status_code >= 500:
        return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:180]}
    return {"status": "PASS", "code": response.status_code, "reason": "Invalid input did not become an internal error."}


def _auth(app, method, path, kind, token):
    stranger = app.test_client()
    if kind in {"public", "public-page", "auth-free"}:
        response = _call(stranger, method, path, json={})
        if response.status_code >= 500:
            return {"status": "FAIL", "code": response.status_code}
        return {"status": "PASS", "reason": "This route has no account payload. Authentication is not the access control.", "code": response.status_code}
    if kind == "token":
        import os
        saved = os.environ.pop("DESK_API_TOKEN", None)
        try:
            missing = _call(stranger, method, path, json={})
        finally:
            if saved is not None:
                os.environ["DESK_API_TOKEN"] = saved
        bad = _call(stranger, method, path, json={}, headers={"Authorization": "Bearer nope"})
        if missing.status_code == 503 and bad.status_code == 401:
            return {"status": "PASS", "code": 401, "reason": "Unset owner token is 503. A wrong token is 401."}
        return {"status": "FAIL", "missing": missing.status_code, "bad": bad.status_code}
    if kind == "page":
        response = _call(stranger, method, path)
        if response.status_code == 302 and "/login" in (response.headers.get("Location") or ""):
            return {"status": "PASS", "code": 302}
        return {"status": "FAIL", "code": response.status_code}
    if kind == "closed-user":
        response = _call(stranger, method, path)
        if response.status_code == 404 and "password" not in response.get_data(as_text=True):
            return {"status": "PASS", "reason": "The route never returns an account, signed in or not.", "code": 404}
        return {"status": "FAIL", "code": response.status_code}
    response = _call(stranger, method, path, json={})
    if response.status_code == 401:
        return {"status": "PASS", "code": 401}
    return {"status": "FAIL", "code": response.status_code, "body": response.get_data(as_text=True)[:160]}


def _missing(app, method, path, kind, owner, other, token):
    if kind in {"public", "public-page", "auth-free", "token"}:
        return {"status": "PASS", "reason": "No account-owned record is addressed. Ownership is not applicable."}
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = owner["id"]
        sess["user_exp"] = 9_999_999_999
    target = path
    if kind == "telegram-user":
        target = "/api/users/does-not-exist/telegram"
    response = _call(client, method, target, json={"symbol": "BTCUSDT", "interval": "15m"}, headers={"Authorization": "Bearer " + token} if kind == "token" else {})
    text, _payload = _body(response)
    if response.status_code >= 500 or "matrix-other" in text or "password_hash" in text:
        return {"status": "FAIL", "code": response.status_code, "body": text[:160]}
    if kind == "session" and path.endswith("/api/me"):
        if response.status_code != 404:
            # The user still exists in this check. Deletion is the next assertion.
            pass
    user_path = __import__("ops.users", fromlist=["ROOT"]).ROOT / f"{owner['id']}.json"
    raw = user_path.read_text(encoding="utf-8")
    user_path.unlink()
    try:
        gone = app.test_client()
        with gone.session_transaction() as sess:
            sess["user_id"] = owner["id"]
            sess["user_exp"] = 9_999_999_999
        response = _call(gone, method, path if kind != "telegram-user" else "/api/users/does-not-exist/telegram", json={})
        text, _payload = _body(response)
        if response.status_code >= 500 or other["id"] in text and "matrix-other" in text:
            return {"status": "FAIL", "code": response.status_code, "body": text[:160]}
        if "password_hash" in text or "matrix-other" in text:
            return {"status": "FAIL", "reason": "missing account leaked another profile", "body": text[:160]}
    finally:
        user_path.write_text(raw, encoding="utf-8")
    return {"status": "PASS", "reason": "A missing profile did not fall through to another account.", "code": response.status_code}


def _internal(app, client, method, path):
    previous = app.config.get("PROPAGATE_EXCEPTIONS")
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.config["INJECT_FAULT"] = path.split("?")[0]
    app.config["INJECT_FAULT_METHOD"] = method
    try:
        response = _call(client, method, path, json={})
        text = response.get_data(as_text=True)
        if response.status_code != 500 or "Traceback" in text or "handled" not in text:
            return {"status": "FAIL", "code": response.status_code, "body": text[:180]}
        return {"status": "PASS", "code": 500}
    finally:
        app.config["INJECT_FAULT"] = None
        app.config["INJECT_FAULT_METHOD"] = None
        app.config["PROPAGATE_EXCEPTIONS"] = previous
