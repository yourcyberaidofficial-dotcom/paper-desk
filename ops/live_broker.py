"""Live exchange sends are locked off.

Request helpers remain in this file and are not called by `execute`.
A paper order never reaches an exchange.
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
    return False


def status():
    return {
        "venue": "paper",
        "armed": False,
        "flag": False,
        "key_present": False,
        "secret_present": False,
        "symbols": sorted(CRYPTO),
        "gold": "paper",
        "shorts": "paper",
        "broker": False,
        "note": "Paper only. Live exchange orders are not available.",
    }


def execute(symbol, side, quantity, stop, price=None, transport=None):
    """Paper desk. A server flag or a key cannot place an exchange order."""
    return {"ok": False, "reason": "paper_only", "sent": False}


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
