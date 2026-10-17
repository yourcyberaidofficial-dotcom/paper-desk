"""Aureon Trading Lab dashboard. Paper only. Public health is coarse."""

import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, session, redirect, make_response

from ops.auth import RateLimit, api_token, require_token
from ops.engine import PaperEngine
from ops.ledger import Ledger
from ops.signals import research_states
from ops.paper_candidates import candidates
from ops.experimental import ExperimentalBook
from pathlib import Path
from ops.replay import replay, yesterday_ms, period
from ops.leaderboard import leaderboard
from ops.deepboard import deep_board
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


@app.get("/api/deep-board")
def deep_board_api():
    try:
        return jsonify(deep_board())
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 502


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


@app.get("/api/paper-status")
def paper_status():
    book = ExperimentalBook(Path("/app/data/paper/experimental.jsonl"))
    return jsonify({
        "open": book.open_position(),
        "rows": book.read()[-10:],
        "label": "EXPERIMENTAL PAPER — NOT VALIDATED",
        "broker": False,
    })


@app.get("/api/research-signals")
def research_signals():
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "15m")
    data = fetch_klines(symbol, interval, limit=50)
    bars = [{"high": c["h"], "low": c["l"], "close": c["c"]} for c in data.get("candles") or []]
    candles = data.get("candles") or []
    last = candles[-1] if candles else {}
    steps = {"15m": 15 * 60 * 1000, "1h": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000}
    close_ms = last.get("t") + steps.get(interval, 0) if last else None
    now_ms = int(time.time() * 1000)
    fresh = bool(close_ms and now_ms - close_ms < 2 * steps.get(interval, 15 * 60 * 1000))
    return jsonify({
        "symbol": symbol,
        "interval": interval,
        "production": "WAIT_DEFAULT",
        "validated": False,
        "kind": "research_observation",
        "fresh": fresh,
        "source_candle_close_ms": close_ms,
        "states": research_states(bars) if bars else [],
        "paper_candidates": candidates(research_states(bars) if bars else [], symbol, close_ms),
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
@app.get("/signals")
@app.get("/trading")
@app.get("/strategies")
@app.get("/indicators")
@app.get("/research")
@app.get("/portfolio")
@app.get("/risk")
@app.get("/activity")
@app.get("/system")
@app.get("/settings")
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
:root{--bg:#111318;--panel:#1a1e27;--line:#2a3140;--text:#e7ebf3;--muted:#9aa3b5;--accent:#8aa4ff;--ok:#3dd68c;--bad:#ff6b6b;--warn:#f5c451}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--text)}
.shell{display:grid;grid-template-columns:220px 1fr;min-height:100vh}
aside{background:#151922;border-right:1px solid var(--line);padding:16px}
aside a{display:block;color:var(--text);text-decoration:none;padding:8px 10px;border-radius:8px;margin:2px 0}
aside a.active{background:#24304a;color:var(--accent)}
main{padding:16px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}
.muted{color:var(--muted);font-size:.85rem}
.warn{color:var(--warn)} .ok{color:var(--ok)} .bad{color:var(--bad)}
pre{white-space:pre-wrap;word-break:break-word;font-size:.8rem}
button{background:var(--accent);color:#111;border:0;border-radius:8px;padding:8px 12px;font-weight:600}
@media(max-width:800px){.shell{grid-template-columns:1fr} aside{border-right:0;border-bottom:1px solid var(--line)}}
</style>
</head>
<body>
<div class="shell">
  <aside>
    <strong>Aureon</strong>
    <div class="muted">Trading Lab</div>
    <a href="/" data-path="/">Overview</a>
    <a href="/signals" data-path="/signals">Live Signals</a>
    <a href="/trading" data-path="/trading">Live Trading Desk</a>
    <a href="/strategies" data-path="/strategies">Strategy Lab</a>
    <a href="/indicators" data-path="/indicators">Indicators</a>
    <a href="/research" data-path="/research">Backtesting & Research</a>
    <a href="/portfolio" data-path="/portfolio">Paper Portfolio</a>
    <a href="/risk" data-path="/risk">Risk Management</a>
    <a href="/activity" data-path="/activity">Activity & Trade History</a>
    <a href="/system" data-path="/system">System Health</a>
    <a href="/settings" data-path="/settings">Settings & Data Sources</a>
  </aside>
  <main>
    <header>
      <h1 id="title">Overview</h1>
      <span class="badge warn">WAIT_DEFAULT · paper only</span>
    </header>
    <section id="view" class="grid"></section>
  </main>
</div>
<script>
const path = location.pathname;
document.querySelectorAll("aside a").forEach(a => { if (a.dataset.path === path) a.classList.add("active"); });
const titles = {"/":"Overview","/signals":"Live Signals","/trading":"Live Trading Desk","/strategies":"Strategy Lab","/indicators":"Indicators","/research":"Backtesting & Research","/portfolio":"Paper Portfolio","/risk":"Risk Management","/activity":"Activity & Trade History","/system":"System Health","/settings":"Settings & Data Sources"};
document.getElementById("title").textContent = titles[path] || "Aureon";
const view = document.getElementById("view");
function card(title, body){ return `<article class="card"><h2>${title}</h2>${body}</article>`; }
async function load(){
  if (path === "/signals" || path === "/") {
    const rows = await Promise.all(["BTCUSDT","ETHUSDT"].map(s => fetch("/api/research-signals?symbol="+s+"&interval=15m").then(r=>r.json())));
    const paper = await fetch("/api/paper-status").then(r=>r.json()).catch(()=>({}));
    const sig = rows.map(d => `<div><strong>${d.symbol}</strong> fresh=${d.fresh}<br>${d.states.map(s => s.strategy+" "+s.direction).join("<br>")}</div>`).join("");
    if (path === "/") {
      view.innerHTML = card("Market", "BTC and ETH research outputs are live.") + card("Live Signals", sig + '<p><a href="/signals">View all signals</a></p>') + card("Paper", "<pre>"+JSON.stringify(paper.open||"no open position",null,2)+"</pre>");
    } else {
      view.innerHTML = card("Latest evaluations", sig) + card("Paper state", "<pre>"+JSON.stringify(paper,null,2)+"</pre>");
    }
  } else if (path === "/portfolio" || path === "/trading" || path === "/activity") {
    const paper = await fetch("/api/paper-status").then(r=>r.json());
    view.innerHTML = card(titles[path], "<pre>"+JSON.stringify(paper,null,2)+"</pre>");
  } else if (path === "/system") {
    const h = await fetch("/health").then(r=>r.json());
    view.innerHTML = card("Health", "<pre>"+JSON.stringify(h,null,2)+"</pre>");
  } else if (path === "/research") {
    view.innerHTML = card("Research", "Use the existing replay and leaderboard APIs. Board is NOT VALIDATED.") + card("Actions", '<button onclick="loadBoard()">Load leaderboard</button><pre id="board">waiting</pre>');
  } else if (path === "/settings") {
    view.innerHTML = card("Data sources", "BTC/ETH from Binance public. Gold NOT_CONFIGURED. Broker disabled.");
  } else {
    view.innerHTML = card(titles[path], "Connected to the existing desk. No fabricated metrics.");
  }
}
async function loadBoard(){ const d = await fetch("/api/leaderboard").then(r=>r.json()); document.getElementById("board").textContent = JSON.stringify(d,null,2); }
load();
</script>
</body>
</html>
"""
