"""Stage 4: one web process, one worker, a baked content hash, and a safe copy."""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_content_hash_is_baked_apart_from_the_commit_label(tmp_path, monkeypatch):
    from ops.content_hash import compute_content_hash, content_hash_baked, write_baked

    first = compute_content_hash(ROOT)
    assert first == compute_content_hash(ROOT)
    assert len(first) == 64
    target = tmp_path / "IMAGE_CONTENT_HASH"
    assert write_baked(target, ROOT) == first
    monkeypatch.setenv("AUREON_CONTENT_HASH_FILE", str(target))
    monkeypatch.setenv("AUREON_BUILD_COMMIT", "ab" * 20)
    assert content_hash_baked() is True
    from ops.app import app

    app.config["TESTING"] = True
    body = app.test_client().get("/version").get_json()
    assert body["build_commit"] == "ab" * 20
    assert body["build_commit_kind"] == "label"
    assert body["content_hash"] == first
    assert body["content_hash_kind"] == "image"
    assert body["content_hash_baked"] is True
    assert body["content_hash"] != body["build_commit"]
    assert body["data_schema"]["version"] == 1
    assert "ab" * 20 not in body["content_hash"]


def test_compose_runs_one_web_wsgi_process_and_a_worker_on_the_same_volumes():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'DESK_BIND: "0.0.0.0"' in compose
    assert '"127.0.0.1:8080:8080"' in compose
    assert "http://127.0.0.1:8080/health" in compose
    assert "AUREON_DISABLE_WORKERS" in compose
    assert "AUREON_ROLE: web" in compose
    assert "AUREON_ROLE: worker" in compose
    assert "gunicorn" in compose
    assert "--workers" in compose
    assert '"1"' in compose
    assert "ops.worker_main" in compose
    assert "python -m ops.app" not in compose
    assert compose.count("ports:") == 1
    for mount in (
        "desk-data:/app/data/paper",
        "desk-users:/app/data/users",
        "desk-shadow:/app/data/shadow",
        "desk-signals:/app/data/signals",
        "desk-activity:/app/data/activity",
        "desk-rights:/app/data/rights",
        "desk-cache:/app/data/cache",
        "desk-canonical:/app/data/canonical",
        "desk-ai:/app/data/ai",
    ):
        assert compose.count(mount) == 2
    assert "gunicorn" in docker
    assert "IMAGE_CONTENT_HASH" in docker
    assert "ops.app" in docker
    assert "requirements-lock.txt" in docker
    assert "--workers" in docker and '"1"' in docker


def test_web_process_does_not_start_worker_loops():
    code = textwrap.dedent(
        """
        import os, threading, time
        os.environ["AUREON_DISABLE_WORKERS"] = "1"
        os.environ["AUREON_ROLE"] = "web"
        os.environ["DESK_SESSION_SECRET"] = "phase4-session-secret-is-32-characters-minimum"
        import ops.app
        time.sleep(0.2)
        names = [thread.name for thread in threading.enumerate()]
        assert "aureon-desk" not in names, names
        assert "aureon-telegram" not in names, names
        assert "aureon-digest" not in names, names
        print("web-quiet")
        """
    )
    env = os.environ.copy()
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not prior else str(ROOT) + os.pathsep + prior
    ran = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=30)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "web-quiet" in ran.stdout


def test_empty_crypto_bars_fall_back_to_kraken_and_a_full_list_does_not(monkeypatch):
    from ops.worker import Worker

    worker = Worker(None, "/tmp/unused-prefs.json")
    monkeypatch.setattr("ops.terminal_route.feed_state", lambda *_args, **_kwargs: "live")
    calls = {"empty": 0, "full": 0}

    def empty(*_args, **_kwargs):
        return []

    def kraken_empty(*_args, **_kwargs):
        calls["empty"] += 1
        return [{"close": 1, "close_time_ms": 5}]

    monkeypatch.setattr("ops.terminal_route.load_crypto_bars", empty)
    monkeypatch.setattr(worker, "_kraken_bars", kraken_empty)
    window = worker._one_window("BTCUSDT", "15m", 1_700_000_000_000)
    assert calls["empty"] == 1
    assert window["bars"][0]["close"] == 1
    assert window["feed_state"] == "live"

    def full(*_args, **_kwargs):
        return [{"close": 9, "close_time_ms": 6}]

    def kraken_full(*_args, **_kwargs):
        calls["full"] += 1
        return [{"close": 2, "close_time_ms": 6}]

    monkeypatch.setattr("ops.terminal_route.load_crypto_bars", full)
    monkeypatch.setattr(worker, "_kraken_bars", kraken_full)
    kept = worker._one_window("ETHUSDT", "15m", 1_700_000_000_000)
    assert calls["full"] == 0
    assert kept["bars"][0]["close"] == 9

    def failed(*_args, **_kwargs):
        return (None, "TimeoutError")

    monkeypatch.setattr("ops.terminal_route.load_crypto_bars", failed)
    monkeypatch.setattr(worker, "_kraken_bars", lambda *_a, **_k: [{"close": 3, "close_time_ms": 7}])
    recovered = worker._one_window("BTCUSDT", "1h", 1_700_000_000_000)
    assert recovered["bars"][0]["close"] == 3


def test_outbox_change_from_another_process_is_visible_without_the_event(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.inbox_notify import wait_for_work

    path = tmp_path / "paper" / "telegram_inbox.jsonl"
    box = {}

    def wait():
        box["value"] = wait_for_work(3)

    thread = threading.Thread(target=wait)
    thread.start()
    time.sleep(0.15)
    code = textwrap.dedent(
        f"""
        from pathlib import Path
        path = Path({str(path)!r})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{{"key":"other-container"}}\\n', encoding="utf-8")
        """
    )
    ran = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, timeout=10)
    assert ran.returncode == 0, ran.stderr
    thread.join(2)
    assert not thread.is_alive()
    assert box["value"] is False


def test_web_reads_the_worker_file_and_does_not_fetch(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.desk_pulse import reset

    reset()
    code = textwrap.dedent(
        f"""
        import os, time
        os.environ["AUREON_DATA"] = {str(tmp_path)!r}
        os.environ["AUREON_ROLE"] = "worker"
        from ops.desk_pulse import publish
        from ops.worker_status import publish_patch
        now = int(time.time() * 1000)
        publish({{
            "symbol": "BTCUSDT",
            "interval": "15m",
            "decision": "WAIT",
            "decision_label": "WAIT",
            "bar_close_ms": now - 1000,
            "feed_state": "live",
            "reference_price": 101.5,
            "price": 101.5,
        }}, now)
        publish_patch({{
            "alive_ms": now,
            "last_beat_ms": now,
            "role": "worker",
            "runtime": {{"state": "RUNNING", "phase": "running", "accepting": True}},
        }})
        """
    )
    env = os.environ.copy()
    prior = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) if not prior else str(ROOT) + os.pathsep + prior
    env["AUREON_DATA"] = str(tmp_path)
    ran = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, text=True, capture_output=True, timeout=30)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    monkeypatch.setenv("AUREON_ROLE", "web")
    monkeypatch.setattr("ops.customer_release.any_customer_display", lambda: True)
    monkeypatch.setattr("ops.customer_release.candles_released", lambda *_a, **_k: True)
    monkeypatch.setattr("ops.customer_release.reading_released", lambda *_a, **_k: True)

    def boom(*_args, **_kwargs):
        raise AssertionError("upstream fetch")

    monkeypatch.setattr("ops.app.market_snapshot", boom)
    monkeypatch.setattr("ops.desk_snapshot.headline_board", boom)
    monkeypatch.setattr("ops.desk_snapshot.desk_scan", boom)
    monkeypatch.setattr("ops.desk_snapshot.observe", boom)
    from ops.app import app
    import ops.users as users

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    created = users.register("ada", "password-s")
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = created["id"]
        sess["user_exp"] = 9_999_999_999
    health = client.get("/health").get_json()
    assert health["market_data"]["BTCUSDT"]["source"] == "canonical"
    assert health["market_data"]["BTCUSDT"]["status"] == "fresh"
    assert health["worker"]["source"] == "worker_file"
    assert health["worker"]["status"] == "beating"
    assert health["runtime"]["source"] == "worker_file"
    markets = client.get("/api/markets").get_json()
    btc = next(row for row in markets["markets"] if row["symbol"] == "BTCUSDT")
    assert btc["fetched_upstream"] is False
    assert btc["data"]["price"] == 101.5
    scan = client.get("/api/scanner").get_json()
    assert scan["fetched_upstream"] is False
    assert scan["source"] == "canonical"
    desk = client.get("/api/desk").get_json()
    assert desk["fetched_upstream"] is False
    workspace = client.get("/api/workspace").get_json()
    assert "did not fetch" in workspace["notice"]
    panel = next(row for row in workspace["panels"] if row["symbol"] == "BTCUSDT")
    assert panel["price"] == 101.5
    reset()


def test_schema_guard_stamps_without_rewriting_and_refuses_a_newer_file(tmp_path, monkeypatch):
    from ops.schema_guard import guard
    from ops.worker_main import main

    account = tmp_path / "users" / "ada.json"
    account.parent.mkdir()
    account.write_text('{"id":"ada","capital":10}', encoding="utf-8")
    before = account.read_bytes()
    stamped = guard(tmp_path, apply=True)
    assert stamped["action"] == "stamped"
    assert stamped["rewritten"] is False
    assert account.read_bytes() == before
    assert guard(tmp_path, apply=True)["action"] == "current"
    readings = tmp_path / "canonical" / "readings.json"
    readings.write_text(json.dumps({"schema": 9, "readings": [{"symbol": "BTCUSDT"}]}), encoding="utf-8")
    kept = readings.read_bytes()
    refused = guard(tmp_path, apply=True)
    assert refused["action"] == "newer_than_code"
    assert refused["rewritten"] is False
    assert readings.read_bytes() == kept
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    assert main() == 2
    assert readings.read_bytes() == kept


def test_volume_backup_copies_and_does_not_delete(tmp_path):
    from ops.volume_backup import backup_root, restore_volume

    root = tmp_path / "opt-aureon"
    users = root / "users"
    users.mkdir(parents=True)
    (users / "ada.json").write_text('{"id":"ada"}', encoding="utf-8")
    canonical = root / "canonical"
    canonical.mkdir()
    (canonical / "schema.json").write_text('{"schema":1}', encoding="utf-8")
    dest = tmp_path / "backups" / "stamp"
    created = backup_root(root, dest)
    assert created["ok"] is True
    assert created["deleted"] is False
    assert (users / "ada.json").read_text(encoding="utf-8") == '{"id":"ada"}'
    assert json.loads((dest / "index.json").read_text(encoding="utf-8"))["data_schema"] == 1
    restored = tmp_path / "restore-users"
    assert restore_volume(dest / "desk-users", restored)["ok"] is True
    assert json.loads((restored / "ada.json").read_text(encoding="utf-8"))["id"] == "ada"
    tampered = dest / "desk-users" / "files" / "ada.json"
    tampered.write_text("nope", encoding="utf-8")
    refused = restore_volume(dest / "desk-users", tmp_path / "should-stay-empty")
    assert refused["ok"] is False
    assert not (tmp_path / "should-stay-empty").exists()
    assert (users / "ada.json").exists()


def test_settings_polls_me_while_telegram_is_pending():
    text = (ROOT / "ops" / "ui" / "dashboard.html").read_text(encoding="utf-8")
    assert "function watchTelegram()" in text
    assert 'fetch("/api/me"' in text
    assert 'if (me.telegram_state === "pending") watchTelegram();' in text
    assert "watchTelegram();" in text
    assert "setInterval" in text


def test_health_without_customer_candles_is_not_a_server_error(monkeypatch):
    monkeypatch.setattr("ops.customer_release.candles_released", lambda *_args, **_kwargs: False)
    from ops.app import _reading_not_shown, app

    app.config["TESTING"] = True
    response = app.test_client().get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "reading_unavailable"
    assert body["market_data"]["BTCUSDT"] == _reading_not_shown()
    assert body["market_data"]["ETHUSDT"]["status"] == "not_shown"
    assert body["market_data"]["ETHUSDT"]["kind"] == "not_a_customer_reading"
    assert "traceback" not in json.dumps(body).lower()


def test_worker_check_fails_when_a_loop_has_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.worker_status import check, publish_patch

    now = int(time.time() * 1000)
    publish_patch({
        "alive_ms": now,
        "threads": ["aureon-desk", "aureon-telegram", "aureon-digest"],
        "role": "worker",
    })
    assert check() is True
    publish_patch({
        "alive_ms": int(time.time() * 1000),
        "threads": ["aureon-telegram", "aureon-digest"],
    })
    assert check() is False


def test_term_asks_the_worker_to_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import signal

    from ops.runtime import DeskRuntime
    from ops.worker_main import install_signals, request_stop

    runtime = DeskRuntime(deadline_s=0.2)
    runtime.mark_started()
    request_stop(runtime)
    assert runtime._stop.is_set()
    runtime._stop.clear()
    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    try:
        install_signals(runtime)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert runtime._stop.is_set()
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
    stopped = runtime.shutdown(deadline_s=0.2)
    assert stopped["phase"] == "stopped"
    assert stopped["completed"] is True


def test_outbox_watch_uses_stat_and_not_a_full_read(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from pathlib import Path

    from ops.inbox_notify import _outbox, _outbox_stamp

    path = _outbox()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("a" * 24, encoding="utf-8")
    first = _outbox_stamp()
    time.sleep(0.02)
    path.write_text("b" * 24, encoding="utf-8")

    def explode(self, *args, **kwargs):
        raise AssertionError("the outbox watcher read the file")

    monkeypatch.setattr(Path, "read_bytes", explode)
    second = _outbox_stamp()
    assert first is not None and second is not None
    assert first != second
    assert len(second) == 3


def test_active_writes_stay_inside_the_nine_volumes(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.desk_pulse import _path as readings_path
    from ops.inbox_notify import _outbox
    from ops.paths import (
        VOLUME_DIRS,
        bot_root,
        claims_root,
        imports_root,
        ledger_path,
        on_volume,
        promotions_path,
        runtime_state_path,
        shadow_observations_path,
        telegram_offset_path,
        telegram_seen_path,
    )
    from ops.volume_backup import VOLUMES
    from ops.worker_status import status_path

    paths = [
        ledger_path(),
        shadow_observations_path(),
        promotions_path(),
        telegram_offset_path(),
        telegram_seen_path(),
        claims_root() / "BTCUSDT-15m.json",
        runtime_state_path(),
        imports_root("ada") / "import_log.jsonl",
        bot_root() / "ada.jsonl",
        status_path(),
        readings_path(),
        _outbox(),
    ]
    for path in paths:
        assert on_volume(path), path
    names = {volume for _directory, volume in VOLUME_DIRS}
    assert names == {name for name, _relative in VOLUMES}
    assert len(names) == 9
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for directory, volume in VOLUME_DIRS:
        assert compose.count(f"{volume}:/app/data/{directory}") == 2

