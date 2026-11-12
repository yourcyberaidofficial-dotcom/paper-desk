"""Spot execution stays off without keys, and a buy keeps its stop."""

import json

from ops.live_broker import execute, floor_step, status


def _rules(symbol):
    return {
        "symbols": [{
            "symbol": symbol,
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            ],
        }]
    }


def test_live_stays_off_without_keys(monkeypatch):
    monkeypatch.delenv("AUREON_LIVE_TRADING", raising=False)
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    called = []
    result = execute("BTCUSDT", "BUY", 0.01, 100, price=100000, transport=lambda *args: called.append(args))
    assert result["ok"] is False
    assert result["sent"] is False
    assert result["reason"] == "not_configured"
    assert called == []
    assert status()["armed"] is False


def test_a_spot_short_and_gold_are_not_sent(monkeypatch):
    monkeypatch.setenv("AUREON_LIVE_TRADING", "1")
    monkeypatch.setenv("BINANCE_API_KEY", "key")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret")
    assert execute("BTCUSDT", "SELL", 0.01, 100)["reason"] == "spot_short_unavailable"
    assert execute("XAUUSD", "BUY", 1, 3900)["reason"] == "live_symbol"


def test_a_buy_places_a_stop_and_hides_the_key(monkeypatch):
    monkeypatch.setenv("AUREON_LIVE_TRADING", "1")
    monkeypatch.setenv("BINANCE_API_KEY", "key-value")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret-value")
    seen = []

    def transport(method, url, headers, body):
        seen.append((method, url, headers.get("X-MBX-APIKEY")))
        if "/exchangeInfo" in url:
            return 200, json.dumps(_rules("BTCUSDT")).encode()
        if "STOP_LOSS_LIMIT" in url:
            return 200, json.dumps({"orderId": 9, "executedQty": "0.015"}).encode()
        if "MARKET" in url and "side=BUY" in url:
            return 200, json.dumps({"orderId": 4, "executedQty": "0.015"}).encode()
        return 500, b"{}"

    result = execute("BTCUSDT", "BUY", 0.0154, 99000, price=100000, transport=transport)
    assert result["ok"] is True
    assert result["order_id"] == 4
    assert result["stop_order_id"] == 9
    assert result["quantity"] == 0.015
    blob = json.dumps(result)
    assert "key-value" not in blob and "secret-value" not in blob
    assert seen[1][2] == "key-value"
    assert "signature=" in seen[1][1]
    assert floor_step(0.0154, "0.001") == 0.015


def test_a_rejected_stop_closes_the_buy(monkeypatch):
    monkeypatch.setenv("AUREON_LIVE_TRADING", "1")
    monkeypatch.setenv("BINANCE_API_KEY", "key")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret")
    sides = []

    def transport(method, url, headers, body):
        if "/exchangeInfo" in url:
            return 200, json.dumps(_rules("ETHUSDT")).encode()
        if "side=BUY" in url:
            sides.append("BUY")
            return 200, json.dumps({"orderId": 1, "executedQty": "0.010"}).encode()
        if "STOP_LOSS_LIMIT" in url:
            sides.append("STOP")
            return 400, json.dumps({"code": -1013, "msg": "no"}).encode()
        if "side=SELL" in url:
            sides.append("SELL")
            return 200, json.dumps({"orderId": 2, "executedQty": "0.010"}).encode()
        return 500, b"{}"

    result = execute("ETHUSDT", "BUY", 0.01, 2000, price=2100, transport=transport)
    assert result["ok"] is False
    assert result["reason"] == "stop_not_held"
    assert sides == ["BUY", "STOP", "SELL"]
