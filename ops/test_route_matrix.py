"""Unauthenticated route smoke. A 503 here means the owner token is unset, not a crash."""

def test_empty_requests_do_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.app import app

    app.config["TESTING"] = True
    client = app.test_client()
    crashed = []
    for rule in app.url_map.iter_rules():
        if rule.arguments:
            continue
        for method in sorted(rule.methods & {"GET", "POST"}):
            response = client.get(rule.rule) if method == "GET" else client.post(rule.rule, json={})
            if response.status_code == 500:
                crashed.append(f"{method} {rule.rule}")
    assert crashed == []
