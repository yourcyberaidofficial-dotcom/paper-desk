"""The same closed candle cannot be decided twice, even from two passes at once."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ops.ledger import Ledger
from ops.test_monitor import _compress
from ops.worker import Worker


def _worker(tmp_path):
    return Worker(Ledger(tmp_path / "ledger.jsonl"), tmp_path / "prefs.json")


def _window(bars, interval="4h"):
    copied = []
    for bar in bars:
        row = dict(bar)
        row["interval"] = interval
        copied.append(row)
    return [{"symbol": "BTCUSDT", "interval": interval, "bars": copied}]


def test_simultaneous_passes_decide_a_close_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.terminal_signal import decide as real_decide

    calls = {"n": 0}
    gate = threading.Lock()

    def counting(*args, **kwargs):
        with gate:
            calls["n"] += 1
        return real_decide(*args, **kwargs)

    monkeypatch.setattr("ops.terminal_signal.decide", counting)
    bars = _compress()
    now = bars[-1]["close_time_ms"] + 1000
    worker = _worker(tmp_path)
    window = _window(bars)

    def once(_index):
        return worker.monitor(now_ms=now, windows=window)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(once, range(8)))
    assert calls["n"] == 1


def test_a_revised_candle_does_not_rewrite_the_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.signal_ledger import read
    from ops.terminal_signal import decide as real_decide

    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_decide(*args, **kwargs)

    monkeypatch.setattr("ops.terminal_signal.decide", counting)
    bars = _compress()
    now = bars[-1]["close_time_ms"] + 1000
    worker = _worker(tmp_path)
    worker.monitor(now_ms=now, windows=_window(bars))
    revised = [dict(bar) for bar in bars]
    revised[-1]["close"] = revised[-1]["close"] + 25
    revised[-1]["high"] = revised[-1]["high"] + 25
    worker.monitor(now_ms=now + 1, windows=_window(revised))
    assert calls["n"] == 1
    notes = [row.get("note") or "" for row in read()]
    assert any("original decision was not rewritten" in note for note in notes)


def test_an_older_candle_does_not_replace_the_newer_reading(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.desk_pulse import _READINGS

    bars = _compress()
    newer = [dict(bar) for bar in bars]
    newer[-1]["close_time_ms"] = newer[-1]["close_time_ms"] + 14_400_000
    worker = _worker(tmp_path)
    worker.monitor(now_ms=newer[-1]["close_time_ms"] + 1000, windows=_window(newer))
    worker.monitor(now_ms=bars[-1]["close_time_ms"] + 1000, windows=_window(bars))
    assert _READINGS[("BTCUSDT", "4h")]["bar_close_ms"] == newer[-1]["close_time_ms"]


def test_a_failed_write_is_retried_and_then_stored_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.signal_engine import cycle
    from ops.signal_ledger import read

    calls = {"n": 0}
    monkeypatch.setattr("ops.signal_engine.record_observations", _fail_once(calls))
    bars = _window(_compress(), "15m")[0]["bars"]
    for index, bar in enumerate(bars):
        bar["interval"] = "15m"
        bar["close_time_ms"] = 1_700_000_000_000 + index * 900_000
    try:
        cycle(1_700_000_000_000, windows=[{"symbol": "BTCUSDT", "interval": "15m", "bars": bars}])
    except RuntimeError:
        pass
    cycle(1_700_000_000_000, windows=[{"symbol": "BTCUSDT", "interval": "15m", "bars": bars}])
    rows = [row for row in read() if row.get("symbol") == "BTCUSDT" and row.get("interval") == "15m"]
    identities = {(row.get("opportunity_id"), row.get("observation"), row.get("note")) for row in rows}
    assert rows
    assert len(rows) == len(identities)
    assert calls["n"] >= 1


def _fail_once(calls):
    from ops.signal_ledger import record_observations as real

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk")
        return real(*args, **kwargs)

    return wrapped


def test_fixture_closes_stay_single_decisions(tmp_path, monkeypatch):
    """In-process fixture timing. This is not a production latency measurement."""
    monkeypatch.setenv("AUREON_DATA", str(tmp_path))
    from ops.terminal_signal import decide as real_decide

    calls = {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real_decide(*args, **kwargs)

    monkeypatch.setattr("ops.terminal_signal.decide", counting)
    worker = _worker(tmp_path)
    samples = []
    base = _compress()
    for step in range(20):
        bars = [dict(bar) for bar in base]
        bars[-1]["close_time_ms"] = bars[-1]["close_time_ms"] + step * 14_400_000
        started = time.perf_counter()
        worker.monitor(now_ms=bars[-1]["close_time_ms"] + 1000, windows=_window(bars))
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    summary = {
        "decisions": calls["n"],
        "passes": len(samples),
        "p50_ms": round(samples[len(samples) // 2], 3),
        "p95_ms": round(samples[max(0, int(len(samples) * 0.95) - 1)], 3),
        "max_ms": round(samples[-1], 3),
        "scope": "in-process fixture, one pair, no network",
    }
    Path("/tmp/claim-bench.json").write_text(json.dumps(summary), encoding="utf-8")
    assert calls["n"] == 20
    assert summary["p95_ms"] >= summary["p50_ms"]
