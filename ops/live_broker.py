"""Binance spot execution for this desk.

A market buy is sent only when the server flag, both keys, and the account
switch are all on. A stop is placed immediately after the fill. If the stop
is rejected, the buy is closed. Spot cannot short, and gold is not this venue.
Keys and signatures are never copied into a result.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_DOWN

SPOT = "https://api.binance.com"
CRYPTO = frozenset({"BTCUSDT", "ETHUSDT"})


def _flag(name):
    return os.environ.get(name) or ""


def configured():
    return bool(_flag("AUREON_LIVE_TRADING") == "1" and _flag("BINANCE_API_KEY") and _flag("BINANCE_API_SECRET"))


def status():
    armed = configured()
    if armed:
        note = "Binance spot is armed. Buys can be sent. Shorts and gold stay on the paper book."
    elif _flag("AUREON_LIVE_TRADING") != "1":
        note = "Set AUREON_LIVE_TRADING=1 on the server, with both Binance keys, to send a spot buy."
    else:
        note = "The live flag is on, but a Binance key or secret is missing. No order was sent."
    return {
        "venue": "binance-spot",
        "armed": armed,
        "flag": _flag("AUREON_LIVE_TRADING") == "1",
        "key_present": bool(_flag("BINANCE_API_KEY")),
        "secret_present": bool(_flag("BINANCE_API_SECRET")),
        "symbols": sorted(CRYPTO),
        "gold": "paper",
        "shorts": "paper",
        "note": note,
    }


def floor_step(quantity, step):
    try:
        qty = Decimal(str(quantity))
        size = Decimal(str(step))
    except Exception:
        return None
    if qty <= 0 or size <= 0:
        return None
    units = (qty / size).to_integral_value(ROUND_DOWN)
    return float(units * size)


def _sign(query, secret):
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def _default_transport(method, url, headers, body):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _public_get(path, transport):
    status, raw = transport("GET", SPOT + path, {}, None)
    if status != 200:
        return None
    try:
        return json.loads(raw.decode())
    except Exception:
        return None


def _signed(method, path, params, key, secret, transport):
    query = urllib.parse.urlencode(params)
    signature = _sign(query, secret)
    url = f"{SPOT}{path}?{query}&signature={signature}"
    status, raw = transport(method, url, {"X-MBX-APIKEY": key}, None)
    try:
        body = json.loads(raw.decode()) if raw else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    return status, body


def _filters(symbol, transport):
    payload = _public_get("/api/v3/exchangeInfo?symbol=" + urllib.parse.quote(symbol), transport)
    symbols = (payload or {}).get("symbols") or []
    info = next((row for row in symbols if row.get("symbol") == symbol), None)
    if not info:
        return None
    step = minimum = notional = None
    for item in info.get("filters") or []:
        kind = item.get("filterType")
        if kind == "LOT_SIZE":
            step = item.get("stepSize")
            minimum = item.get("minQty")
        elif kind in {"MIN_NOTIONAL", "NOTIONAL"}:
            notional = item.get("minNotional") or item.get("notional")
    if step is None:
        return None
    return {"step": step, "min_qty": minimum, "min_notional": notional}


def _order(symbol, side, order_type, quantity, key, secret, transport, **extra):
    params = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": quantity,
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    params.update(extra)
    status, body = _signed("POST", "/api/v3/order", params, key, secret, transport)
    if status != 200 or body.get("orderId") is None:
        return {"ok": False, "reason": "exchange_rejected", "code": body.get("code")}
    return {"ok": True, "order_id": body.get("orderId"), "executed": body.get("executedQty") or quantity}


def execute(symbol, side, quantity, stop, price=None, transport=None):
    """Send one spot buy and its stop. A missing key does not invent a fill."""
    if symbol not in CRYPTO:
        return {"ok": False, "reason": "live_symbol", "sent": False}
    if side != "BUY":
        return {"ok": False, "reason": "spot_short_unavailable", "sent": False}
    if not configured():
        return {"ok": False, "reason": "not_configured", "sent": False}
    try:
        stop_price = float(stop)
        requested = float(quantity)
        mark = float(price) if price is not None else None
    except (TypeError, ValueError):
        return {"ok": False, "reason": "incomplete", "sent": False}
    if stop_price <= 0 or requested <= 0:
        return {"ok": False, "reason": "incomplete", "sent": False}
    transport = transport or _default_transport
    key, secret = _flag("BINANCE_API_KEY"), _flag("BINANCE_API_SECRET")
    try:
        rules = _filters(symbol, transport)
        if not rules:
            return {"ok": False, "reason": "exchange_rules_unavailable", "sent": False}
        qty = floor_step(requested, rules["step"])
        if qty is None or (rules.get("min_qty") and qty + 1e-12 < float(rules["min_qty"])):
            return {"ok": False, "reason": "min_qty", "sent": False}
        if mark and rules.get("min_notional") and qty * mark < float(rules["min_notional"]):
            return {"ok": False, "reason": "min_notional", "sent": False}
        opened = _order(symbol, "BUY", "MARKET", qty, key, secret, transport)
        if not opened.get("ok"):
            return {**opened, "sent": False}
        filled = floor_step(opened.get("executed") or qty, rules["step"]) or qty
        limit = float(Decimal(str(stop_price * 0.995)).quantize(Decimal("0.01"), rounding=ROUND_DOWN))
        protected = _order(
            symbol, "SELL", "STOP_LOSS_LIMIT", filled, key, secret, transport,
            stopPrice=stop_price, price=limit, timeInForce="GTC",
        )
        if protected.get("ok"):
            return {
                "ok": True,
                "sent": True,
                "reason": "opened",
                "order_id": opened["order_id"],
                "stop_order_id": protected["order_id"],
                "quantity": filled,
                "venue": "binance-spot",
            }
        _order(symbol, "SELL", "MARKET", filled, key, secret, transport)
        return {"ok": False, "reason": "stop_not_held", "sent": True, "closed": True}
    except Exception:
        return {"ok": False, "reason": "exchange_unreachable", "sent": False}
