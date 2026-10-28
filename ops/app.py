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
from ops.experimental import ExperimentalBook, present_book
from pathlib import Path
from ops.replay import replay, yesterday_ms, period
from ops.leaderboard import leaderboard
from ops.deepboard import deep_board
from ops.market import snapshot as market_snapshot, fetch_klines
from ops.notify import send_alert
from ops.strategy import WaitStrategy
from ops.build_id import build_commit, shadow_enabled
from ops.worker import Worker
import threading

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "data" / "paper" / "ledger.jsonl"
STARTED = time.time()
LIMITER = RateLimit(60)
_FEED_CACHE = {}

app = Flask(__name__)
app.secret_key = os.environ.get("DESK_SESSION_SECRET") or api_token() or "disabled"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("DESK_COOKIE_SECURE", "0") == "1",
)
ledger = Ledger(LEDGER_PATH)
engine = PaperEngine(ledger, WaitStrategy())
worker = Worker(ledger, LEDGER_PATH.parent / "prefs.json", shadow_path=ROOT / "data" / "shadow" / "observations.jsonl")


SESSION_TTL = 12 * 3600

def _owner_ok():
    exp = session.get("exp")
    return bool(session.get("ok") and exp and time.time() <= exp)


def _user_ok():
    exp = session.get("user_exp")
    return bool(session.get("user_id") and exp and time.time() <= exp)


def _gate():
    return _owner_ok() or _user_ok()


ALLOWED_NEXT = {
    "/overview", "/signals", "/trading", "/strategies", "/indicators",
    "/research", "/portfolio", "/risk", "/activity", "/system", "/settings", "/onboarding",
    "/scanner", "/learn", "/plan", "/notifications",
}


def _safe_next(value):
    if value in ALLOWED_NEXT:
        return value
    return "/overview"


def _start_user_session(user):
    session["user_id"] = user["id"]
    session["user_exp"] = time.time() + SESSION_TTL


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
    if session.get("ok") and not _owner_ok():
        session.pop("ok", None)
        session.pop("exp", None)
    if session.get("user_id") and not _user_ok():
        session.pop("user_id", None)
        session.pop("user_exp", None)

@app.get("/health")
def health():
    markets = market_snapshot()
    report = _market_report(markets)
    promoted = _promotion_state()
    beat = worker.last_beat_ms or 0
    return jsonify({
        "status": "ok" if report["BTCUSDT"]["status"] == "fresh" and report["ETHUSDT"]["status"] == "fresh" else "degraded",
        "process": "ok",
        "uptime_s": int(time.time() - STARTED),
        "market_data": report,
        "notification": {
            "pipeline": "blocked" if promoted == "empty" else "armed_for_promoted_only",
            "reason": "promotion_registry_empty" if promoted == "empty" else "promotion_record_present",
            "global_chat_used_for_trades": False,
        },
        "ledger": "ok" if LEDGER_PATH.parent.exists() else "missing",
        "strategy": engine.strategy.name,
        "strategy_status": "WAIT_DEFAULT" if promoted == "empty" else "PROMOTION_RECORD_PRESENT",
        "promotion_registry": promoted,
        "build_commit": build_commit(),
        "shadow": "enabled" if shadow_enabled() else "disabled",
        "paper_only": True,
        "broker": False,
        "worker": {
            "last_beat_ms": beat or None,
            "heartbeat_age_ms": None if not beat else max(0, int(time.time() * 1000) - beat),
            "status": "unknown" if not beat else "beating",
        },
    })


def _promotion_state():
    from ops.delivery import load_promotions
    return "present" if load_promotions() else "empty"


def _market_report(snapshot):
    out = {}
    now_ms = int(time.time() * 1000)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        row = (snapshot or {}).get(symbol) or {}
        close_ms = row.get("close_time_ms")
        checked = row.get("checked_at_ms") or now_ms
        if not isinstance(close_ms, (int, float)):
            status = "unknown"
        elif checked - close_ms <= 15 * 60 * 1000 and close_ms < checked:
            status = "fresh"
        else:
            status = "stale"
        out[symbol] = {"status": status, "last_close_time_ms": close_ms, "source": row.get("source") or "unknown"}
    out["XAUUSD"] = {"status": "not_checked", "reason": "health_does_not_treat_spot_as_a_candle", "source": "none"}
    return out


@app.get("/version")
def version():
    return jsonify({
        "build_commit": build_commit(),
        "strategy_status": "WAIT_DEFAULT",
        "paper_only": True,
        "broker": False,
        "shadow": "enabled" if shadow_enabled() else "disabled",
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
        return jsonify({"error": "unavailable"}), 502


@app.get("/api/leaderboard")
def leaderboard_api():
    try:
        return jsonify(leaderboard())
    except Exception as exc:
        return jsonify({"error": "unavailable"}), 502


@app.get("/api/period")
def period_api():
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "15m")
    at = request.args.get("at")
    at_ms = yesterday_ms() if not at or at == "yesterday" else int(at)
    try:
        return jsonify(period(symbol, interval, at_ms))
    except Exception as exc:
        return jsonify({"error": "unavailable"}), 502


@app.get("/api/replay")
def replay_api():
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "15m")
    at = request.args.get("at")
    at_ms = yesterday_ms() if not at or at == "yesterday" else int(at)
    try:
        return jsonify(replay(symbol, interval, at_ms))
    except Exception as exc:
        return jsonify({"error": "unavailable"}), 502


@app.get("/api/paper-status")
def paper_status():
    candidates = [
        Path("/app/data/paper/experimental.jsonl"),
        Path(os.environ.get("AUREON_DATA", "data")) / "paper" / "experimental.jsonl",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            book = ExperimentalBook(path)
            rows = book.read()
            shown = present_book(rows, book.open_position())
            return jsonify({
                "open": shown["open"],
                "rows": shown["trades"][-10:],
                "observations": shown["observations"][-8:],
                "label": "Research notes are not orders.",
                "broker": False,
                "note": "A directional research observation is not a holding or an order.",
            })
        except Exception as exc:
            return jsonify({"open": None, "rows": [], "label": "Research notes are not orders.", "broker": False, "error": "unavailable"})
    return jsonify({"open": None, "rows": [], "label": "Research notes are not orders.", "broker": False})


def _remember(key, ttl, loader):
    now = time.time()
    hit = _FEED_CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = loader()
    _FEED_CACHE[key] = (now, value)
    return value


def _gold_bars(interval, now_ms):
    from ops.bars import aggregate
    from ops.feeds import xaus_chart

    interval = interval if interval in {"15m", "1h", "4h", "1d"} else "1h"
    if interval == "4h":
        base = _remember(("xaus", "1h"), 60, lambda: xaus_chart("1h", now_ms))
        if not base.get("ok"):
            return base
        return {
            "ok": True,
            "bars": aggregate(base.get("bars") or [], "1h", "4h"),
            "provider": "xaus.com",
            "quote_semantics": "ohlc_not_bid_ask",
            "partial_dropped": base.get("partial_dropped"),
            "interval": "4h",
        }
    series = _remember(("xaus", interval), 60, lambda: xaus_chart(interval, now_ms))
    series = dict(series)
    series["interval"] = interval
    return series


def _engine_view(symbol, now_ms=None):
    from ops.engine_eval import evaluate_snapshot, headline
    from ops.feeds import binance_bars

    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    empty = {
        "symbol": symbol,
        "production": "WAIT_DEFAULT",
        "approved": False,
        "broker": False,
        "validated": False,
        "rows": [],
    }
    if symbol == "XAUUSD":
        series = _gold_bars("1h", now_ms)
        higher = _gold_bars("4h", now_ms) if series.get("ok") else {"bars": []}
        if not series.get("ok") or not series.get("bars"):
            empty.update(state="DATA_UNAVAILABLE", reason=series.get("reason") or "GOLD_FEED_UNAVAILABLE", interval="1h")
            return empty
        bars, higher_bars, interval = series["bars"], higher.get("bars") or [], "1h"
    elif symbol in {"BTCUSDT", "ETHUSDT"}:
        entry = _remember(
            ("binance", symbol, "15m"),
            30,
            lambda: binance_bars(symbol, "15m", now_ms - 160 * 15 * 60 * 1000, now_ms, now_ms),
        )
        higher = _remember(
            ("binance", symbol, "1h"),
            30,
            lambda: binance_bars(symbol, "1h", now_ms - 90 * 60 * 60 * 1000, now_ms, now_ms),
        )
        if not entry.get("ok") or not higher.get("ok") or not entry.get("bars"):
            empty.update(state="DATA_UNAVAILABLE", reason=entry.get("reason") or higher.get("reason") or "DATA_UNAVAILABLE", interval="15m")
            return empty
        bars, higher_bars, interval = entry["bars"], higher.get("bars") or [], "15m"
    else:
        empty.update(state="DATA_UNAVAILABLE", reason="symbol_not_allowed")
        return empty
    rows = evaluate_snapshot(symbol, bars, higher_bars, now_ms, interval)
    head = headline(rows)
    empty.update(
        interval=interval,
        state=head.get("state"),
        reason=head.get("reason"),
        direction=head.get("direction"),
        strategy=head.get("strategy"),
        headline=head,
        rows=rows,
        quote_semantics=bars[-1].get("quote_semantics"),
        bars=len(bars),
    )
    return empty


def _gold():
    from ops.feeds import xaus_spot
    from ops.gold_cache import load, save
    try:
        spot = _remember(("xaus", "spot"), 15, xaus_spot)
    except Exception as exc:
        spot = {"ok": False, "reason": type(exc).__name__}
    if spot.get("ok") and spot.get("price") is not None:
        payload = {
            "symbol": "XAUUSD",
            "instrument": "XAUUSD_SPOT",
            "source": "xaus.com",
            "kind": "indicative_spot",
            "quote_semantics": "indicative_mid",
            "price": spot.get("price"),
            "fresh": bool(spot.get("fresh")),
            "market_open": spot.get("market_open"),
            "updated_at": spot.get("updated_at"),
            "not_bid_ask": True,
            "not_a_candle": True,
            "note": "Indicative mid-market USD/oz. Not an executable bid or ask and not a candle.",
        }
        save({"spot": payload})
        return payload
    cached = (load() or {}).get("spot")
    if cached:
        cached = dict(cached)
        cached["fresh"] = False
        cached["quote_semantics"] = "indicative_mid"
        cached["note"] = "Provider limited. Last known indicative mid, not a live quote."
        return cached
    return {
        "symbol": "XAUUSD",
        "source": "xaus.com",
        "status": "error",
        "error": spot.get("reason") or "GOLD_FEED_UNAVAILABLE",
        "fresh": False,
        "quote_semantics": "indicative_mid",
        "note": "GOLD_FEED_UNAVAILABLE",
    }


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


@app.post("/api/register")
def register():
    from ops.users import register as create_user
    body = request.json or {}
    user = create_user(str(body.get("name") or ""), str(body.get("password") or ""))
    if not user:
        return jsonify({"error": "invalid or duplicate"}), 400
    _start_user_session(user)
    return jsonify({"ok": True, "id": user["id"], "name": user["name"]})


@app.post("/api/login")
def user_login():
    from ops.users import login as check_login
    body = request.json or {}
    user = check_login(str(body.get("name") or ""), str(body.get("password") or ""))
    if not user:
        return jsonify({"error": "invalid"}), 401
    _start_user_session(user)
    return jsonify({"ok": True, "id": user["id"]})


@app.post("/api/logout")
def user_logout():
    session.clear()
    return jsonify({"ok": True})


@app.post("/api/profile")
def save_profile():
    from ops.users import update_profile
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    user = update_profile(user_id, request.json or {})
    if not user:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "profile": user.get("profile")})


@app.post("/api/telegram/link")
def telegram_link():
    from ops.users import start_telegram_link
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    body = request.json or {}
    result = start_telegram_link(user_id)
    if not result:
        return jsonify({"error": "not_found"}), 404
    return jsonify(result)


@app.get("/api/registry")
def registry_api():
    if not _gate():
        return jsonify({"error": "unauthorized"}), 401
    from ops.registry import catalog
    return jsonify(catalog())


@app.get("/api/plan")
def plan_get():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.plan import normalize, week_status
    from ops.profiles import risk_cap
    from ops.users import get
    user = get(user_id) or {}
    profile = user.get("profile") or {}
    cap = risk_cap(profile.get("signal_style"))
    plan = user.get("plan") or normalize({}, {}, cap)
    return jsonify({"plan": plan, "week": week_status(plan, int(time.time() * 1000)), "style_cap": cap, "currency": profile.get("currency")})


@app.post("/api/plan")
def plan_save():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.users import save_plan
    saved = save_plan(user_id, request.json or {})
    if not saved:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "plan": saved.get("plan"), "notes": saved.get("plan_notes") or []})


@app.post("/api/size")
def size_quote():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.plan import propose_size
    from ops.users import get
    user = get(user_id) or {}
    profile = user.get("profile") or {}
    plan = user.get("plan") or {}
    risk = plan.get("risk_per_trade_percent")
    if risk is None:
        risk = profile.get("max_risk_pct")
    result = propose_size(profile.get("capital"), risk, (request.json or {}).get("entry"), (request.json or {}).get("stop"))
    result["recorded"] = False
    return jsonify(result)


@app.post("/api/telegram/update")
def telegram_update():
    from ops.telegram_in import apply_update
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not secret or request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return jsonify({"ok": True, "ignored": True, "reason": "polling_mode"})
    result = apply_update(request.json or {})
    return jsonify({"ok": bool(result.get("ok")), "ignored": bool(result.get("ignored") or result.get("duplicate")), "error": result.get("error")})


@app.post("/api/telegram/unlink")
def telegram_unlink():
    from ops.users import unlink_telegram
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    ok = unlink_telegram(user_id)
    return jsonify({"ok": ok})


@app.post("/api/telegram/confirm")
def telegram_confirm():
    from ops.users import confirm_telegram_link
    body = request.json or {}
    result = confirm_telegram_link(str(body.get("token") or ""), str(body.get("telegram_id") or ""))
    if not result or result.get("error"):
        return jsonify(result or {"error": "failed"}), 400
    return jsonify(result)


@app.post("/api/prefs")
def save_prefs():
    from ops.users import update_prefs
    user_id = session.get("user_id")
    exp = session.get("user_exp")
    if not user_id or not exp or time.time() > exp:
        return jsonify({"error": "unauthorized"}), 401
    user = update_prefs(user_id, request.json or {})
    if not user:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "prefs": user.get("prefs"), "profile": user.get("profile"), "telegram_verified": bool((user.get("telegram") or {}).get("verified"))})


@app.get("/api/me")
def me():
    from ops.users import get
    user_id = session.get("user_id")
    exp = session.get("user_exp")
    if not user_id or not exp or time.time() > exp:
        return jsonify({"error": "unauthorized"}), 401
    user = get(user_id)
    if not user:
        return jsonify({"error": "not_found"}), 404
    telegram = user.get("telegram") or {}
    return jsonify({
        "id": user["id"],
        "name": user["name"],
        "telegram_linked": bool(telegram),
        "telegram_verified": bool(telegram.get("verified")),
        "prefs": user.get("prefs"),
        "profile": user.get("profile") or {},
    })


@app.get("/api/profiles")
def profiles_api():
    from ops.profiles import CURRENCIES, catalog
    return jsonify({
        "source": "awuru-goal-signal-engine accounts_personas.py",
        "excluded": "Titan Structured is a later fourth persona and is not one of the original three.",
        "note": "Profiles change research eligibility and risk posture only. Production remains WAIT_DEFAULT. No currency conversion is performed.",
        "profiles": catalog(),
        "currencies": list(CURRENCIES),
        "conversion": False,
    })


def _research_votes(symbol):
    e1 = sma = rsi = "WAIT"
    fresh = False
    try:
        if symbol == "XAUUSD":
            now_ms = int(time.time() * 1000)
            series = _gold_bars("1h", now_ms)
            candles = series.get("bars") or []
            fresh = bool(series.get("ok") and candles and candles[-1].get("fresh"))
        else:
            data = fetch_klines(symbol, "15m", limit=80)
            candles = data.get("candles") or []
            snap = market_snapshot().get(symbol) or {}
            fresh = bool(candles) and bool(snap.get("fresh"))
        norm = []
        for bar in candles:
            norm.append({
                "high": bar.get("high", bar.get("h")),
                "low": bar.get("low", bar.get("l")),
                "close": bar.get("close", bar.get("c")),
            })
        if norm and all(v is not None for b in norm for v in b.values()):
            states = research_states(norm)
            by = {s["strategy"]: s["direction"] for s in states}
            e1 = by.get("E1-donchian-20", "WAIT")
            sma = by.get("SMA20-state", "WAIT")
            rsi = by.get("RSI14-state", "WAIT")
        else:
            fresh = False
    except Exception:
        fresh = False
    return e1, sma, rsi, fresh


@app.get("/api/eligibility")
def eligibility_api():
    if not _user_ok():
        return jsonify({"error": "unauthorized"}), 401
    from ops.profiles import evaluate
    from ops.users import get
    user = get(session["user_id"]) or {}
    profile = user.get("profile") or {}
    symbol = request.args.get("symbol", "BTCUSDT")
    if symbol not in {"BTCUSDT", "ETHUSDT", "XAUUSD"}:
        return jsonify({"error": "symbol_not_allowed"}), 400
    e1, sma, rsi, fresh = _research_votes(symbol)
    out = evaluate(profile.get("signal_style"), e1, sma, rsi, fresh, symbol)
    out["account"] = {
        "signal_style": profile.get("signal_style"),
        "signal_style_name": profile.get("signal_style_name"),
        "max_risk_pct": profile.get("max_risk_pct"),
        "currency": profile.get("currency"),
        "capital": profile.get("capital"),
        "experimental_alerts": profile.get("experimental_alerts", False),
    }
    return jsonify(out)


@app.get("/api/users/<user_id>")
def get_user(user_id):
    return jsonify({"error": "use /api/me"}), 404


@app.post("/api/users/<user_id>/telegram")
def link_telegram(user_id):
    if session.get("user_id") != user_id:
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"error": "typed_id_not_accepted"}), 400


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
        series = _gold_bars("1h", int(time.time() * 1000))
        bars = series.get("bars") or []
        norm = [{"high": bar["high"], "low": bar["low"], "close": bar["close"]} for bar in bars]
        states = research_states(norm) if len(norm) >= 21 else []
        by = {s["strategy"]: s["direction"] for s in states}
        last = bars[-1] if bars else {}
        out.append({
            "symbol": "XAUUSD",
            "timeframe": "1h",
            "fresh": bool(series.get("ok") and last.get("fresh")),
            "history": len(bars),
            "quote_semantics": "ohlc_not_bid_ask",
            "states": states,
            "limitation": "Completed XAUUSD chart OHLC. Not bid/ask. Not a daily close copied into the open. Weekend gaps are a closed market.",
            "council": council(by.get("E1-donchian-20", "WAIT"), by.get("SMA20-state", "WAIT"), by.get("RSI14-state", "WAIT"), bool(last.get("fresh")), last.get("open_time_ms")),
        })
    except Exception as exc:
        out.append({"symbol": "XAUUSD", "timeframe": "1h", "fresh": False, "error": type(exc).__name__, "reason": "GOLD_FEED_UNAVAILABLE"})
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
    view = _engine_view("XAUUSD")
    head = view.get("headline") or {}
    return jsonify({
        "symbol": "XAUUSD",
        "interval": view.get("interval") or "1h",
        "strategy": head.get("strategy"),
        "state": view.get("state"),
        "reason": view.get("reason"),
        "result": head.get("direction") or "WAIT",
        "direction": head.get("direction") or "WAIT",
        "production": "WAIT_DEFAULT",
        "approved": False,
        "validated": False,
        "broker": False,
        "quote_semantics": view.get("quote_semantics") or "ohlc_not_bid_ask",
        "rows": view.get("rows") or [],
        "note": "Completed 1h XAUUSD chart OHLC. Not a paper order, not bid/ask, and not an approved signal.",
    })


@app.get("/api/gold/candles")
def gold_candles():
    from ops.bars import to_chart_candles

    interval = request.args.get("interval", "1h")
    series = _gold_bars(interval, int(time.time() * 1000))
    if not series.get("ok"):
        return jsonify({
            "symbol": "XAUUSD",
            "interval": interval,
            "candles": [],
            "error": series.get("reason") or "GOLD_FEED_UNAVAILABLE",
            "quote_semantics": "ohlc_not_bid_ask",
            "note": "No gold candle was invented.",
        }), 502
    candles = to_chart_candles(series.get("bars") or [])[-180:]
    return jsonify({
        "symbol": "XAUUSD",
        "instrument": "XAUUSD_SPOT",
        "interval": series.get("interval") or interval,
        "source": "xaus.com",
        "kind": "chart_ohlc",
        "quote_semantics": "ohlc_not_bid_ask",
        "count": len(candles),
        "partial_dropped": series.get("partial_dropped"),
        "candles": candles,
        "note": "Completed XAUUSD chart OHLC. Open is the provider open. Not a live bid/ask quote.",
    })


@app.get("/api/engine")
def engine_api():
    symbol = request.args.get("symbol", "BTCUSDT")
    view = _engine_view(symbol)
    view.pop("headline", None)
    return jsonify(view)


@app.get("/api/research-lab")
def research_lab():
    payload = {
        "promoted_count": 0,
        "production": "WAIT_DEFAULT",
        "approved": [],
        "gates": [
            {"name": "Minimum trade count", "status": "FAIL", "evidence": "Sample sizes were insufficient or not met for promotion."},
            {"name": "Positive net expectancy after costs", "status": "FAIL", "evidence": "E1 and E2 negative after fees. G1-H4 totals small and unvalidated."},
            {"name": "Stress-cost resilience", "status": "FAIL", "evidence": "Stress costs worsened results."},
            {"name": "Robustness across periods", "status": "NOT_EVALUATED", "evidence": "SPA/White/DSR/PBO not computed for G1-H4-r2."},
            {"name": "No look-ahead", "status": "PASS", "evidence": "Prior bars only. Decision candle excluded."},
        ],
        "experiments": [
            {"id": "G0-H1", "name": "Trend continuation", "decision": "FAILED", "reason": "Negative net expectancy under costs."},
            {"id": "G0-H2", "name": "Volatility expansion", "decision": "FAILED", "reason": "Negative net expectancy under costs."},
            {"id": "G0-H3", "name": "Range fade", "decision": "FAILED", "reason": "Negative net expectancy under costs."},
            {"id": "G1-H4-r2", "name": "Trend continuation (corrected)", "decision": "NO_PROMOTION", "reason": "Positive point estimates but SPA/White/DSR/PBO not computed. ETH 20 rejected."},
            {"id": "E1-donchian-20", "name": "Donchian 20 breakout", "decision": "REJECTED", "reason": "Failed benchmark on BTC and ETH after costs. Not re-tuned."},
            {"id": "E2", "name": "E2 candidate", "decision": "REJECTED", "reason": "Negative expectancy after costs. Profit factor below 1."},
            {"id": "tf-pullback-20261027", "name": "Trend-following pullback", "decision": "NOT_PROMOTED", "reason": "Frozen rule. See docs/GATE3_SPEC.md. Not an approved signal."},
            {"id": "vol-break-20261027", "name": "Volatility-normalized breakout", "decision": "NOT_PROMOTED", "reason": "Frozen rule. Distinct from raw E1. Not an approved signal."},
            {"id": "mr-range-20261027", "name": "Regime-filtered mean reversion", "decision": "NOT_PROMOTED", "reason": "Disabled outside its range regime. Not an approved signal."},
            {"id": "xau-session-20261027", "name": "Gold New York session pullback", "decision": "NOT_PROMOTED", "reason": "XAUUSD 1h research. Cannot pass promotion without measured bid/ask."},
        ],
        "note": "No strategy has passed promotion gates. Experimental observations are not validated signals.",
    }
    path = ROOT / "docs" / "GATE3_RESULTS.json"
    if path.exists():
        try:
            report = json.loads(path.read_text())
        except Exception:
            report = None
        if report:
            grouped = {}
            for row in report.get("rows") or []:
                grouped.setdefault(row["strategy"], []).append(f"{row['symbol']} {row['split']} {row['judgment']} n={row.get('trades')}")
            qualified = set(report.get("qualified_for_review") or [])
            for item in payload["experiments"]:
                bits = grouped.get(item["id"])
                if not bits:
                    continue
                item["reason"] = "; ".join(bits) + ". Not an approved production signal."
                if any(item["id"] + ":" in key or key.startswith(item["id"] + ":") for key in qualified):
                    item["decision"] = "QUALIFIED_FOR_REVIEW"
                elif any(" FAIL" in " " + bit or bit.endswith(" FAIL") or " FAIL " in bit for bit in bits):
                    item["decision"] = "FAIL"
                elif any(" BLOCKED" in bit for bit in bits):
                    item["decision"] = "BLOCKED"
            payload["qualified_for_review"] = sorted(qualified)
            payload["approved"] = []
            payload["note"] = "Gate 3 judgments are research results. Qualified for review is not production approval. Production remains WAIT_DEFAULT."
    return jsonify(payload)


@app.get("/api/research-signals")
def research_signals():
    symbol = request.args.get("symbol", "BTCUSDT")
    if symbol not in {"BTCUSDT", "ETHUSDT", "XAUUSD"}:
        return jsonify({"error": "symbol_not_allowed"}), 400
    view = _engine_view(symbol)
    e1, sma, rsi, fresh = _research_votes(symbol)
    states = [
        {"strategy": "E1-donchian-20", "direction": e1, "classification": "research_observation", "validated": False, "evidence": "benchmark_failed"},
        {"strategy": "SMA20-state", "direction": sma, "classification": "research_observation", "validated": False},
        {"strategy": "RSI14-state", "direction": rsi, "classification": "research_observation", "validated": False},
    ]
    return jsonify({
        "symbol": symbol,
        "interval": view.get("interval"),
        "production": "WAIT_DEFAULT",
        "validated": False,
        "approved": False,
        "broker": False,
        "kind": "research_observation",
        "fresh": fresh,
        "states": states,
        "engine": view.get("rows") or [],
        "state": view.get("state"),
        "reason": view.get("reason"),
        "paper_candidates": [],
        "label": "RESEARCH OBSERVATION — NOT VALIDATED",
        "note": "E1 is a failed benchmark. A paper candidate is not an order. Production remains WAIT_DEFAULT.",
    })


@app.get("/api/experimental")
@require_token
def experimental():
    rows = worker.book.read()
    return jsonify({"rows": rows[-50:], "total": len(rows), "label": "Research notes are not orders."})


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


def _telegram_loop():
    while True:
        try:
            from ops.telegram_in import poll_if_enabled
            poll_if_enabled()
        except Exception:
            pass
        time.sleep(3)


threading.Thread(target=_telegram_loop, daemon=True).start()


threading.Thread(target=_loop, daemon=True).start()


@app.get("/")
def landing():
    if _gate():
        return redirect("/overview")
    return make_response(LANDING)


@app.get("/login")
def login_page():
    nxt = _safe_next(request.args.get("next"))
    if _gate():
        return redirect(nxt)
    return make_response(_auth_page("login", nxt))


@app.get("/register")
def register_page():
    raw = request.args.get("next")
    nxt = _safe_next(raw) if raw else "/onboarding"
    if _gate():
        return redirect(nxt)
    return make_response(_auth_page("register", nxt))


@app.get("/api/scanner")
def scanner_api():
    if not _user_ok() and not _owner_ok():
        return jsonify({"error": "unauthorized"}), 401
    from ops.scanner import scan
    from ops.shadow_bridge import load_live_windows
    now_ms = int(time.time() * 1000)
    try:
        windows = load_live_windows(now_ms)
    except Exception:
        windows = []
    body = scan(windows, now_ms=now_ms)
    if not body["markets"]:
        body["markets"] = [
            {"symbol": "BTCUSDT", "status": "unavailable", "state": "DATA_UNAVAILABLE", "scanner_state": "BLOCKED", "message": "BTCUSDT is not being scanned. The latest completed bar is missing or stale.", "approved": False},
            {"symbol": "ETHUSDT", "status": "unavailable", "state": "DATA_UNAVAILABLE", "scanner_state": "BLOCKED", "message": "ETHUSDT is not being scanned. The latest completed bar is missing or stale.", "approved": False},
            {"symbol": "XAUUSD", "status": "unavailable", "state": "DATA_UNAVAILABLE", "scanner_state": "BLOCKED", "message": "Gold scanning is temporarily unavailable. Last verified market update: unknown.", "approved": False},
        ]
    user_id = session.get("user_id")
    if user_id:
        from ops.inbox import record_scan
        from ops.users import get
        plan = (get(user_id) or {}).get("plan") or {}
        record_scan(user_id, body, plan, now_ms)
    return jsonify(body)


@app.get("/api/notifications")
def notifications_api():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.inbox import items, unread_count
    return jsonify({"items": items(user_id), "unread": unread_count(user_id)})


@app.post("/api/notifications/read")
def notifications_read():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.inbox import mark_read
    event_id = (request.json or {}).get("id")
    return jsonify(mark_read(user_id, event_id or None))


@app.get("/overview")
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
@app.get("/scanner")
@app.get("/learn")
@app.get("/plan")
@app.get("/notifications")
@app.get("/onboarding")
def index():
    if not _gate():
        return redirect("/login?next=" + _safe_next(request.path))
    failed = request.args.get("login") == "failed"
    page = DASHBOARD.replace("{{AUTHED}}", "1").replace("{{FAILED}}", "1" if failed else "0").replace("{{CSRF}}", _csrf())
    return make_response(page)


def _auth_page(kind, nxt):
    title = "Create account" if kind == "register" else "Sign in"
    button = "Create account" if kind == "register" else "Sign in"
    alt = '<a href="/login">Already have an account? Sign in</a>' if kind == "register" else '<a href="/register">Need an account? Create one</a>'
    endpoint = "/api/register" if kind == "register" else "/api/login"
    fail = "That name is taken or the details are invalid." if kind == "register" else "Name or password is incorrect."
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Aureon Trading Lab</title>
<style>
body{{margin:0;font-family:system-ui;background:#0b1220;color:#e8eef7}}
header{{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-bottom:1px solid #1e293b}}
a{{color:#99f6e4;text-decoration:none}}
.brand{{font-weight:700;color:#e8eef7}}
.muted{{color:#94a3b8;font-size:12px}}
main{{max-width:420px;margin:48px auto;padding:0 24px}}
form{{background:#111827;border:1px solid #1e293b;border-radius:12px;padding:20px;display:grid;gap:12px}}
label{{display:grid;gap:6px;font-size:14px}}
input{{background:#0b1220;color:#e8eef7;border:1px solid #334155;border-radius:8px;padding:10px}}
button{{background:#0f766e;color:white;border:0;padding:10px 16px;border-radius:8px;cursor:pointer}}
button:disabled{{opacity:.6}}
.err{{color:#fda4af;min-height:1.2em}}
.pw{{display:flex;gap:8px;align-items:center}}
.pw input{{flex:1}}
.pw button{{background:#152033;border:1px solid #334155}}
</style>
</head>
<body>
<header>
  <a class="brand" href="/">Aureon Trading Lab</a>
  <div class="muted">Brought to you by Cyber Aid</div>
</header>
<main>
  <h1>{title}</h1>
  <form id="form" novalidate>
    <label>Name <input id="name" name="name" autocomplete="username" required></label>
    <label>Password <span class="pw"><input id="password" name="password" type="password" autocomplete="{"new-password" if kind == "register" else "current-password"}" minlength="8" required><button id="peek" type="button">Show</button></span></label>
    <button id="submit" type="submit">{button}</button>
    <p id="msg" class="err" role="alert"></p>
    <p>{alt}</p>
    <p><a href="/">Back to Aureon</a></p>
  </form>
</main>
<script>
const form = document.getElementById("form");
const btn = document.getElementById("submit");
const msg = document.getElementById("msg");
document.getElementById("peek").onclick = () => {{
  const input = document.getElementById("password");
  const showing = input.type === "text";
  input.type = showing ? "password" : "text";
  document.getElementById("peek").textContent = showing ? "Show" : "Hide";
}};
form.onsubmit = async (event) => {{
  event.preventDefault();
  const name = document.getElementById("name").value.trim();
  const password = document.getElementById("password").value;
  msg.textContent = "";
  if (!name || password.length < 8) {{
    msg.textContent = "Name is required and the password must be at least 8 characters.";
    return;
  }}
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Please wait…";
  try {{
    const response = await fetch("{endpoint}", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      credentials: "same-origin",
      body: JSON.stringify({{name, password}})
    }});
    if (!response.ok) {{
      msg.textContent = "{fail}";
      btn.disabled = false;
      btn.textContent = label;
      return;
    }}
    location.href = {json.dumps(nxt)};
  }} catch (err) {{
    msg.textContent = "The request failed. Try again.";
    btn.disabled = false;
    btn.textContent = label;
  }}
}};
</script>
</body>
</html>"""


LANDING = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aureon Trading Lab</title>
<style>
body{margin:0;font-family:Inter,system-ui,sans-serif;background:#070b12;color:#eef3fb}
header{display:flex;justify-content:space-between;align-items:center;padding:18px 28px;border-bottom:1px solid #1d2a3d;position:sticky;top:0;background:#070b12ee}
.brand{font-weight:700;font-size:1.05rem}
.muted{color:#8ea0b8}
nav{display:flex;gap:8px;align-items:center}
nav a{color:#eef3fb;text-decoration:none;padding:8px 12px;border-radius:8px}
.hero{max-width:1080px;margin:0 auto;padding:64px 24px 24px;display:grid;grid-template-columns:1.2fr .8fr;gap:28px;align-items:center}
h1{font-size:clamp(36px,5vw,58px);line-height:1.05;margin:8px 0 12px;letter-spacing:-.03em}
.lede{font-size:1.05rem;color:#c5d2e4;max-width:40rem}
.actions{display:flex;gap:12px;margin:22px 0;flex-wrap:wrap}
.btn{background:#0f766e;color:white;border:0;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:600}
.ghost{background:transparent;border:1px solid #334155;color:#eef3fb}
.preview{background:linear-gradient(180deg,#121c2c,#0c1422);border:1px solid #1d2a3d;border-radius:16px;padding:18px}
.preview .row{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #1d2a3d;font-size:.92rem}
.wrap{max-width:1080px;margin:0 auto;padding:8px 24px 48px}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.card{background:#101826;border:1px solid #1d2a3d;border-radius:14px;padding:16px}
.card h3{margin:0 0 8px}
footer a{color:#99f6e4}
@media(max-width:800px){header{flex-wrap:wrap;gap:10px}.hero,.grid{grid-template-columns:1fr}nav{width:100%}}
</style>
</head>
<body>
<header>
  <div><div class="brand">Aureon Trading Lab</div><div class="muted">Brought to you by Cyber Aid</div></div>
  <nav><a href="#styles">Signal styles</a><a href="#risk">Research & risk</a><a href="/login" class="ghost">Sign in</a><a href="/register" class="btn">Create account</a></nav>
</header>
<section class="hero">
  <div>
    <p class="muted">Paper trading and research</p>
    <h1>See the market clearly. Research with discipline.</h1>
    <p class="lede">One account for BTC, ETH, and gold observation. Choose a signal posture, set a real base currency, and read research states without pretending they are trades.</p>
    <div class="actions"><a class="btn" href="/register">Create your account</a><a class="btn ghost" href="/login">Sign in</a></div>
  </div>
  <aside class="preview" aria-label="Product preview">
    <p class="muted">Illustrative desk layout. Not a live quote and not a performance claim.</p>
    <div class="row"><span>Production</span><strong>WAIT_DEFAULT</strong></div>
    <div class="row"><span>Broker</span><strong>Disabled</strong></div>
    <div class="row"><span>Account currency</span><strong>Set by you</strong></div>
    <div class="row"><span>Paper position</span><strong>Only if recorded</strong></div>
  </aside>
</section>
<section class="wrap" id="styles">
  <h2>Three signal styles, one login</h2>
  <p class="muted">Recovered from Awuru's account personas. They change confirmation strictness and risk caps. They do not promote a strategy.</p>
  <div class="grid">
    <article class="card"><h3>Apex Momentum</h3><p>Aggressive. BTC and ETH may follow an E1 observation alone. Gold still requires agreement. Risk cap 2.5% per trade.</p></article>
    <article class="card"><h3>Orion Precision</h3><p>Balanced. E1 plus a confirming research state, and no opposing vote. Risk cap 1.5% per trade.</p></article>
    <article class="card"><h3>Aegis Shield</h3><p>Defensive. All three research states must agree, or the result is WAIT. Risk cap 0.8% per trade.</p></article>
  </div>
</section>
<section class="wrap" id="platform">
  <div class="grid">
    <article class="card"><h3>Market workspace</h3><p>BTC and ETH from Binance closed candles. Gold only when a real XAUUSD source returns data.</p></article>
    <article class="card"><h3>Research signals</h3><p>E1, SMA20, and RSI14 stay labeled as research. A WAIT result is kept visible.</p></article>
    <article class="card"><h3>Paper records</h3><p>Portfolio and history show recorded paper orders only. A directional bias is not a holding.</p></article>
  </div>
  <article class="card" id="risk"><h3>Research and risk</h3><p>The platform operates in paper-trading and research mode. Broker execution is disabled. No strategy has passed promotion gates. There is no guarantee of profitable results. Account balances keep the currency you choose. Aureon does not convert them.</p></article>
</section>
<footer>Aureon Trading Lab · Brought to you by Cyber Aid · Paper only · Broker disabled<br><a href="/register">Create account</a> · <a href="/login">Sign in</a> · <a href="#styles">Signal styles</a> · <a href="#risk">Research and risk</a></footer>
</body>
</html>"""

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
canvas{width:100%;height:320px;background:#0a101a;border-radius:10px;display:block}
canvas.spark{height:46px;background:transparent;border-radius:0}
a{color:#9ae6d5}
#view a{text-underline-offset:2px}
select,button{background:#152033;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.fieldrow{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.fieldrow label,.field{display:grid;gap:6px;font-size:.85rem;color:var(--muted)}
.field{margin:12px 0;max-width:320px}
.styles label,.checks label{display:flex;gap:10px;align-items:flex-start;margin:8px 0;line-height:1.45}
.styles label{background:#0b1220;border:1px solid var(--line);border-radius:10px;padding:10px 12px}
#view input,#view select{background:#0b1220;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
#view .field input,#view .field select{width:100%;max-width:320px}
#view article+article{margin-top:12px}
main h1{margin:0;font-size:1.55rem}
#menu{display:none;background:#152033;color:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:10px}
@media(max-width:900px){.shell{grid-template-columns:1fr}#menu{display:inline-block}aside{display:none;position:fixed;inset:0 auto 0 0;width:240px;z-index:20}aside.open{display:block}.markets,.workspace{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="shell">
  <button id="menu" aria-label="Open navigation" aria-expanded="false">☰ Menu</button>
  <aside id="nav">
    <div class="brand">Aureon Trading Lab</div>
    <a href="/overview" data-path="/overview">Overview</a>
    <a href="/scanner" data-path="/scanner">Live Scanner</a>
    <a href="/trading" data-path="/trading">Trading Terminal</a>
    <a href="/signals" data-path="/signals">Live Signals</a>
    <a href="/learn" data-path="/learn">Academy</a>
    <a href="/plan" data-path="/plan">My Plan</a>
    <a href="/notifications" data-path="/notifications">Inbox</a>
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
      <div class="pills"><span class="pill">WAIT_DEFAULT</span><span class="pill">Paper only</span><span class="pill">Broker off</span><a href="/notifications" id="inboxlink">Inbox</a><button id="signout" type="button">Sign out</button></div>
    </header>
    <section id="view"></section>
  </main>
</div>
<script>
const menu = document.getElementById("menu");
const nav = document.getElementById("nav");
menu.onclick = () => { const open = nav.classList.toggle("open"); menu.setAttribute("aria-expanded", open); };
document.querySelectorAll("#nav a").forEach(a => a.onclick = () => nav.classList.remove("open"));
document.getElementById("signout").onclick = async () => {
  await fetch("/api/logout", {method:"POST", credentials:"same-origin"});
  location.href = "/";
};
const path = location.pathname === "/" ? "/overview" : location.pathname;
document.querySelectorAll("aside a").forEach(a => { if (a.dataset.path === path) a.classList.add("active"); });
const titles = {"/":"Overview","/signals":"Live Signals","/trading":"Trading Terminal","/strategies":"Strategies","/portfolio":"Portfolio","/risk":"Risk Management","/activity":"Orders & Trade History","/system":"System Status","/settings":"Account & Settings","/research":"Backtesting & Research","/onboarding":"Account setup","/scanner":"Live Scanner","/learn":"Academy","/indicators":"Academy","/plan":"My Trading Plan","/notifications":"Inbox"};
document.getElementById("title").textContent = titles[path] || "Aureon";
document.title = (titles[path] || "Aureon") + " · Aureon Trading Lab";
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
  const w = c.width = Math.max(320, c.clientWidth * 2), h = c.height = 720;
  ctx.clearRect(0,0,w,h);
  const slice = candles.slice(-90);
  const hi = Math.max(...slice.map(x=>x.h)), lo = Math.min(...slice.map(x=>x.l));
  const left = 12, right = 132, top = 18, bottom = 42;
  const bw = (w - left - right) / slice.length;
  const y = p => top + ((hi - p) / (hi - lo || 1)) * (h - top - bottom);
  slice.forEach((bar,i)=>{
    const x = left + i*bw + bw/2;
    ctx.strokeStyle = bar.c >= bar.o ? "#2fce8b" : "#ff5d6c";
    ctx.beginPath(); ctx.moveTo(x,y(bar.h)); ctx.lineTo(x,y(bar.l)); ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle;
    const topY = Math.min(y(bar.o), y(bar.c)), botY = Math.max(y(bar.o), y(bar.c));
    ctx.fillRect(x-bw*0.22, topY, bw*0.44, Math.max(2, botY-topY));
  });
  ctx.fillStyle = "#8ea0b8";
  ctx.font = "22px sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(hi.toFixed(2), w - right + 10, y(hi) + 8);
  ctx.fillText(((hi + lo) / 2).toFixed(2), w - right + 10, y((hi + lo) / 2));
  ctx.fillText(lo.toFixed(2), w - right + 10, Math.min(h - bottom, y(lo)));
  const stamp = (bar) => {
    if (!bar || bar.t == null) return "";
    const d = new Date(bar.t);
    return Number.isNaN(d.getTime()) ? String(bar.t).slice(0, 16) : d.toISOString().slice(5, 16).replace("T", " ");
  };
  ctx.fillText(stamp(slice[0]), left, h - 12);
  ctx.fillText(stamp(slice[slice.length - 1]), Math.max(left, w - right - 150), h - 12);
}
function money(amount, code){
  if (amount === null || amount === undefined || amount === "") return "Not set";
  const n = Number(amount);
  if (!Number.isFinite(n)) return "Not set";
  if (!code) return n.toLocaleString(undefined, {maximumFractionDigits: 2}) + " — currency not set";
  try { return new Intl.NumberFormat(undefined, {style:"currency", currency: code}).format(n); }
  catch (e) { return n.toLocaleString(undefined, {maximumFractionDigits: 2}) + " " + code; }
}
async function overview(){
  const me = await fetch("/api/me").then(r => r.ok ? r.json() : null);
  const profile = (me && me.profile) || {};
  const balance = money(profile.capital, profile.currency || "");
  const styleName = profile.signal_style_name || "Not selected";
  const who = me && me.name ? me.name : "Account";
  const steps = [];
  if (!profile.signal_style) steps.push("Choose a signal style.");
  if (!profile.currency) steps.push("Set a base currency. Amounts are not converted.");
  if (!(me && me.telegram_verified)) steps.push("Telegram is not verified. Alerts stay off until you link a chat.");
  const stepHtml = steps.length ? `<article class="card"><h2>Next steps</h2><ul>${steps.map(s => `<li>${s}</li>`).join("")}</ul><p><a href="/settings">Open settings</a></p></article>` : "";
  const accountCard = `<article class="card"><h2>${who}</h2><div class="row"><span>Signal style</span><span>${styleName}</span></div><div class="row"><span>Configured paper capital</span><span>${balance}</span></div><div class="row"><span>Production</span><span>WAIT_DEFAULT</span></div><p class="muted">Research eligibility is not a trade. Broker execution is disabled. No strategy is promoted. ${profile.currency ? "Amounts use " + profile.currency + ". Quotes stay in their market currency." : "Choose a base currency before treating the balance as money."}</p><p><a href="/settings">Account settings</a> · <a href="/research">Research laboratory</a></p></article>${stepHtml}`;
  view.innerHTML = accountCard + `<p class="muted" id="mload">Loading markets…</p>`;
  const selected = me && me.prefs && me.prefs.markets ? me.prefs.markets : null;
  const m = await fetch("/api/markets").then(r=>r.json()).catch(()=>({markets:[]}));
  const markets = selected ? (m.markets||[]).filter(item => selected.includes(item.symbol) || (item.id === "GOLD" && selected.includes("XAUUSD"))) : (m.markets||[]);
  const cards = markets.map(item => {
    if (item.id === "GOLD") {
      const g = item.data || {};
      const price = g.price != null ? Number(g.price).toLocaleString(undefined,{maximumFractionDigits:2}) : "unavailable";
      return `<article class="card" id="card-XAUUSD"><div class="muted">XAUUSD · indicative mid · USD/oz</div><div class="price">${price}</div><canvas id="spark-gold" class="spark"></canvas><div id="detail-XAUUSD" class="muted">${g.fresh===false?"Not a live quote. ":""}${g.note||"Indicative mid. Not bid/ask."} Research state loading.</div></article>`;
    }
    const price = item.data && item.data.close != null ? Number(item.data.close).toLocaleString() : "unavailable";
    const fresh = item.data && item.data.fresh === false ? "Feed is not fresh. " : "";
    return `<article class="card" id="card-${item.symbol}"><div class="muted">${item.symbol}</div><div class="price">${price}</div><canvas id="spark-${item.symbol}" class="spark"></canvas><div id="detail-${item.symbol}" class="muted">${fresh}Research state loading.</div></article>`;
  });
  view.innerHTML = `${accountCard}${selected ? `<p class="muted">Showing your selected markets. <a href="/settings">Change settings</a></p>` : ""}<div class="markets">${cards.join("") || "<p>No markets selected.</p>"}</div><div class="workspace"><article class="card"><h2>Chart</h2><select id="sym"><option>BTCUSDT</option><option>ETHUSDT</option><option>XAUUSD</option></select> <select id="tf"><option>15m</option><option>1h</option><option>4h</option><option>1d</option></select><canvas id="chart"></canvas><p class="muted" id="chartnote">Loading closed candles.</p></article><article class="card"><h2>Profile eligibility</h2><div id="elig">loading</div><p class="muted">Eligibility uses the saved signal style. It is not an order.</p></article></div><article class="card" id="councilcard"><h2>Strategy council</h2><p class="muted">Loading the combined research summary. This is not the account signal style.</p></article>`;
  async function loadChart(){
    const sym = document.getElementById("sym").value, tf = document.getElementById("tf").value;
    const note = document.getElementById("chartnote");
    if (sym === "XAUUSD") {
      const bars = await fetch("/api/gold/candles?interval="+encodeURIComponent(tf)).then(r=>r.json());
      const candles = (bars.candles||[]).filter(c => c.o != null && c.h != null && c.l != null && c.c != null).map(c => ({t:c.t, o:+c.o, h:+c.h, l:+c.l, c:+c.c}));
      if (!candles.length) { if (note) note.textContent = bars.error ? "Chart unavailable: " + bars.error : (bars.note || "No completed gold candles."); return; }
      draw(candles);
      if (note) note.textContent = (bars.interval || tf) + " · " + (bars.note || "XAUUSD chart OHLC") + (bars.quote_semantics ? " · " + bars.quote_semantics : "");
      return;
    }
    const bars = await fetch(`/api/klines?symbol=${sym}&interval=${tf}`).then(r=>r.json());
    if (!bars.candles || !bars.candles.length) {
      if (note) note.textContent = bars.error ? "Chart unavailable: " + bars.error : "No closed candles returned.";
      return;
    }
    draw(bars.candles||[]);
    if (note) note.textContent = (bars.source || "market") + " · " + tf + " · closed candles only · quote currency is the market's own";
  }
  document.getElementById("sym").onchange = loadChart;
  document.getElementById("tf").onchange = loadChart;
  loadChart();
  const symbols = selected && selected.length ? selected : ["BTCUSDT","ETHUSDT"];
  const eligPromise = Promise.all(symbols.filter(s => ["BTCUSDT","ETHUSDT","XAUUSD"].includes(s)).map(s => fetch("/api/eligibility?symbol="+s).then(r=>r.json()).then(d => ({...d, symbol:s})).catch(()=>({symbol:s, decision:"WAIT", reason:"Eligibility unavailable"}))));
  eligPromise.then(elig => {
    const box = document.getElementById("elig");
    if (box) box.innerHTML = elig.map(d => `<div class="row"><span>${d.symbol}</span><span class="${cls(d.decision||"WAIT")}">${label(d.decision||"WAIT")}</span></div><div class="muted">${d.reason||""}</div>`).join("") || "<p>No markets selected.</p>";
  });
  for (const item of markets) {
    const symbol = item.id === "GOLD" ? "XAUUSD" : item.symbol;
    if (item.id === "GOLD") {
      fetch("/api/gold/signal").then(r=>r.json()).then(sig => {
        const box = document.getElementById("detail-XAUUSD");
        if (box) box.innerHTML = `<div class="row"><span>${sig.interval||"1h"} ${sig.state||"WAIT"}</span><span class="${cls(sig.result||"")}">${label(sig.result||"unavailable")}</span></div><div class="muted">${sig.reason||""}. ${sig.note||"Not a paper order."}</div>`;
      }).catch(()=>{});
      fetch("/api/gold/candles?interval=1h").then(r=>r.json()).then(g => spark("spark-gold", (g.candles||[]).map(c=>({c:+c.c})))).catch(()=>{});
    } else {
      fetch(`/api/research-signals?symbol=${symbol}&interval=15m`).then(r=>r.json()).then(s => {
        const box = document.getElementById("detail-"+symbol);
        if (!box) return;
        box.innerHTML = (s.states||[]).map(st => `<div class="row"><span>${st.strategy}</span><span class="${cls(st.direction)}">${label(st.direction)}</span></div>`).join("") + `<div class="muted">${s.label||""}</div>`;
      }).catch(()=>{});
      fetch(`/api/klines?symbol=${symbol}&interval=15m`).then(r=>r.json()).then(bars => spark("spark-"+symbol, bars.candles||[])).catch(()=>{});
    }
  }
  fetch("/api/council").then(r=>r.json()).then(council => {
    const box = document.getElementById("councilcard");
    if (!box) return;
    const html = (council.markets||[]).map(row => row.council ? `<div class="row"><span>${row.symbol} ${row.timeframe||""}</span><span>${label(row.council.state)}</span></div><div class="muted">${row.council.reason||""} ${row.limitation||""}</div>` : `<div class="row"><span>${row.symbol}</span><span>unavailable</span></div>`).join("");
    box.innerHTML = `<h2>Strategy council</h2>${html}<p class="muted">Combined research summary. Not the account signal style, and not a validated signal.</p>`;
  }).catch(()=>{});
}
async function signals(){
  view.innerHTML = `<p class="muted">Loading current research states…</p>`;
  const me = await fetch("/api/me").then(r => r.ok ? r.json() : null).catch(()=>null);
  const profile = (me && me.profile) || {};
  const markets = (me && me.prefs && me.prefs.markets && me.prefs.markets.length) ? me.prefs.markets : ["BTCUSDT","ETHUSDT"];
  const cards = await Promise.all(markets.map(async symbol => {
    const elig = await fetch("/api/eligibility?symbol="+encodeURIComponent(symbol)).then(r=>r.json()).catch(()=>({decision:"WAIT", reason:"Eligibility unavailable"}));
    let detail = "";
    if (symbol === "XAUUSD") {
      const gold = await fetch("/api/gold/signal").then(r=>r.json()).catch(()=>({}));
      detail = `<div class="muted">${gold.interval||"1h"} ${gold.state||"WAIT"} ${label(gold.result||"unavailable")}. ${gold.reason||""} ${gold.note||"Not an order. Quote is USD/oz chart OHLC, not bid/ask."}</div>`;
    } else {
      const s = await fetch("/api/research-signals?symbol="+symbol+"&interval=15m").then(r=>r.json()).catch(()=>({states:[]}));
      detail = (s.states||[]).map(st => `<div class="row"><span>${st.strategy}</span><span class="${cls(st.direction)}">${label(st.direction)}</span></div>`).join("");
      detail += `<div class="muted">${s.fresh===false?"Feed is not fresh. ":""}${s.label||"Research observation."} Timeframe 15m.</div>`;
    }
    return `<article class="card" data-symbol="${symbol}"><h2>${symbol}</h2><div class="row"><span>Profile</span><span>${profile.signal_style_name||"Not selected"}</span></div><div class="row"><span>Eligibility</span><span class="${cls(elig.decision||"WAIT")}">${label(elig.decision||"WAIT")}</span></div><div class="muted">${elig.reason||""}</div>${detail}<div class="muted">Production ${elig.production||"WAIT_DEFAULT"}. Not an order.</div></article>`;
  }));
  const hist = await fetch("/api/signal-history").then(r=>r.json()).catch(()=>({signals:[]}));
  const seen = new Map();
  for (const s of (hist.signals||[])) {
    const key = [s.asset, s.timeframe, s.result].join("|");
    const cur = seen.get(key) || {row:s, n:0};
    cur.n += 1;
    seen.set(key, cur);
  }
  const rows = [...seen.values()].slice(0, 8).map(({row, n}) => `<div class="row"><span>${row.asset||""} ${row.timeframe||""}</span><span>${label(row.result||"")}</span><span>${n} stored ${n===1?"evaluation":"evaluations"}</span></div>`);
  view.innerHTML = `<label class="field">Market filter <select id="sigfilter"><option value="">All selected markets</option>${markets.map(s => `<option value="${s}">${s}</option>`).join("")}</select></label><p class="muted">Decisions use the saved profile ${profile.signal_style_name||"(none selected)"}. Repeated unchanged evaluations are collapsed.</p>${cards.join("")}<article class="card"><h2>Earlier evaluations</h2>${rows.join("")||"<p>No stored evaluations.</p>"}<p class="muted">Research evaluations are not trades. Identical results are counted instead of repeated row by row.</p></article>`;
  const filter = document.getElementById("sigfilter");
  filter.onchange = () => {
    const chosen = filter.value;
    document.querySelectorAll("#view article[data-symbol]").forEach(el => { el.hidden = Boolean(chosen) && el.dataset.symbol !== chosen; });
  };
}
async function terminal(){
  view.innerHTML = `<article class="card"><h2>Market workspace</h2><div class="fieldrow"><label>Market <select id="sym"><option>BTCUSDT</option><option>ETHUSDT</option><option>XAUUSD</option></select></label><label>Timeframe <select id="tf"><option>15m</option><option>1h</option><option>4h</option><option>1d</option></select></label></div><canvas id="chart"></canvas><p class="muted" id="chartnote">Loading closed candles…</p><div id="termmeta"></div></article>`;
  async function loadChart(){
    const sym = document.getElementById("sym").value;
    const tf = document.getElementById("tf").value;
    const note = document.getElementById("chartnote");
    const meta = document.getElementById("termmeta");
    note.textContent = "Loading closed candles…";
    meta.innerHTML = "";
    try {
      if (sym === "XAUUSD") {
        const bars = await fetch("/api/gold/candles?interval="+encodeURIComponent(tf)).then(r=>r.json());
        const candles = (bars.candles||[]).filter(c => c.o != null && c.h != null && c.l != null && c.c != null).map(c => ({t:c.t, o:+c.o, h:+c.h, l:+c.l, c:+c.c}));
        if (!candles.length) { note.textContent = bars.error ? "Gold chart unavailable: " + bars.error : (bars.note || "No completed gold candles."); return; }
        draw(candles);
        note.textContent = (bars.interval || tf) + " · " + (bars.note || "XAUUSD chart OHLC");
      } else {
        const bars = await fetch(`/api/klines?symbol=${sym}&interval=${tf}`).then(r=>r.json());
        if (!bars.candles || !bars.candles.length) { note.textContent = bars.error ? "Chart unavailable: " + bars.error : "No closed candles returned."; return; }
        draw(bars.candles);
        const last = bars.candles[bars.candles.length-1];
        note.textContent = (bars.source || "market") + " · " + tf + " · last close " + last.c + (last.t ? " · " + new Date(last.t).toISOString() : "") + " · quote currency is the market's own";
      }
      const elig = await fetch("/api/eligibility?symbol="+encodeURIComponent(sym)).then(r=>r.ok?r.json():{decision:"WAIT", reason:"Eligibility unavailable"});
      meta.innerHTML = `<div class="row"><span>Profile eligibility</span><span class="${cls(elig.decision||"WAIT")}">${label(elig.decision||"WAIT")}</span></div><div class="muted">${elig.name?elig.name+". ":""}${elig.reason||""} Not a trade.</div>`;
    } catch (err) {
      note.textContent = "Market data request failed.";
    }
  }
  document.getElementById("sym").onchange = loadChart;
  document.getElementById("tf").onchange = loadChart;
  await loadChart();
}
async function signalsLegacy(){
  const rows = await Promise.all(["BTCUSDT","ETHUSDT"].map(s=>fetch("/api/research-signals?symbol="+s+"&interval=15m").then(r=>r.json())));
  const gold = await fetch("/api/gold/signal").then(r=>r.json()).catch(()=>({}));
  view.innerHTML = rows.map(d => `<article class="card"><h2>${d.symbol}</h2>${d.states.map(s => `<div class="row"><span>${s.strategy}</span><span class="${cls(s.direction)}">${s.direction}</span></div>`).join("")}</article>`).join("") + `<article class="card"><h2>XAUUSD</h2><div class="row"><span>${gold.state||"WAIT"}</span><span class="${cls(gold.result||"")}">${label(gold.result||"unavailable")}</span></div><div class="muted">${gold.reason||""} ${gold.note||""}</div></article><article class="card"><h2>Research backtest</h2><button id="backtest">Run research backtest</button><pre id="backtestout">waiting</pre></article>`;
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
async function researchLab(){
  const d = await fetch("/api/research-lab").then(r=>r.json());
  const gates = (d.gates||[]).map(g => `<div class="row"><span>${g.name}</span><span class="${cls(g.status)}">${g.status}</span></div><div class="muted">${g.evidence}</div>`).join("");
  const rows = (d.experiments||[]).map(e => `<div class="row"><span>${e.id}</span><span class="${cls(e.decision)}">${e.decision}</span></div><div class="muted">${e.name}. ${e.reason}</div>`).join("");
  view.innerHTML = `<article class="card"><h2>Promotion gates</h2><p>Promoted strategies: ${d.promoted_count}. Production: ${d.production}.</p>${gates}</article><article class="card"><h2>Experiment archive</h2>${rows}<p class="muted">${d.note}</p></article>`;
}
async function scannerPage(){
  const draw = (body) => {
    const cards = (body.markets||[]).map(m => `<article class="card" data-symbol="${m.symbol}"><h2>${m.symbol}</h2><div class="row"><span>${m.interval||""} ${m.quote||""}</span><span>${m.price==null?"—":m.price}</span></div><div class="row"><span>Status</span><span>${m.status||"unknown"}</span></div><p>${m.message||"No qualifying setup yet."}</p><p class="muted">${m.scanner_state||m.state||"WAIT"}. Evidence grade ${m.evidence_grade==null?"—":m.evidence_grade}/100. ${m.evidence_label||"Checklist score, not a probability of profit."}</p></article>`).join("");
    view.innerHTML = `<p role="status">${body.notice||"No approved strategy is currently active; trade alerts are unavailable."}</p><div class="markets">${cards}</div><p class="muted">Scanned ${body.scanned_at||""}. Completed bars only. <a href="/learn">Why the scanner says this</a></p>`;
  };
  const loadScan = async () => {
    const response = await fetch("/api/scanner", {credentials:"same-origin"});
    if (response.status === 401) { view.innerHTML = `<article class="card"><h2>Sign in required</h2><p><a href="/login">Sign in</a></p></article>`; return; }
    const body = await response.json().catch(()=>({notice:"The scanner could not be read. Please retry.", markets:[]}));
    draw(body);
  };
  await loadScan();
  if (window.__scanTimer) clearInterval(window.__scanTimer);
  window.__scanTimer = setInterval(loadScan, 15000);
}
async function learnPage(){
  view.innerHTML = `<article class="card"><h2>How to read the desk</h2><p>A candlestick shows the open, high, low and close of one completed period. A 15-minute candle is fifteen minutes of trades. A one-hour candle is one hour. The scanner uses only candles that have already closed.</p><p>E1 Donchian-20 compares the latest close with the highest high and lowest low of the previous 20 completed bars. SMA20 is the average of the last 20 closes. RSI14 is a momentum reading. They are research observations. If E1 is waiting, every account style waits.</p></article><article class="card"><h2>What a result means</h2><ul><li>No qualifying setup yet: the rule did not match.</li><li>Research observation: a condition was seen. It is not an order.</li><li>Paper candidate: the written rule is complete, and it is still not approved.</li><li>Approved signal: only after a promotion record exists. None exists now.</li><li>Paper trade: a simulated fill. Broker execution is off, so this desk does not send one.</li></ul><p>WAIT means the rule or the data does not justify an entry. It is the safe result, not a missing page.</p></article><article class="card"><h2>Accounts and alerts</h2><p>Apex Momentum caps risk at 2.5% of paper capital. Orion Precision caps it at 1.5%. Aegis Shield caps it at 0.8%. These are ceilings. Changing the base currency does not convert the stored amount.</p><p>Connect Telegram from Settings. The link is single-use. A connected chat can be removed, and a removed chat receives nothing. Trade alerts stay off until a strategy is explicitly approved.</p><p>The evidence grade is a checklist. It is not a probability of profit, and it has not been calibrated. A weekly aim is a personal target. Missing it is shown as a shortfall. The aim does not create a signal or raise risk.</p></article>`;
}
async function planPage(){
  const response = await fetch("/api/plan", {credentials:"same-origin"});
  if (response.status === 401) { view.innerHTML = `<article class="card"><h2>Sign in required</h2><p><a href="/login">Sign in</a> to save a plan.</p></article>`; return; }
  const body = await response.json();
  const plan = body.plan || {};
  const week = body.week || {};
  const catalog = await fetch("/api/registry", {credentials:"same-origin"}).then(r => r.json());
  const options = (catalog.strategies||[]).map(s => `<label><input type="checkbox" value="${s.id}" ${ (plan.strategies||[]).includes(s.id) ? "checked" : "" }> ${s.name} · ${s.research_status} · not approved</label>`).join("");
  view.innerHTML = `<article class="card"><h2>This week ${week.week||""}</h2><p>Chosen aim: ${week.aim_percent==null?"not set":week.aim_percent+"%"}.</p><p>${week.paper_note||""}</p><p class="muted">Approved alerts this week: ${week.approved_alerts}. Simulated trades: ${week.simulated_trades}. A target does not force a signal.</p></article><form id="planform" class="card"><h2>Plan</h2><p id="plannote" role="status"></p><label>Mode <select id="mode"><option value="auto">Auto: evaluate every compatible strategy</option><option value="selected">Selected strategies only</option></select></label><div class="checks">${options}</div><label>Minimum evidence grade <input id="grade" type="number" min="0" max="100" value="${plan.min_evidence_grade||0}"></label><p class="muted">This is a checklist score, not a probability of profit.</p><label>Weekly aim percent <input id="aim" type="number" min="0" max="100" step="any" value="${plan.weekly_aim_percent??""}"></label><label>Weekly loss limit percent <input id="loss" type="number" min="0" max="100" step="any" value="${plan.weekly_loss_limit_percent??""}"></label><label>Per-trade risk percent <input id="risk" type="number" min="0" max="100" step="any" value="${plan.risk_per_trade_percent??""}"></label><p class="muted">Style cap ${body.style_cap==null?"not set":body.style_cap+"%"}. A higher number is rejected. Currency stays ${body.currency||"unset"} and is not converted.</p><label><input id="research" type="checkbox" ${plan.research_alerts?"checked":""}> Optional research notes in the app. Off by default. These are not trade alerts.</label><button type="submit">Save plan</button></form>`;
  document.getElementById("mode").value = plan.mode || "auto";
  document.getElementById("planform").onsubmit = async (event) => {
    event.preventDefault();
    const strategies = [...document.querySelectorAll("#planform input[type=checkbox][value]")].filter(box => box.checked).map(box => box.value);
    const payload = {mode: document.getElementById("mode").value, strategies, min_evidence_grade: document.getElementById("grade").value, weekly_aim_percent: document.getElementById("aim").value, weekly_loss_limit_percent: document.getElementById("loss").value, risk_per_trade_percent: document.getElementById("risk").value, research_alerts: document.getElementById("research").checked, markets: ["BTCUSDT","ETHUSDT","XAUUSD"]};
    const saved = await fetch("/api/plan", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
    const result = await saved.json();
    document.getElementById("plannote").textContent = saved.ok ? ((result.notes||[]).join(" ") || "Plan saved.") : "Your plan could not be saved. Please retry.";
  };
}
async function inboxPage(){
  const response = await fetch("/api/notifications", {credentials:"same-origin"});
  if (response.status === 401) { view.innerHTML = `<article class="card"><h2>Sign in required</h2><p><a href="/login">Sign in</a> to see your inbox.</p></article>`; return; }
  const body = await response.json();
  const rows = body.items || [];
  const list = rows.map(item => `<article class="card"><h2>${item.symbol || "Desk"} · ${item.label}</h2><p>${item.message || ""}</p><p class="muted">${item.kind} · ${item.strategy || "no strategy"} ${item.version || ""} · ${item.read ? "read" : "unread"} · ${item.created_ms ? new Date(item.created_ms).toISOString() : ""}</p>${item.actionable ? "" : "<p>Not an approved trade.</p>"}<button type="button" data-id="${item.id}">Mark read</button></article>`).join("");
  view.innerHTML = `<p role="status">${body.unread || 0} unread.</p>${list || "<article class='card'><h2>No notifications</h2><p>A quiet scan is recorded once a day. A research note appears only if you opted in. Nothing here is a trade alert unless a strategy has been approved. None has.</p></article>"}<button id="readall" type="button">Mark all read</button>`;
  const refresh = async (id) => { await fetch("/api/notifications/read", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify(id ? {id} : {})}); inboxPage(); };
  document.getElementById("readall").onclick = () => refresh(null);
  document.querySelectorAll("[data-id]").forEach(button => { button.onclick = () => refresh(button.dataset.id); });
}
async function load(){
  if (path === "/notifications") return inboxPage();
  if (path === "/plan") return planPage();
  if (path === "/scanner") return scannerPage();
  if (path === "/learn" || path === "/indicators") return learnPage();
  if (path === "/trading") return terminal();
  if (path === "/" || path === "/overview") return overview();
  if (path === "/signals") return signals();
  if (path === "/onboarding" || path === "/settings") return settings();
  if (path === "/portfolio" || path === "/activity") return paperPages();
  if (path === "/research") return researchLab();
  if (path === "/strategies") {
    const catalog = await fetch("/api/profiles").then(r=>r.json());
    const styles = (catalog.profiles||[]).map(p => `<article class="card"><h2>${p.name}</h2><p>${p.role}. ${p.purpose}</p><p class="muted">${p.confirmation} Risk cap ${p.risk_per_trade_percent}% per trade. Minimum reward/risk ${p.min_rr}. At most ${p.max_trades_per_day} trades a day in the Awuru account defaults. Not a promoted strategy.</p></article>`).join("");
    view.innerHTML = `<article class="card"><h2>E1 Donchian-20</h2><p>Breakout on the prior 20 completed bars. Failed benchmark on BTC and ETH. Research observation only. Not promoted and not re-tuned.</p></article><article class="card"><h2>Registered strategies</h2><div id="reg">Loading the registry.</div></article>${styles}<p class="muted">${catalog.note||""} ${catalog.excluded||""}</p>`;
    const registry = await fetch("/api/registry", {credentials:"same-origin"}).then(r => r.ok ? r.json() : {strategies:[]});
    const box = document.getElementById("reg");
    if (box) box.innerHTML = (registry.strategies||[]).map(s => `<div class="row"><span>${s.name}</span><span>${s.research_status}</span></div><div class="muted">${s.instruments.join(", ")} · ${s.timeframe}. ${s.evidence} Promoted: no.</div>`).join("") || "<p>The registry could not be loaded.</p>";
    return;
  }
  if (path === "/risk") return riskPage();
  if (path === "/system") return systemPage();
  view.innerHTML = `<article class="card"><h2>${titles[path]||"Aureon"}</h2><p>This page has no separate data source yet.</p></article>`;
}
async function paperPages(){
  const p = await fetch("/api/paper-status").then(r=>r.json()).catch(()=>({open:null, rows:[], observations:[], label:""}));
  const me = await fetch("/api/me").then(r=>r.ok?r.json():null);
  const code = me && me.profile && me.profile.currency;
  const bias = new Set(["LONG_BIAS","SHORT_BIAS","WAIT","NEUTRAL"]);
  const trades = (p.rows||[]).filter(r => r.side && !bias.has(r.side));
  const open = p.open && p.open.side && !bias.has(p.open.side) ? p.open : null;
  const observations = p.observations || [];
  const obsNote = observations.length ? `<p class="muted">${observations.length} research observation${observations.length===1?"":"s"} saved. ${label(observations[observations.length-1].side||"")} is not a holding and not an order.</p>` : "";
  if (path === "/portfolio") {
    const body = open
      ? `<div class="row"><span>Paper position</span><span>${open.asset} ${open.side}</span></div><div class="row"><span>Entry</span><span>${open.entry_price}</span></div><p class="muted">Recorded paper order. ${p.label||""}</p>`
      : `<p>No open paper position.</p><p class="muted">A bullish or bearish research state is not a holding. Nothing is shown as a position until an order side is recorded.</p>${obsNote}`;
    view.innerHTML = `<article class="card"><h2>Portfolio</h2><div class="row"><span>Configured paper capital</span><span>${money(me && me.profile && me.profile.capital, code||"")}</span></div>${body}</article>`;
    return;
  }
  const list = trades.map(r => `<div class="row"><span>${r.type}</span><span>${r.asset||""} ${r.side||""}</span></div>`).join("");
  view.innerHTML = `<article class="card"><h2>Orders and trade history</h2>${list || "<p>No recorded paper orders.</p>"}<p class="muted">Signal evaluations and directional observations are not listed as trades. ${p.label||""}</p>${obsNote}</article>`;
}
async function riskPage(){
  const me = await fetch("/api/me").then(r=>r.ok?r.json():null);
  const profile = (me && me.profile) || {};
  view.innerHTML = `<article class="card"><h2>Risk</h2><div class="row"><span>Active style</span><span>${profile.signal_style_name||"Not selected"}</span></div><div class="row"><span>Risk posture</span><span>${profile.risk_mode||"unset"}</span></div><div class="row"><span>Max risk per trade</span><span>${profile.max_risk_pct==null?"Not set":profile.max_risk_pct+"%"}</span></div><div class="row"><span>Max daily loss</span><span>${profile.max_daily_loss_percent==null?"Not set":profile.max_daily_loss_percent+"%"}</span></div><div class="row"><span>Max open risk</span><span>${profile.max_open_risk_percent==null?"Not set":profile.max_open_risk_percent+"%"}</span></div><div class="row"><span>Minimum reward/risk</span><span>${profile.min_rr==null?"Not set":profile.min_rr}</span></div><p class="muted">These caps come from the selected Awuru account style. Apex per-trade risk is 2.5%. A 4% figure, where shown, is the style's daily-loss ceiling, not the per-trade limit. Production remains WAIT_DEFAULT, so this page does not place an order.</p></article>`;
}
async function systemPage(){
  const h = await fetch("/health").then(r=>r.json());
  const row = (name, value) => `<div class="row"><span>${name}</span><span>${value}</span></div>`;
  const market = h.market_data && h.market_data.BTCUSDT ? h.market_data.BTCUSDT.status + " / " + (h.market_data.ETHUSDT ? h.market_data.ETHUSDT.status : "unknown") : (h.market_data || "unknown");
  const note = h.notification && h.notification.pipeline ? h.notification.pipeline : (typeof h.notification === "string" ? h.notification : "unknown");
  view.innerHTML = `<article class="card"><h2>System</h2>${row("Process", h.process||"unknown")}${row("BTC / ETH", market)}${row("Notifications", note)}${row("Ledger", h.ledger||"unknown")}${row("Strategy", h.strategy_status||"unknown")}${row("Broker", String(h.broker))}${row("Build", h.build_commit||"unknown")}${row("Worker heartbeat", h.worker && h.worker.last_beat_ms ? new Date(h.worker.last_beat_ms).toISOString() : "unknown")}</article><p class="muted">A missing field stays unknown. Trade alerts stay blocked while no strategy is approved.</p>`;
}
async function settings(){
  const me = await fetch("/api/me").then(r => r.ok ? r.json() : null);
  const catalog = await fetch("/api/profiles").then(r=>r.json());
  if (!me) {
    view.innerHTML = `<article class="card"><h2>Sign in required</h2><p><a href="/login">Sign in</a> or <a href="/register">create an account</a>.</p></article>`;
    return;
  }
  const prefs = me.prefs || {markets:["BTCUSDT","ETHUSDT","XAUUSD"]};
  const has = (m) => (prefs.markets||[]).includes(m) ? "checked" : "";
  const profile = me.profile || {};
  const styles = (catalog.profiles||[]).map(p => `<label><input type="radio" name="style" value="${p.key}" ${profile.signal_style===p.key?"checked":""}> ${p.name} — ${p.risk_mode}. ${p.confirmation}</label>`).join("");
  const currencies = (catalog.currencies||[]).map(c => `<option value="${c}" ${profile.currency===c?"selected":""}>${c}</option>`).join("");
  view.innerHTML = `<article class="card"><h2>${path==="/onboarding"?"Choose a signal style":"Signal style"}</h2><p class="muted">${catalog.note||""}</p><div class="styles">${styles}</div></article><article class="card"><h2>Base currency and capital</h2><div class="field"><span>Currency</span><select id="currency"><option value="">Not set</option>${currencies}</select></div><div class="field"><span>Paper capital</span><input id="capital" type="number" min="0" step="any" value="${profile.capital??""}"></div><p class="muted">Saving a currency does not convert the stored amount. Market quotes stay in USDT or USD/oz.</p></article><article class="card"><h2>Markets</h2><div class="checks"><label><input type="checkbox" id="btc" ${has("BTCUSDT")}> BTCUSDT · 15m</label><label><input type="checkbox" id="eth" ${has("ETHUSDT")}> ETHUSDT · 15m</label><label><input type="checkbox" id="gold" ${has("XAUUSD")}> XAUUSD · 1h research</label></div></article><article class="card"><h2>Notifications and risk</h2><div class="checks"><label><input type="checkbox" id="exp" ${profile.experimental_alerts?"checked":""}> Experimental alerts</label><label><input type="checkbox" id="digest" ${profile.daily_report!==false?"checked":""}> Daily digest</label></div><div class="field"><span>Max risk per trade %</span><input id="risk" type="number" step="0.1" min="0" value="${profile.max_risk_pct??""}"></div><p class="muted">Risk cannot be set above the active style cap. These caps do not guarantee protection from losses. Production is WAIT_DEFAULT, so no trade alert is sent until a strategy is promoted. Turning experimental alerts on does not bypass that. Telegram is ${me.telegram_verified?"verified":"not verified"}.</p><button id="tglink" type="button">Create a one-time Telegram link</button><p id="tglinkout" class="muted"></p></article><p><button id="saveall" type="button">Save</button> <button id="skip" type="button">Continue without optional alerts</button> <button id="out" type="button">Sign out</button></p><p id="savedp" class="muted"></p>`;
  async function save(go){
    const style = (document.querySelector("input[name=style]:checked") || {}).value;
    const markets = [];
    if (document.getElementById("btc").checked) markets.push("BTCUSDT");
    if (document.getElementById("eth").checked) markets.push("ETHUSDT");
    if (document.getElementById("gold").checked) markets.push("XAUUSD");
    const body = {
      signal_style: style,
      currency: document.getElementById("currency").value,
      capital: document.getElementById("capital").value,
      max_risk_pct: document.getElementById("risk").value,
      experimental_alerts: document.getElementById("exp").checked,
      daily_report: document.getElementById("digest").checked
    };
    const pref = await fetch("/api/prefs", {method:"POST", headers:{"Content-Type":"application/json"}, credentials:"same-origin", body: JSON.stringify({markets})});
    const prof = await fetch("/api/profile", {method:"POST", headers:{"Content-Type":"application/json"}, credentials:"same-origin", body: JSON.stringify(body)});
    const data = await prof.json().catch(()=>({}));
    document.getElementById("savedp").textContent = prof.ok && pref.ok ? "Saved. Active style and currency are stored on this account." : "Save failed.";
    if (prof.ok && go) location.href = "/overview";
    return data;
  }
  document.getElementById("saveall").onclick = () => save(path === "/onboarding");
  document.getElementById("skip").onclick = () => { location.href = "/overview"; };
  document.getElementById("tglink").onclick = async () => {
    const r = await fetch("/api/telegram/link", {method:"POST", headers:{"Content-Type":"application/json"}, credentials:"same-origin", body: "{}"});
    const d = await r.json();
    document.getElementById("tglinkout").textContent = r.ok ? "Open Telegram and start the bot with the token. The link is ready." : "Link failed.";
    if (r.ok && d.token) document.getElementById("tglinkout").textContent = "Open: https://t.me/AureonLabBot?start=" + d.token;
  };
  document.getElementById("out").onclick = async () => { await fetch("/api/logout", {method:"POST", credentials:"same-origin"}); location.href = "/"; };
}
load();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)


def _account_day(tzname):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        zone = ZoneInfo(tzname or "Africa/Lagos")
    except Exception:
        zone = ZoneInfo("UTC")
    return datetime.now(zone).date().isoformat()


def _digest_text(user):
    from ops.profiles import evaluate
    profile = user.get("profile") or {}
    markets = (user.get("prefs") or {}).get("markets") or ["BTCUSDT", "ETHUSDT"]
    lines = [
        f"Aureon daily · {profile.get('signal_style_name') or 'no signal style'}",
        f"Base currency {profile.get('currency') or 'not set'}. Amounts are not converted.",
    ]
    directional = False
    for symbol in markets:
        if symbol not in {"BTCUSDT", "ETHUSDT", "XAUUSD"}:
            continue
        e1, sma, rsi, fresh = _research_votes(symbol)
        decision = evaluate(profile.get("signal_style"), e1, sma, rsi, fresh, symbol)
        if decision.get("decision") in {"LONG_BIAS", "SHORT_BIAS"}:
            directional = True
        lines.append(f"{symbol}: {decision.get('decision')} — {decision.get('reason')}")
    if not directional:
        lines.append("No qualifying directional eligibility.")
    lines.append("Production remains WAIT_DEFAULT. This is not an order.")
    return "\n".join(lines)


def _deliver_digest(user):
    """A digest is not an approved signal. The empty registry blocks the send."""
    from ops.delivery import authorize
    from ops.users import record_digest

    profile = user.get("profile") or {}
    if not profile.get("daily_report", True):
        return {"ok": False, "reason": "opted_out"}
    day = _account_day(profile.get("timezone"))
    if profile.get("last_digest_day") == day:
        return {"ok": True, "duplicate": True, "day": day}
    event = {
        "state": "RESEARCH_OBSERVATION",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "strategy": "digest",
        "version": "digest",
        "fresh": False,
        "event_id": f"digest:{user.get('id')}:{day}",
        "text": _digest_text(user),
    }
    decision = authorize(event, user, now_ms=int(time.time() * 1000))
    record_digest(user["id"], day, decision["reason"])
    return {"ok": False, "delivered": False, "reason": decision["reason"], "day": day}


@app.post("/api/digest")
def digest():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.users import get
    user = get(user_id)
    if not user:
        return jsonify({"error": "not_found"}), 404
    result = _deliver_digest(user)
    status = 400 if result.get("reason") == "opted_out" else 200
    return jsonify(result), status


def _digest_loop():
    while True:
        try:
            from ops.users import list_users
            for user in list_users():
                _deliver_digest(user)
        except Exception:
            pass
        time.sleep(3600)


threading.Thread(target=_digest_loop, daemon=True).start()
