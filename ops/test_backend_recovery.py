"""Backend recovery. Fixtures only. No socket, no live feed, no paid call."""

import json

from ops.candle_book import CandleBook
from ops.model_host import chat, health, requirements
from ops.qualification import autopilot_may_open
from ops.research_eval import evaluate_supplied, registry_finding
from ops.signal_pipeline import STRATEGY_ID, STRATEGY_VERSION, SignalBook
from ops.telegram_bot import Bot

BASE = 1_699_999_920_000
STEP = 60_000


def _raw(open_ms, close="100", instrument="BTCUSDT", native="1m"):
    span = {"1m": 1, "3m": 3, "15m": 15, "1h": 60}[native] * STEP
    return {
        "provider": "fixture",
        "source_id": "fixture-1",
        "instrument": instrument,
        "market_type": "spot",
        "native_interval": native,
        "interval": native,
        "open_time": open_ms,
        "close_time": open_ms + span - 1,
        "open": "100",
        "high": "101",
        "low": "99",
        "close": close,
        "volume": "1",
        "timestamp_unit": "ms",
        "retrieved_at_ms": open_ms,
        "complete": True,
        "source_format": "fixture",
    }


def _series():
    rows = []
    for index in range(21):
        close = "110" if index == 20 else "100"
        high = "110" if index == 20 else "101"
        raw = _raw(BASE + index * STEP, close=close)
        raw["high"] = high
        rows.append(raw)
    return rows


def _clear_ai(monkeypatch):
    for key in ("AUREON_AI_API_KEY", "AUREON_AI_BASE_URL", "AUREON_AI_MODEL", "AUREON_AI_FALLBACK_MODEL", "AUREON_AI_SPEND_APPROVED"):
        monkeypatch.delenv(key, raising=False)


def _ready(monkeypatch, fallback="fallback-model"):
    monkeypatch.setenv("AUREON_AI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("AUREON_AI_BASE_URL", "https://ai.example.test")
    monkeypatch.setenv("AUREON_AI_MODEL", "primary-model")
    monkeypatch.setenv("AUREON_AI_FALLBACK_MODEL", fallback)
    monkeypatch.setenv("AUREON_AI_SPEND_APPROVED", "1")


def test_hosted_model_stays_blocked_without_credentials(monkeypatch):
    _clear_ai(monkeypatch)
    called = []

    def transport(*_args):
        called.append(True)
        return 200, {}, {}

    spec = requirements()
    assert spec["configured"] is False
    assert spec["local_model"] is False
    assert spec["missing"] == ["api_key", "base_url", "model", "spend_approval"]
    assert spec["settings"]["api_key"] == "AUREON_AI_API_KEY"
    assert spec["settings"]["spend_approval"] == "AUREON_AI_SPEND_APPROVED=1"
    assert health(transport=transport, allow_network=True)["network"] is False
    assert chat([{"role": "user", "content": "Explain"}], transport=transport)["summary"] is None
    assert called == []


def test_hosted_model_uses_openai_shape_retry_and_fallback(monkeypatch):
    _ready(monkeypatch)
    calls = []

    def transport(method, url, payload):
        calls.append((method, url, None if payload is None else payload.get("model")))
        if url.endswith("/v1/models"):
            return 200, {"data": [{"id": "primary-model"}]}, {}
        if payload["model"] == "primary-model":
            return 503, {}, {}
        return 200, {"choices": [{"message": {"content": "Stored observation is none."}}]}, {}

    blocked = health(allow_network=False)
    assert blocked["network"] is False and blocked["reason"] == "health_probe_not_requested"
    probed = health(transport=transport, allow_network=True)
    assert probed["model_available"] is True and probed["live"] is False
    result = chat([{"role": "user", "content": "Explain"}], transport=transport)
    assert result["ok"] is True
    assert result["summary"] == "Stored observation is none."
    assert result["fallback_used"] is True
    assert result["model_id"] == "fallback-model"
    assert "test-key-not-real" not in json.dumps(result)
    assert calls[1][1].endswith("/v1/chat/completions")

    rate_calls = {"n": 0}

    def rate(_method, _url, _payload):
        rate_calls["n"] += 1
        if rate_calls["n"] == 1:
            return 429, {}, {"retry-after": "9"}
        return 200, {"choices": [{"message": {"content": "Broker is false."}}]}, {}

    limited = chat([{"role": "user", "content": "Explain"}], transport=rate)
    assert limited["ok"] is True and limited["retries"] == 1

    def rejected(_method, _url, payload):
        calls.append(payload["model"])
        return 401, {}, {}

    before = len(calls)
    denied = chat([{"role": "user", "content": "Explain"}], transport=rejected)
    assert denied["reason"] == "provider_rejected"
    assert calls[before:] == ["primary-model"]


def test_candle_book_validates_without_a_live_feed(tmp_path):
    book = CandleBook(tmp_path)
    now = BASE + 3 * STEP
    assert book.accept(_raw(BASE, instrument="XAUUSD"), now_ms=now)["reason"] == "xau_minute_unlicensed"
    first = book.accept(_raw(BASE), now_ms=now)
    assert first["stored"] is True and first["live"] is False
    assert book.accept(_raw(BASE), now_ms=now)["reason"] == "duplicate"
    assert book.accept(_raw(BASE + 2 * STEP), now_ms=now)["stored"] is True
    report = book.health(now_ms=now)
    assert report["live"] is False and report["downloaded"] is False
    assert report["feeds"][0]["gaps"]
    assert report["feeds"][0]["stale"] is False
    assert book.resample_3m("BTCUSDT", now_ms=now, derived_allowed=False)["reason"] == "licence_does_not_permit_resample"
    late = book.accept(_raw(BASE + STEP), now_ms=now)
    assert late["stored"] is True and late["reason"] == "out_of_order"
    filled = CandleBook(tmp_path / "filled")
    for offset in (0, 1, 2):
        assert filled.accept(_raw(BASE + offset * STEP), now_ms=now)["stored"] is True
    allowed = filled.resample_3m("BTCUSDT", now_ms=now, derived_allowed=True)
    assert allowed["ok"] is True and len(allowed["bars"]) == 1 and allowed["bars"][0]["interval"] == "3m"
    assert allowed["live"] is False


def test_signal_lifecycle_is_deterministic_and_not_approval(tmp_path):
    book = SignalBook(tmp_path)
    candles = []
    for raw in _series():
        candles.append({
            "open_time_ms": raw["open_time"],
            "close_time_ms": raw["close_time"],
            "open": raw["open"],
            "high": raw["high"],
            "low": raw["low"],
            "close": raw["close"],
            "complete": True,
            "source_id": "fixture-1",
        })
    now = candles[-1]["close_time_ms"] + 1000
    missing = book.evaluate(candles, symbol="BTCUSDT", interval="1m", now_ms=now, rights="missing")
    assert missing["row"]["lifecycle"] == "UNAVAILABLE" and missing["row"]["signal"] is False
    active = book.evaluate(candles, symbol="BTCUSDT", interval="1m", now_ms=now, rights="fixture")
    row = active["row"]
    assert row["lifecycle"] == "CONFIRMED_ACTIVE" and row["signal"] is True
    assert row["approved"] is False and row["paper_eligible"] is False and row["autopilot"] is False
    assert row["live"] is False
    again = book.evaluate(candles, symbol="BTCUSDT", interval="1m", now_ms=now, rights="fixture")
    assert again["reason"] == "duplicate"
    stale = book.evaluate(candles, symbol="BTCUSDT", interval="1m", now_ms=now + STEP * 5, rights="fixture")
    assert stale["row"]["lifecycle"] == "UNAVAILABLE" and stale["row"]["reason"] == "stale_feed"
    invalidated = book.expire_or_invalidate(symbol="BTCUSDT", interval="1m", price=row["stop"], now_ms=now + 1, max_age_ms=10**12)
    assert invalidated["row"]["lifecycle"] == "INVALIDATED" and invalidated["row"]["signal"] is False
    assert book.rows()[1]["lifecycle"] == "CONFIRMED_ACTIVE"
    finding = registry_finding()
    assert finding["failed"] == 11 and finding["insufficient"] == 2 and finding["approved_for_paper"] == 0
    assert finding["thresholds_changed"] is False
    evidence = evaluate_supplied(candles, symbol="BTCUSDT", interval="1m", now_ms=now, root=tmp_path / "eval", rights="fixture")
    assert evidence["approved_for_paper"] is False and evidence["promoted"] is False
    assert autopilot_may_open({"approved": True, "strategy_id": STRATEGY_ID, "version": STRATEGY_VERSION}) is False


def test_telegram_outbox_is_idempotent_and_isolated(tmp_path):
    bot = Bot(tmp_path)
    calls = []

    def transport(method, name, payload):
        calls.append((method, name, payload))
        if name == "getMe":
            return 200, {"ok": True, "result": {"username": "aureon_fixture_bot"}}
        return 200, {"ok": True, "result": {"message_id": 7}}

    assert bot.get_me("", transport=transport)["network"] is False
    assert calls == []
    assert bot.get_me("token", transport=transport)["username"] == "aureon_fixture_bot"
    assert bot.configure("polling")["ok"] is True
    assert bot.configure("webhook")["reason"] == "one_update_mode"
    assert bot.accept_update(10)["ok"] is True
    assert bot.accept_update(10)["reason"] == "duplicate_update"
    assert bot.enqueue({"event": "WAIT", "account_id": "a", "event_id": "w", "text": "wait"})["reason"] == "wait_suppressed"
    assert bot.enqueue({"event": "confirmed", "account_id": "a", "event_id": "c1", "chat_id": "1", "text": "buy now"})["reason"] == "order_language_blocked"
    queued = bot.enqueue({
        "event": "confirmed",
        "account_id": "ada",
        "event_id": "c1",
        "chat_id": "11",
        "text": "BTCUSDT 1m research observation. Paper only.",
    })
    assert queued["stored"] is True
    assert bot.enqueue(queued["row"] | {"event": "confirmed"})["reason"] == "duplicate_event" or bot.enqueue({
        "event": "confirmed", "account_id": "ada", "event_id": "c1", "chat_id": "11", "text": "again",
    })["reason"] == "duplicate_event"
    bot.enqueue({
        "event": "feed_interrupted",
        "account_id": "ben",
        "event_id": "f1",
        "chat_id": "22",
        "text": "BTCUSDT feed interrupted. No candle was invented.",
    })
    first = {"n": 0}

    def flaky(method, name, payload):
        first["n"] += 1
        if payload["chat_id"] == "11" and first["n"] == 1:
            return 429, {}
        return 200, {"ok": True, "result": {"message_id": 8}}

    bot.deliver(flaky)
    assert bot.for_account("ada")[0]["status"] == "pending"
    bot.deliver(flaky)
    assert bot.for_account("ada")[0]["status"] == "delivered"
    assert bot.for_account("ben")[0]["status"] == "delivered"
    assert all(row["authorizes_trade"] is False for row in bot.pending())
    assert "ben" not in json.dumps(bot.for_account("ada"))


def test_event_chain_uses_fixtures_and_does_not_claim_a_live_integration(tmp_path, monkeypatch):
    from ops.app import LIMITER

    previous_limit = LIMITER.per_minute
    try:
        _event_chain(tmp_path, monkeypatch)
    finally:
        LIMITER.per_minute = previous_limit


def _event_chain(tmp_path, monkeypatch):
    from ops.test_experience_product import _boot, _login

    book = CandleBook(tmp_path / "candles")
    raws = _series()
    now = raws[-1]["close_time"] + 1000
    for raw in raws:
        stored = book.accept(raw, now_ms=now)
        assert stored["live"] is False
    candles = book.history("BTCUSDT", "1m")
    signals = SignalBook(tmp_path / "signals")
    result = signals.evaluate(candles, symbol="BTCUSDT", interval="1m", now_ms=now, rights="fixture")
    row = result["row"]
    assert row["lifecycle"] == "CONFIRMED_ACTIVE" and row["approved"] is False
    bot = Bot(tmp_path / "telegram")
    bot.configure("polling")
    bot.enqueue({
        "event": "confirmed",
        "account_id": "ada",
        "event_id": row["opportunity_id"],
        "chat_id": "11",
        "text": "Research observation " + row["opportunity_id"] + ". Paper only.",
    })
    sent = []

    def send(_method, _name, payload):
        sent.append(payload["text"])
        return 200, {"ok": True, "result": {"message_id": 1}}

    bot.deliver(send)
    assert sent and "Paper only." in sent[0]
    assert bot.for_account("other") == []

    app, users = _boot(tmp_path / "desk", monkeypatch)
    ada, _body = _login(app, "Ada")
    monkeypatch.setenv("AUREON_AI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("AUREON_AI_BASE_URL", "https://ai.example.test")
    monkeypatch.setenv("AUREON_AI_MODEL", "primary-model")
    monkeypatch.setenv("AUREON_AI_SPEND_APPROVED", "1")
    calls = {"n": 0}

    def route_post(_payload):
        calls["n"] += 1
        return 200, {"summary": "Stored observation is none. Broker is false.", "evidence_used": ["broker false"], "model_id": "primary-model", "latency_ms": 4, "retries": 0}

    monkeypatch.setattr("ops.hosted_ai._post", route_post)
    grounded = ada.post("/api/aureon-ai", json={"page": "/overview", "question": "Explain"}).get_json()
    assert grounded["ok"] is True
    assert grounded["approved"] is False and grounded["order_opened"] is False
    assert grounded["usage"]["model_id"] == "primary-model"
    assert grounded["usage"]["provider_called"] is True
    invented = {"summary": "The price is 110.", "evidence_used": ["broker false"]}

    def invent(_payload):
        return 200, invented

    monkeypatch.setattr("ops.hosted_ai._post", invent)
    rejected = ada.post("/api/aureon-ai", json={"page": "/overview", "question": "Explain", "summary": "The price is 110.", "approved": True}).get_json()
    assert rejected["reason"] == "invalid_output" and rejected["analysis"] is None
    assert rejected["approved"] is False and rejected["order_opened"] is False
    monkeypatch.delenv("AUREON_AI_SPEND_APPROVED")

    def explode(_payload):
        raise AssertionError("provider")

    monkeypatch.setattr("ops.hosted_ai._post", explode)
    silent = ada.post("/api/aureon-ai", json={"page": "/overview", "question": "Explain"}).get_json()
    assert silent["reason"] is None and silent["operational"] == "DESK" and silent["analysis"] is None
    assert silent["missing"] == []
    assert "AUREON_AI_API_KEY" not in json.dumps(silent)
    assert calls["n"] == 1
    del users
