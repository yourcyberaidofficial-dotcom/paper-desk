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
    assert len(sent) == 2
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
