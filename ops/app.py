"""Aureon Trading Lab dashboard. Paper only. Public health is coarse."""

import json
import os
import time
import urllib.request
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


def _gold():
    try:
        with urllib.request.urlopen("https://xaus.com/api/v1/spot", timeout=10) as response:
            spot = json.loads(response.read().decode())
        price = spot.get("spot_usd_oz")
        return {"symbol": "XAUUSD", "source": "xaus.com", "kind": "spot", "price": price, "fresh": price is not None, "note": "Gold spot USD/oz. Not a crypto exchange candle."}
    except Exception as exc:
        return {"symbol": "XAUUSD", "source": "xaus.com", "status": "error", "error": type(exc).__name__, "fresh": False}


@app.get("/api/markets")
def markets():
    snap = market_snapshot()
    return jsonify({
        "markets": [
            {"id": "BTC", "symbol": "BTCUSDT", "status": "configured", "data": snap.get("BTCUSDT")},
            {"id": "ETH", "symbol": "ETHUSDT", "status": "configured", "data": snap.get("ETHUSDT")},
            {"id": "GOLD", "symbol": "XAUUSD", "status": "configured", "source": "xaus.com", "kind": "spot", "data": _gold()},
        ],
        "broker": False,
        "production": "WAIT_DEFAULT",
    })


@app.get("/api/gold/signal")
def gold_signal():
    try:
        with urllib.request.urlopen("https://xaus.com/api/v1/history", timeout=15) as response:
            data = json.loads(response.read().decode())
        points = data.get("points") or []
        bars = [{"high": p["h"], "low": p["l"], "close": p["c"]} for p in points]
        from ops.e1 import e1_side
        side = e1_side(bars)
        last = points[-1] if points else {}
        return jsonify({"symbol": "XAUUSD", "interval": "1d", "strategy": "E1-donchian-20", "result": side, "source_date": last.get("d"), "close": last.get("c"), "validated": False, "note": "Evaluated on daily gold history. Not a paper order."})
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 502


@app.get("/api/gold/candles")

def gold_candles():
    try:
        with urllib.request.urlopen("https://xaus.com/api/v1/history", timeout=15) as response:
            data = json.loads(response.read().decode())
        points = data.get("points") or []
        candles = [{"t": p.get("d"), "o": p.get("c"), "h": p.get("h"), "l": p.get("l"), "c": p.get("c")} for p in points[-120:]]
        return jsonify({"symbol": "XAUUSD", "interval": "1d", "source": "xaus.com", "kind": "daily_spot_history", "count": len(points), "candles": candles, "note": "Daily gold history. Open is not supplied, so open is shown as close."})
    except Exception as exc:
        return jsonify({"error": type(exc).__name__}), 502


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
:root{--bg:#07090d;--panel:#121821;--line:#243041;--text:#f5f7fb;--muted:#93a0b5;--accent:#9db7ff;--ok:#35d39a;--bad:#ff6b78;--warn:#f0c36a}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--text)}
.shell{display:grid;grid-template-columns:240px 1fr;min-height:100vh}
#menu{display:none;background:#1b2130;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:12px}
aside{background:#10141b;border-right:1px solid var(--line);padding:18px 12px}
aside strong{font-size:1.05rem;letter-spacing:.02em}
aside a{display:block;color:var(--muted);text-decoration:none;padding:9px 12px;border-radius:8px;margin:3px 0;font-size:.92rem}
aside a.active{background:#1d2636;color:var(--text)}
main{padding:18px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
h1{margin:0;font-size:1.35rem}
.grid{display:grid;grid-template-columns:minmax(0,2.2fr) minmax(280px,1fr);gap:14px}
.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.price{font-size:1.6rem;margin:6px 0}
@media(max-width:900px){.grid3{grid-template-columns:1fr}}
.card{background:linear-gradient(180deg,#151c27,#10161f);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 8px 24px rgba(0,0,0,.25)}
.gold{border-color:#6b5420}
.muted{color:var(--muted);font-size:.84rem}
.row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)}
.long{color:var(--ok)} .short{color:var(--bad)} .wait{color:var(--warn)}
canvas{width:100%;height:420px;background:#0d1118;border-radius:10px;margin-top:10px}
select{background:#1b2130;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
@media(max-width:900px){.shell{grid-template-columns:1fr}#menu{display:inline-block}aside{display:none;position:fixed;inset:0 auto 0 0;width:240px;z-index:20}aside.open{display:block}.grid,.grid3{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="shell">
  <button id="menu" aria-label="Open navigation" aria-expanded="false">☰</button>
  <aside id="nav">
    <strong>Aureon</strong>
    <div class="muted">Trading Lab</div>
    <a href="/" data-path="/">Overview</a>
    <a href="/trading" data-path="/trading">Trading Terminal</a>
    <a href="/signals" data-path="/signals">Live Signals</a>
    <a href="/strategies" data-path="/strategies">Strategies</a>
    <a href="/portfolio" data-path="/portfolio">Portfolio</a>
    <a href="/activity" data-path="/activity">Orders & Trade History</a>
    <a href="/research" data-path="/research">Backtesting & Research</a>
    <a href="/risk" data-path="/risk">Risk Management</a>
    <a href="/system" data-path="/system">System Status</a>
    <a href="/settings" data-path="/settings">Account & Settings</a>
  </aside>
  <main>
    <header>
      <h1 id="title">Overview</h1>
      <span class="warn">WAIT_DEFAULT · paper only · broker off</span>
    </header>
    <section id="view"></section>
  </main>
</div>
<script>
const menu = document.getElementById("menu");
const nav = document.getElementById("nav");
menu.onclick = () => { const open = nav.classList.toggle("open"); menu.setAttribute("aria-expanded", open); };
document.querySelectorAll("#nav a").forEach(a => a.onclick = () => nav.classList.remove("open"));
const path = location.pathname;
document.querySelectorAll("aside a").forEach(a => { if (a.dataset.path === path) a.classList.add("active"); });
const titles = {"/":"Overview","/signals":"Live Signals","/trading":"Trading Terminal","/strategies":"Strategies","/indicators":"Indicators","/research":"Backtesting & Research","/portfolio":"Portfolio","/risk":"Risk Management","/activity":"Orders & Trade History","/system":"System Status","/settings":"Account & Settings"};
document.getElementById("title").textContent = titles[path] || "Aureon";
const view = document.getElementById("view");
function draw(candles){
  const c = document.getElementById("chart");
  if (!c || !candles.length) return;
  const ctx = c.getContext("2d");
  const w = c.width = c.clientWidth * 2, h = c.height = 720;
  ctx.clearRect(0,0,w,h);
  const slice = candles.slice(-80);
  const hi = Math.max(...slice.map(x=>x.h)), lo = Math.min(...slice.map(x=>x.l));
  const bw = w / slice.length;
  slice.forEach((bar,i)=>{
    const x = i*bw + bw/2;
    const y = p => h - ((p-lo)/(hi-lo||1))*h;
    ctx.strokeStyle = bar.c >= bar.o ? "#3dd68c" : "#ff6b6b";
    ctx.beginPath(); ctx.moveTo(x,y(bar.h)); ctx.lineTo(x,y(bar.l)); ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle;
    const top = Math.min(y(bar.o), y(bar.c)), bot = Math.max(y(bar.o), y(bar.c));
    ctx.fillRect(x-bw*0.25, top, bw*0.5, Math.max(2, bot-top));
  });
}
async function terminal(){
  view.innerHTML = `<div class="grid"><article class="card"><h2>Chart</h2><select id="sym"><option>BTCUSDT</option><option>ETHUSDT</option><option>XAUUSD</option></select> <select id="tf"><option>15m</option><option>1h</option><option>4h</option><option>1d</option></select><canvas id="chart"></canvas></article><article class="card"><h2>Strategies</h2><pre id="states">loading</pre><p><a href="/signals">Open Live Signals</a></p></article></div>`;
  async function load(){
    const sym = document.getElementById("sym").value, tf = document.getElementById("tf").value;
    if (sym === "XAUUSD") {
      const bars = await fetch("/api/gold/candles").then(r=>r.json());
      draw((bars.candles||[]).map(c => ({o:c.o,h:c.h,l:c.l,c:c.c})));
      document.getElementById("states").textContent = "Gold uses daily spot history. E1 is not evaluated on gold yet.";
      return;
    }
    const bars = await fetch(`/api/klines?symbol=${sym}&interval=${tf}`).then(r=>r.json());
    draw(bars.candles||[]);
    const s = await fetch(`/api/research-signals?symbol=${sym}&interval=${tf}`).then(r=>r.json());
    document.getElementById("states").textContent = (s.states||[]).map(x=>x.strategy+" "+x.direction).join(" | ")+" fresh="+s.fresh;
  }
  document.getElementById("sym").onchange = load;
  document.getElementById("tf").onchange = load;
  load();
}

async function overview(){
  const m = await fetch("/api/markets").then(r=>r.json());
  const cards = await Promise.all(m.markets.map(async item => {
    if (item.id === "GOLD") {
      const g = item.data || {};
      const sig = await fetch("/api/gold/signal").then(r=>r.json()).catch(()=>({}));
      return `<article class="card gold"><h2>GOLD <span class="muted">XAUUSD</span></h2><p class="price">${g.price || "unavailable"}</p><div class="row"><span>E1 daily</span><span class="${(sig.result||"").includes("LONG")?"long":(sig.result||"").includes("SHORT")?"short":"wait"}">${sig.result || "unavailable"}</span></div><p class="muted">Source ${sig.source_date || ""} · close ${sig.close || ""} · not a paper order</p></article>`;
    }
    if (item.status !== "configured") {
      return `<article class="card"><h2>GOLD</h2><p class="wait">NOT_CONFIGURED</p></article>`;
    }
    const s = await fetch(`/api/research-signals?symbol=${item.symbol}&interval=15m`).then(r=>r.json());
    const price = item.data && item.data.close != null ? item.data.close : "unavailable";
    return `<article class="card"><h2>${item.id} <span class="muted">${item.symbol}</span></h2><p class="price">${price}</p><p class="muted">fresh=${item.data && item.data.fresh}</p>${(s.states||[]).map(st => `<div class="row"><span>${st.strategy}</span><span class="${st.direction.includes("LONG")?"long":st.direction.includes("SHORT")?"short":"wait"}">${st.direction}</span></div>`).join("")}<p><a href="/trading">Open terminal</a></p></article>`;
  }));
  view.innerHTML = `<div class="grid3">${cards.join("")}</div><p class="muted">Production ${m.production}. Broker ${m.broker ? "on" : "off"}.</p>`;
}
async function signals(){
  const rows = await Promise.all(["BTCUSDT","ETHUSDT"].map(s=>fetch("/api/research-signals?symbol="+s+"&interval=15m").then(r=>r.json())));
  view.innerHTML = rows.map(d => `<article class="card"><h2>${d.symbol} ${d.interval}</h2><p class="muted">fresh=${d.fresh}</p>${d.states.map(s => `<div class="row"><span>${s.strategy}</span><span class="${s.direction.includes("LONG")?"long":s.direction.includes("SHORT")?"short":"wait"}">${s.direction}</span></div>`).join("")}<p><a href="/trading">Open in terminal</a></p></article>`).join("") + `<article class="card"><h2>Backtest</h2><button id="backtest">Run research backtest</button><p class="muted">Loads the existing leaderboard. Not validated.</p><pre id="backtestout">waiting</pre></article>`;
document.getElementById("backtest").onclick = async () => {
  const box = document.getElementById("backtestout");
  box.textContent = "loading research board";
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 20000);
  try {
    const d = await fetch("/api/leaderboard", {signal: ctl.signal}).then(r=>r.json());
    box.textContent = JSON.stringify(d, null, 2);
  } catch (e) {
    box.textContent = "Backtest request did not finish. Research board is still NOT VALIDATED.";
  } finally { clearTimeout(t); }
};
}
async function load(){
  if (path === "/trading") return terminal();
  if (path === "/") return overview();
  if (path === "/signals") return signals();
  if (path === "/portfolio" || path === "/activity") {
    const p = await fetch("/api/paper-status").then(r=>r.json());
    const open = p.open ? `${p.open.asset} ${p.open.side} at ${p.open.entry_price}` : "No open paper position";
    view.innerHTML = `<article class="card"><h2>${titles[path]}</h2><p>${open}</p><p class="muted">${p.label||""}</p></article>`;
    return;
  }
  if (path === "/system") {
    const h = await fetch("/health").then(r=>r.json());
    view.innerHTML = `<article class="card"><h2>System</h2><div class="row"><span>Market data</span><span>${h.market_data}</span></div><div class="row"><span>Strategy</span><span>${h.strategy_status}</span></div><div class="row"><span>Broker</span><span>${h.broker}</span></div></article>`;
    return;
  }
  if (path === "/strategies") {
    view.innerHTML = `<article class="card"><h2>E1 Donchian-20</h2><p>Breakout on the prior 20 bars. Entry is the next open. Exit is the opposite band or 20 bars in the current worker.</p><p class="muted">BTC and ETH. Not yet evaluated on gold.</p></article><article class="card"><h2>SMA20 and RSI14</h2><p>Research observations only. They do not create paper orders.</p></article>`;
    return;
  }
  if (path === "/settings") {
    view.innerHTML = `<article class="card"><h2>Settings</h2><p>Gold NOT_CONFIGURED. Broker disabled. Production WAIT_DEFAULT.</p></article>`;
    return;
  }
  view.innerHTML = `<article class="card"><h2>${titles[path]||"Aureon"}</h2><p>Connected to the live desk. No fabricated metrics.</p></article>`;
}
load();
</script>
</body>
</html>
"""




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
