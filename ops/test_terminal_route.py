"""The Generate Signal handler uses the decision engine and not the chart feed."""

import inspect

from ops.bars import make_bar
from ops.terminal_route import handle_signal
import ops.terminal_route as route
import ops.app as app_module


def _bars(symbol, now_ms, count=50):
    step = 4 * 60 * 60 * 1000
    start = now_ms - count * step
    rows = []
    for index in range(count):
        open_time = start + index * step
        close_time = open_time + step - 1
        rows.append(make_bar(
            symbol=symbol, interval="4h", open_time_ms=open_time, close_time_ms=close_time,
            open=100, high=101, low=99, close=100, volume=1, complete=True, fresh=True,
            provider="fixture", source_type="fixture", quote_semantics="last_trade",
        ))
    return rows


def test_crypto_requests_use_completed_bars_and_stay_unapproved(monkeypatch, tmp_path):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    now = 1_800_000_000_000
    seen = []

    def bars_loader(symbol, interval, now_ms):
        seen.append((symbol, interval, now_ms))
        return _bars(symbol, now_ms)

    status, btc = handle_signal("user-a", {"symbol": "BTCUSDT", "interval": "4h", "strategy": "auto"}, now, bars_loader=bars_loader)
    status_eth, eth = handle_signal("user-a", {"symbol": "ETHUSDT", "interval": "4h", "strategy": "auto"}, now, bars_loader=bars_loader)
    assert status == status_eth == 200
    assert seen == [("BTCUSDT", "4h", now), ("ETHUSDT", "4h", now)]
    assert btc["strategy"] == "compress-break-4h-20261028"
    assert eth["strategy"] == "sweep-reclaim-4h-20261028"
    assert btc["decision"] == eth["decision"] == "WAIT"
    assert btc["validation_status"] == eth["validation_status"] == "FAIL"
    assert btc["approved"] is eth["approved"] is False
    assert btc["order"] is False and btc["filled"] is False and btc["pnl"] is None
    short = handle_signal("user-a", {"symbol": "BTCUSDT", "interval": "15m", "strategy": "auto"}, now, bars_loader=bars_loader)
    assert short[1]["decision"] == "WAIT"
    assert short[1]["blocked"] == "timeframe"
    assert short[1]["approved"] is False


def test_gold_snapshot_cannot_become_a_trade(monkeypatch, tmp_path):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    called = {"bars": 0}

    def bars_loader(*args):
        called["bars"] += 1
        raise AssertionError("gold must not load the chart path")

    status, result = handle_signal(
        "user-a",
        {"symbol": "XAUUSD", "interval": "1h", "strategy": "auto"},
        1_000_000,
        bars_loader=bars_loader,
        quote_loader=lambda now: {"ok": True, "bid": 100.0, "ask": 100.4, "spread": 0.4, "timestamp_ms": now, "platform": "fixture", "spread_profile": "premium", "provider": "fixture"},
        session_loader=lambda now: {"day": "2026-10-28", "bid": "http_404", "ask": "http_503"},
    )
    assert status == 200
    assert called["bars"] == 0
    assert result["decision"] == "WAIT"
    assert result["blocked"] == "snapshot_not_candle"
    assert result["approved"] is False
    assert result["validation_status"] == "BLOCKED"
    assert result["order"] is False
    assert "100.4" in result["reason"]
    assert "http_404" in result["reason"]


def test_history_stays_with_the_requesting_user(monkeypatch, tmp_path):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    now = 1_800_000_000_000
    handle_signal("user-a", {"symbol": "BTCUSDT", "interval": "4h"}, now, bars_loader=lambda *args: _bars("BTCUSDT", args[-1]))
    handle_signal("user-b", {"symbol": "ETHUSDT", "interval": "4h"}, now, bars_loader=lambda *args: _bars("ETHUSDT", args[-1]))
    from ops.terminal_signal import read_history
    own = read_history("user-a")
    other = read_history("user-b")
    assert [row["symbol"] for row in own] == ["BTCUSDT"]
    assert [row["symbol"] for row in other] == ["ETHUSDT"]


def test_handler_source_does_not_call_the_chart_or_a_sender():
    source = inspect.getsource(route)
    assert "xaus_chart" not in source
    assert "telegram" not in source.lower()
    assert "send_alert" not in source
    handler = inspect.getsource(app_module.terminal_signal)
    assert "handle_signal" in handler
    assert "xaus_chart" not in handler
    assert "_terminal_bars" not in handler
