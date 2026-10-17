"""Worker tests. No network. No fills."""

import json
from pathlib import Path

from ops.ledger import Ledger
from ops.worker import Worker


def _bar(symbol, close_time, fresh=True):
    return {
        "symbol": symbol,
        "interval": "15m",
        "close_time_ms": close_time,
        "fresh": fresh,
        "source": "fixture",
    }


def test_duplicate_and_wait(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 1000))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    worker = Worker(ledger, tmp_path / "prefs.json")
    sent = []
    first = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status": "DELIVERED", "delivered": True})
    second = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status": "DELIVERED", "delivered": True})
    assert len(first) == 2
    assert second == []
    assert all(row["result"] == "WAIT" for row in first)
    assert sent == []
    assert not any(row.get("type") == "fill" for row in ledger.read())


def test_stale_and_quiet(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 2000, fresh=False))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text(json.dumps({"assets": ["BTCUSDT"], "quiet_hours_utc": list(range(24)), "alerts_enabled": True}))
    worker = Worker(ledger, prefs)
    sent = []
    rows = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status": "DELIVERED", "delivered": True})
    assert rows[0]["reason"] == "stale_or_unavailable"
    assert sent == []


def test_prefs_cap(tmp_path):
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")
    saved = worker.save_prefs({"assets": ["BTCUSDT", "XAU"], "max_alerts_per_day": 999})
    assert saved["assets"] == ["BTCUSDT"]
    assert saved["max_alerts_per_day"] == 48


def test_experimental_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 3000))
    candles = [{"h": 10, "l": 9, "c": 9.5} for _ in range(20)] + [{"h": 12, "l": 11, "c": 11}]
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": candles})
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":false}')
    worker = Worker(ledger, prefs)
    rows = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: {"status":"FAILED","delivered":False})
    assert rows[0]["experimental"]["result"] == "LONG_BIAS"
    assert rows[0]["experimental"]["classification"] == "experimental_unvalidated"
    again = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: {"status":"FAILED","delivered":False})
    assert again == []


def test_wait_does_not_notify(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 4000))
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": [{"h": 10, "l": 9, "c": 9.5} for _ in range(21)]})
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":true}')
    worker = Worker(ledger, prefs)
    sent = []
    rows = worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status":"DELIVERED","delivered":True})
    assert rows[0]["experimental"]["result"] == "WAIT"
    assert sent == []
    assert any(r.get("type") == "evaluation" for r in ledger.read())


def test_trigger_notifies(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 5000))
    candles = [{"h": 10, "l": 9, "c": 9.5} for _ in range(20)] + [{"h": 12, "l": 11, "c": 11}]
    monkeypatch.setattr("ops.worker.fetch_klines", lambda symbol, interval, limit=22, now_ms=None: {"candles": candles})
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"experimental_alerts":true,"alerts_enabled":true}')
    worker = Worker(ledger, prefs)
    sent = []
    worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status":"DELIVERED","delivered":True,"telegram_message_id":1})
    assert len(sent) == 1
    assert "EXPERIMENTAL — NOT VALIDATED" in sent[0]
    assert "LONG_BIAS" in sent[0]


def test_stale_warns(tmp_path, monkeypatch):
    monkeypatch.setattr("ops.worker.fetch_last_closed", lambda symbol, interval, now_ms=None: _bar(symbol, 6000, fresh=False))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    prefs = tmp_path / "prefs.json"
    prefs.write_text('{"assets":["BTCUSDT"],"alerts_enabled":true,"quiet_hours_utc":[]}')
    worker = Worker(ledger, prefs)
    sent = []
    worker.evaluate(now_ms=1_700_000_000_000, sender=lambda text: sent.append(text) or {"status":"FAILED","delivered":False,"reason":"Timeout"})
    assert len(sent) == 1
    assert "stale" in sent[0]
    notes = [r for r in ledger.read() if r.get("type") == "notify"]
    assert notes[0]["delivered"] is False
