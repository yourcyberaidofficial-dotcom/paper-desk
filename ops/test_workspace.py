"""Shared signal history and a private reading of it. No network and no Telegram."""

from ops.bars import make_bar
from ops.signal_book import read_events, remember, remember_live, replay
from ops.workspace import compose


def _bars(count=48):
    step = 900_000
    start = 1_700_006_400_000 - (1_700_006_400_000 % step)
    rows = []
    for index in range(count):
        open_time = start + index * step
        close = 100 + (index % 3)
        rows.append(make_bar(
            symbol="BTCUSDT", interval="15m", open_time_ms=open_time, close_time_ms=open_time + step - 1,
            open=100, high=101, low=99, close=close, volume=1, complete=True, fresh=True,
            provider="fixture", source_type="fixture", quote_semantics="last_trade",
        ))
    return rows


def test_ledger_dedupes_and_cannot_approve_or_invent_pnl(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    event = {"id": "same", "source": "live", "symbol": "BTCUSDT", "state": "RESEARCH_OBSERVATION", "scanner_state": "SETUP_WATCH", "message": "watch", "approved": True}
    assert remember(event)["stored"] is True
    assert remember(event)["duplicate"] is True
    stored = read_events()[0]
    assert stored["approved"] is False
    assert stored["delivered"] is False
    assert stored["filled"] is False
    assert stored["pnl"] is None
    body = {"markets": [{"symbol": "ETHUSDT", "scanner_state": "WAIT", "state": "WAIT", "updated_at_ms": 10, "message": "No qualifying setup yet.", "rule": "E1-donchian-20"}]}
    remember_live(body)
    remember_live(body)
    assert len(read_events()) == 2


def test_replay_does_not_use_a_future_bar_or_create_a_fill(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    bars = _bars()
    replay("BTCUSDT", bars, bars[-25:], bars[-2]["close_time_ms"])
    first = read_events()
    mutated = [dict(bar) for bar in bars]
    mutated[-1]["close"] = 500
    replay("BTCUSDT", mutated, mutated[-25:], bars[-2]["close_time_ms"])
    assert read_events() == first
    assert all(row["source"] == "historical_replay" and row["filled"] is False and row["approved"] is False for row in first)


def test_two_users_get_different_instructions_from_one_event():
    scan = {"notice": "No approved strategy is currently active; trade alerts are unavailable.", "markets": [
        {"symbol": "BTCUSDT", "scanner_state": "WAIT", "message": "No qualifying setup yet.", "approved": False},
        {"symbol": "XAUUSD", "scanner_state": "BLOCKED", "message": "Gold scanning is temporarily unavailable.", "approved": False},
    ]}
    history = [{
        "id": "watch-1", "source": "live", "symbol": "BTCUSDT", "interval": "15m", "strategy": "E1-donchian-20",
        "scanner_state": "SETUP_WATCH", "direction": "LONG", "message": "A condition matched.",
        "approved": False, "entry": 100, "stop": 99, "delivered": False, "filled": False, "pnl": None,
    }]
    small = compose({"profile": {"capital": 1000, "currency": "USD", "signal_style": "aegis_shield"}, "plan": {"mode": "auto", "markets": ["BTCUSDT", "ETHUSDT", "XAUUSD"], "strategies": [], "min_evidence_grade": 0, "risk_per_trade_percent": 0.8}}, scan, history)
    large = compose({"profile": {"capital": 1000, "currency": "USD", "signal_style": "apex_momentum"}, "plan": {"mode": "auto", "markets": ["BTCUSDT", "ETHUSDT", "XAUUSD"], "strategies": [], "min_evidence_grade": 0, "risk_per_trade_percent": 2.5}}, scan, history)
    assert [panel["symbol"] for panel in small["panels"]] == ["BTCUSDT", "ETHUSDT", "XAUUSD"]
    assert small["panels"][1]["scanner_state"] == "BLOCKED"
    assert small["panels"][2]["quote_note"].startswith("Chart OHLC")
    assert small["current"][0]["account"]["quantity"] == 8
    assert large["current"][0]["account"]["quantity"] == 25
    assert small["current"][0]["live"] is False
    assert "not the current scan" in small["current"][0]["why_not"]
    assert small["current"][0]["qualifies"] is False
    assert small["history"][0]["pnl"] is None
    hidden = compose({"plan": {"mode": "selected", "strategies": ["xau-session-20261027"], "markets": ["XAUUSD"], "min_evidence_grade": 0}}, scan, history)
    assert hidden["current"] == []
    assert hidden["panels"][0]["symbol"] == "BTCUSDT"


def test_workspace_requires_a_user():
    from ops.app import app
    app.config["TESTING"] = True
    assert app.test_client().get("/api/workspace").status_code == 401
