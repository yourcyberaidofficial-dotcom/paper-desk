"""In-app inbox and the frozen spot rules. No Telegram and no network."""

from ops.bars import make_bar
from ops.inbox import items, mark_read, offer, record_scan, unread_count
from ops.spot_momentum import RULES, setup
from ops.users import register


def _user(tmp_path, monkeypatch, name):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    import ops.users as users
    monkeypatch.setattr(users, "ROOT", tmp_path / "users")
    users.ROOT.mkdir(parents=True, exist_ok=True)
    return register(name, "password-s")


def test_inbox_is_private_deduped_and_cannot_approve(tmp_path, monkeypatch):
    first = _user(tmp_path, monkeypatch, "ada")
    import ops.users as users
    second = register("bea", "password-s")
    refused = offer(first["id"], {"id": "e1", "kind": "official", "state": "RESEARCH_OBSERVATION", "strategy": "E1-donchian-20", "symbol": "BTCUSDT"}, registry=[])
    assert refused["stored"] is False
    notice = {"id": "quiet:2026-10-28", "kind": "status", "symbol": "BTCUSDT", "message": "Scan completed. No qualifying setup.", "created_ms": 10}
    assert offer(first["id"], notice)["stored"] is True
    assert offer(first["id"], notice)["duplicate"] is True
    assert len(items(first["id"])) == 1
    assert items(second["id"]) == []
    research = offer(first["id"], {"id": "watch-1", "kind": "research", "strategy": "E1-donchian-20", "symbol": "BTCUSDT", "message": "A breakout was observed.", "created_ms": 11})
    assert research["stored"] is True
    assert items(first["id"])[0]["actionable"] is False
    assert "Not an approved trade" in items(first["id"])[0]["label"]
    assert unread_count(first["id"]) == 2
    mark_read(first["id"], "watch-1")
    assert unread_count(first["id"]) == 1
    body = {"markets": [{"symbol": "BTCUSDT", "scanner_state": "WAIT", "message": "No qualifying setup yet."}]}
    before = sum(1 for row in items(first["id"]) if str(row["id"]).startswith("quiet:"))
    record_scan(first["id"], body, {}, 1_700_000_000_000)
    record_scan(first["id"], body, {}, 1_700_000_000_000)
    after = sum(1 for row in items(first["id"]) if str(row["id"]).startswith("quiet:"))
    assert after == before + 1


def test_spot_rule_does_not_read_the_next_bar():
    bars = []
    step = 3_600_000
    start = 1_700_006_400_000
    for index in range(40):
        open_time = start + index * step
        close = 100 + index
        bars.append(make_bar(
            symbol="BTCUSDT", interval="1h", open_time_ms=open_time, close_time_ms=open_time + step - 1,
            open=close - 1, high=close + 1, low=close - 2, close=close, volume=1,
            complete=True, fresh=True, provider="fixture", source_type="fixture", quote_semantics="last_trade",
        ))
    signal = setup(bars, 30, [], "BTCUSDT")
    assert signal["direction"] == "LONG"
    assert signal["anchor_open_ms"] == bars[30]["open_time_ms"]
    future = [dict(bar) for bar in bars]
    future[31]["close"] = 1
    assert setup(bars, 30, [], "BTCUSDT") == setup(future, 30, [], "BTCUSDT")
    assert setup(bars, 30, [], "XAUUSD") is None
    assert "spot-tsmom-1h-20261028" in RULES
    assert "tight-range-long-1h-20261028" in RULES


def test_notifications_require_a_user(tmp_path, monkeypatch):
    _user(tmp_path, monkeypatch, "ada")
    from ops.app import app
    app.config["TESTING"] = True
    assert app.test_client().get("/api/notifications").status_code == 401
