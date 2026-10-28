"""Shadow ledger stays out of production accounting and never sends."""

import inspect
import json

from ops.bars import make_bar
from ops.gate4_hypotheses import fail_break_setup
from ops.shadow import ShadowLedger, observe_setup
from ops.worker import PRODUCTION

HOUR = 60 * 60 * 1000
START = 1_767_600_000_000


def _bars():
    rows = []
    for index in range(40):
        open_time = START + index * 15 * 60 * 1000
        rows.append(make_bar(
            symbol="BTCUSDT", instrument="BTCUSDT", interval="15m",
            open_time_ms=open_time, close_time_ms=open_time + 15 * 60 * 1000 - 1,
            open=100, high=100.4, low=99.6, close=100, volume=1,
            provider="fixture", source_type="fixture", quote_semantics="last_trade",
            retrieved_at_ms=open_time, complete=True, fresh=False,
        ))
    return rows


def _event(event_id="shadow:1", **extra):
    row = {
        "observed_at_ms": START,
        "symbol": "XAUUSD",
        "timeframe": "1h",
        "source": "dukascopy",
        "source_kind": "historical_replay",
        "strategy_version": "xau-london-range-20261028",
        "config_sha256": "abc",
        "quality": "historical_or_unconfirmed",
        "fresh": False,
        "state": "WAIT",
        "reason": "no_setup",
        "event_id": event_id,
    }
    row.update(extra)
    return row


def test_restart_dedupes_and_refuses_a_trade_or_an_approval(tmp_path):
    path = tmp_path / "shadow" / "observations.jsonl"
    users = tmp_path / "users" / "one.json"
    users.parent.mkdir()
    users.write_text('{"capital": 1000}')
    ledger_path = tmp_path / "paper" / "ledger.jsonl"
    ledger_path.parent.mkdir()
    ledger_path.write_text("")
    book = ShadowLedger(path)
    first = book.append(_event())
    assert first["telegram"] == "NOT_CALLED"
    assert first["approved"] is False
    assert first["production"] == "WAIT_DEFAULT"
    again = ShadowLedger(path).append(_event())
    assert again == {"duplicate": True, "event_id": "shadow:1"}
    assert len(ShadowLedger(path).read()) == 1
    blocked = book.append(_event(event_id="shadow:approved", state="APPROVED_SIGNAL"))
    assert blocked["state"] == "WAIT"
    assert blocked["reason"] == "not_approved"
    assert blocked["attempted_state"] == "APPROVED_SIGNAL"
    try:
        book.append(_event(event_id="shadow:trade", state="paper_open"))
        raised = False
    except ValueError:
        raised = True
    assert raised is True
    stale = book.append(_event(event_id="shadow:stale", source_kind="prospective", fresh=False, state="PAPER_CANDIDATE"))
    assert stale["state"] == "DATA_UNAVAILABLE"
    assert stale["source_kind"] == "unavailable"
    assert "live" not in stale["source_kind"]
    assert users.read_text() == '{"capital": 1000}'
    assert ledger_path.read_text() == ""
    assert PRODUCTION == "WAIT_DEFAULT"
    assert "send_alert" not in inspect.getsource(ShadowLedger)


def test_same_setup_is_one_event_and_missing_gold_is_unavailable(tmp_path):
    path = tmp_path / "observations.jsonl"
    book = ShadowLedger(path)
    bars = _bars()
    probe = dict(bars[30])
    prior_low = min(bar["low"] for bar in bars[10:30])
    probe.update(open=100.0, high=100.4, low=prior_low - 1, close=100.2)
    bars[30] = probe
    first = observe_setup(
        book, symbol="BTCUSDT", timeframe="15m", bars=bars, index=30, higher=[],
        strategy="fail-break-20261028", setup_fn=fail_break_setup, source="binance-public",
        source_kind="historical_replay", now_ms=START, config_sha256="frozen", fresh=False,
    )
    second = observe_setup(
        book, symbol="BTCUSDT", timeframe="15m", bars=bars, index=30, higher=[],
        strategy="fail-break-20261028", setup_fn=fail_break_setup, source="binance-public",
        source_kind="historical_replay", now_ms=START + HOUR, config_sha256="frozen", fresh=False,
    )
    assert first["state"] == "PAPER_CANDIDATE"
    assert first["source_kind"] == "historical_replay"
    assert first["reason"] == "setup_seen_not_an_order"
    assert second["duplicate"] is True
    assert "paper_open" not in path.read_text()
    empty = observe_setup(
        book, symbol="XAUUSD", timeframe="1h", bars=[], index=0, higher=[],
        strategy="xau-london-range-20261028", setup_fn=fail_break_setup, source="dukascopy",
        source_kind="prospective", now_ms=START, config_sha256="frozen", fresh=False,
    )
    assert empty["state"] == "DATA_UNAVAILABLE"
    assert empty["source_kind"] == "unavailable"
    stored = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert all(row.get("type") not in {"paper_open", "paper_close"} for row in stored)
    assert all(row["telegram"] == "NOT_CALLED" for row in stored)
