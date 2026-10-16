"""Paper dashboard. Public health is coarse. Private state requires a token."""

import os
import time
from pathlib import Path

from flask import Flask, jsonify, request

from ops.auth import RateLimit, require_token
from ops.engine import PaperEngine
from ops.ledger import Ledger
from ops.market import snapshot as market_snapshot
from ops.notify import send_alert
from ops.strategy import WaitStrategy

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "data" / "paper" / "ledger.jsonl"
STARTED = time.time()
LIMITER = RateLimit(30)

app = Flask(__name__)
ledger = Ledger(LEDGER_PATH)
engine = PaperEngine(ledger, WaitStrategy())

def _limited():
    if not LIMITER.allow(request.remote_addr or "local"):
        return jsonify({"error": "rate_limited"}), 429
    return None

@app.get("/health")
def health():
    markets = market_snapshot()
    fresh = all(markets[s].get("fresh") for s in ("BTCUSDT", "ETHUSDT"))
    return jsonify({
        "status": "ok" if fresh else "degraded",
        "process": "ok",
        "uptime_s": int(time.time() - STARTED),
        "market_data": "fresh" if fresh else "stale",
        "notification": "not_verified",
        "ledger": "ok" if LEDGER_PATH.parent.exists() else "missing",
        "strategy": engine.strategy.name,
        "strategy_status": "WAIT_DEFAULT",
        "paper_only": True,
        "broker": False,
    })

@app.get("/api/market")
def market():
    blocked = _limited()
    return blocked if blocked else jsonify(market_snapshot())

@app.get("/api/state")
@require_token
def state():
    return jsonify(engine.snapshot())

@app.get("/api/events")
@require_token
def events():
    return jsonify(ledger.read()[-50:])

@app.post("/api/bar")
@require_token
def bar():
    payload = request.get_json(force=True)
    if payload.get("symbol") not in {"BTCUSDT", "ETHUSDT"}:
        return jsonify({"error": "symbol_not_allowed"}), 400
    return jsonify(engine.ingest_bar(payload["symbol"], payload.get("bar")))

@app.post("/api/alert-test")
@require_token
def alert_test():
    result = send_alert("SYSTEM TEST — paper desk. Not a trade signal.")
    ledger.append({"type": "alert", "status": result["status"], "delivered": result["delivered"], "id": "system-test"})
    return jsonify({k: v for k, v in result.items() if k != "response"})

@app.get("/")
def index():
    return """<!doctype html><html><head><meta charset=\"utf-8\"><title>Paper Desk</title></head><body><h1>Paper Desk</h1><p>Paper only. Strategy WAIT. Balances are private.</p><pre id=\"h\"></pre><script>fetch('/health').then(r=>r.json()).then(d=>document.getElementById('h').textContent=JSON.stringify(d,null,2));</script></body></html>"""

if __name__ == "__main__":
    app.run(host=os.environ.get("DESK_BIND", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")))
