"""Worker shadow path and release identity. No network and no Telegram."""

import json
from datetime import datetime, timezone

from ops.bars import make_bar
from ops.build_id import build_commit
from ops.engine_eval import PRODUCTION
from ops.ledger import Ledger
from ops.shadow import ShadowLedger
from ops.shadow_bridge import config_sha256, observe_prospective, promotion_ids
from ops.worker import Worker

STEP = 15 * 60 * 1000
HOUR = 60 * 60 * 1000
START = int(datetime(2026, 3, 2, tzinfo=timezone.utc).timestamp() * 1000)


def _bars(count, step, start, price=100.0, symbol="BTCUSDT", interval="15m", fresh=True, complete=True):
    rows = []
    for index in range(count):
        open_time = start + index * step
        close = price + 5 if index == count - 1 else price
        rows.append(make_bar(
            symbol=symbol,
            instrument=symbol,
            interval=interval,
            open_time_ms=open_time,
            close_time_ms=open_time + step - 1,
            open=price,
            high=close + 0.4,
            low=price - 0.4,
            close=close,
            volume=1,
            provider="fixture",
            source_type="fixture",
            quote_semantics="last_trade",
            retrieved_at_ms=open_time + step,
            complete=complete if index == count - 1 else True,
            fresh=fresh if index == count - 1 else False,
        ))
    return rows


def _window(bars, higher, **extra):
    last = bars[-1]
    row = {
        "symbol": "BTCUSDT",
        "interval": "15m",
        "ok": True,
        "reason": None,
        "bars": bars,
        "higher": higher,
        "provider": "binance-public",
        "quote_semantics": "last_trade",
        "source_kind": "prospective",
    }
    row.update(extra)
    row["bars"][-1]["fresh"] = extra.get("fresh", last.get("fresh"))
    return row


def test_build_commit_is_a_sha_or_unknown(monkeypatch):
    monkeypatch.delenv("AUREON_BUILD_COMMIT", raising=False)
    assert build_commit() == "unknown"
    monkeypatch.setenv("AUREON_BUILD_COMMIT", "not-a-commit")
    assert build_commit() == "unknown"
    monkeypatch.setenv("AUREON_BUILD_COMMIT", "ABCDEF" * 6 + "abcd")
    assert build_commit() == ("abcdef" * 6 + "abcd")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token-value")
    assert "secret-token-value" not in build_commit()


def test_health_names_the_build_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secret-token-value")
    monkeypatch.setenv("DESK_API_TOKEN", "desk-secret-value")
    monkeypatch.setenv("AUREON_BUILD_COMMIT", "1234567890abcdef" * 2 + "12345678")
    monkeypatch.setattr("ops.app.market_snapshot", lambda: {"BTCUSDT": {"fresh": False}, "ETHUSDT": {"fresh": False}})
    from ops.app import app

    app.config["TESTING"] = True
    body = app.test_client().get("/health").get_json()
    version = app.test_client().get("/version").get_json()
    assert body["build_commit"] == "1234567890abcdef" * 2 + "12345678"
    assert version["build_commit"] == body["build_commit"]
    assert body["strategy_status"] == "WAIT_DEFAULT"
    assert body["broker"] is False
    dumped = json.dumps(body) + json.dumps(version)
    assert "secret-token-value" not in dumped
    assert "desk-secret-value" not in dumped
    assert "data/" not in dumped
    assert body["shadow"] == "disabled"


def test_an_old_worker_heartbeat_is_not_reported_as_healthy():
    import time
    from ops.app import app, worker
    previous_beat = worker.last_beat_ms
    previous_error = worker.last_monitor_error
    app.config["TESTING"] = True
    client = app.test_client()
    try:
        previous_cycle = worker.last_cycle_error
        worker.last_monitor_error = None
        worker.last_cycle_error = None
        worker.last_beat_ms = int(time.time() * 1000) - 10 * 60 * 1000
        assert client.get("/health").get_json()["worker"]["status"] == "stale"
        worker.last_beat_ms = int(time.time() * 1000)
        assert client.get("/health").get_json()["worker"]["status"] == "beating"
        worker.last_monitor_error = "TimeoutError"
        assert client.get("/health").get_json()["worker"]["status"] == "error"
        worker.last_monitor_error = None
        worker.last_cycle_error = "RuntimeError"
        assert client.get("/health").get_json()["worker"]["status"] == "error"
        text = __import__("pathlib").Path(__file__).resolve().parent.joinpath("ui", "dashboard.html").read_text(encoding="utf-8")
        assert "Worker status" in text
        assert "not confirmed" in text
        assert "The health report could not be read" in text
        assert '<option selected>4h</option>' not in text
        assert 'id="term-interval"' in text
    finally:
        worker.last_beat_ms = previous_beat
        worker.last_monitor_error = previous_error
        worker.last_cycle_error = previous_cycle


def test_worker_shadow_is_off_unless_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("AUREON_SHADOW", raising=False)
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: {"symbol": symbol, "close_time_ms": 1000, "fresh": True})

    def explode(now_ms):
        raise AssertionError("shadow loader ran while disabled")

    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json", shadow_path=tmp_path / "shadow.jsonl")
    worker.shadow_loader = explode
    worker.evaluate(now_ms=1_700_000_000_000, sender=lambda *args, **kwargs: {"delivered": True})
    assert not (tmp_path / "shadow.jsonl").exists()


def test_fresh_bar_is_recorded_once_and_does_not_send_or_trade(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_SHADOW", "1")
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    from ops.users import register

    user = register("shadow-user", "password-s")
    user_path = users.ROOT / f"{user['id']}.json"
    before = user_path.read_text()
    bars = _bars(50, STEP, START)
    now = bars[-1]["close_time_ms"] + 1000
    higher = _bars(25, HOUR, bars[-1]["open_time_ms"] - 24 * HOUR, interval="1h")
    stale = _bars(50, STEP, START, symbol="ETHUSDT", fresh=False)
    calls = {"n": 0}

    def loader(now_ms):
        calls["n"] += 1
        return [
            _window(bars, higher),
            _window(stale, higher, symbol="ETHUSDT", fresh=False),
            {
                "symbol": "XAUUSD",
                "interval": "1h",
                "ok": True,
                "bars": _bars(10, HOUR, START, symbol="XAUUSD", interval="1h", fresh=True),
                "higher": [],
                "provider": "dukascopy",
                "quote_semantics": "bid_ask",
                "source_kind": "historical_replay",
            },
        ]

    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: {"symbol": symbol, "interval": interval, "close_time_ms": bars[-1]["close_time_ms"], "fresh": True, "close": 105})
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": [{"h": 10, "l": 9, "c": 11} for _ in range(21)]})
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":true}')
    shadow_path = tmp_path / "shadow" / "observations.jsonl"
    sent = []
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), prefs, experimental_path=tmp_path / "experimental.jsonl", shadow_path=shadow_path)
    worker.shadow_loader = loader
    worker.evaluate(now_ms=now, sender=lambda *args, **kwargs: sent.append(args) or {"delivered": True, "telegram_message_id": 1})
    assert sent == []
    assert calls["n"] == 1
    stored = ShadowLedger(shadow_path).read()
    assert stored
    assert all(row["telegram"] == "NOT_CALLED" and row["approved"] is False for row in stored)
    assert all(row["config_sha256"] == config_sha256() for row in stored)
    btc = [row for row in stored if row["symbol"] == "BTCUSDT"]
    assert btc
    assert any(row["source_kind"] == "prospective" for row in btc)
    e1 = next(row for row in btc if row["strategy_version"] == "e1-20261016")
    assert e1["state"] == "RESEARCH_OBSERVATION"
    assert e1["classification"] == "RESEARCH_OBSERVATION"
    assert e1["eligibility"] == "not_eligible_for_promotion"
    eth = next(row for row in stored if row["symbol"] == "ETHUSDT")
    assert eth["state"] == "DATA_UNAVAILABLE"
    assert eth["source_kind"] == "unavailable"
    gold = next(row for row in stored if row["symbol"] == "XAUUSD")
    assert gold["source_kind"] == "historical_replay"
    assert gold["state"] != "PAPER_CANDIDATE"
    assert "live" not in gold["source_kind"]
    count = len(shadow_path.read_text().splitlines())
    restarted = Worker(Ledger(tmp_path / "ledger.jsonl"), prefs, experimental_path=tmp_path / "experimental.jsonl", shadow_path=shadow_path)
    restarted.shadow_loader = loader
    restarted.evaluate(now_ms=now, sender=lambda *args, **kwargs: sent.append("again") or {"delivered": True})
    assert sent == []
    assert len(shadow_path.read_text().splitlines()) == count
    book = worker.book.read()
    assert not any(row.get("type") in {"paper_open", "paper_close", "order", "fill"} for row in book)
    assert not any(row.get("type") in {"paper_open", "paper_close", "notify"} for row in worker.ledger.read())
    assert user_path.read_text() == before
    assert promotion_ids(tmp_path / "missing-promotions.json") == []
    refused = ShadowLedger(shadow_path).append({
        "observed_at_ms": now,
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "source": "binance-public",
        "source_kind": "prospective",
        "strategy_version": "e1-20261016",
        "config_sha256": config_sha256(),
        "quality": "fresh",
        "fresh": True,
        "state": "APPROVED_SIGNAL",
        "reason": "should_not_stick",
        "event_id": "attempted-approval",
    })
    assert refused["state"] == "WAIT"
    assert refused["reason"] == "not_approved"
    assert refused["approved"] is False
    assert PRODUCTION == "WAIT_DEFAULT"


def test_incomplete_bar_is_not_a_live_signal(tmp_path):
    bars = _bars(50, STEP, START, complete=False)
    higher = _bars(25, HOUR, START, interval="1h")
    book = ShadowLedger(tmp_path / "shadow.jsonl")
    row = observe_prospective(book, START, lambda now_ms: [_window(bars, higher, complete=False)])[0]
    assert row["state"] == "DATA_UNAVAILABLE"
    assert row["reason"] == "incomplete_bar"
    assert row["source_kind"] == "unavailable"
