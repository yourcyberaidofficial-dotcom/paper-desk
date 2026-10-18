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


@app.get("/api/triad")
def triad():
    from ops.awuru_triad import triad as align
    symbol = request.args.get("symbol", "BTCUSDT")
    data = fetch_klines(symbol, "15m", limit=50)
    bars = [{"high": c["h"], "low": c["l"], "close": c["c"]} for c in data.get("candles") or []]
    states = research_states(bars) if bars else []
    by = {s["strategy"]: s["direction"] for s in states}
    out = align(by.get("E1-donchian-20", "WAIT"), by.get("SMA20-state", "WAIT"), by.get("RSI14-state", "WAIT"), True)
    out["symbol"] = symbol
    out["note"] = "Adapted from Awuru triad. Not a validated edge."
    return jsonify(out)


@app.get("/api/council")
def api_council():
    from ops.council import council
    from ops.e1 import e1_side
    out = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        data = fetch_klines(symbol, "15m", limit=50)
        bars = [{"high": c["h"], "low": c["l"], "close": c["c"]} for c in data.get("candles") or []]
        states = research_states(bars) if bars else []
        by = {s["strategy"]: s["direction"] for s in states}
        candle = (data.get("candles") or [{}])[-1].get("t")
        out.append({
            "symbol": symbol,
            "timeframe": "15m",
            "fresh": True,
            "council": council(by.get("E1-donchian-20", "WAIT"), by.get("SMA20-state", "WAIT"), by.get("RSI14-state", "WAIT"), True, candle),
        })
    try:
        with urllib.request.urlopen("https://xaus.com/api/v1/history", timeout=15) as response:
            points = json.loads(response.read().decode()).get("points") or []
        bars = [{"high": p["h"], "low": p["l"], "close": p["c"]} for p in points]
        side = e1_side(bars)
        last = points[-1] if points else {}
        out.append({
            "symbol": "XAUUSD",
            "timeframe": "1d",
            "fresh": True,
            "limitation": "Daily history only. Intraday gold candles are not available.",
            "council": council(side, "WAIT", "WAIT", True, last.get("d")),
        })
    except Exception as exc:
        out.append({"symbol": "XAUUSD", "timeframe": "1d", "fresh": False, "error": type(exc).__name__})
    return jsonify({"markets": out, "source": "awuru-goal-signal-engine council idea, simplified"})


@app.get("/api/signal-history")
def signal_history():
    from ops.assurance import score_e1
    rows = []
    for row in reversed(ledger.read()):
        if row.get("type") != "evaluation":
            continue
        exp = row.get("experimental") or {}
        result = exp.get("result") or row.get("result")
        scored = score_e1(result, bool(row.get("fresh")), 21)
        rows.append({
            "asset": row.get("asset"),
            "timeframe": row.get("timeframe"),
            "result": result,
            "candle_ts_ms": row.get("candle_ts_ms"),
            "fresh": row.get("fresh"),
            "assurance": scored,
        })
        if len(rows) >= 40:
            break
    return jsonify({"signals": rows, "note": "Assurance is not a win probability."})


@app.get("/api/notify-history")
def notify_history():
    rows = [r for r in reversed(ledger.read()) if r.get("type") == "notify"]
    return jsonify({"deliveries": rows[:30], "note": "Accepted by Telegram is not proof the user read it."})


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
:root{--bg:#070b12;--panel:#101826;--panel2:#0d1420;--line:#1d2a3d;--text:#eef3fb;--muted:#8ea0b8;--blue:#4f7dff;--ok:#2fce8b;--bad:#ff5d6c;--warn:#e0b15a}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--text)}
.shell{display:grid;grid-template-columns:230px 1fr;min-height:100vh}
aside{background:#0b1220;border-right:1px solid var(--line);padding:16px 12px}
.brand{font-weight:700;letter-spacing:.02em;margin-bottom:14px}
aside a{display:flex;align-items:center;gap:8px;color:var(--muted);text-decoration:none;padding:9px 10px;border-radius:10px;margin:2px 0}
aside a.active{background:#17305c;color:#fff}
main{padding:16px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.pills{display:flex;gap:8px;flex-wrap:wrap}
.pill{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:6px 10px;color:var(--muted);font-size:.82rem}
.markets{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:12px}
.card{background:linear-gradient(180deg,#121c2c,#0e1624);border:1px solid var(--line);border-radius:14px;padding:14px}
.price{font-size:1.7rem;font-weight:700;margin:6px 0}
.muted{color:var(--muted);font-size:.82rem}
.row{display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04)}
.long{color:var(--ok)} .short{color:var(--bad)} .wait{color:var(--warn)}
.workspace{display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:12px}
canvas{width:100%;height:360px;background:#0a101a;border-radius:10px}
select,button{background:#152033;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
#menu{display:none;background:#152033;color:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:10px}
@media(max-width:900px){.shell{grid-template-columns:1fr}#menu{display:inline-block}aside{display:none;position:fixed;inset:0 auto 0 0;width:240px;z-index:20}aside.open{display:block}.markets,.workspace{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="shell">
  <button id="menu" aria-label="Open navigation" aria-expanded="false">☰ Menu</button>
  <aside id="nav">
    <div class="brand">Aureon Trading Lab</div>
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
      <div>
        <h1 id="title">Overview</h1>
        <div class="muted">Live market desk. Paper only. Broker off.</div>
      </div>
      <div class="pills"><span class="pill">Engine online</span><span class="pill">Paper only</span><span class="pill">Broker off</span></div>
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
const titles = {"/":"Overview","/signals":"Live Signals","/trading":"Trading Terminal","/strategies":"Strategies","/portfolio":"Portfolio","/risk":"Risk Management","/activity":"Orders & Trade History","/system":"System Status","/settings":"Account & Settings","/research":"Backtesting & Research"};
document.getElementById("title").textContent = titles[path] || "Aureon";
const view = document.getElementById("view");
function cls(d){ return d.includes("LONG")?"long":d.includes("SHORT")?"short":"wait"; }
function label(d){ if (d==="SHORT_BIAS") return "Bearish observation"; if (d==="LONG_BIAS") return "Bullish observation"; if (d==="WAIT") return "No entry yet"; return d; }
function spark(id, candles){
  const c = document.getElementById(id);
  if (!c || !candles.length) return;
  const ctx = c.getContext("2d");
  const w = c.width = 180, h = c.height = 48;
  const vals = candles.slice(-30).map(x => x.c);
  const hi = Math.max(...vals), lo = Math.min(...vals);
  ctx.clearRect(0,0,w,h);
  ctx.strokeStyle = vals[vals.length-1] >= vals[0] ? "#2fce8b" : "#ff5d6c";
  ctx.beginPath();
  vals.forEach((v,i)=>{ const x=i*(w/(vals.length-1||1)); const y=h-((v-lo)/(hi-lo||1))*h; i?ctx.lineTo(x,y):ctx.moveTo(x,y); });
  ctx.stroke();
}
function draw(candles){
  const c = document.getElementById("chart");
  if (!c || !candles.length) return;
  const ctx = c.getContext("2d");
  const w = c.width = c.clientWidth * 2, h = c.height = 720;
  ctx.clearRect(0,0,w,h);
  const slice = candles.slice(-90);
  const hi = Math.max(...slice.map(x=>x.h)), lo = Math.min(...slice.map(x=>x.l));
  const bw = w / slice.length;
  slice.forEach((bar,i)=>{
    const x = i*bw + bw/2;
    const y = p => h - ((p-lo)/(hi-lo||1))*h;
    ctx.strokeStyle = bar.c >= bar.o ? "#2fce8b" : "#ff5d6c";
    ctx.beginPath(); ctx.moveTo(x,y(bar.h)); ctx.lineTo(x,y(bar.l)); ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle;
    const top = Math.min(y(bar.o), y(bar.c)), bot = Math.max(y(bar.o), y(bar.c));
    ctx.fillRect(x-bw*0.22, top, bw*0.44, Math.max(2, bot-top));
  });
}
async function overview(){
  const m = await fetch("/api/markets").then(r=>r.json());
  const cards = await Promise.all(m.markets.map(async item => {
    if (item.id === "GOLD") {
      const g = item.data || {};
      const sig = await fetch("/api/gold/signal").then(r=>r.json()).catch(()=>({}));
      return `<article class="card"><div class="muted">XAUUSD · Gold</div><div class="price">${Number(g.price||0).toLocaleString(undefined,{maximumFractionDigits:2})}</div><canvas id="spark-gold"></canvas><div class="row"><span>E1 daily</span><span class="${cls(sig.result||"")}">${label(sig.result||"unavailable")}</span></div><div class="muted">No entry yet on the latest daily bar. Source ${sig.source_date||""}</div></article>`;
    }
    const s = await fetch(`/api/research-signals?symbol=${item.symbol}&interval=15m`).then(r=>r.json());
    const price = item.data && item.data.close != null ? Number(item.data.close).toLocaleString() : "unavailable";
    const triad = await fetch(`/api/triad?symbol=${item.symbol}`).then(r=>r.json()).catch(()=>({}));
    return `<article class="card"><div class="muted">${item.symbol}</div><div class="price">${price}</div><canvas id="spark-${item.symbol}"></canvas><div class="row"><span>Awuru triad</span><span class="${cls(triad.decision||"")}">${label(triad.decision||"WAIT")}</span></div><div class="muted">${triad.reason||""}</div>${(s.states||[]).map(st => `<div class="row"><span>${st.strategy}</span><span class="${cls(st.direction)}">${label(st.direction)}</span></div>`).join("")}</article>`;
  }));
  const council = await fetch("/api/council").then(r=>r.json()).catch(()=>({markets:[]}));
  const councilHtml = (council.markets||[]).map(m => m.council ? `<div class="row"><span>${m.symbol} ${m.timeframe||""}</span><span>${label(m.council.state)}</span></div><div class="muted">${m.council.reason} ${m.council.next_condition||""} ${m.limitation||""}</div>` : `<div class="row"><span>${m.symbol}</span><span>unavailable</span></div>`).join("");
  view.innerHTML = `<div class="markets">${cards.join("")}</div><article class="card"><h2>Strategy council</h2>${councilHtml}<p class="muted">Adapted from Awuru. Not a validated signal.</p></article><div class="workspace"><article class="card"><h2>Chart</h2><select id="sym"><option>BTCUSDT</option><option>ETHUSDT</option><option>XAUUSD</option></select> <select id="tf"><option>15m</option><option>1h</option><option>4h</option><option>1d</option></select><canvas id="chart"></canvas></article><article class="card"><h2>Live signals</h2><div id="feed">loading</div><p><a href="/signals">View all signals</a></p></article></div>`;
  async function load(){
    const sym = document.getElementById("sym").value, tf = document.getElementById("tf").value;
    if (sym === "XAUUSD") {
      const bars = await fetch("/api/gold/candles").then(r=>r.json());
      draw((bars.candles||[]).map(c => ({o:c.o,h:c.h,l:c.l,c:c.c})));
      return;
    }
    const bars = await fetch(`/api/klines?symbol=${sym}&interval=${tf}`).then(r=>r.json());
    draw(bars.candles||[]);
  }
  document.getElementById("sym").onchange = load;
  document.getElementById("tf").onchange = load;
  load();
  for (const item of m.markets) {
    if (item.id === "GOLD") {
      const g = await fetch("/api/gold/candles").then(r=>r.json());
      spark("spark-gold", (g.candles||[]).map(c=>({c:c.c})));
    } else {
      const bars = await fetch(`/api/klines?symbol=${item.symbol}&interval=15m`).then(r=>r.json());
      spark("spark-"+item.symbol, bars.candles||[]);
    }
  }
  const rows = await Promise.all(["BTCUSDT","ETHUSDT"].map(s => fetch("/api/research-signals?symbol="+s+"&interval=15m").then(r=>r.json())));
  document.getElementById("feed").innerHTML = rows.map(d => d.states.map(s => `<div class="row"><span>${d.symbol} ${s.strategy}</span><span class="${cls(s.direction)}">${s.direction}</span></div>`).join("")).join("");
}
async function signals(){
  const hist = await fetch("/api/signal-history").then(r=>r.json()).catch(()=>({signals:[]}));
  const notes = await fetch("/api/notify-history").then(r=>r.json()).catch(()=>({deliveries:[]}));
  const color = lvl => lvl==="high"?"#43D9A0":lvl==="medium"?"#F5BE4F":lvl==="watch"?"#C4A1FF":"#8ea0b8";
  const rows = (hist.signals||[]).slice(0,20).map(s => `<div class="row"><span>${s.asset} ${s.timeframe}</span><span>${label(s.result||"")}</span><span style="color:${color(s.assurance&&s.assurance.level)}">${(s.assurance&&s.assurance.level)||"none"}</span></div>`).join("");
  const dels = (notes.deliveries||[]).slice(0,10).map(d => `<div class="row"><span>${d.asset}</span><span>${d.status||""}</span><span>${d.telegram_message_id||""}</span></div>`).join("");
  view.innerHTML = `<article class="card"><h2>Signal history</h2>${rows||"<p>No evaluations.</p>"}<p class="muted">Assurance is not a win probability.</p></article><article class="card"><h2>Telegram deliveries</h2>${dels||"<p>None.</p>"}<p class="muted">Accepted by Telegram is not proof you read it.</p></article>`;
}
async function signalsLegacy(){
  const rows = await Promise.all(["BTCUSDT","ETHUSDT"].map(s=>fetch("/api/research-signals?symbol="+s+"&interval=15m").then(r=>r.json())));
  const gold = await fetch("/api/gold/signal").then(r=>r.json()).catch(()=>({}));
  view.innerHTML = rows.map(d => `<article class="card"><h2>${d.symbol}</h2>${d.states.map(s => `<div class="row"><span>${s.strategy}</span><span class="${cls(s.direction)}">${s.direction}</span></div>`).join("")}</article>`).join("") + `<article class="card"><h2>XAUUSD</h2><div class="row"><span>E1 daily</span><span class="${cls(gold.result||"")}">${label(gold.result||"unavailable")}</span></div><div class="muted">Source ${gold.source_date||""}</div></article><article class="card"><h2>Research backtest</h2><button id="backtest">Run research backtest</button><pre id="backtestout">waiting</pre></article>`;
  document.getElementById("backtest").onclick = async () => {
    const box = document.getElementById("backtestout");
    box.textContent = "loading";
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 20000);
    try { box.textContent = JSON.stringify(await fetch("/api/leaderboard", {signal: ctl.signal}).then(r=>r.json()), null, 2); }
    catch(e){ box.textContent = "Research board did not finish. Not validated."; }
    finally { clearTimeout(t); }
  };
}
async function terminal(){ await overview(); }
async function load(){
  if (path === "/" || path === "/trading") return overview();
  if (path === "/signals") return signals();
  if (path === "/portfolio" || path === "/activity") {
    const p = await fetch("/api/paper-status").then(r=>r.json());
    const open = p.open ? `${p.open.asset} ${p.open.side} at ${p.open.entry_price}` : "No open paper position";
    view.innerHTML = `<article class="card"><h2>${titles[path]}</h2><p>${open}</p><p class="muted">${p.label||""}</p></article>`;
    return;
  }
  if (path === "/strategies") {
    view.innerHTML = `<article class="card"><h2>E1 Donchian-20</h2><p>Breakout on the prior 20 bars. Entry is the next open. Exit is the opposite band or 20 bars in the current worker.</p><p class="muted">BTC and ETH 15m. Gold daily.</p></article><article class="card"><h2>SMA20 and RSI14</h2><p>Research observations only. They do not create paper orders.</p></article>`;
    return;
  }
  if (path === "/system") {
    const h = await fetch("/health").then(r=>r.json());
    view.innerHTML = `<article class="card"><h2>System</h2><div class="row"><span>Market data</span><span>${h.market_data}</span></div><div class="row"><span>Strategy</span><span>${h.strategy_status}</span></div><div class="row"><span>Broker</span><span>${h.broker}</span></div></article>`;
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
