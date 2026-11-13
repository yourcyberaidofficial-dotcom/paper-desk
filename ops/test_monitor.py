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
    save_inbox_delivery(quiet["id"], {"experimental": False})
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


def test_one_bad_window_does_not_drop_the_next(tmp_path):
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")
    summary = worker.monitor(now_ms=1_700_000_000_000, windows=[
        {"symbol": "BTCUSDT", "interval": "nope", "bars": [{"high": 1, "low": 1, "close": 1, "complete": True, "close_time_ms": 1}]},
        {"symbol": "ETHUSDT", "interval": "15m", "bars": [], "reason": "missing_bars"},
    ])
    assert summary["error"] is None
    assert summary["evaluations"][0]["decision"] == "DATA BLOCK"
    assert summary["evaluations"][1]["symbol"] == "ETHUSDT"
    assert summary["evaluations"][1]["decision"] == "DATA BLOCK"


def test_a_later_wait_supersedes_the_old_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = register("ada", "password-s")
    save_inbox_delivery(owner["id"], {"experimental": True, "markets": ["BTCUSDT"], "timeframes": ["4h"], "buy": True})
    bars = _compress()
    now = bars[-1]["close_time_ms"] + 1000
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")
    first = worker.monitor(now_ms=now, windows=[{"symbol": "BTCUSDT", "interval": "4h", "bars": bars}])
    assert first["delivered"] == 1
    quiet = [_flat(i) for i in range(70)]
    later = quiet[-1]["close_time_ms"] + 1000
    second = worker.monitor(now_ms=later, windows=[{"symbol": "BTCUSDT", "interval": "4h", "bars": quiet}])
    assert second["delivered"] == 0
    saved = items(owner["id"])
    assert saved[0]["lifecycle"] == "expired"
    assert "its own candle" in saved[0]["lifecycle_note"]


def test_an_unchanged_candle_is_carried_and_not_decided_again(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    from ops.desk_pulse import account_view
    from ops.terminal_signal import decide as real_decide

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    owner = register("ada", "password-s")
    calls = {"n": 0}

    def counting(symbol, interval, *args, **kwargs):
        if symbol == "BTCUSDT" and interval == "4h":
            calls["n"] += 1
        return real_decide(symbol, interval, *args, **kwargs)

    monkeypatch.setattr("ops.terminal_signal.decide", counting)
    bars = _compress()
    now = bars[-1]["close_time_ms"] + 1000
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")
    window = [{"symbol": "BTCUSDT", "interval": "4h", "bars": bars}]
    first = worker.monitor(now_ms=now, windows=window)
    second = worker.monitor(now_ms=now + 1000, windows=window)
    assert calls["n"] == 1
    assert second["unchanged"] == 1
    assert second["evaluations"][0]["carried"] is True
    view = account_view(users.get(owner["id"]))
    assert view["broker"] is False
    assert view["readings"][0]["symbol"] == "BTCUSDT"
    assert view["readings"][0]["entry"] == 106
    assert "Entry 106.00" in view["readings"][0]["explanation"]


def test_a_new_close_is_not_suppressed_by_the_clock(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    from ops.signal_engine import cycle as real_cycle

    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    calls = {"n": 0}

    def wrapped(now_ms=None, transport=None, windows=None):
        calls["n"] += 1
        return real_cycle(now_ms, transport=transport, windows=windows)

    monkeypatch.setattr("ops.signal_engine.cycle", wrapped)
    bars = _compress()
    now = bars[-1]["close_time_ms"] + 1000
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")
    window = [{"symbol": "BTCUSDT", "interval": "4h", "bars": bars}]
    worker.monitor(now_ms=now, windows=window)
    moved = [dict(bar) for bar in bars]
    moved[-1]["close_time_ms"] = moved[-1]["close_time_ms"] + 14_400_000
    worker.monitor(now_ms=now + 1000, windows=[{"symbol": "BTCUSDT", "interval": "4h", "bars": moved}])
    assert calls["n"] == 2


def test_one_pass_loads_each_pair_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    counts = {"crypto": 0, "gold": 0}

    def crypto(*_args, **_kwargs):
        counts["crypto"] += 1
        return []

    def gold(*_args, **_kwargs):
        counts["gold"] += 1
        return []

    monkeypatch.setattr("ops.terminal_route.load_crypto_bars", crypto)
    monkeypatch.setattr("ops.terminal_route.load_gold_ohlc", gold)
    worker = Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")
    summary = worker.monitor(now_ms=1_700_000_000_000)
    assert counts == {"crypto": 8, "gold": 2}
    assert summary["error"] is None
    assert len(summary["evaluations"]) == 12



