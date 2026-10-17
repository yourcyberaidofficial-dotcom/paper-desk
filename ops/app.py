"""Aureon Trading Lab dashboard. Paper only. Public health is coarse."""

import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, session, redirect, make_response

from ops.auth import RateLimit, api_token, require_token
from ops.engine import PaperEngine
from ops.ledger import Ledger
from ops.signals import research_states
from ops.replay import replay, yesterday_ms, period
from ops.leaderboard import leaderboard
from ops.market import snapshot as market_snapshot, fetch_klines
from ops.notify import send_alert
from ops.strategy import WaitStrategy
from ops.worker import Worker
import threading

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
worker = Worker(ledger, LEDGER_PATH.parent / "prefs.json")


SESSION_TTL = 12 * 3600

def _session_ok():
    exp = session.get("exp")
    if not session.get("ok") or not exp or time.time() > exp:
        session.clear()
        return False
    return True

def _csrf():
    token = session.get("csrf")
    if not token:
        token = os.urandom(16).hex()
        session["csrf"] = token
    return token

def _limited():
    if not LIMITER.allow(request.remote_addr or "local"):
        return jsonify({"error": "rate_limited"}), 429
    return None


@app.before_request
def _expire():
    if session.get("ok") and not _session_ok():
        session.clear()

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
        "worker": worker.status(),
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


@app.get("/api/signal")
def signal():
    return jsonify({
        "asset": "BTCUSDT",
        "direction": "WAIT",
        "classification": "no_validated_strategy",
        "label": "Not a trading signal",
        "rationale": "No hypothesis has passed the sealed research protocol.",
        "validated": False,
        "paper_only": True,
    })


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
    if request.form.get("csrf") != session.get("csrf"):
        return redirect("/?login=failed")
    token = (request.form.get("token") or "").strip()
    expected = api_token()
    if not expected or token != expected:
        return redirect("/?login=failed")
    session["ok"] = True
    session["exp"] = time.time() + SESSION_TTL
    session["csrf"] = os.urandom(16).hex()
    return redirect("/")


@app.post("/logout")
def logout():
    if request.form.get("csrf") != session.get("csrf"):
        return redirect("/")
    session.clear()
    return redirect("/")



@app.get("/api/evaluations")
@require_token
def evaluations():
    try:
        limit = min(int(request.args.get("limit", 20)), 50)
    except ValueError:
        limit = 20
    rows = [row for row in ledger.read() if row.get("type") == "evaluation"]
    return jsonify({"rows": rows[-limit:], "total": len(rows)})


@app.get("/api/leaderboard")
def leaderboard_api():
    try:
        return jsonify(leaderboard())
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 502


@app.get("/api/period")
def period_api():
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "15m")
    at = request.args.get("at")
    at_ms = yesterday_ms() if not at or at == "yesterday" else int(at)
    try:
        return jsonify(period(symbol, interval, at_ms))
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 502


@app.get("/api/replay")
def replay_api():
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "15m")
    at = request.args.get("at")
    at_ms = yesterday_ms() if not at or at == "yesterday" else int(at)
    try:
        return jsonify(replay(symbol, interval, at_ms))
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 502


@app.get("/api/research-signals")
def research_signals():
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "15m")
    data = fetch_klines(symbol, interval, limit=50)
    bars = [{"high": c["h"], "low": c["l"], "close": c["c"]} for c in data.get("candles") or []]
    return jsonify({
        "symbol": symbol,
        "interval": interval,
        "production": "WAIT_DEFAULT",
        "validated": False,
        "states": research_states(bars) if bars else [],
        "label": "RESEARCH OBSERVATION — NOT VALIDATED",
    })


@app.get("/api/experimental")
@require_token
def experimental():
    rows = worker.book.read()
    return jsonify({"rows": rows[-50:], "total": len(rows), "label": "EXPERIMENTAL PAPER — NOT VALIDATED"})


@app.get("/api/prefs")
@require_token
def get_prefs():
    return jsonify(worker.prefs())


@app.post("/api/prefs")
@require_token
def set_prefs():
    return jsonify(worker.save_prefs(request.get_json(force=True)))


def _loop():
    while True:
        try:
            worker.evaluate()
        except Exception:
            pass
        time.sleep(60)


threading.Thread(target=_loop, daemon=True).start()

@app.get("/")
def index():
    authed = _session_ok()
    failed = request.args.get("login") == "failed"
    page = DASHBOARD.replace("{{AUTHED}}", "1" if authed else "0").replace("{{FAILED}}", "1" if failed else "0").replace("{{CSRF}}", _csrf())
    return make_response(page)


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
header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid #222;flex-wrap:wrap}
h1{font-size:1.15rem;margin:0}
nav{display:flex;gap:8px;flex-wrap:wrap}
nav button, .tf button{background:#1e2433;color:var(--text);border:0;border-radius:8px;padding:6px 10px;cursor:pointer}
nav button.active, .tf button.active{background:var(--accent);color:#0b0e14}
.badge{font-size:.75rem;padding:4px 8px;border-radius:999px;background:#1e2433;color:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;padding:16px}
.card{background:var(--card);border-radius:14px;padding:14px}
.card h2{margin:0 0 8px;font-size:.95rem}
.muted{color:var(--muted);font-size:.85rem}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
pre{white-space:pre-wrap;word-break:break-word;font-size:.8rem;margin:0}
form{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
input{flex:1;min-width:160px;padding:8px;border-radius:8px;border:1px solid #333;background:#0f121a;color:var(--text)}
button{padding:8px 12px;border-radius:8px;border:0;background:var(--accent);color:#0b0e14;font-weight:600;cursor:pointer}
.warnbox{color:var(--warn);font-size:.85rem}
.tf{display:flex;gap:6px;margin:8px 0}
canvas{width:100%;height:180px;background:#0f121a;border-radius:8px}
@media (max-width:640px){header{align-items:flex-start} .grid{padding:10px}}
</style>
</head>
<body>
<header>
  <h1>Aureon Trading Lab</h1>
  <nav>
    <button class="active" data-panel="desk">Desk</button>
    <button data-panel="charts">Charts</button>
    <button data-panel="history">History</button>
    <button data-panel="settings">Settings</button>
    <button data-panel="research">Research</button>
  </nav>
  <span class="badge">PAPER ONLY · WAIT_DEFAULT</span>
</header>
<div id="desk" class="grid">
  <section class="card">
    <h2>System</h2>
    <pre id="health">loading</pre>
    <p class="warnbox">Simulated desk. No broker. No real-money execution.</p>
  </section>
  <section class="card">
    <h2>Market</h2>
    <pre id="market">loading</pre>
    <p class="muted">Closed Binance candles. Watch only. Gold has no feed.</p>
  </section>
  <section class="card">
    <h2>Historical replay</h2>
    <p class="warnbox">Hypothetical simulation. Not a trade. Decision uses only closed bars.</p>
    <input id="replayat" placeholder="yesterday or epoch ms">
    <select id="replaysym"><option>BTCUSDT</option><option>ETHUSDT</option></select>
    <select id="replaytf"><option>15m</option><option>1h</option><option>4h</option><option>1d</option></select>
    <button id="replaybtn" type="button">Replay candle</button>
    <button id="periodbtn" type="button">Period ledger</button>
    <button id="boardbtn" type="button">Leaderboard</button>
    <pre id="replaybox">Select replay.</pre>
  </section>
  <section class="card">
    <h2>Research states</h2>
    <p class="warnbox">Independent model outputs. Not production. Not validated.</p>
    <pre id="researchstates">loading</pre>
  </section>
  <section class="card">
    <h2>Signal</h2>
    <p><b id="sig">WAIT</b> <span class="badge">NOT A VALIDATED SIGNAL</span></p>
    <p class="muted" id="sigwhy">No hypothesis has passed the sealed research protocol. No edge is claimed.</p>
    <p class="muted" id="alertstatus">Alert status loading.</p>
  </section>
  <section class="card">
    <h2>Experimental paper</h2>
    <p class="warnbox">EXPERIMENTAL PAPER — NOT VALIDATED. Not production. Not a real account.</p>
    <pre id="paper">Unlock to view.</pre>
  </section>
  <section class="card">
    <h2>Paper equity</h2>
    <pre id="equity">No paper fills yet. Starting balance is 10000 per sleeve. Curve appears after the first recorded fill.</pre>
    <p class="muted">Simulated. Not a real account. Fees and slippage are not applied until a fill exists.</p>
  </section>
  <section class="card">
    <h2>Access</h2>
    <div id="loginbox">
      <p class="muted">Enter the desk token to view balances and events. It is not stored in the page.</p>
      <form method="post" action="/login">
        <input type="hidden" name="csrf" value="{{CSRF}}">
        <input type="password" name="token" placeholder="Owner token" required autocomplete="current-password">
        <button type="submit">Unlock</button>
      </form>
      <p id="fail" class="bad" hidden>Token rejected.</p>
    </div>
    <div id="private" hidden>
      <h3>Balances (paper)</h3>
      <pre id="state">loading</pre>
      <h3>Recent events</h3>
      <pre id="events">loading</pre>
      <form method="post" action="/logout"><input type="hidden" name="csrf" value="{{CSRF}}"><button type="submit">Lock</button></form>
    </div>
  </section>
</div>
<div id="charts" class="grid" hidden>
  <section class="card" style="grid-column:1/-1">
    <h2>Closed candles</h2>
    <div class="tf">
      <button data-sym="BTCUSDT" class="active">BTC</button>
      <button data-sym="ETHUSDT">ETH</button>
      <button data-tf="15m" class="active">15m</button>
      <button data-tf="1h">1h</button>
      <button data-tf="4h">4h</button>
      <button data-tf="1d">1d</button>
    </div>
    <canvas id="chart" width="720" height="220" role="img" aria-label="Closed candlestick chart"></canvas>
    <p class="muted" id="chartmeta">Loading closed Binance candles. Not a signal. Gold has no chart.</p>
  </section>
</div>

<div id="history" class="grid" hidden>
  <section class="card" style="grid-column:1/-1">
    <h2>Signal history</h2>
    <p class="muted">Evaluations only. Not orders. Not fills. Not a performance record.</p>
    <pre id="historybox">Unlock to load history.</pre>
  </section>
</div>
<div id="settings" class="grid" hidden>
  <section class="card">
    <h2>Preferences</h2>
    <p class="muted">BTC and ETH only. Cap cannot exceed 48. Gold is not available.</p>
    <form id="prefsform">
      <label><input type="checkbox" name="btc" checked> BTC</label>
      <label><input type="checkbox" name="eth" checked> ETH</label>
      <label><input type="checkbox" name="experimental"> Experimental alerts (not validated)</label>
      <select name="interval"><option>15m</option><option>1h</option><option>4h</option></select>
      <input name="max_alerts" type="number" min="0" max="48" value="24">
      <input name="quiet" placeholder="quiet hours UTC, e.g. 0,1,2">
      <button type="submit">Save</button>
    </form>
    <p id="prefstatus" class="muted"></p>
  </section>
</div>
<div id="research" class="grid" hidden>
  <section class="card">
    <h2>Research</h2>
    <p class="muted">G0 is a frozen, protocol-defective historical result. It is not deployed here.</p>
    <p class="muted"><b>G1-H4-r2: CLOSED / NO PROMOTION.</b> Positive point estimates are not validated signals.</p>
    <p class="muted">No new generation is authorized. Holdout remains sealed. No candidate is approved.</p>
  </section>
</div>
<script>
const AUTHED = "{{AUTHED}}" === "1";
const FAILED = "{{FAILED}}" === "1";
let SYM = "BTCUSDT", TF = "15m";
document.querySelectorAll("nav button").forEach(b => b.onclick = () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  ["desk","charts","history","settings","research"].forEach(id => document.getElementById(id).hidden = id !== b.dataset.panel);
  if (b.dataset.panel === "charts") loadChart();
});
document.querySelectorAll("[data-sym]").forEach(b => b.onclick = () => { SYM = b.dataset.sym; document.querySelectorAll("[data-sym]").forEach(x=>x.classList.remove("active")); b.classList.add("active"); loadChart(); });
document.querySelectorAll("[data-tf]").forEach(b => b.onclick = () => { TF = b.dataset.tf; document.querySelectorAll("[data-tf]").forEach(x=>x.classList.remove("active")); b.classList.add("active"); loadChart(); });
function replayQuery(){
  return "symbol="+document.getElementById("replaysym").value+"&interval="+document.getElementById("replaytf").value+"&at="+(document.getElementById("replayat").value||"yesterday");
}
document.getElementById("replaybtn").onclick = () => {
  document.getElementById("replaybox").textContent = "loading";
  fetch("/api/replay?"+replayQuery()).then(r=>r.json()).then(d=>{ document.getElementById("replaybox").textContent = JSON.stringify(d, null, 2); });
};
document.getElementById("periodbtn").onclick = () => {
  document.getElementById("replaybox").textContent = "loading";
  fetch("/api/period?"+replayQuery()).then(r=>r.json()).then(d=>{ document.getElementById("replaybox").textContent = JSON.stringify(d, null, 2); });
};
document.getElementById("boardbtn").onclick = () => {
  document.getElementById("replaybox").textContent = "loading leaderboard";
  fetch("/api/leaderboard").then(r=>r.json()).then(d=>{ document.getElementById("replaybox").textContent = JSON.stringify(d, null, 2); });
};
fetch("/api/research-signals?symbol=BTCUSDT&interval=15m").then(r=>r.json()).then(d=>{
  document.getElementById("researchstates").textContent = d.states.map(s => s.strategy+" "+s.direction+" validated="+s.validated).join("\n");
}).catch(()=>{ document.getElementById("researchstates").textContent = "Research states unavailable"; });
fetch("/health").then(r=>r.json()).then(d=>{
  document.getElementById("health").textContent=JSON.stringify(d,null,2);
  const w = d.worker || {};
  const p = w.prefs || {};
  const last = w.last_result || {};
  const n = last.notification || {};
  document.getElementById("alertstatus").textContent =
    "Experimental alerts: " + (p.experimental_alerts ? "ON" : "OFF") +
    " · last eval: " + (last.asset || "none") +
    " · last notify: " + (n.status || "none") +
    " · delivered: " + (n.delivered === true) +
    " · read proof: false";
});
function loadChart(){
  const meta = document.getElementById("chartmeta");
  meta.textContent = "Loading…";
  fetch("/api/klines?symbol="+SYM+"&interval="+TF).then(r=>r.json()).then(draw).catch(()=>{ meta.textContent = "Chart unavailable"; });
}
function draw(data){
  const c = document.getElementById("chart");
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height;
  ctx.clearRect(0,0,w,h);
  const candles = (data.candles || []).slice(-60);
  const meta = document.getElementById("chartmeta");
  if (!candles.length) { ctx.fillStyle="#9aa3b5"; ctx.fillText("no closed candles", 8, 20); meta.textContent = "No closed candles."; return; }
  const last = candles[candles.length-1];
  const age = Date.now() - last.t;
  const stale = age > 30*60*1000;
  meta.className = stale ? "warn" : "muted";
  meta.textContent = SYM+" "+TF+" · last closed "+new Date(last.t).toISOString()+" · "+(stale?"stale":"fresh")+" · source "+(data.source||"unknown")+" · watch only";
  const hi = Math.max(...candles.map(x=>x.h)), lo = Math.min(...candles.map(x=>x.l));
  const span = hi - lo || 1;
  const cw = w / candles.length;
  candles.forEach((bar, i) => {
    const x = i * cw + cw/2;
    const y = v => h - ((v - lo) / span) * (h-12) - 6;
    ctx.strokeStyle = bar.c >= bar.o ? "#3dd68c" : "#ff6b6b";
    ctx.beginPath(); ctx.moveTo(x, y(bar.h)); ctx.lineTo(x, y(bar.l)); ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillRect(x-2, Math.min(y(bar.o), y(bar.c)), 4, Math.max(1, Math.abs(y(bar.c)-y(bar.o))));
  });
}
loadChart();
if (FAILED) document.getElementById("fail").hidden = false;

function loadPaper(){
  const box = document.getElementById("paper");
  if(!box) return;
  fetch("/api/experimental").then(r=>{ if(!r.ok) throw new Error("unauthorized"); return r.json(); }).then(d=>{
    box.textContent = d.rows.length ? d.rows.map(r => [r.type, r.asset, r.side||"", r.entry_price||r.reference||"", r.net||"", r.label].join(" · ")).join("\n") : "No experimental paper records.";
  }).catch(()=>{ box.textContent = "Unlock to view experimental paper records."; });
}
function loadHistory(){
  const box = document.getElementById("historybox");
  if (!AUTHED) { box.textContent = "Unlock to load history."; return; }
  box.textContent = "Loading…";
  fetch("/api/evaluations?limit=20").then(r=>{ if(!r.ok) throw new Error("unauthorized"); return r.json(); }).then(d=>{
    if (!d.rows || !d.rows.length) { box.textContent = "No evaluations yet."; return; }
    box.textContent = d.rows.map(r => {
      const exp = r.experimental ? (" | experimental " + r.experimental.result + " " + r.experimental.classification) : "";
      return [r.asset, r.timeframe, r.result, r.reason, r.fresh?"fresh":"stale", new Date(r.candle_ts_ms||0).toISOString()].join(" · ") + exp;
    }).join("\n");
  }).catch(()=>{ box.textContent = "History unavailable."; });
}
function loadPrefs(){
  if (!AUTHED) return;
  fetch("/api/prefs").then(r=>r.json()).then(p=>{
    document.querySelector("[name=btc]").checked = (p.assets||[]).includes("BTCUSDT");
    document.querySelector("[name=eth]").checked = (p.assets||[]).includes("ETHUSDT");
    document.querySelector("[name=interval]").value = p.interval || "15m";
    document.querySelector("[name=max_alerts]").value = p.max_alerts_per_day || 24;
    document.querySelector("[name=quiet]").value = (p.quiet_hours_utc||[]).join(",");
    document.querySelector("[name=experimental]").checked = !!p.experimental_alerts;
  });
}
document.getElementById("prefsform").onsubmit = (e) => {
  e.preventDefault();
  const assets = [];
  if (document.querySelector("[name=btc]").checked) assets.push("BTCUSDT");
  if (document.querySelector("[name=eth]").checked) assets.push("ETHUSDT");
  const quiet = document.querySelector("[name=quiet]").value.split(",").map(x=>parseInt(x,10)).filter(x=>x>=0 && x<=23);
  fetch("/api/prefs", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({assets, interval:document.querySelector("[name=interval]").value, max_alerts_per_day:Number(document.querySelector("[name=max_alerts]").value), quiet_hours_utc:quiet, experimental_alerts:document.querySelector("[name=experimental]").checked})})
    .then(r=>r.json()).then(p=>{ document.getElementById("prefstatus").textContent = "Saved. Assets: "+(p.assets||[]).join(","); })
    .catch(()=>{ document.getElementById("prefstatus").textContent = "Save failed."; });
};
if (AUTHED) {
  loadHistory(); loadPaper();
  loadPrefs();

  document.getElementById("loginbox").hidden = true;
  document.getElementById("private").hidden = false;
  fetch("/api/state").then(r=>r.json()).then(d=>document.getElementById("state").textContent=JSON.stringify(d,null,2));
  fetch("/api/events").then(r=>r.json()).then(d=>document.getElementById("events").textContent=JSON.stringify(d,null,2));
}
</script>
</body>
</html>"""



if __name__ == "__main__":
    app.run(host=os.environ.get("DESK_BIND", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")))
