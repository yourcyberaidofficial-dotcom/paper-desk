"""Aureon Trading Lab dashboard. Paper only. Public health is coarse."""

import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, session, redirect, make_response

from ops.auth import RateLimit, api_token, require_token
from ops.engine import PaperEngine
from ops.ledger import Ledger
from ops.market import snapshot as market_snapshot, fetch_klines
from ops.notify import send_alert
from ops.strategy import WaitStrategy

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "data" / "paper" / "ledger.jsonl"
STARTED = time.time()
LIMITER = RateLimit(60)

app = Flask(__name__)
app.secret_key = os.environ.get("DESK_SESSION_SECRET") or api_token() or "disabled"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("DESK_COOKIE_SECURE", "0") == "1",
)
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


@app.get("/api/klines")
def klines():
    blocked = _limited()
    if blocked:
        return blocked
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "15m")
    return jsonify(fetch_klines(symbol, interval))


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
    result = send_alert("SYSTEM TEST — Aureon Trading Lab. Not a trade signal.")
    ledger.append({
        "type": "alert",
        "status": result["status"],
        "delivered": result["delivered"],
        "id": f"system-test-{int(time.time() * 1000)}",
    })
    return jsonify({k: v for k, v in result.items() if k != "response"})


@app.post("/login")
def login():
    token = (request.form.get("token") or "").strip()
    expected = api_token()
    if not expected or token != expected:
        return redirect("/?login=failed")
    session["ok"] = True
    return redirect("/")


@app.post("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.get("/")
def index():
    authed = bool(session.get("ok"))
    failed = request.args.get("login") == "failed"
    return make_response(DASHBOARD.replace("{{AUTHED}}", "1" if authed else "0").replace("{{FAILED}}", "1" if failed else "0"))


DASHBOARD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aureon Trading Lab</title>
<style>
:root{--bg:#0b0e14;--card:#141824;--text:#e8eaf0;--muted:#9aa3b5;--accent:#7c9cff;--warn:#f5c451;--ok:#3dd68c;--bad:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--text)}
header{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid #222}
h1{font-size:1.15rem;margin:0}
.badge{font-size:.75rem;padding:4px 8px;border-radius:999px;background:#1e2433;color:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;padding:16px}
.card{background:var(--card);border-radius:14px;padding:14px}
.card h2{margin:0 0 8px;font-size:.95rem}
.muted{color:var(--muted);font-size:.85rem}
.ok{color:var(--ok)}.bad{color:var(--bad)}
pre{white-space:pre-wrap;word-break:break-word;font-size:.8rem;margin:0}
form{display:flex;gap:8px;margin-top:8px}
input{flex:1;padding:8px;border-radius:8px;border:1px solid #333;background:#0f121a;color:var(--text)}
button{padding:8px 12px;border-radius:8px;border:0;background:var(--accent);color:#0b0e14;font-weight:600;cursor:pointer}
.warnbox{color:var(--warn);font-size:.85rem}
</style>
</head>
<body>
<header>
  <h1>Aureon Trading Lab</h1>
  <span class="badge">PAPER ONLY · WAIT_DEFAULT</span>
</header>
<div class="grid">
  <section class="card">
    <h2>System</h2>
    <pre id="health">loading</pre>
    <p class="warnbox">Simulated desk. No broker. No real-money execution.</p>
  </section>
  <section class="card">
    <h2>Market (watch only)</h2>
    <pre id="market">loading</pre>
    <p class="muted">Source: Binance public klines. Gold is observation-only.</p>
  </section>
  <section class="card">
    <h2>BTC / ETH candles</h2>
    <canvas id="chart" width="360" height="160" style="width:100%;height:160px;background:#0f121a;border-radius:8px"></canvas>
    <p class="muted">Closed Binance candles only. Not a signal. Gold has no chart.</p>
  </section>
  <section class="card">
    <h2>Paper equity</h2>
    <pre id="equity">No paper fills yet. Starting balance is 10000 per sleeve. Curve appears after the first recorded fill.</pre>
    <p class="muted">Simulated. Not a real account.</p>
  </section>
  <section class="card">
    <h2>Signal</h2>
    <p><b>WAIT</b></p>
    <p class="muted">No hypothesis has passed the sealed research protocol. No edge is claimed.</p>
  </section>
  <section class="card">
    <h2>Access</h2>
    <div id="loginbox">
      <p class="muted">Enter the desk token to view balances and events. It is not stored in the page.</p>
      <form method="post" action="/login">
        <input type="password" name="token" placeholder="DESK_API_TOKEN" required>
        <button type="submit">Unlock</button>
      </form>
      <p id="fail" class="bad" hidden>Token rejected.</p>
    </div>
    <div id="private" hidden>
      <h3>Balances (paper)</h3>
      <pre id="state">loading</pre>
      <h3>Recent events</h3>
      <pre id="events">loading</pre>
      <form method="post" action="/logout"><button type="submit">Lock</button></form>
    </div>
  </section>
</div>
<script>
const AUTHED = "{{AUTHED}}" === "1";
const FAILED = "{{FAILED}}" === "1";
fetch('/health').then(r=>r.json()).then(d=>document.getElementById('health').textContent=JSON.stringify(d,null,2));
fetch('/api/klines?symbol=BTCUSDT&interval=15m').then(r=>r.json()).then(draw);
function draw(data){
  const c = document.getElementById('chart');
  const ctx = c.getContext('2d');
  const w = c.width, h = c.height;
  ctx.clearRect(0,0,w,h);
  const candles = (data.candles || []).slice(-40);
  if (!candles.length) { ctx.fillStyle='#9aa3b5'; ctx.fillText('no candles', 8, 20); return; }
  const highs = candles.map(x=>x.h), lows = candles.map(x=>x.l);
  const hi = Math.max(...highs), lo = Math.min(...lows);
  const span = hi - lo || 1;
  const cw = w / candles.length;
  candles.forEach((bar, i) => {
    const x = i * cw + cw/2;
    const yH = h - ((bar.h - lo) / span) * (h-8) - 4;
    const yL = h - ((bar.l - lo) / span) * (h-8) - 4;
    const yO = h - ((bar.o - lo) / span) * (h-8) - 4;
    const yC = h - ((bar.c - lo) / span) * (h-8) - 4;
    ctx.strokeStyle = bar.c >= bar.o ? '#3dd68c' : '#ff6b6b';
    ctx.beginPath(); ctx.moveTo(x, yH); ctx.lineTo(x, yL); ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillRect(x-2, Math.min(yO,yC), 4, Math.max(1, Math.abs(yC-yO)));
  });
}
if (FAILED) document.getElementById('fail').hidden = false;
if (AUTHED) {
  document.getElementById('loginbox').hidden = true;
  document.getElementById('private').hidden = false;
  fetch('/api/state').then(r=>r.json()).then(d=>document.getElementById('state').textContent=JSON.stringify(d,null,2));
  fetch('/api/events').then(r=>r.json()).then(d=>document.getElementById('events').textContent=JSON.stringify(d,null,2));
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host=os.environ.get("DESK_BIND", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")))
