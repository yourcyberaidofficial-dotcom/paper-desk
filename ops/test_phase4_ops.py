"""Phase 4 checks against the process Compose actually starts.

Docker is not installed in this environment. These tests do not start a
container and they do not touch a production volume. The rate-limit numbers
are the process defaults, not the lowered ceilings used by other tests.
"""

import http.cookiejar
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _listen_addresses(port):
    needle = f":{int(port):04X}"
    found = []
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        path = Path(name)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            local = line.split()[1]
            if local.endswith(needle) and line.split()[3] == "0A":
                found.append(local.split(":")[0])
    return found


def _spawn(port, bind, data, extra_env=None):
    data.mkdir(parents=True, exist_ok=True)
    log_path = Path(data) / "server.log"
    handle = log_path.open("w", encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "AUREON_DATA": str(data),
        "AUREON_DISABLE_WORKERS": "1",
        "DESK_BIND": bind,
        "PORT": str(port),
        "PYTHONPATH": str(ROOT),
        "PYTHONUNBUFFERED": "1",
    })
    env.pop("DESK_AUTH_LIMIT", None)
    env.pop("DESK_GENERAL_LIMIT", None)
    if extra_env:
        env.update(extra_env)
    process = subprocess.Popen(
        ["python3", "-m", "ops.app"],
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process._log_path = log_path
    process._log_handle = handle
    deadline = time.time() + 15
    while time.time() < deadline:
        if process.poll() is not None:
            handle.flush()
            raise AssertionError(f"desk exited early on {bind}:{port}: {log_path.read_text(encoding='utf-8')}")
        text = log_path.read_text(encoding="utf-8")
        if "Running on" in text:
            time.sleep(0.2)
            return process
        time.sleep(0.05)
    process.terminate()
    raise AssertionError(f"desk did not report a listen on {bind}:{port}: {log_path.read_text(encoding='utf-8')}")


def _stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    handle = getattr(process, "_log_handle", None)
    if handle is not None:
        handle.close()


def _open(request, opener=None):
    try:
        source = opener.open if opener is not None else urllib.request.urlopen
        with source(request, timeout=3) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _login(port, name, password, forwarded_for=None, opener=None):
    headers = {"Content-Type": "application/json"}
    if forwarded_for:
        headers["X-Forwarded-For"] = forwarded_for
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/login",
        data=json.dumps({"name": name, "password": password}).encode(),
        headers=headers,
    )
    return _open(request, opener)


def test_compose_binds_the_container_but_publishes_only_loopback():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    private = (ROOT / "deploy" / "private-inference" / "ollama-loopback.compose.yml").read_text(encoding="utf-8")
    assert 'DESK_BIND: "0.0.0.0"' in compose
    assert '"127.0.0.1:8080:8080"' in compose
    assert "http://127.0.0.1:8080/health" in compose
    assert "ops.app" in docker
    assert "requirements-lock.txt" in docker
    assert "127.0.0.1:11434:11434" in private
    assert "0.0.0.0:11434:11434" not in private
    assert "OLLAMA_HOST: 0.0.0.0:11434" in private
    from ops.ai_safety import endpoint_allowed

    assert endpoint_allowed("http://127.0.0.1:11434") is True
    assert endpoint_allowed("http://ollama:11434") is True
    assert endpoint_allowed("http://ollama:11435") is False
    assert endpoint_allowed("http://ollama.example.com:11434") is False
    assert endpoint_allowed("https://ollama:11434") is False
    assert endpoint_allowed("http://evil.com:11434") is False


def test_compose_startup_command_answers_on_loopback_and_records_the_listen_address(tmp_path):
    wide = _free_port()
    narrow = _free_port()
    wide_proc = _spawn(wide, "0.0.0.0", tmp_path / "wide")
    try:
        status, _headers, _body = _open(urllib.request.Request(f"http://127.0.0.1:{wide}/version"))
        assert status == 200
        listeners = _listen_addresses(wide)
        assert "00000000" in listeners
    finally:
        _stop(wide_proc)
    narrow_proc = _spawn(narrow, "127.0.0.1", tmp_path / "narrow")
    try:
        status, _headers, _body = _open(urllib.request.Request(f"http://127.0.0.1:{narrow}/version"))
        assert status == 200
        listeners = _listen_addresses(narrow)
        assert "0100007F" in listeners
        assert "00000000" not in listeners
    finally:
        _stop(narrow_proc)


def test_effective_limits_are_20_logins_and_300_general_without_a_test_override(tmp_path):
    """Other tests lower the ceiling so a third call is 429. This process does not.

    A sandbox probe may GET / once when the port opens. The access log is the
    count that matters: 300 general 200s, then 429. Login stays on its own
    bucket of 20.
    """
    port = _free_port()
    process = _spawn(port, "127.0.0.1", tmp_path / "rate")
    try:
        login_codes = []
        last_auth = None
        for _ in range(21):
            last_auth = _login(port, "nobody", "not-the-password")
            login_codes.append(last_auth[0])
        assert login_codes[:20] == [401] * 20
        assert login_codes[20] == 429
        auth_body = json.loads(last_auth[2])
        assert auth_body == {"error": "rate_limited", "scope": "auth"}
        assert int(last_auth[1]["Retry-After"]) >= 1
        spoofed = _login(port, "nobody", "not-the-password", forwarded_for="203.0.113.51")
        assert spoofed[0] == 429
        assert json.loads(spoofed[2])["scope"] == "auth"
        general = []
        last_general = None
        for _ in range(305):
            last_general = _open(urllib.request.Request(f"http://127.0.0.1:{port}/version"))
            general.append(last_general[0])
            if last_general[0] == 429:
                break
        assert general[-1] == 429
        assert general.count(429) == 1
        assert json.loads(last_general[2])["scope"] == "general"
        forwarded = _open(urllib.request.Request(
            f"http://127.0.0.1:{port}/version",
            headers={"X-Forwarded-For": "203.0.113.50"},
        ))
        assert forwarded[0] == 429
        assert json.loads(forwarded[2])["scope"] == "general"
        process._log_handle.flush()
        log = Path(process._log_path).read_text(encoding="utf-8")
        allowed = 0
        for line in log.splitlines():
            if '"GET ' not in line:
                continue
            if line.rstrip().endswith(" 200 -"):
                allowed += 1
            elif line.rstrip().endswith(" 429 -"):
                break
        assert allowed == 300
        assert general.count(200) in {299, 300}
        # The deployment window is 60 seconds. Wait it out on this same process.
        time.sleep(int(last_auth[1]["Retry-After"]) + 1)
        expired_login = _login(port, "nobody", "not-the-password")
        assert expired_login[0] == 401
        expired_general = _open(urllib.request.Request(f"http://127.0.0.1:{port}/version"))
        assert expired_general[0] == 200
    finally:
        _stop(process)


def test_default_limits_allow_a_signed_in_account(tmp_path):
    """Compose does not lower the ceilings. A normal register and read is not a 429."""
    port = _free_port()
    process = _spawn(port, "127.0.0.1", tmp_path / "account")
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        created = _open(urllib.request.Request(
            f"http://127.0.0.1:{port}/api/register",
            data=json.dumps({"name": "ada", "password": "password-s"}).encode(),
            headers={"Content-Type": "application/json"},
        ), opener)
        assert created[0] == 200, created[2]
        signed = _login(port, "ada", "password-s", opener=opener)
        assert signed[0] == 200, signed[2]
        for path in (
            "/overview", "/signals", "/orders", "/history", "/live",
            "/api/me", "/api/activity", "/api/ai", "/api/autopilot", "/api/signals/lifecycle",
        ):
            status, _headers, body = _open(urllib.request.Request(f"http://127.0.0.1:{port}{path}"), opener)
            assert status == 200, (path, status, body[:180])
        health = _open(urllib.request.Request(f"http://127.0.0.1:{port}/health"))
        assert health[0] == 200
        me = json.loads(_open(urllib.request.Request(f"http://127.0.0.1:{port}/api/me"), opener)[2])
        assert me["name"] == "ada"
    finally:
        _stop(process)


def test_trusted_proxy_counts_the_appended_hop_not_a_rotating_prefix(tmp_path):
    """DESK_TRUST_PROXY is off in Compose. When it is on, the left side must not mint buckets."""
    port = _free_port()
    process = _spawn(port, "127.0.0.1", tmp_path / "proxy", extra_env={"DESK_TRUST_PROXY": "1"})
    try:
        codes = []
        for index in range(21):
            result = _login(
                port,
                "nobody",
                "not-the-password",
                forwarded_for=f"198.51.100.{index}, 203.0.113.9",
            )
            codes.append(result[0])
        assert codes[:20] == [401] * 20
        assert codes[20] == 429
        assert json.loads(result[2])["scope"] == "auth"
    finally:
        _stop(process)


def test_this_host_is_not_an_inference_machine_and_foreign_refs_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setenv("OLLAMA_MODEL", "qwen-test")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    from ops.ai_provider import ask
    from ops.inference_host import inventory
    from ops.ollama import explain

    body = inventory()
    assert body["operational"] == "BLOCKED"
    assert body["suitable_host_found"] is False
    assert body["download_attempted"] is False
    assert body["selected_model"] is None
    assert body["benchmark_status"] == "NOT TESTED"
    assert body["hosts"][0]["ram_bytes"] < body["refusal_floor_bytes"]
    captured = {}

    def transport(method, url, payload):
        captured["payload"] = payload
        if method == "GET":
            return 200, {"models": [{"name": "qwen-test"}]}
        return 200, {"message": {"content": json.dumps({
            "summary": "Stored observation only.",
            "evidence_used": ["opp:not-a-real-row"],
        })}}

    import ops.users as users

    previous = users.ROOT
    users.ROOT = tmp_path / "users"
    users.ROOT.mkdir(parents=True, exist_ok=True)
    try:
        owner = users.register("ada", "password-s")
        result = ask(owner["id"], "explain_signal", transport=transport, now_ms=4)
    finally:
        users.ROOT = previous
    assert result["reason"] == "ungrounded"
    assert result["approved"] is False
    assert result["order_opened"] is False
    assert "opp:not-a-real-row" not in " ".join(result["explanation"]["evidence_used"])
    explained = explain({"symbol": "BTCUSDT", "observation": "data_unavailable"}, transport=transport)
    assert explained["ok"] is True
    assert captured["payload"]["options"]["num_predict"] == 320
