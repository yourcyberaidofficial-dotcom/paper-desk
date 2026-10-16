"""Aureon Trading Lab dashboard. Paper only."""

import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, session, redirect, make_response

from ops.auth import RateLimit, api_token, require_token
from ops.engine import PaperEngine
from ops.ledger import Ledger
from ops.market import snapshot as market_snapshot
from ops.notify import send_alert
from ops.strategy import WaitStrategy

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "data" / "paper" / "ledger.jsonl"
STARTED = time.time()
LIMITER = RateLimit(60)

app = Flask(__name__)
app.secret_key = os.environ.get("DESK_SESSION_SECRET") or api_token() or "disabled"
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
ledger = Ledger(LEDGER_PATH)
engine = PaperEngine(ledger, WaitStrategy())

@app.get("/health")
def health():
    markets = market_snapshot()
    fresh = all(markets[s].get("fresh") for s in ("BTCUSDT", "ETHUSDT"))
    telegram_set = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
    return jsonify({
        "status": "ok" if fresh else "degraded",
        "process": "ok",
        "uptime_s": int(time.time() - STARTED),
        "market_data": "fresh" if fresh else "stale",
        "notification": "configured" if telegram_set else "not_configured",
        "ledger": "ok" if LEDGER_PATH.parent.exists() else "missing",
        "strategy": engine.strategy.name,
        "strategy_status": "WAIT_DEFAULT",
        "paper_only": True,
        "broker": False,
    })
