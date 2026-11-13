"""Live sends stay off even when a flag and keys are present."""

import json

from ops.live_broker import execute, floor_step, status


def test_live_stays_off_without_keys(monkeypatch):
    monkeypatch.delenv("AUREON_LIVE_TRADING", raising=False)
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    called = []
    result = execute("BTCUSDT", "BUY", 0.01, 100, price=100000, transport=lambda *args: called.append(args))
    assert result["ok"] is False
    assert result["sent"] is False
    assert result["reason"] == "paper_only"
    assert called == []
    assert status()["armed"] is False
    assert status()["broker"] is False


def test_a_spot_short_and_gold_are_not_sent(monkeypatch):
    monkeypatch.setenv("AUREON_LIVE_TRADING", "1")
    monkeypatch.setenv("BINANCE_API_KEY", "key")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret")
    called = []
    assert execute("BTCUSDT", "SELL", 0.01, 100, transport=lambda *args: called.append(args))["reason"] == "paper_only"
    assert execute("XAUUSD", "BUY", 1, 3900, transport=lambda *args: called.append(args))["reason"] == "paper_only"
    assert called == []


def test_keys_and_the_live_flag_still_do_not_send(monkeypatch):
    monkeypatch.setenv("AUREON_LIVE_TRADING", "1")
    monkeypatch.setenv("BINANCE_API_KEY", "key-value")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret-value")
    called = []
    result = execute("BTCUSDT", "BUY", 0.0154, 99000, price=100000, transport=lambda *args: called.append(args))
    assert result == {"ok": False, "reason": "paper_only", "sent": False}
    assert called == []
    blob = json.dumps(result)
    assert "key-value" not in blob and "secret-value" not in blob
    assert floor_step(0.0154, "0.001") == 0.015


def test_a_rejected_stop_is_never_reached(monkeypatch):
    monkeypatch.setenv("AUREON_LIVE_TRADING", "1")
    monkeypatch.setenv("BINANCE_API_KEY", "key")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret")
    called = []
    result = execute("ETHUSDT", "BUY", 0.01, 2000, price=2100, transport=lambda *args: called.append(1))
    assert result["reason"] == "paper_only"
    assert called == []
