"""Background scan. Fixtures only. No Telegram and no browser."""

from ops.bars import make_bar
from ops.inbox import items
from ops.ledger import Ledger
from ops.users import register, save_inbox_delivery
from ops.worker import Worker


def _flat(index, close=100, high=100.2, low=99.9, start=1_700_000_000_000):
    step = 14_400_000
    start = start - (start % step)
    open_time = start + index * step
    return make_bar(
        symbol="BTCUSDT", interval="4h", open_time_ms=open_time, close_time_ms=open_time + step - 1,
        open=close, high=high, low=low, close=close, volume=1, complete=True, fresh=True,
        provider="fixture", source_type="fixture", quote_semantics="last_trade",
    )


def _compress():
    bars = []
    for index in range(50):
        if index < 38:
            bars.append(_flat(index, close=100, high=110, low=90))
        else:
            bars.append(_flat(index, close=100, high=100.4, low=99.8))
    bars[-1] = _flat(49, close=106, high=107, low=100)
    return bars


def test_background_scan_delivers_once_and_stays_private(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    allowed = register("ada", "password-s")
    quiet = register("bea", "password-s")
    save_inbox_delivery(allowed["id"], {"experimental": True, "markets": ["BTCUSDT"], "timeframes": ["4h", "15m"], "buy": True})
    bars = _compress()
    now = bars[-1]["close_time_ms"] + 1000
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")
    windows = [
        {"symbol": "BTCUSDT", "interval": "4h", "bars": bars},
        {"symbol": "ETHUSDT", "interval": "15m", "bars": [], "reason": "missing_bars"},
    ]
    first = worker.monitor(now_ms=now, windows=windows)
    assert first["delivered"] == 1
    assert first["evaluations"][0]["decision"] == "BUY · Experimental"
    assert first["evaluations"][1]["decision"] == "DATA BLOCK"
    assert len(items(allowed["id"])) == 1
    assert items(allowed["id"])[0]["approved"] is False
    assert items(quiet["id"]) == []
    second = worker.monitor(now_ms=now, windows=windows)
    assert second["delivered"] == 0
    assert len(items(allowed["id"])) == 1
    assert worker.last_monitor["evaluated_at_ms"] == now
