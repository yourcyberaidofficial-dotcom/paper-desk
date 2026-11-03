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
    "/research", "/portfolio", "/risk", "/activity", "/live", "/system", "/settings", "/onboarding",
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
    if "aureon_request_id" not in request.environ:
        request.environ["aureon_request_id"] = os.urandom(8).hex()


@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
    response.headers["X-Request-Id"] = request.environ.get("aureon_request_id", "")
    return response

@app.get("/api/coverage")
def coverage():
    from ops.worker import COVERAGE, pair_availability
    monitor = worker.last_monitor or {}
    from ops.customer_release import diagnostic_monitor
    public = diagnostic_monitor(monitor) or {}
    return jsonify({
        "pairs": [{"symbol": symbol, "interval": interval} for symbol, interval in COVERAGE],
        "availability": pair_availability(),
        "last_monitor_ms": getattr(worker, "last_monitor_ms", 0) or None,
        "evaluations": public.get("evaluations") or [],
        "delivered": monitor.get("delivered"),
        "error": public.get("error"),
    })


@app.get("/api/data-coverage")
def data_coverage():
    from ops.market_data import public_report
    return jsonify(public_report())


def _worker_public():
    beat = worker.last_beat_ms or 0
    heartbeat_age = None if not beat else max(0, int(time.time() * 1000) - beat)
    if not beat:
        worker_status = "unknown"
    elif getattr(worker, "last_monitor_error", None):
        worker_status = "error"
    elif heartbeat_age > 180_000:
        worker_status = "stale"
    else:
        worker_status = "beating"
    return {
        "last_beat_ms": beat or None,
        "heartbeat_age_ms": heartbeat_age,
        "status": worker_status,
        "last_monitor_ms": getattr(worker, "last_monitor_ms", 0) or None,
        "last_monitor": __import__("ops.customer_release", fromlist=["diagnostic_monitor"]).diagnostic_monitor(getattr(worker, "last_monitor", None)),
        "last_monitor_error": getattr(worker, "last_monitor_error", None),
        "healthy": worker_status == "beating",
    }


@app.get("/health")
def health():
    markets = market_snapshot()
    report = _market_report(markets)
    promoted = _promotion_state()
    fresh = report["BTCUSDT"]["status"] == "fresh" and report["ETHUSDT"]["status"] == "fresh"
    withheld = report["BTCUSDT"]["status"] == "withheld" or report["ETHUSDT"]["status"] == "withheld"
    return jsonify({
        "status": "rights_withheld" if withheld else ("ok" if fresh else "degraded"),
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
        "worker": _worker_public(),
        "qualification": _qualification_public(),
    })


def _promotion_state():
    from ops.delivery import load_promotions
    return "present" if load_promotions() else "empty"


def _qualification_public():
    from ops.qualification import summary
    return summary()


def _market_report(snapshot):
    from ops.data_rights import MESSAGE, is_rights_reason

    out = {}
    now_ms = int(time.time() * 1000)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        row = (snapshot or {}).get(symbol) or {}
        if is_rights_reason(row.get("reason")) or row.get("rights_status") in {"rights_unconfirmed", "prohibited", "restricted", "fixture_only"}:
            out[symbol] = {
                "status": "withheld",
                "rights_status": row.get("rights_status") or "rights_unconfirmed",
                "display_permission": row.get("display_permission"),
                "retention_permission": row.get("retention_permission"),
                "research_permission": row.get("research_permission"),
                "decision_permission": row.get("decision_permission"),
                "source_reachable": "not_checked",
                "feed_freshness": "not_applicable",
                "reason": "commercial_use_unverified",
                "message": MESSAGE,
                "last_close_time_ms": None,
                "source": "withheld",
            }
            continue
        close_ms = row.get("close_time_ms")
        checked = row.get("checked_at_ms") or now_ms
        if not isinstance(close_ms, (int, float)):
            status = "unknown"
        elif checked - close_ms <= 15 * 60 * 1000 and close_ms < checked:
            status = "fresh"
        else:
            status = "stale"
        out[symbol] = {
            "status": status,
            "last_close_time_ms": close_ms,
            "source": row.get("source") or "unknown",
            "kind": "completed_kline",
            "not_a_quote": True,
            "desk_snapshot": False,
            "note": "Independent completed-kline check from the Binance spot REST klines endpoint. Not a quote and not the desk snapshot.",
        }
    scan = getattr(worker, "last_monitor", None) or {}
    gold = [row for row in (scan.get("evaluations") or []) if row.get("symbol") == "XAUUSD"]
    out["XAUUSD"] = {
        "status": "not_shown",
        "source_reachable": "not_checked",
        "rows": [{"interval": row.get("interval")} for row in gold],
        "note": "A verified live reading is not available.",
    }
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
    from ops.customer_release import candles_released, unavailable_candles
    if not candles_released(symbol, interval):
        return jsonify(unavailable_candles(symbol, interval))
    if symbol in {"BTCUSDT", "ETHUSDT"} and interval in {"1m", "3m", "15m", "1h"}:
        from ops.bars import to_chart_candles
        from ops.desk_snapshot import observe
        now_ms = int(time.time() * 1000)
        try:
            limit = min(int(request.args.get("limit", 100)), 200)
        except ValueError:
            limit = 100
        snap = observe(symbol, interval, now_ms)
        loaded = list(snap.get("_loaded") or [])
        return jsonify({
            "symbol": symbol,
            "interval": interval,
            "source": "binance-public",
            "label": "WATCH ONLY",
            "kind": "completed_bar",
            "not_a_quote": True,
            "candles": to_chart_candles(loaded)[-limit:],
            "snapshot_id": snap.get("snapshot_id"),
            "reading_version": snap.get("reading_version"),
            "candle_semantics": snap.get("candle_semantics"),
            "quality": snap.get("quality"),
        })
    return jsonify(fetch_klines(symbol, interval))


@app.get("/api/market")
def market():
    blocked = _limited()
    if blocked:
        return blocked
    from ops.customer_release import any_customer_display, unavailable_quote
    if not any_customer_display():
        return jsonify({symbol: unavailable_quote(symbol) for symbol in ("BTCUSDT", "ETHUSDT")})
    return jsonify(market_snapshot())


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
    from ops.customer_release import any_customer_display
    if not any_customer_display():
        return jsonify({"production": "WAIT_DEFAULT", "customer_status": "reading_unavailable", "broker": False, "paper_only": True})
    return jsonify(engine.snapshot())


@app.get("/api/events")
@require_token
def events():
    from ops.customer_release import redact_public_numbers
    return jsonify(redact_public_numbers(ledger.read()[-50:]))


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
    from ops.customer_release import redact_public_numbers
    return jsonify({"rows": redact_public_numbers(rows[-limit:]), "total": len(rows)})


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
    except PermissionError:
        from ops.data_rights import MESSAGE
        return jsonify({"ok": False, "reason": "commercial_use_unverified", "message": MESSAGE, "trades": []})
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
    except PermissionError:
        from ops.data_rights import MESSAGE
        return jsonify({"ok": False, "reason": "commercial_use_unverified", "message": MESSAGE})
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
            from ops.customer_release import redact_public_numbers
            return jsonify(redact_public_numbers({
                "open": shown["open"],
                "rows": shown["trades"][-10:],
                "observations": shown["observations"][-8:],
                "label": "Research notes are not orders.",
                "broker": False,
                "note": "A directional research observation is not a holding or an order.",
            }))
        except Exception as exc:
            return jsonify({"open": None, "rows": [], "label": "Research notes are not orders.", "broker": False, "error": "unavailable"})
    return jsonify({"open": None, "rows": [], "label": "Research notes are not orders.", "broker": False})


def _session_user():
    from ops.users import get
    user_id = session.get("user_id")
    if not user_id:
        return None, None
    return user_id, get(user_id)


@app.get("/api/paper/book")
def paper_book():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.paperbook import summary
    return jsonify(summary(user_id))


@app.post("/api/paper/orders")
def paper_open():
    user_id, user = _session_user()
    if not user_id or not user:
        return jsonify({"error": "unauthorized"}), 401
    from ops.paperbook import open_order, opportunity_row
    body = request.json or {}
    row = opportunity_row(user_id, body.get("opportunity_id"))
    if not row:
        return jsonify({"ok": False, "reason": "missing_opportunity"}), 404
    user["id"] = user_id
    result = open_order(user, row, int(time.time() * 1000))
    return jsonify(result), (200 if result.get("ok") else 409)


@app.post("/api/paper/close")
def paper_close():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.paperbook import close_order
    body = request.json or {}
    result = close_order(user_id, body.get("order_id"), body.get("exit_price"), int(time.time() * 1000))
    return jsonify(result), (200 if result.get("ok") else 409)


@app.get("/api/autopilot")
def autopilot_state():
    user_id, user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.autopilot import view
    from ops.paperbook import summary
    state = view(user)
    orders = summary(user_id)["orders"]
    state["automated_orders"] = sum(1 for row in orders if row.get("opened_by") == "autopilot")
    state["open_automated"] = [
        {"id": row.get("id"), "symbol": row.get("symbol"), "direction": row.get("direction"), "status": row.get("status")}
        for row in orders if row.get("opened_by") == "autopilot" and row.get("status") == "open"
    ]
    worker_state = _worker_public()
    state["worker"] = {key: worker_state.get(key) for key in ("status", "healthy", "heartbeat_age_ms", "last_monitor_error")}
    from ops.autopilot import presentation
    from ops.desk_state import product_gates
    state.update(presentation(state, worker_state.get("healthy") is True, open_positions=len(state["open_automated"]), gates=product_gates()))
    if not state["enabled"] or state["status"] == "off":
        state["health"] = "off"
    elif worker_state.get("healthy") is not True:
        state["health"] = "not_confirmed"
    else:
        state["health"] = "confirmed"
    state["health_note"] = state["facing_note"]
    return jsonify(state)


@app.get("/api/platform")
def platform_api():
    from ops.desk_state import platform_state
    return jsonify(platform_state(_worker_public()))


@app.post("/api/autopilot")
def autopilot_act():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.autopilot import act
    body = request.json or {}
    result = act(user_id, body.get("action"), int(time.time() * 1000), confirm=body.get("confirm") is True, max_orders_per_day=body.get("max_orders_per_day"))
    return jsonify(result), (200 if result.get("ok") else 409)


@app.get("/api/lab")
def lab_state():
    user_id, user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.academy import catalog, courses, public_rules, suggestions
    from ops.autopilot import presentation, view
    from ops.desk_state import product_gates
    from ops.paperbook import summary
    from ops.profiles import canonical_style, get_profile
    lab = user.get("lab") if isinstance(user.get("lab"), dict) else {}
    book = summary(user_id)
    persona = get_profile(canonical_style((user.get("profile") or {}).get("signal_style")))
    auto = view(user)
    opened = sum(1 for row in (book.get("orders") or []) if row.get("opened_by") == "autopilot" and row.get("status") == "open")
    auto.update(presentation(auto, _worker_public().get("healthy") is True, open_positions=opened, gates=product_gates()))
    trades = (book.get("performance") or {}).get("trades") or 0
    journal = []
    for row in (book.get("orders") or [])[-8:]:
        journal.append({
            "id": row.get("id"),
            "symbol": row.get("symbol"),
            "opened_by": row.get("opened_by") or "account",
            "status": row.get("status"),
            "exit_kind": row.get("exit_kind"),
            "note": (row.get("events") or [{}])[-1].get("note") or row.get("note"),
        })
    return jsonify({
        "profile": user.get("profile") or {},
        "experience": lab.get("experience") or "not_stated",
        "objective": lab.get("objective") or "",
        "focus": lab.get("focus") or [],
        "completed_lessons": lab.get("completed_lessons") or [],
        "persona": {"name": persona.get("name"), "min_rr": persona.get("min_rr"), "risk_per_trade_percent": persona.get("risk_per_trade_percent"), "paper_timeframes": persona.get("paper_timeframes")} if persona else None,
        "autopilot": auto,
        "performance": book.get("performance"),
        "lessons": catalog(),
        "courses": courses(),
        "rules": public_rules(user),
        "journal": journal,
        "journal_notes": lab.get("journal_notes") or [],
        "improvement": suggestions(lab, book.get("performance")),
        "preferences": {"markets": (user.get("prefs") or {}).get("markets") or [], "plan_markets": (user.get("plan") or {}).get("markets")},
        "observation": "Not enough closed paper trades to describe a strength or a weakness." if trades < 5 else "Counts below are closed paper trades only. They are not a skill score and not a profitable strategy.",
        "note": "This page reads this account only. It does not create a strategy.",
    })


@app.post("/api/lab")
def lab_save():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.academy import catalog
    from ops.files import update_json
    from ops.users import ROOT
    body = request.json or {}
    experience = body.get("experience") if body.get("experience") in {"new", "developing", "independent"} else None
    objective = str(body.get("objective") or "")[:160]
    focus = [item for item in (body.get("focus") or []) if item in {"candles", "risk", "psychology", "prop"}][:4]
    completed = [str(item)[:40] for item in (body.get("completed_lessons") or [])][:40]
    rule = str(body.get("custom_rule") or "")[:400]
    reflection = str(body.get("journal_note") or "")[:500]
    known = {lesson["id"] for lesson in catalog()}

    def apply(user):
        if not isinstance(user, dict):
            return {"unreadable": True}
        lab = user.get("lab") if isinstance(user.get("lab"), dict) else {}
        if experience:
            lab["experience"] = experience
        if "objective" in body:
            lab["objective"] = objective
        if "focus" in body:
            lab["focus"] = focus
        if "completed_lessons" in body:
            lab["completed_lessons"] = [item for item in completed if item in known]
        if rule:
            rows = list(lab.get("custom_rules") or [])
            rows.append({"text": rule, "verified": False})
            lab["custom_rules"] = rows[-10:]
        if reflection:
            notes = list(lab.get("journal_notes") or [])
            notes.append({"text": reflection, "inferred_behaviour": False})
            lab["journal_notes"] = notes[-20:]
        user["lab"] = lab
        return user

    update_json(ROOT / f"{user_id}.json", apply, None)
    return jsonify({"ok": True})


def _remember(key, ttl, loader):
    from ops.data_rights import network_block

    source_id = None
    if isinstance(key, tuple) and key and key[0] == "binance":
        source_id = "binance_spot_rest_klines"
    elif isinstance(key, tuple) and key and key[0] == "xaus":
        source_id = "xaus_public_chart"
    if source_id:
        blocked = network_block(source_id, "display")
        if blocked:
            return blocked
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

    if interval in {"1m", "3m"}:
        return {
            "ok": False,
            "bars": [],
            "reason": "xau_minute_unlicensed",
            "blocked": "xau_minute_unlicensed",
            "interval": interval,
            "quote_semantics": "unavailable",
        }
    interval = interval if interval in {"15m", "1h", "4h", "1d"} else "1h"
    if interval in {"15m", "1h"}:
        from ops.terminal_route import load_gold_ohlc
        try:
            loaded = load_gold_ohlc(interval, now_ms)
        except Exception as exc:
            return {"ok": False, "bars": [], "reason": type(exc).__name__, "interval": interval, "quote_semantics": "ohlc_not_bid_ask"}
        if isinstance(loaded, tuple):
            return {"ok": False, "bars": [], "reason": loaded[1], "interval": interval, "quote_semantics": "ohlc_not_bid_ask"}
        semantics = (loaded[-1].get("quote_semantics") if loaded else None) or "ohlc_not_bid_ask"
        return {
            "ok": bool(loaded),
            "bars": loaded or [],
            "provider": "xaus.com",
            "quote_semantics": semantics,
            "interval": interval,
        }
    try:
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
    except Exception as exc:
        return {"ok": False, "bars": [], "reason": type(exc).__name__, "interval": interval, "quote_semantics": "ohlc_not_bid_ask"}
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
        if series.get("reason") == "commercial_use_unverified" or series.get("rights_status"):
            empty.update(state="DATA_UNAVAILABLE", reason="commercial_use_unverified", interval="1h", evaluated=False, rights_status=series.get("rights_status"))
            return empty
        higher = _gold_bars("4h", now_ms) if series.get("ok") else {"bars": []}
        if not series.get("ok") or not series.get("bars"):
            empty.update(state="DATA_UNAVAILABLE", reason=series.get("reason") or "GOLD_FEED_UNAVAILABLE", interval="1h")
            return empty
        bars, higher_bars, interval = series["bars"], higher.get("bars") or [], "1h"
        from ops.data_rights import screen_bars
        bars = screen_bars("xaus_public_chart", bars)
        higher_bars = screen_bars("xaus_public_chart", higher_bars)
        if not bars:
            empty.update(state="DATA_UNAVAILABLE", reason="commercial_use_unverified", interval="1h", evaluated=False)
            return empty
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
            empty.update(state="DATA_UNAVAILABLE", reason=entry.get("reason") or higher.get("reason") or "DATA_UNAVAILABLE", interval="15m", evaluated=False, rights_status=entry.get("rights_status"))
            return empty
        from ops.data_rights import screen_bars
        bars = screen_bars("binance_spot_rest_klines", entry.get("bars") or [])
        higher_bars = screen_bars("binance_spot_rest_klines", higher.get("bars") or [])
        if not bars:
            empty.update(state="DATA_UNAVAILABLE", reason="commercial_use_unverified", interval="15m", evaluated=False)
            return empty
        interval = "15m"
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
    from ops.data_rights import MESSAGE, network_block

    blocked = network_block("xaus_public_chart", "display")
    if blocked:
        return {
            "symbol": "XAUUSD",
            "instrument": "XAUUSD_SPOT",
            "source": "withheld",
            "kind": "indicative_spot",
            "quote_semantics": "indicative_mid",
            "price": None,
            "fresh": False,
            "status": "withheld",
            "rights_status": blocked.get("rights_status"),
            "display_permission": blocked.get("display_permission"),
            "source_reachable": "not_checked",
            "feed_freshness": "not_applicable",
            "reason": "commercial_use_unverified",
            "not_bid_ask": True,
            "not_a_candle": True,
            "note": MESSAGE,
            "message": MESSAGE,
        }
    from ops.feeds import xaus_spot
    from ops.gold_cache import load, save
    try:
        spot = _remember(("xaus", "spot"), 15, xaus_spot)
    except Exception as exc:
        spot = {"ok": False, "reason": type(exc).__name__}
    if spot.get("reason") == "commercial_use_unverified" or spot.get("rights_status"):
        return {
            "symbol": "XAUUSD",
            "price": None,
            "fresh": False,
            "status": "withheld",
            "reason": "commercial_use_unverified",
            "rights_status": spot.get("rights_status") or "rights_unconfirmed",
            "note": MESSAGE,
            "message": MESSAGE,
        }
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
        return {
            "symbol": "XAUUSD",
            "price": None,
            "close": None,
            "fresh": False,
            "status": "not_shown",
            "customer_status": "reading_unavailable",
            "quote_semantics": "indicative_mid",
            "not_bid_ask": True,
            "not_a_candle": True,
            "note": "A verified live reading is not available.",
        }
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
    from ops.customer_release import any_customer_display, customer_markets, candles_released, reading_released, verified, source_for, STATUS
    if not any_customer_display():
        return jsonify(customer_markets())
    from ops.desk_snapshot import headline_board, public_reading

    now_ms = int(time.time() * 1000)
    try:
        snaps, readings = headline_board(now_ms)
    except Exception:
        snaps, readings = [], []
    by_symbol = {snap.get("instrument"): (snap, readings[index] if index < len(readings) else {}) for index, snap in enumerate(snaps)}

    def row(symbol, row_id, frame, source=None):
        snap, reading = by_symbol.get(symbol) or ({}, {})
        semantics = (snap.get("candle_semantics") if snap else None)
        sampled = semantics == "spot_sample_not_bid_ask"
        sample = "spot_sample_not_bid_ask" if sampled else None
        display = dict((snap.get("display") or {}) if snap else {})
        if not candles_released(symbol, frame, sample):
            display = {
                "price": None,
                "close": None,
                "fresh": False,
                "quality": "unavailable",
                "timeframe": frame,
                "customer_status": "reading_unavailable",
                "note": STATUS,
            }
        elif isinstance(display.get("quote"), dict) and not verified(source_for(symbol, sample), "quote_display", symbol=symbol, interval=frame):
            display["quote"] = {"status": "reference_quote_unavailable", "price": None}
        shown = public_reading(reading) if reading else None
        if shown and not reading_released(symbol, frame, sample):
            shown = dict(shown)
            shown["entry"] = None
            shown["stop"] = None
            shown["target"] = None
            shown["decision"] = "WAIT"
            shown["direction_label"] = "neutral"
            shown["explanation"] = STATUS
            shown["customer_status"] = "reading_unavailable"
            shown["manual_paper"] = False
            shown["source_id"] = None
            shown["provider"] = None
        payload = {"id": row_id, "symbol": symbol, "status": "configured", "data": display, "reading": shown}
        if source and candles_released(symbol, frame, sample):
            payload["source"] = source
            payload["kind"] = "sampled_reference" if sampled else "completed_bar"
            payload["snapshot_id"] = snap.get("snapshot_id")
        return payload

    return jsonify({
        "markets": [
            row("BTCUSDT", "BTC", "15m"),
            row("ETHUSDT", "ETH", "15m"),
            row("XAUUSD", "GOLD", "1h", "xaus.com"),
        ],
        "broker": False,
        "production": "WAIT_DEFAULT",
        "customer_status": "reading_unavailable" if not any_customer_display() else None,
    })


@app.get("/api/triad")
def triad():
    from ops.customer_release import derived_withheld, reading_released
    symbol = request.args.get("symbol", "BTCUSDT")
    if not reading_released(symbol, "15m"):
        body = derived_withheld(symbol, "15m")
        body["note"] = "No eligible live reading is available. Adapted research states are not calculated from an unverified feed."
        return jsonify(body)
    from ops.awuru_triad import triad as align
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


@app.get("/api/qualification")
def qualification_api():
    if not _gate():
        return jsonify({"error": "unauthorized"}), 401
    from ops.qualification import catalog
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
    from ops.paperbook import as_fills
    return jsonify({"plan": plan, "week": week_status(plan, int(time.time() * 1000), as_fills(user_id)), "style_cap": cap, "currency": profile.get("currency")})


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
    from ops.customer_release import STATUS, reading_released
    interval = "1h" if symbol == "XAUUSD" else "15m"
    if not reading_released(symbol, interval, "spot_sample_not_bid_ask" if symbol == "XAUUSD" else None):
        from ops.profiles import get_profile
        spec = get_profile(profile.get("signal_style"))
        return jsonify({
            "customer_status": "reading_unavailable",
            "eligible": False,
            "reason": STATUS,
            "message": STATUS,
            "symbol": symbol,
            "fresh": False,
            "trading_policy": None if not spec else {
                "name": spec["name"],
                "risk_cap": spec["risk_per_trade_percent"],
                "min_rr": spec["min_rr"],
                "max_daily_loss_percent": spec["max_daily_loss_percent"],
                "note": "The terminal uses this risk policy. No live reading was used, and this is not a research-strategy result.",
            },
            "account": {
                "signal_style": profile.get("signal_style"),
                "signal_style_name": profile.get("signal_style_name"),
                "max_risk_pct": profile.get("max_risk_pct"),
                "currency": profile.get("currency"),
                "capital": profile.get("capital"),
                "experimental_alerts": profile.get("experimental_alerts", False),
            },
        })
    e1, sma, rsi, fresh = _research_votes(symbol)
    out = evaluate(profile.get("signal_style"), e1, sma, rsi, fresh, symbol)
    from ops.profiles import get_profile
    spec = get_profile(profile.get("signal_style"))
    out["trading_policy"] = None if not spec else {
        "name": spec["name"],
        "risk_cap": spec["risk_per_trade_percent"],
        "min_rr": spec["min_rr"],
        "max_daily_loss_percent": spec["max_daily_loss_percent"],
        "note": "The terminal uses this risk policy. The research-state line above is not a vote of the candle families and it does not size a trade.",
    }
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
    from ops.customer_release import derived_withheld, reading_released
    out = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        if not reading_released(symbol, "15m"):
            row = derived_withheld(symbol, "15m")
            row["timeframe"] = "15m"
            row["council"] = None
            out.append(row)
            continue
        from ops.council import council
        data = fetch_klines(symbol, "15m", limit=50)
        bars = [{"high": c["h"], "low": c["l"], "close": c["c"]} for c in data.get("candles") or [] if c.get("h") is not None]
        withheld = data.get("reason") == "commercial_use_unverified" or not bars
        states = research_states(bars) if bars and not withheld else []
        by = {s["strategy"]: s["direction"] for s in states}
        candle = (data.get("candles") or [{}])[-1].get("t") if bars else None
        out.append({
            "symbol": symbol,
            "timeframe": "15m",
            "fresh": not withheld,
            "rights_status": data.get("rights_status"),
            "reason": "commercial_use_unverified" if withheld else None,
            "limitation": data.get("message") if withheld else None,
            "council": None if withheld else council(by.get("E1-donchian-20", "WAIT"), by.get("SMA20-state", "WAIT"), by.get("RSI14-state", "WAIT"), True, candle),
        })
    if not reading_released("XAUUSD", "1h", "spot_sample_not_bid_ask") and not reading_released("XAUUSD", "1h"):
        row = derived_withheld("XAUUSD", "1h")
        row["timeframe"] = "1h"
        row["council"] = None
        out.append(row)
    else:
        from ops.council import council
        try:
            series = _gold_bars("1h", int(time.time() * 1000))
            if series.get("reason") == "commercial_use_unverified" or series.get("rights_status") or not series.get("ok"):
                out.append(derived_withheld("XAUUSD", "1h"))
            else:
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
            out.append({"symbol": "XAUUSD", "timeframe": "1h", "fresh": False, "error": type(exc).__name__, "reason": "GOLD_FEED_UNAVAILABLE", "council": None, "price": None})
    return jsonify({"markets": out, "customer_status": "reading_unavailable", "source": "research observation, not a live price"})


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
    from ops.customer_release import redact_public_numbers
    return jsonify({"signals": redact_public_numbers(rows), "note": "Assurance is not a win probability. Live prices are not included."})


@app.get("/api/notify-history")
def notify_history():
    rows = [r for r in reversed(ledger.read()) if r.get("type") == "notify"]
    from ops.customer_release import redact_public_numbers
    return jsonify({"deliveries": redact_public_numbers(rows[:30]), "note": "Accepted by Telegram is not proof the user read it."})


@app.get("/api/gold/signal")
def gold_signal():
    from ops.customer_release import derived_withheld, reading_released
    if not reading_released("XAUUSD", "1h") and not reading_released("XAUUSD", "1h", "spot_sample_not_bid_ask"):
        body = derived_withheld("XAUUSD", "1h")
        body["quote_semantics"] = "unavailable"
        return jsonify(body)
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
        "note": "XAUUSD 1-hour reading from the desk source. A sampled reference bar is not exchange OHLC. Not a paper order, not bid/ask, and not an approved signal.",
    })


@app.get("/api/gold/candles")
def gold_candles():
    from ops.bars import to_chart_candles

    interval = request.args.get("interval", "1h")
    if interval in {"1m", "3m"}:
        return jsonify({
            "symbol": "XAUUSD",
            "interval": interval,
            "candles": [],
            "blocked": "xau_minute_unlicensed",
            "error": "xau_minute_unlicensed",
            "quote_semantics": "unavailable",
            "note": "Licensed spot minute data is unavailable. A quote was not drawn as a candle, and a longer candle was not substituted.",
        })
    from ops.customer_release import candles_released, unavailable_candles
    sample = "spot_sample_not_bid_ask" if interval in {"15m", "1h"} else None
    if not candles_released("XAUUSD", interval, sample):
        return jsonify(unavailable_candles("XAUUSD", interval))
    if interval in {"15m", "1h"}:
        from ops.desk_snapshot import observe
        snap = observe("XAUUSD", interval, int(time.time() * 1000))
        series = list(snap.get("_loaded") or [])
        semantics = snap.get("candle_semantics") or "ohlc_not_bid_ask"
        sampled = semantics == "spot_sample_not_bid_ask"
        if not series:
            return jsonify({
                "symbol": "XAUUSD",
                "interval": interval,
                "candles": [],
                "error": snap.get("blocked_reason") or "GOLD_FEED_UNAVAILABLE",
                "quote_semantics": semantics,
                "snapshot_id": snap.get("snapshot_id"),
                "reading_version": snap.get("reading_version"),
                "kind": "sampled_reference" if sampled else "chart_ohlc",
                "note": "No complete sampled reference bar was returned. Nothing was invented." if sampled else "No chart bar was returned. Nothing was invented.",
            }), 502
        candles = to_chart_candles(series)[-180:]
        return jsonify({
            "symbol": "XAUUSD",
            "instrument": "XAUUSD_SPOT",
            "interval": interval,
            "source": "xaus.com",
            "kind": "sampled_reference" if sampled else "chart_ohlc",
            "quote_semantics": semantics,
            "count": len(candles),
            "candles": candles,
            "snapshot_id": snap.get("snapshot_id"),
            "reading_version": snap.get("reading_version"),
            "not_a_quote": True,
            "execution_grade": False,
            "reference_quote": "reference_quote_unavailable",
            "note": "Sampled indicative reference bars from five-minute spot prints. Not exchange OHLC, not a bid or ask, and not an execution price. Reference quote unavailable." if sampled else "Chart OHLC from xaus.com. Not a bid or ask and not an execution price. Reference quote unavailable.",
        })
    series = _gold_bars(interval, int(time.time() * 1000))
    if series.get("reason") == "commercial_use_unverified" or series.get("rights_status"):
        from ops.data_rights import MESSAGE
        return jsonify({
            "symbol": "XAUUSD",
            "interval": interval,
            "candles": [],
            "blocked": "commercial_use_unverified",
            "reason": "commercial_use_unverified",
            "rights_status": series.get("rights_status") or "rights_unconfirmed",
            "source_reachable": "not_checked",
            "feed_freshness": "not_applicable",
            "quote_semantics": "withheld",
            "note": MESSAGE,
            "message": MESSAGE,
        })
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
    payload = {
        "symbol": "XAUUSD",
        "instrument": "XAUUSD_SPOT",
        "interval": series.get("interval") or interval,
        "source": "xaus.com",
        "kind": "chart_ohlc",
        "quote_semantics": series.get("quote_semantics") or "ohlc_not_bid_ask",
        "count": len(candles),
        "partial_dropped": series.get("partial_dropped"),
        "candles": candles,
        "not_a_quote": True,
        "execution_grade": False,
        "note": "Chart OHLC from xaus.com. Not a bid or ask and not an execution price. A quote is not drawn as a bar.",
    }
    return jsonify(payload)


@app.get("/api/engine")
def engine_api():
    from ops.customer_release import derived_withheld, reading_released
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = "1h" if symbol == "XAUUSD" else "15m"
    sample = "spot_sample_not_bid_ask" if symbol == "XAUUSD" else None
    if not reading_released(symbol, interval, sample):
        return jsonify(derived_withheld(symbol, interval))
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
    discovery_path = ROOT / "docs" / "DISCOVERY_RESULTS.json"
    audit_path = ROOT / "docs" / "DATA_AUDIT.json"
    if discovery_path.exists():
        try:
            discovery = json.loads(discovery_path.read_text())
        except Exception:
            discovery = None
        if discovery:
            payload["discovery"] = {
                "version": discovery.get("version"),
                "decision": discovery.get("decision"),
                "approved_for_paper": discovery.get("approved_for_paper") or [],
                "holdout_opened_for": discovery.get("holdout_opened_for") or [],
                "protocol_sha256": discovery.get("protocol_sha256"),
                "software_sha": discovery.get("software_sha"),
                "multiple_testing": (discovery.get("protocol") or {}).get("multiple_testing"),
                "costs": (discovery.get("protocol") or {}).get("costs"),
                "markets": [
                    {
                        "symbol": market.get("symbol"),
                        "holdout": market.get("holdout"),
                        "development": market.get("development"),
                        "validation": market.get("validation"),
                        "benchmark_prefix": market.get("benchmark_prefix"),
                        "folds_on_prefix_signals": market.get("folds_on_prefix_signals"),
                        "approved_for_paper": False,
                    }
                    for market in discovery.get("markets") or []
                ],
            }
            states = []
            reasons = []
            for market in discovery.get("markets") or []:
                dev = market.get("development") or {}
                val = market.get("validation") or {}
                states.extend((dev.get("judgment"), val.get("judgment")))
                reasons.append(f"{market.get('symbol')} development {dev.get('judgment')} n={dev.get('trades')}; validation {val.get('judgment')} n={val.get('trades')}; holdout {market.get('holdout')}")
            label = "FAIL" if "FAIL" in states else ("BLOCKED" if "BLOCKED" in states else "RECORDED")
            payload["experiments"].append({
                "id": discovery.get("version"),
                "name": "Slow 4h trend hold",
                "decision": label,
                "reason": ". ".join(reasons) + ". Not an approved strategy.",
            })
    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text())
        except Exception:
            audit = None
        if audit:
            payload["data_audit"] = {
                "retained": [
                    {
                        "symbol": row.get("symbol"),
                        "interval": row.get("interval"),
                        "bars": (row.get("span") or {}).get("bars"),
                        "start": (row.get("span") or {}).get("start"),
                        "end": (row.get("span") or {}).get("end"),
                        "file_sha256": row.get("file_sha256"),
                        "gaps": row.get("gaps"),
                        "duplicates": row.get("duplicates"),
                        "invalid": row.get("invalid_ohlc_or_alignment"),
                        "limitation": row.get("limitation"),
                    }
                    for row in audit.get("retained") or []
                ],
                "desk_pairs_missing_history": [
                    f"{row['symbol']} {row['interval']}"
                    for row in audit.get("coverage") or []
                    if row.get("classification") == "missing_retained_history"
                ],
                "not_retained": audit.get("not_retained") or [],
            }
    return jsonify(payload)


@app.get("/api/research-signals")
def research_signals():
    from ops.customer_release import derived_withheld, reading_released
    symbol = request.args.get("symbol", "BTCUSDT")
    if symbol not in {"BTCUSDT", "ETHUSDT", "XAUUSD"}:
        return jsonify({"error": "symbol_not_allowed"}), 400
    interval = "1h" if symbol == "XAUUSD" else "15m"
    sample = "spot_sample_not_bid_ask" if symbol == "XAUUSD" else None
    if not reading_released(symbol, interval, sample):
        body = derived_withheld(symbol, interval)
        body["kind"] = "research_observation"
        body["label"] = "RESEARCH OBSERVATION — NOT VALIDATED"
        body["note"] = "No eligible live reading is available. A missing market permission is not a failed research strategy. Production remains WAIT_DEFAULT."
        return jsonify(body)
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
    from ops.customer_release import redact_public_numbers
    rows = worker.book.read()
    return jsonify(redact_public_numbers({"rows": rows[-50:], "total": len(rows), "label": "Research notes are not orders."}))


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
        try:
            worker.monitor()
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
    from ops.customer_release import any_customer_display, empty_desk, release_scan
    now_ms = int(time.time() * 1000)
    if not any_customer_display():
        body = empty_desk()
    else:
        from ops.desk_snapshot import desk_scan
        try:
            body = release_scan(desk_scan(now_ms))
        except Exception:
            body = {"markets": [], "notice": "The scan did not return a reading. No price was invented."}
    if not body.get("markets"):
        from ops.worker import pair_availability
        body["markets"] = []
        for row in pair_availability():
            minute = row["symbol"] == "XAUUSD" and row["interval"] in {"1m", "3m"}
            body["markets"].append({
                "symbol": row["symbol"],
                "interval": row["interval"],
                "price": None,
                "entry": None,
                "stop": None,
                "target": None,
                "approved": False,
                "evaluated": False,
                "scanner_state": "BLOCKED" if minute else "WAIT",
                "decision_label": "UNAVAILABLE" if minute else "WAIT",
                "status": "unavailable" if minute else "scanning",
                "blocked": "xau_minute_unlicensed" if minute else None,
                "message": row.get("reason") or "No reading was returned. No price was invented.",
                "reading_class": "unavailable" if minute else "insufficient",
                "autopilot_eligible": False,
                "probability": None,
            })
        body["notice"] = "The scan did not return a reading. No price was invented."
    user_id = session.get("user_id")
    if user_id:
        from ops.inbox import record_scan
        from ops.users import get
        plan = (get(user_id) or {}).get("plan") or {}
        record_scan(user_id, body, plan, now_ms)
    from ops.signal_book import remember_live
    remember_live(body)
    return jsonify(body)


@app.get("/api/desk")
def desk_api():
    if not _user_ok() and not _owner_ok():
        return jsonify({"error": "unauthorized"}), 401
    from ops.customer_release import any_customer_display, empty_desk, release_scan
    from ops.desk_snapshot import desk_scan
    now_ms = int(time.time() * 1000)
    if not any_customer_display():
        return jsonify(empty_desk())
    try:
        return jsonify(release_scan(desk_scan(now_ms)))
    except Exception as exc:
        return jsonify({"error": "unavailable", "reason": type(exc).__name__, "markets": [], "broker": False, "snapshots": []}), 502


@app.post("/api/desk/plan")
def desk_plan():
    """Review a live reading. This records a plan. It does not open an order."""
    user_id, user = _session_user()
    if not user_id or not user:
        return jsonify({"error": "unauthorized"}), 401
    body = request.json or {}
    symbol = str(body.get("symbol") or "")
    interval = str(body.get("interval") or "")
    from ops.data_rights import DESK
    from ops.customer_release import STATUS
    from ops.inbox import build_user_plan, record_desk_plan
    from ops.paperbook import opportunity_row, plan_preview
    if (symbol, interval) not in DESK:
        return jsonify({"ok": False, "reason": "unsupported", "order_opened": False, "broker": False, "entry": None, "stop": None, "target": None}), 400
    user = dict(user)
    user["id"] = user_id
    if body.get("authored") is not True:
        return jsonify({
            "ok": False,
            "reason": "reading_unavailable",
            "message": STATUS,
            "customer_status": "reading_unavailable",
            "entry": None,
            "stop": None,
            "target": None,
            "order_opened": False,
            "broker": False,
            "approved": False,
            "autopilot_eligible": False,
            "levels_persisted": False,
        })
    now_ms = int(time.time() * 1000)
    try:
        from ops.desk_snapshot import reading_for
        card = reading_for(symbol, interval, now_ms) or {}
    except Exception:
        card = {}
    built = build_user_plan(card, {**body, "symbol": symbol, "interval": interval})
    if not built.get("ok"):
        return jsonify({
            "ok": False,
            "reason": built.get("reason"),
            "order_opened": False,
            "broker": False,
            "levels_persisted": False,
            "autopilot_eligible": False,
            "approved": False,
            "entry": None,
            "stop": None,
            "target": None,
        })
    saved = record_desk_plan(user_id, user, built["plan"])
    stored = opportunity_row(user_id, saved.get("opportunity_id")) if saved.get("opportunity_id") else None
    plan_row = stored or built["plan"]
    preview = plan_preview(user, plan_row)
    return jsonify({
        "ok": bool(saved.get("opportunity_id")),
        "stored": bool(saved.get("stored")),
        "duplicate": bool(saved.get("duplicate")),
        "reason": saved.get("reason"),
        "opportunity_id": saved.get("opportunity_id"),
        "snapshot_id": (stored or {}).get("snapshot_id"),
        "reading_class": "manual_plan",
        "provenance": "user_authored",
        "source_id": "user_authored",
        "entry": plan_row.get("entry"),
        "stop": plan_row.get("stop"),
        "target": plan_row.get("target"),
        "explanation": (stored or {}).get("explanation") or built["plan"].get("explanation"),
        "invalidation": plan_row.get("invalidation"),
        "levels_persisted": saved.get("levels_persisted") is True,
        "paper": preview,
        "autopilot_eligible": False,
        "approved": False,
        "order_opened": False,
        "broker": False,
    })


@app.get("/api/workspace")
def workspace_api():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.customer_release import any_customer_display, empty_desk, release_scan
    from ops.desk_snapshot import desk_scan
    from ops.signal_book import read_events, remember_live
    from ops.users import get
    from ops.workspace import compose
    now_ms = int(time.time() * 1000)
    if not any_customer_display():
        body = empty_desk()
    else:
        try:
            body = release_scan(desk_scan(now_ms))
        except Exception:
            body = empty_desk()
    remember_live(body)
    from ops.leader_run import published_leaders
    body["leaders"] = published_leaders()
    return jsonify(compose(get(user_id) or {}, body, read_events()))


@app.get("/api/notifications")
def notifications_api():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.customer_release import redact_feed_view
    from ops.inbox import items, notice_view, unread_count
    now_ms = int(time.time() * 1000)
    return jsonify({"items": [redact_feed_view(notice_view(item, now_ms)) for item in items(user_id)], "unread": unread_count(user_id)})


@app.post("/api/notifications/read")
def notifications_read():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.inbox import mark_read
    event_id = (request.json or {}).get("id")
    return jsonify(mark_read(user_id, event_id or None))


@app.get("/api/inbox/settings")
def inbox_settings_get():
    user_id = session.get("user_id")
    if not user_id or not _user_ok():
        return jsonify({"error": "unauthorized"}), 401
    from ops.inbox import inbox_settings
    from ops.users import get
    return jsonify({"settings": inbox_settings(get(user_id) or {})})


@app.post("/api/inbox/settings")
def inbox_settings_save():
    user_id = session.get("user_id")
    if not user_id or not _user_ok():
        return jsonify({"error": "unauthorized"}), 401
    from ops.inbox import inbox_settings
    from ops.users import save_inbox_delivery
    saved = save_inbox_delivery(user_id, request.get_json(silent=True) or {})
    if not saved:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "settings": inbox_settings(saved)})


@app.post("/api/terminal/signal")
def terminal_signal():
    user_id = session.get("user_id")
    if not user_id or not _user_ok():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol") or "BTCUSDT"
    interval = body.get("interval") or "4h"
    from ops.customer_release import customer_terminal, reading_released
    sample = "spot_sample_not_bid_ask" if symbol == "XAUUSD" and interval in {"15m", "1h"} else None
    if not reading_released(symbol, interval, sample):
        payload = customer_terminal(symbol, interval)
        payload["request_id"] = str(body.get("request_id") or "")
        payload["requested_symbol"] = symbol
        payload["requested_interval"] = interval
        payload["requested_strategy"] = body.get("strategy") or "auto"
        payload["rejected"] = None
        return jsonify(payload), 200
    from ops.terminal_route import handle_signal
    status, payload = handle_signal(user_id, body)
    return jsonify(payload), status


@app.get("/api/terminal/history")
def terminal_history():
    user_id = session.get("user_id")
    if not user_id or not _user_ok():
        return jsonify({"error": "unauthorized"}), 401
    from ops.customer_release import redact_feed_view
    from ops.terminal_signal import read_history
    rows = [redact_feed_view(row) for row in reversed(read_history(user_id))]
    return jsonify({"items": rows[:40]})


@app.get("/overview")
@app.get("/signals")
@app.get("/trading")
@app.get("/strategies")
@app.get("/indicators")
@app.get("/research")
@app.get("/portfolio")
@app.get("/risk")
@app.get("/activity")
@app.get("/live")
@app.get("/system")
@app.get("/settings")
@app.get("/scanner")
@app.get("/learn")
@app.get("/plan")
@app.get("/lab")
@app.get("/notifications")
@app.get("/onboarding")
def index():
    if not _gate():
        return redirect("/login?next=" + _safe_next(request.path))
    failed = request.args.get("login") == "failed"
    title = {
        "/": "Overview",
        "/overview": "Overview",
        "/signals": "Live Signals",
        "/trading": "Trading Terminal",
        "/strategies": "Strategies",
        "/portfolio": "Portfolio",
        "/risk": "Risk Management",
        "/activity": "Orders & Trade History",
        "/live": "Live Activities",
        "/system": "System Status",
        "/settings": "Account & Settings",
        "/research": "Backtesting & Research",
        "/onboarding": "Account setup",
        "/scanner": "Live Scanner",
        "/learn": "Academy",
        "/indicators": "Academy",
        "/plan": "My Trading Plan",
        "/notifications": "Inbox",
        "/lab": "Trading Lab",
    }.get(request.path, "Aureon")
    page = (
        DASHBOARD.replace("{{AUTHED}}", "1")
        .replace("{{FAILED}}", "1" if failed else "0")
        .replace("{{CSRF}}", _csrf())
        .replace("{{PAGE_TITLE}}", title)
        .replace("{{PAGE_PATH}}", request.path)
    )
    needle = f'data-path="{request.path}"'
    page = page.replace(needle, needle + ' class="active"')
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
    <p class="lede">One account for the live desk, free paper AutoPilot, the Academy and your Trading Lab. AutoPilot opens paper trades only after you turn it on. It is not a broker.</p>
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
    <article class="card"><h3>Apex Momentum</h3><p>Up to 2.5% risk and a 1.7 reward floor. Paper timeframes include 1m, 3m, 15m and 1h. Same entry rule as the other styles.</p></article>
    <article class="card"><h3>Orion Precision</h3><p>Up to 1.5% risk and a 2.0 reward floor. Paper orders on 15m and 1h. A plan below the floor stays visible.</p></article>
    <article class="card"><h3>Aegis Shield</h3><p>Up to 0.8% risk and a 2.5 reward floor. Paper orders on 15m and 1h. Not a vote of three indicators.</p></article>
  </div>
</section>
<section class="wrap" id="platform">
  <div class="grid">
    <article class="card"><h3>Market workspace</h3><p>Market prices stay hidden until commercial-use permissions are confirmed. Gold one-minute and three-minute data stay unlicensed. Nothing on this page is a live quote.</p></article>
    <article class="card"><h3>Research signals</h3><p>E1, SMA20, and RSI14 stay labeled as research. A WAIT result is kept visible.</p></article>
    <article class="card"><h3>AutoPilot</h3><p>Free automated paper trading. It stays off until you enable it. A paper order is not a live broker order.</p></article>
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
<title>{{PAGE_TITLE}} · Aureon Trading Lab</title>
<style>
:root{--bg:#07090d;--panel:#12161d;--line:#242b36;--text:#f4f7fb;--muted:#93a0b4;--teal:#2dd4bf;--ok:#3dd68c;--bad:#ff6b7a;--warn:#e7b85a}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--text)}
.shell{display:grid;grid-template-columns:248px 1fr;min-height:100vh}
aside{background:#0c1016;border-right:1px solid var(--line);padding:18px 12px 24px}
.brand{font-weight:750;letter-spacing:-.02em;font-size:1.05rem}
.navlabel{margin:16px 10px 6px;color:#66758a;font-size:.68rem;letter-spacing:.14em;text-transform:uppercase}
aside a{display:flex;align-items:center;gap:8px;color:#c5d0de;text-decoration:none;padding:9px 10px;border-radius:10px;margin:2px 0;font-size:.92rem}
aside a.active{background:#14343a;color:#fff;box-shadow:inset 3px 0 0 var(--teal)}
main{padding:18px 20px 32px;min-width:0}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:16px}
.pills{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.pill{background:#10151c;border:1px solid var(--line);border-radius:999px;padding:6px 10px;color:var(--muted);font-size:.78rem}
.markets,.courses{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:12px}
.card{background:linear-gradient(180deg,#161c26,#10151c);border:1px solid var(--line);border-radius:16px;padding:16px}
.course .bar{height:6px;background:#222a36;border-radius:99px;margin:10px 0}
.course .bar span{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#14b8a6,#3dd68c)}
.price{font-size:1.7rem;font-weight:700;margin:6px 0}
.muted{color:var(--muted);font-size:.82rem}
.row{display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.long{color:var(--ok)} .short{color:var(--bad)} .wait{color:var(--warn)}
.desk{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(280px,.85fr);gap:12px;align-items:start}
.desk #watch{grid-column:1 / -1}
.split{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(280px,.95fr);gap:12px;align-items:start}
.split > .card,.split > article{margin-top:0}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:12px}
.kpis.five{grid-template-columns:repeat(5,minmax(0,1fr))}
.kpis .price{font-size:1.2rem;margin:4px 0 0}
.matrix{width:100%;border-collapse:collapse}
canvas{width:100%;height:0;display:none;background:transparent}
canvas.is-live{display:block;height:280px;background:#0a0e14;border-radius:12px}
canvas.is-empty{display:none}
.empty-chart{min-height:0;display:block;text-align:left;padding:4px 0 0;border:0;border-radius:0;background:transparent;color:var(--text);line-height:1.5}
.empty-chart[hidden]{display:none !important}
.price.quiet{font-size:1.05rem;font-weight:650;color:var(--muted)}
canvas.spark{height:46px;background:transparent;border-radius:0}
a{color:#99f6e4}
#view a{text-underline-offset:2px}
select,button{background:#1a222e;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:8px 12px}
button:disabled{opacity:.55;cursor:not-allowed}
button[data-lesson],#saverule,#auto-on{background:#0f766e;border-color:#0f766e;color:#fff;font-weight:650}
.fieldrow{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.fieldrow label,.field{display:grid;gap:6px;font-size:.85rem;color:var(--muted)}
.field{margin:12px 0;max-width:320px}
.styles label,.checks label{display:flex;gap:10px;align-items:flex-start;margin:8px 0;line-height:1.45}
.styles label{background:#0b1017;border:1px solid var(--line);border-radius:12px;padding:10px 12px}
#view input,#view select{background:#0b1017;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:8px 10px}
#view .field input,#view .field select{width:100%;max-width:320px}
#view article+article{margin-top:12px}
#view{max-width:1240px;min-width:0;overflow-wrap:anywhere}
.card p{line-height:1.5;max-width:68ch}
.badge{display:inline-block;border-radius:999px;padding:3px 8px;font-size:.72rem;letter-spacing:.04em;text-transform:uppercase;border:1px solid var(--line);color:var(--muted);margin:0 6px 8px 0}
.badge.block{color:#e7b85a;border-color:#6b5420}
.badge.research{color:#9ec5ff;border-color:#24406a}
.badge.wait{color:var(--warn);border-color:#6b5420}
.badge.ok{color:var(--ok);border-color:#145c45}
.card.research{border-left:3px solid #3b6ea5}
.card.blocked{border-left:3px solid #e7b85a}
.card.approved{border-left:3px solid #14b8a6}
.sections{display:grid;grid-template-columns:minmax(140px,180px) minmax(0,1fr);gap:8px 14px;margin:12px 0}
.sections dt{color:var(--muted);font-size:.78rem}
.sections dd{margin:0}
.empty-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(240px,.8fr);gap:12px;align-items:start}
.plan-group{margin:14px 0 6px}
#planform > label{display:grid;gap:6px;margin:12px 0;max-width:360px}
#planform > label input[type="checkbox"]{justify-self:start}
#planform .checks label{display:flex;max-width:none;margin:8px 0}
#planform button{margin-top:8px}
.num{font-variant-numeric:tabular-nums}
.skeleton{background:#1c2430;border-radius:10px;height:12px;margin:8px 0}
.skeleton.lg{height:26px;width:46%}
.stale-note{color:#e7b85a}
#menu{display:none;background:#1a222e;color:#fff;border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:10px}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #99f6e4;outline-offset:2px}
.row{flex-wrap:wrap}
.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:.88rem}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #222a36;white-space:nowrap}
.matrix th,.matrix td{white-space:normal;vertical-align:top;word-break:break-word}
th{color:#93a0b4;font-weight:600;font-size:.75rem;letter-spacing:.04em;text-transform:uppercase}
tr:last-child td{border-bottom:0}
@media(max-width:1100px){.desk,.split{grid-template-columns:1fr}.kpis.five{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:900px){header{flex-direction:column;align-items:flex-start}.shell{grid-template-columns:1fr}#menu{display:inline-block}aside{display:none;position:fixed;inset:0 auto 0 0;width:min(260px,88vw);z-index:20;overflow:auto}aside.open{display:block}.markets,.courses,.workspace,.empty-grid,.sections,.desk,.split,.kpis,.kpis.five{grid-template-columns:1fr}button,select{min-height:40px}main{padding:12px 12px 28px}}
</style>
</head>
<body data-path="{{PAGE_PATH}}">
<div class="shell">
  <button id="menu" aria-label="Open navigation" aria-expanded="false">☰ Menu</button>
  <aside id="nav">
    <div class="brand">Aureon</div>
    <div class="muted" style="margin:2px 10px 4px">Trading Lab · Cyber Aid</div>
    <p class="navlabel">Trading desk</p>
    <a href="/overview" data-path="/overview">Overview</a>
    <a href="/trading" data-path="/trading">Terminal</a>
    <a href="/scanner" data-path="/scanner">Scanner</a>
    <a href="/signals" data-path="/signals">Live Signals</a>
    <p class="navlabel">Market intelligence</p>
    <a href="/strategies" data-path="/strategies">Strategies</a>
    <a href="/research" data-path="/research">Research</a>
    <p class="navlabel">Paper trading</p>
    <a href="/settings" data-path="/settings">AutoPilot</a>
    <a href="/portfolio" data-path="/portfolio">Portfolio</a>
    <a href="/activity" data-path="/activity">Journal</a>
    <a href="/risk" data-path="/risk">Risk</a>
    <a href="/plan" data-path="/plan">My Plan</a>
    <p class="navlabel">Learning</p>
    <a href="/learn" data-path="/learn">Academy</a>
    <a href="/lab" data-path="/lab">Trading Lab</a>
    <a href="/notifications" data-path="/notifications">Inbox</a>
    <a href="/live" data-path="/live">Activity</a>
    <p class="navlabel">Account</p>
    <a href="/system" data-path="/system">System</a>
    <a href="/settings" data-path="/settings">Settings</a>
  </aside>
  <main>
    <header>
      <div>
        <h1 id="title">{{PAGE_TITLE}}</h1>
        <div class="muted">Paper desk. A plan is not an order, and a paper result is not a broker fill.</div>
      </div>
      <div class="pills"><span class="pill" id="whobadge">Account</span><span class="pill" id="autobadge">AutoPilot</span><span class="pill" id="feedbadge">Checking status</span><a href="/notifications" id="inboxlink">Inbox</a><button id="signout" type="button">Sign out</button></div>
    </header>
    <section id="view"><article class="card"><p role="status">Loading this page. Prices are not invented while this loads.</p></article></section>
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
const titles = {"/":"Overview","/signals":"Live Signals","/trading":"Trading Terminal","/strategies":"Strategies","/portfolio":"Portfolio","/risk":"Risk Management","/activity":"Orders & Trade History","/live":"Live Activities","/system":"System Status","/settings":"Account & Settings","/research":"Backtesting & Research","/onboarding":"Account setup","/scanner":"Live Scanner","/learn":"Academy","/indicators":"Academy","/plan":"My Trading Plan","/notifications":"Inbox","/lab":"Trading Lab"};
document.getElementById("title").textContent = titles[path] || "Aureon";
document.title = (titles[path] || "Aureon") + " · Aureon Trading Lab";
fetch("/api/autopilot", {credentials:"same-origin"}).then(r => r.ok ? r.json() : null).then(bot => {
  const badge = document.getElementById("autobadge");
  if (!badge || !bot) return;
  badge.textContent = "AutoPilot " + (bot.facing || bot.status || "unknown");
}).catch(()=>{});
fetch("/api/me", {credentials:"same-origin"}).then(r => r.ok ? r.json() : null).then(me => {
  const badge = document.getElementById("whobadge");
  if (badge && me && me.profile) badge.textContent = (me.name || "Account") + " · " + (me.profile.signal_style_name || "No persona");
}).catch(()=>{});
fetch("/health").then(r => r.ok ? r.json() : null).then(health => {
  const badge = document.getElementById("feedbadge");
  if (!badge || !health) return;
  const worker = health.worker || {};
  badge.textContent = "Worker " + (worker.status || "unknown");
}).catch(() => {
  const badge = document.getElementById("feedbadge");
  if (badge) badge.textContent = "Health not confirmed";
});
const view = document.getElementById("view");
function plainReason(text){
  return String(text || "")
    .replaceAll("sample_is_5m", "the gold feed is five-minute samples, so this shorter candle is not available")
    .replaceAll("xau_minute_unlicensed", "gold one-minute and three-minute data are not licensed")
    .replaceAll("last_trade", "last completed candle close")
    .replaceAll("spot_sample_not_bid_ask", "sampled indicative reference bar, not exchange OHLC and not a bid or ask")
    .replaceAll("dukascopy_xauusd_bid_ask", "gold bid and ask")
    .replaceAll("ohlc_not_bid_ask", "chart OHLC, not a bid, ask, or execution price")
    .replaceAll("quote_divergence", "the spot sample and the separate quote disagree")
    .replaceAll("reference_quote_unavailable", "reference quote unavailable")
    .replaceAll("paper_ledger_persistence", "paper ledger persistence is unverified")
    .replaceAll("feed_copy", "those levels match the feed reading")
    .replaceAll("unverified_observation", "unverified observation")
    .replaceAll("snapshot_not_candle", "quote available, candle unavailable")
    .replaceAll("quote_not_bid_ask", "source is not a completed bid and ask candle")
    .replaceAll("stale_or_incomplete", "the latest candle is missing, still forming, or too old")
    .replaceAll("DATA_UNAVAILABLE", "not available")
    .replaceAll("rights_unconfirmed", "rights not confirmed")
    .replaceAll("commercial_use_unverified", "commercial use permissions are being verified")
    .replaceAll("withheld", "not shown")
    .replaceAll("binance_spot", "Binance spot candles")
    .replaceAll("spot_sample", "spot sample")
    .replaceAll("LONG_BIAS", "bullish research")
    .replaceAll("SHORT_BIAS", "bearish research");
}
function cls(d){ return String(d||"").includes("LONG")?"long":String(d||"").includes("SHORT")?"short":"wait"; }
function label(d){ if (d==="SHORT_BIAS") return "Bearish observation"; if (d==="LONG_BIAS") return "Bullish observation"; if (d==="WAIT") return "No entry yet"; return d; }
const RIGHTS_MESSAGE = "Market data access unavailable — commercial use permissions are being verified.";
function chartHold(message){
  const canvas = document.getElementById("chart");
  const empty = document.getElementById("chartempty");
  if (canvas) { canvas.classList.add("is-empty"); canvas.classList.remove("is-live"); }
  if (empty) { empty.hidden = false; empty.textContent = message || RIGHTS_MESSAGE; }
}
function chartShow(){
  const canvas = document.getElementById("chart");
  const empty = document.getElementById("chartempty");
  if (canvas) { canvas.classList.remove("is-empty"); canvas.classList.add("is-live"); }
  if (empty) empty.hidden = true;
}
function isRightsHold(headline, state, status){
  return headline === "RIGHTS" || state === "RIGHTS" || status === "withheld" || status === "rights_unconfirmed" || status === "restricted" || status === "prohibited";
}
function autoSentence(bot){
  if (!bot) return "AutoPilot status was not loaded.";
  const facing = bot.facing || bot.status || "Disabled";
  const note = bot.facing_note || "";
  if (bot.entries_available === true) return facing + ". " + note;
  return facing + ". New automated paper entries are not eligible. " + note;
}
function timed(url, ms){
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms || 6000);
  return fetch(url, {credentials:"same-origin", signal: ctl.signal}).then(r => r.ok ? r.json() : null).catch(() => null).finally(() => clearTimeout(timer));
}
function priceText(symbol, value){
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const digits = Math.abs(n) >= 1 ? 2 : 4;
  return n.toLocaleString(undefined, {minimumFractionDigits: digits, maximumFractionDigits: digits});
}
function manualPlanCard(){
  return `<article class="card" id="manual-plan-card"><h2>Manual paper plan</h2><p class="muted">Type the entry, stop and target yourself. These fields stay empty. Nothing is copied from a market feed. Confirm records a paper estimate on this account, not a broker fill.</p><form id="manual-plan"><div class="fieldrow"><label>Market <select name="symbol"><option>BTCUSDT</option><option>ETHUSDT</option><option>XAUUSD</option></select></label><label>Timeframe <select name="interval"><option>15m</option><option>1h</option><option>1m</option><option>3m</option></select></label><label>Side <select name="decision"><option>BUY</option><option>SELL</option></select></label><label>Entry <input name="entry" inputmode="decimal" autocomplete="off" /></label><label>Stop <input name="stop" inputmode="decimal" autocomplete="off" /></label><label>Target <input name="target" inputmode="decimal" autocomplete="off" /></label></div><button type="submit">Review my levels</button></form><div id="manual-out"></div></article>`;
}
function bindManualPlan(){
  const form = document.getElementById("manual-plan");
  if (!form || form.dataset.bound) return;
  form.dataset.bound = "1";
  form.onsubmit = async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const slot = document.getElementById("manual-out");
    const sent = await fetch("/api/desk/plan", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({symbol: data.get("symbol"), interval: data.get("interval"), authored: true, decision: data.get("decision"), entry: data.get("entry"), stop: data.get("stop"), target: data.get("target")})});
    const mine = await sent.json().catch(() => ({}));
    if (!sent.ok || !mine.opportunity_id || mine.levels_persisted !== true) {
      if (slot) slot.innerHTML = `<p>Your levels were not saved. ${plainReason(mine.reason || "not available")}. No order was opened.</p>`;
      return;
    }
    const allow = mine.paper && mine.paper.allowed;
    if (slot) slot.innerHTML = `<p>Your levels. Entry ${priceText(data.get("symbol"), mine.entry)}. Stop ${priceText(data.get("symbol"), mine.stop)}. Target ${priceText(data.get("symbol"), mine.target)}. Not a feed plan. Not a broker fill.</p>${allow ? `<p><button type="button" id="manual-confirm" data-confirm="${mine.opportunity_id}">Confirm manual paper order</button></p>` : `<p>The account rules did not allow an order. ${plainReason((mine.paper && mine.paper.reason) || "")}</p>`}`;
    const confirm = document.getElementById("manual-confirm");
    if (confirm) confirm.onclick = async () => {
      confirm.disabled = true;
      const opened = await fetch("/api/paper/orders", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({opportunity_id: confirm.dataset.confirm})});
      const done = await opened.json().catch(() => ({}));
      confirm.textContent = opened.ok && done.ok ? "Paper trade recorded. It is an estimate, not a broker fill." : ("Not opened. " + plainReason(done.reason || "Try again."));
    };
  };
}
function stamp(ms){ return ms ? new Date(ms).toISOString() : "unknown"; }
function when(ms){
  if (!ms) return "time not available";
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "time not available";
  try {
    return d.toLocaleString(undefined, {timeZone:"UTC", year:"numeric", month:"short", day:"2-digit", hour:"2-digit", minute:"2-digit"}) + " UTC";
  } catch (e) {
    return d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
  }
}
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
function researchSummary(qual, platform){
  const life = (qual && qual.by_lifecycle) || {};
  const registered = qual && qual.strategies ? qual.strategies.length : "—";
  const approved = qual && qual.approved_for_paper != null ? qual.approved_for_paper : "—";
  const failed = life.backtest_failed == null ? "—" : life.backtest_failed;
  const insufficient = life.insufficient_data == null ? "—" : life.insufficient_data;
  const rights = !platform ? "—" : (platform.market_data === "rights_withheld" ? "Yes" : "No");
  return `<div class="kpis five"><article class="card"><p class="muted">Registered</p><p class="price num">${registered}</p></article><article class="card"><p class="muted">Approved for paper</p><p class="price num">${approved}</p></article><article class="card"><p class="muted">Failed validation</p><p class="price num">${failed}</p></article><article class="card"><p class="muted">Insufficient data</p><p class="price num">${insufficient}</p></article><article class="card"><p class="muted">Blocked by source rights</p><p class="price num">${rights}</p><p class="muted">Live evaluation. Not a strategy-failure count.</p></article></div>`;
}
async function overview(){
  view.innerHTML = `<div class="kpis" id="ov-kpis"><article class="card"><p class="muted">Paper capital</p><div class="skeleton lg"></div></article><article class="card"><p class="muted">Open paper positions</p><div class="skeleton lg"></div></article><article class="card"><p class="muted">Closed paper trades</p><div class="skeleton lg"></div></article><article class="card"><p class="muted">AutoPilot</p><div class="skeleton lg"></div></article></div><div class="split"><article class="card" id="ov-account"><h2>Account</h2><p role="status">Loading your account. Market prices are not required for this section.</p></article><article class="card" id="ov-market"><h2>Market data</h2><p>Loading the platform state.</p></article></div><article class="card" id="ov-activity"><h2>Recent activity</h2><p class="muted">Loading account events. A price is not required.</p></article>`;
  const [me, bot, book, platform, lab, plan, notes, markets] = await Promise.all([
    timed("/api/me"), timed("/api/autopilot"), timed("/api/paper/book"), timed("/api/platform"), timed("/api/lab"), timed("/api/plan"), timed("/api/notifications"), timed("/api/markets")
  ]);
  const profile = (me && me.profile) || {};
  const balance = me ? money(profile.capital, profile.currency || "") : "—";
  const styleName = profile.signal_style_name || "Not selected";
  const who = me && me.name ? me.name : "Account";
  const figures = (book && book.performance) || {};
  const realised = figures.trades ? Number(figures.pnl_usd).toFixed(2) + " USD" : "—";
  const openCount = book && book.open ? book.open.length : "—";
  const closedCount = book ? (figures.trades || 0) : "—";
  const savedPlan = (plan && plan.plan) || {};
  const weekLimit = savedPlan.weekly_loss_limit_percent == null || savedPlan.weekly_loss_limit_percent === "" ? "Not set" : savedPlan.weekly_loss_limit_percent + "%";
  const account = document.getElementById("ov-account");
  const kpis = document.getElementById("ov-kpis");
  if (!me || !account) {
    if (account) account.innerHTML = `<h2>Account</h2><p>The account could not be loaded in time. Other sections stay visible.</p><p><button type="button" id="ov-retry">Retry</button></p>`;
    const again = document.getElementById("ov-retry");
    if (again) again.onclick = () => overview();
  } else if (account) {
    const steps = [];
    if (!profile.signal_style) steps.push(`<li><a href="/onboarding">Choose a signal style.</a></li>`);
    if (!profile.currency) steps.push(`<li><a href="/settings">Set a base currency.</a> Amounts are not converted.</li>`);
    const lessons = lab && lab.completed_lessons ? lab.completed_lessons.length : 0;
    const lessonTotal = lab && lab.lessons ? lab.lessons.length : 0;
    const openRows = book && book.open && book.open.length ? book.open.map(row => `<div class="row"><span>${row.symbol} ${row.direction}</span><span>Open paper</span></div>`).join("") : `<div class="row"><span>Open paper positions</span><span>None</span></div>`;
    account.innerHTML = `<h2>${who}</h2>${openRows}<div class="row"><span>Persona</span><span>${styleName}</span></div><div class="row"><span>Paper capital</span><span>${balance}</span></div><div class="row"><span>Recorded paper result</span><span>${figures.trades ? realised : "—"}</span></div><div class="row"><span>Daily loss cap</span><span>${profile.max_daily_loss_percent == null ? "Not set" : profile.max_daily_loss_percent + "%"}</span></div><div class="row"><span>Weekly loss limit</span><span>${plan ? weekLimit : "Not loaded"}</span></div><div class="row"><span>Risk per trade</span><span>${profile.max_risk_pct == null ? "Not set" : profile.max_risk_pct + "%"}</span></div><div class="row"><span>Academy</span><span>${lessonTotal ? lessons + " of " + lessonTotal + " lessons" : (lab ? "Available" : "Not loaded")}</span></div><p class="muted">${autoSentence(bot)} Broker execution is disabled. No strategy is promoted. ${profile.currency ? "Amounts use " + profile.currency + "." : "Choose a base currency before treating the balance as money."} ${figures.trades ? "" : "No closed paper trade. No win rate."}</p>${steps.length ? `<h3>Next step</h3><ul>${steps.join("")}</ul>` : `<p><a href="/learn">Continue in the Academy</a> · <a href="/lab">Trading Lab</a> · <a href="/settings">Settings</a></p>`}`;
  }
  if (kpis) kpis.innerHTML = `<article class="card"><p class="muted">Paper capital</p><p class="price">${balance}</p></article><article class="card"><p class="muted">Open paper positions</p><p class="price num">${openCount}</p></article><article class="card"><p class="muted">Closed paper trades</p><p class="price num">${closedCount}</p><p class="muted">${figures.trades ? "Recorded result " + realised + ". Not a win rate." : "No closed paper trade. No win rate."}</p></article><article class="card"><p class="muted">AutoPilot</p><p class="price quiet">${bot ? (bot.facing || "Disabled") : "Not loaded"}</p></article>`;
  const market = document.getElementById("ov-market");
  if (market) {
    const quotes = ((markets && markets.markets) || []).map(row => {
      const data = (row && row.data) || {};
      const reading = row.reading || {};
      const value = data.price != null ? data.price : data.close;
      const unavailable = data.customer_status === "reading_unavailable" || reading.customer_status === "reading_unavailable" || value == null;
      if (unavailable) {
        return `<div class="row"><span>${row.symbol}</span><span class="num">—</span></div><p class="muted">${data.note || reading.explanation || "A verified live reading is not available."}</p>`;
      }
      const shown = priceText(row.symbol, value);
      const sampled = data.candle_semantics === "spot_sample_not_bid_ask";
      const frame = sampled ? ((data.timeframe || "Gold") + " sampled reference close") : ((data.timeframe ? data.timeframe + " " : "") + "completed close");
      const when = data.close_time_ms ? new Date(data.close_time_ms).toISOString().slice(0, 16).replace("T", " ") + " UTC" : "";
      const note = frame + (when ? " · " + when : "") + " · " + (data.quality || "unknown");
      const quote = data.quote && data.quote.price != null
        ? `<p class="muted">Separate quote ${priceText(row.symbol, data.quote.price)}. Not the completed close.</p>`
        : (data.quote && data.quote.status === "reference_quote_unavailable" ? `<p class="muted">Reference quote unavailable. Not the completed close.</p>` : "");
      const context = reading.reading_class && reading.customer_status !== "reading_unavailable" ? `<p class="muted">${reading.direction_label || "neutral"} · ${reading.reading_class}. ${plainReason(reading.explanation || "")}</p>` : "";
      return `<div class="row"><span>${row.symbol}</span><span class="num">${shown}</span></div><p class="muted">${note}</p>${quote}${context}`;
    }).join("");
    const states = ((platform && platform.states) || []).map(row => `<div class="row"><span>${row.label}</span><span>${row.value}</span></div>`).join("");
    market.innerHTML = `<h2>Market data</h2>${quotes || "<p>A verified live reading is not available.</p>"}${states}<p><a href="/trading">Open the terminal</a> · <a href="/signals">Today's setups</a> · <a href="/scanner">Scanner</a></p>`;
    const again = document.getElementById("ov-retry2");
    if (again) again.onclick = () => overview();
  }
  const activity = document.getElementById("ov-activity");
  if (activity) {
    const events = ((notes && notes.items) || []).slice(0, 4).map(item => `<div class="row"><span>${item.decision || item.state || "Notice"} · ${item.symbol || "Account"}</span><span>${item.created_ms ? new Date(item.created_ms).toISOString().slice(0, 16).replace("T", " ") : "—"}</span></div>`).join("");
    activity.innerHTML = `<h2>Recent activity</h2>${notes ? (events || "<p>No account event is recorded. An empty inbox is not a failed service.</p>") : "<p>Activity could not be loaded in time.</p>"}<p class="muted">These lines are account notices, not orders and not live prices.</p><p><a href="/notifications">Inbox</a> · <a href="/activity">Journal</a> · <a href="/portfolio">Portfolio</a></p>${notes ? "" : `<p><button type="button" id="ov-retry3">Retry activity</button></p>`}`;
    const again = document.getElementById("ov-retry3");
    if (again) again.onclick = () => overview();
  }
}
async function signals(){
  view.innerHTML = `<article class="card" id="live-now"><h2>Live signals</h2><p role="status">Loading today's readings. No price is invented while this loads.</p></article><article class="card" id="live-hist"><h2>Historical research</h2><p class="muted">Separated from the live desk. Loading the saved record.</p></article>`;
  const scan = await timed("/api/scanner", 12000);
  const now = document.getElementById("live-now");
  if (now) {
    const grouped = {};
    ((scan && scan.markets) || []).forEach(item => { (grouped[item.symbol] ||= []).push(item); });
    const cards = Object.keys(grouped).map(symbol => {
      const items = grouped[symbol];
      if (items.every(item => item.customer_status === "reading_unavailable")) {
        const minute = items.some(item => item.blocked === "xau_minute_unlicensed");
        return `<div class="row"><span>${symbol}</span><span>—</span></div><p class="muted">${items.map(item => item.interval).filter(Boolean).join(", ")}. A verified live reading is not available.${minute ? " 1-minute and 3-minute are not offered." : ""}</p>`;
      }
      return items.map(item => {
      const headline = item.decision_label || item.scanner_state || "WAIT";
      const minute = item.blocked === "xau_minute_unlicensed" || headline === "UNAVAILABLE" || item.reading_class === "unavailable";
      const px = item.price == null ? "—" : priceText(item.symbol, item.price);
      const decision = minute ? "Unavailable" : (headline === "WAIT" ? "No entry yet" : headline);
      const dir = item.direction_label || "neutral";
      const kind = item.reading_class || "observational";
      const whenText = item.candle_close_ms ? when(item.candle_close_ms) : "time not available";
      const stance = item.customer_status === "reading_unavailable"
        ? `<p class="muted">A verified live reading is not available.</p>`
        : (item.reading_class === "unavailable"
        ? `<p class="muted">This timeframe is unavailable. That is not a missed setup.</p>`
        : (item.reading_class === "insufficient"
          ? `<p class="muted">The candle is not fresh enough to plan. That is not a missed setup.</p>`
          : (item.reading_class === "developing"
            ? `<p class="muted">The setup is forming. It is not a paper plan yet. ${plainReason(item.changes_when || "")}</p>`
            : (item.manual_paper
              ? `<p>Entry ${priceText(item.symbol, item.entry)}. Stop ${priceText(item.symbol, item.stop)}. Target ${priceText(item.symbol, item.target)}. ${plainReason(item.invalidation || "")}</p><p class="muted">Use the manual paper plan below. Levels are not filled in from this reading.</p>`
              : `<p class="muted">Observation only. Not a paper plan and not AutoPilot. ${plainReason(item.changes_when || "")}</p>`))));
      const closeLabel = minute || item.customer_status === "reading_unavailable" ? "Reading" : "Completed close";
      return `<div class="row"><span>${item.symbol} ${item.interval || ""}</span><span>${decision}</span></div><div class="row"><span>${closeLabel}</span><span class="num">${item.customer_status === "reading_unavailable" || minute ? "—" : px}</span></div><p class="muted">${dir} · ${kind} · ${whenText}. ${plainReason(item.explanation || item.message || "")}</p>${stance}`;
      }).join("");
    }).join("");
    now.innerHTML = `<h2>Live signals</h2><p class="muted">No eligible live reading is available. That is separate from whether a research strategy is approved. Nothing here is an order.</p>${cards || "<p>No eligible live reading is available.</p>"}${manualPlanCard()}<p><a href="/scanner">Open the scanner</a> · <a href="/trading">Terminal</a></p>`;
    bindManualPlan();
    const again = document.getElementById("sig-retry");
    if (again) again.onclick = () => signals();
    document.querySelectorAll("[data-review]").forEach(button => { button.onclick = async () => {
      button.disabled = true;
      const box = document.querySelector('[data-review-box="' + button.dataset.review + ":" + button.dataset.frame + '"]');
      const response = await fetch("/api/desk/plan", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({symbol: button.dataset.review, interval: button.dataset.frame})});
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.opportunity_id) {
        if (box) box.innerHTML = `<p>No paper plan was saved. ${plainReason(payload.reason || payload.reading_class || "not available")}. No order was opened.</p>`;
        button.disabled = false;
        return;
      }
      const allow = payload.paper && payload.paper.allowed;
      const sized = payload.paper && payload.paper.size;
      const sizeLine = sized && sized.risk_budget_usd != null
        ? `Risk budget ${Number(sized.risk_budget_usd).toFixed(2)} USD at ${payload.paper.risk_percent} percent. ${sized.ok && sized.quantity != null ? "Quantity " + Number(sized.quantity).toFixed(6) + " is an unrounded estimate, not an exchange lot." : plainReason(sized.note || sized.reason || "Size was not calculated.")}`
        : `Account check: ${plainReason((payload.paper && payload.paper.reason) || "not allowed")}.`;
      if (box) box.innerHTML = `<p>Saved plan. Entry ${priceText(button.dataset.review, payload.entry)}. Stop ${priceText(button.dataset.review, payload.stop)}. Target ${priceText(button.dataset.review, payload.target)}. ${sizeLine} Snapshot ${payload.snapshot_id || ""}. Not approved. Not AutoPilot. No broker order.</p>${payload.levels_persisted === false ? `<p class="muted">${plainReason(payload.persistence_note || "paper_ledger_persistence")}</p><form data-author="${button.dataset.review}:${button.dataset.frame}"><label>Your side <select name="decision"><option>BUY</option><option>SELL</option></select></label> <label>Your entry <input name="entry" inputmode="decimal" /></label> <label>Your stop <input name="stop" inputmode="decimal" /></label> <label>Your target <input name="target" inputmode="decimal" /></label> <button type="submit">Save my levels</button></form><div data-authored="${button.dataset.review}:${button.dataset.frame}"></div>` : (allow ? `<p><button type="button" data-confirm="${payload.opportunity_id}">Confirm manual paper order</button></p>` : `<p>The account rules did not allow an order. The plan stays a review.</p>`)}`;
      const author = box && box.querySelector("[data-author]");
      if (author) author.onsubmit = async (event) => {
        event.preventDefault();
        const data = new FormData(author);
        const sent = await fetch("/api/desk/plan", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({symbol: button.dataset.review, interval: button.dataset.frame, authored: true, decision: data.get("decision"), entry: data.get("entry"), stop: data.get("stop"), target: data.get("target")})});
        const mine = await sent.json().catch(() => ({}));
        const slot = box.querySelector("[data-authored]");
        if (!sent.ok || !mine.opportunity_id || mine.levels_persisted !== true) {
          if (slot) slot.innerHTML = `<p>Your levels were not saved. ${plainReason(mine.reason || "not available")}. No order was opened.</p>`;
          return;
        }
        const mineAllow = mine.paper && mine.paper.allowed;
        if (slot) slot.innerHTML = `<p>Your levels, not a feed plan. Entry ${priceText(button.dataset.review, mine.entry)}. Stop ${priceText(button.dataset.review, mine.stop)}. Target ${priceText(button.dataset.review, mine.target)}.</p>${mineAllow ? `<p><button type="button" data-confirm="${mine.opportunity_id}">Confirm manual paper order</button></p>` : `<p>The account rules did not allow an order.</p>`}`;
        const mineConfirm = slot.querySelector("[data-confirm]");
        if (mineConfirm) mineConfirm.onclick = async () => {
          mineConfirm.disabled = true;
          const opened = await fetch("/api/paper/orders", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({opportunity_id: mineConfirm.dataset.confirm})});
          const done = await opened.json().catch(() => ({}));
          mineConfirm.textContent = opened.ok && done.ok ? "Paper trade recorded. It is an estimate, not a broker fill." : ("Not opened. " + plainReason(done.reason || "Try again."));
        };
      };
      const confirm = box && box.querySelector("[data-confirm]");
      if (confirm) confirm.onclick = async () => {
        confirm.disabled = true;
        const opened = await fetch("/api/paper/orders", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({opportunity_id: confirm.dataset.confirm})});
        const done = await opened.json().catch(() => ({}));
        confirm.textContent = opened.ok && done.ok ? "Paper trade recorded. It is an estimate, not a broker fill." : ("Not opened. " + plainReason(done.reason || "Try again."));
      };
    }; });
  }
  const research = await timed("/api/research-lab");
  const hist = document.getElementById("live-hist");
  if (!hist) return;
  const discovery = (research && research.discovery) || {};
  const markets = (discovery.markets || []).map(market => `<div class="row"><span>${market.symbol}</span><span>${(market.validation && market.validation.judgment) || market.holdout || "recorded"}</span></div>`).join("");
  hist.innerHTML = `<h2>Historical research record</h2><p class="muted">These are saved study outcomes, not live leaders and not an approved signal. Holdout opened for: ${(discovery.holdout_opened_for || []).join(", ") || "nobody"}.</p>${markets || "<p>No scored market is listed on this card.</p>"}<p><a href="/research">Read the full research record</a></p>`;
}
async function terminal(){
  view.innerHTML = `<div class="desk"><article class="card" id="watch"><h2>Market watch</h2><p class="muted">Loading availability. An unavailable market is not shown as a live price.</p></article><article class="card"><h2>Completed candles</h2><div class="fieldrow"><label>Market <select id="term-symbol"><option>BTCUSDT</option><option>ETHUSDT</option><option>XAUUSD</option></select></label><label>Timeframe <select id="term-interval"><option value="1m">1m</option><option value="3m">3m</option><option value="15m" selected>15m</option><option value="1h">1h</option></select></label><label>Reading <select id="term-strategy"><option value="auto">Auto</option><option value="compress-break-4h-20261028">BTC compression breakout</option><option value="sweep-reclaim-4h-20261028">ETH failed-breakdown</option><option value="london-reclaim-1h-20261028">Gold London reclaim</option><option value="dip-in-trend-1d-20261028">Daily dip in trend</option><option value="quiet-week-reversal-1d-20261028">Quiet week reversal</option></select></label></div><canvas id="chart" class="is-empty"></canvas><p class="empty-chart" id="chartempty">Loading closed candles.</p><p id="chartnote" class="muted"></p><p id="crosshair" class="muted"></p><button id="generate" type="button">Evaluate market</button><p id="termstatus" role="status"></p><p class="muted">This requests an analysis. It is not an approved signal and it does not place an order. The chart does not invent ticks.</p></article><article class="card" id="intel"><h2>Market intelligence</h2><div id="termout"><p>No evaluation yet. An empty panel is not a signal.</p></div></article></div><article class="card" id="termbook"><h2>Paper record</h2><p class="muted">Loading this account's paper book.</p></article>${manualPlanCard()}<article class="card"><h2>Saved evaluations</h2><p class="muted">Older requests on this account. They are not live prices, and a past wait is not the current market.</p><div id="termhist"><p>No requested evaluation yet.</p></div></article>`;
  const symbolEl = document.getElementById("term-symbol");
  const intervalEl = document.getElementById("term-interval");
  const strategyEl = document.getElementById("term-strategy");
  let ticket = 0;
  function requestedNow(){ return {symbol: symbolEl.value, interval: intervalEl.value, strategy: strategyEl.value}; }
  function markFrames(){
    const gold = symbolEl.value === "XAUUSD";
    [...intervalEl.options].forEach(opt => {
      if (opt.value === "1m" || opt.value === "3m") opt.textContent = gold ? opt.value + " — unavailable" : opt.value;
    });
  }
  markFrames();
  function goldMinuteSelected(){ return symbolEl.value === "XAUUSD" && (intervalEl.value === "1m" || intervalEl.value === "3m"); }
  function syncEvaluate(){
    const button = document.getElementById("generate");
    if (!button) return;
    if (goldMinuteSelected()) { button.disabled = true; button.textContent = "Unavailable"; return; }
    button.disabled = false;
    button.textContent = "Evaluate market";
  }
  syncEvaluate();
  async function loadWatch(){
    const box = document.getElementById("watch");
    if (!box) return;
    const markets = await timed("/api/markets");
    const rows = (markets && markets.markets) || [];
    if (!rows.length) {
      box.innerHTML = `<h2>Market watch</h2><p>Prices could not be loaded. No price was invented.</p><p><button type="button" id="watch-retry">Retry</button></p>`;
      const again = document.getElementById("watch-retry");
      if (again) again.onclick = () => loadWatch();
      return;
    }
    const lines = rows.map(row => {
      const data = row.data || {};
      const value = data.price != null ? data.price : data.close;
      const shown = value == null ? "—" : priceText(row.symbol, value);
      return `<div class="row"><span>${row.symbol}</span><span class="num">${shown}</span></div>`;
    }).join("");
    const hidden = rows.every(row => ((row.data || {}).price == null) && ((row.data || {}).close == null));
    box.innerHTML = `<h2>Market watch</h2>${lines}<p class="muted">${hidden ? "A verified live reading is not available." : "Closes come from one desk snapshot. A price is not an order."}</p>`;
  }
  async function loadDeskChart(){
    const note = document.getElementById("chartnote");
    const hover = document.getElementById("crosshair");
    const requested = requestedNow();
    if (requested.symbol === "XAUUSD" && (requested.interval === "1m" || requested.interval === "3m")) {
      chartHold("Licensed spot minute data unavailable. No candle was drawn.");
      if (note) note.innerHTML = `Gold ${requested.interval} is unlicensed. It is not built from a five-minute sample, and no evaluation is sent. <a href="/system">System status</a>`;
      if (hover) hover.textContent = "";
      return;
    }
    const url = requested.symbol === "XAUUSD" ? `/api/gold/candles?interval=${requested.interval}` : `/api/klines?symbol=${requested.symbol}&interval=${requested.interval}`;
    const bars = await fetch(url).then(r => r.json()).catch(() => null);
    if (!bars || bars.blocked === "xau_minute_unlicensed" || bars.customer_status === "reading_unavailable" || !(bars.candles || []).length) {
      const minute = bars && bars.blocked === "xau_minute_unlicensed";
      chartHold(minute ? "This timeframe is not available." : "A verified live reading is not available.");
      if (note) note.textContent = minute ? "Gold 1-minute and 3-minute are not offered. No candle was drawn." : "A verified live reading is not available.";
      if (hover) hover.textContent = "";
      return;
    }
    chartShow();
    draw(bars.candles);
    if (note) {
      const sampled = bars.kind === "sampled_reference" || bars.quote_semantics === "spot_sample_not_bid_ask";
      const label = sampled ? "Sampled indicative reference bars, not exchange OHLC" : (bars.kind === "chart_ohlc" ? "Chart OHLC, not an execution price" : "Completed bars");
      note.textContent = label + " · " + requested.interval + (bars.reference_quote === "reference_quote_unavailable" ? " · Reference quote unavailable" : "") + (bars.snapshot_id ? " · " + bars.snapshot_id : "");
    }
    const canvas = document.getElementById("chart");
    if (canvas && !canvas.dataset.bound) {
      canvas.dataset.bound = "1";
      canvas.onmousemove = (event) => {
        const line = document.getElementById("crosshair");
        if (!line) return;
        const rect = canvas.getBoundingClientRect();
        line.textContent = "Pointer " + Math.round(event.clientX - rect.left) + "×" + Math.round(event.clientY - rect.top) + " on the completed-candle chart. This is not an order ticket.";
      };
    }
  }
  async function loadBook(){
    const box = document.getElementById("termbook");
    if (!box) return;
    const response = await fetch("/api/paper/book", {credentials:"same-origin"});
    if (!response.ok) { box.innerHTML = `<h2>Paper record</h2><p>Sign in to see this account's paper trades. No sample trades are shown.</p>`; return; }
    const book = await response.json();
    const open = (book.open || []).map(row => `<div class="row"><span>${row.symbol} ${row.direction}</span><span>${priceText(row.symbol, row.entry)}</span></div><p class="muted">${row.opened_by === "autopilot" ? "AutoPilot paper" : "Account paper"}. Stop ${priceText(row.symbol, row.stop)}. Target ${priceText(row.symbol, row.target)}. Not a broker fill.</p>`).join("");
    const closed = (book.closed || []).slice(-5).map(row => `<div class="row"><span>${row.symbol} ${row.exit_kind || row.status}</span><span>${row.pnl_usd == null ? "—" : Number(row.pnl_usd).toFixed(2) + " USD"}</span></div>`).join("");
    box.innerHTML = `<h2>Paper record</h2>${open || "<p>No open paper position.</p>"}${closed || '<p class="muted">No closed paper trade on this account.</p>'}<p class="muted">These rows are the paper book. A candle estimate is not a broker fill.</p>`;
  }
  function labelPrevious(){
    ticket += 1;
    const status = document.getElementById("termstatus");
    const card = document.querySelector("#termout [data-request]");
    if (card) {
      card.dataset.stale = "1";
      const note = card.querySelector("[data-stale-note]");
      if (note) note.textContent = "Previous evaluation. It is not the current selection.";
    }
    const next = requestedNow();
    status.textContent = "Selection changed. Evaluate market for " + next.symbol + " " + next.interval + ".";
    if (next.symbol === "XAUUSD" && (next.interval === "1m" || next.interval === "3m")) status.textContent = "XAUUSD " + next.interval + " is unavailable. The restriction is xau_minute_unlicensed. No plan, size or paper order will be calculated.";
  }
  symbolEl.onchange = () => { markFrames(); labelPrevious(); loadDeskChart(); syncEvaluate(); };
  intervalEl.onchange = () => { labelPrevious(); loadDeskChart(); syncEvaluate(); };
  strategyEl.onchange = labelPrevious;
  async function history(){
    const response = await fetch("/api/terminal/history", {credentials:"same-origin"});
    const body = response.ok ? await response.json() : {items:[]};
    const rows = (body.items||[]).map(item => {
      const historical = item.interval === "4h" || item.interval === "1d" ? "Historical research record. Not a current desk timeframe. " : "";
      return `<div class="row" data-symbol="${item.symbol||""}"><span>${item.decision_label || item.decision}</span><span>${item.symbol} ${item.interval}</span></div><div class="muted">${historical}Request ${item.request_id||item.id||"saved"}. Strategy ${item.requested_strategy||item.strategy||""}. Validation ${item.validation_status||"unknown"}. Not delivered. Not filled. ${plainReason(item.reason||"")}</div>`;
    }).join("");
    document.getElementById("termhist").innerHTML = rows || "<p>No requested evaluation yet.</p>";
  }
  document.getElementById("generate").onclick = async () => {
    const status = document.getElementById("termstatus");
    const out = document.getElementById("termout");
    const button = document.getElementById("generate");
    if (button && button.disabled) {
      status.textContent = "XAUUSD 1-minute and 3-minute stay unavailable. No evaluation was sent.";
      return;
    }
    const mine = ++ticket;
    const requested = requestedNow();
    const requestId = mine + ":" + requested.symbol + ":" + requested.interval + ":" + Date.now();
    status.textContent = "Evaluating " + requested.symbol + " " + requested.interval + ".";
    out.innerHTML = "";
    try {
      const response = await fetch("/api/terminal/signal", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({symbol:requested.symbol, interval:requested.interval, strategy:requested.strategy, request_id:requestId})});
      if (mine !== ticket) return;
      if (response.status === 401) { status.textContent = "Sign in to evaluate a market."; return; }
      const body = await response.json();
      if (mine !== ticket) return;
      const same = body.symbol === requested.symbol && body.interval === requested.interval && body.request_id === requestId && body.rejected !== "market_mismatch";
      if (!same) {
        status.textContent = "The result did not match " + requested.symbol + " " + requested.interval + " and was not shown.";
        out.innerHTML = `<article class="card"><h2>Rejected</h2><p>That response was not for ${requested.symbol} ${requested.interval}. It was not presented as this selection.</p></article>`;
        return;
      }
      if (body.customer_status === "reading_unavailable") {
        status.textContent = "";
        const minute = body.blocked === "xau_minute_unlicensed";
        out.innerHTML = `<article class="card" data-request="${requestId}" data-symbol="${body.symbol}" data-interval="${body.interval}"><h2>${body.symbol || ""} ${body.interval || ""}</h2><p>${minute ? "This timeframe is not available." : "A verified live reading is not available."}</p><p class="muted">No evaluation was calculated. The manual paper plan on this page is empty until you type it.</p></article>`;
        return;
      }
      const licensed = body.blocked === "xau_minute_unlicensed";
      const size = body.size_presentation && body.size_presentation.text ? body.size_presentation.text : (body.size && body.size.reason ? `Executable sizing is unavailable: ${plainReason(body.size.reason)}.` : "No position size on this result.");
      const headline = licensed ? "UNAVAILABLE" : (body.decision_label || body.decision || "WAIT");
      const rightsHold = headline === "RIGHTS" || body.reason === "commercial_use_unverified";
      const headlineShown = rightsHold ? "Not shown" : headline;
      const withheld = licensed || rightsHold || headline === "QUOTE DIVERGENCE" || headline === "BLOCKED" || headline === "UNAVAILABLE" || Boolean(body.blocked);
      const kind = body.approved ? "Approved paper opportunity" : (rightsHold ? "Price withheld" : (headline === "WATCH" ? "Watch — no entry" : (withheld ? "Blocked" : (String(headline).includes("SELL") || String(headline).includes("BUY") ? "Experimental, not approved" : (headline === "WAIT" ? "No entry yet" : "Research observation")))));
      const klass = body.approved ? "approved" : (withheld ? "blocked" : "research");
      const px = (value) => priceText(body.symbol, value);
      const entryLine = withheld ? "—. Not an actionable entry." : (headline === "WATCH" ? `Watch level ${px(body.watch_entry)}. Not an entry.` : px(body.entry));
      const stopTarget = withheld ? "—. Withheld." : (headline === "WATCH" ? `Watch stop ${px(body.watch_stop)}. Watch target ${px(body.watch_target)}. Not an order.` : `Stop ${px(body.stop)}. Target ${px(body.target)}.`);
      const rr = withheld || body.reward_risk == null ? "—" : Number(body.reward_risk).toFixed(2);
      const gap = body.quote_gap == null ? "" : ` Observed divergence ${(Number(body.quote_gap) * 100).toFixed(2)} percent. Limit 0.08 percent.`;
      const times = headline === "QUOTE DIVERGENCE" ? ` Spot sample ${stamp(body.compared_bar_close_ms || body.bar_close_ms)}. Separate quote ${stamp(body.quote_time_ms)}.` : "";
      const why = licensed ? "Gold 1-minute and 3-minute data are not licensed. No plan was calculated from a quote or a sample candle." : (rightsHold ? (body.message || RIGHTS_MESSAGE) : plainReason(body.reason || ""));
      const sourceLine = licensed ? "Licensed spot minute data unavailable. A quote was not used as a candle." : (rightsHold ? "Not read. No commercial use is approved." : (plainReason(body.source_name || "unknown") + ". " + plainReason(body.quote || "source not named")));
      const sampledBar = body.quote === "spot_sample_not_bid_ask";
      const candleLine = licensed ? "Not evaluated. No 1-minute or 3-minute bar was requested." : (rightsHold ? "Not read. No bar was requested." : ((body.fresh ? (sampledBar ? "Sampled reference bar is fresh." : "Completed bar is fresh.") : (sampledBar ? "Not a fresh sampled reference bar." : "Not a fresh completed bar.")) + " " + stamp(body.bar_close_ms)));
      const audit = body.research_levels && body.research_levels.audit_only ? `<details><summary>Audit only, not a trade plan</summary><p class="muted">Stored research levels stay off the plan. Entry ${px(body.research_levels.entry)}. Stop ${px(body.research_levels.stop)}. Target ${px(body.research_levels.target)}.</p></details>` : "";
      const chain = body.evidence_chain ? `<details><summary>Evidence chain</summary><p class="muted">Source ${plainReason(body.evidence_chain.data_source || "unnamed")}. Candle ${stamp(body.evidence_chain.completed_candle_ms)}. Rule ${body.evidence_chain.strategy_version || "unnamed"}. Decision ${body.evidence_chain.decision || "WAIT"}. Approved: ${body.evidence_chain.approved ? "yes" : "no"}. No calibrated probability is shown.</p></details>` : "";
      const persona = body.persona_name ? `${body.persona_name}. ${body.persona_note || ""}` : "No persona note.";
      const canReview = !withheld && (body.decision === "BUY" || body.decision === "SELL") && body.entry != null && body.approved !== true;
      const paper = canReview
        ? `<p><button id="openpaper" type="button">Review this paper plan</button></p><div id="planreview"></div><p class="muted">Review does not open an order. Confirming records a paper estimate. It does not send a broker order and AutoPilot will not open it.</p>`
        : `<p class="muted">Paper trade unavailable${body.paper&&body.paper.reason?": "+plainReason(body.paper.reason):"."} ${withheld ? "No order is created from a blocked reading." : "An observation is not an order. The market plan is unchanged."}</p>`;
      out.innerHTML = `<article class="card ${klass}" data-request="${requestId}" data-symbol="${body.symbol}" data-interval="${body.interval}"><p data-stale-note></p><p class="badge ${klass === "blocked" ? "block" : (klass === "approved" ? "ok" : "research")}">${kind}</p><h2>${headlineShown}</h2><dl class="sections"><dt>Evaluation status</dt><dd>${headlineShown}</dd><dt>Market and timeframe</dt><dd>${body.symbol||""} ${body.interval||""}</dd><dt>Data source</dt><dd>${sourceLine}</dd><dt>Candle completion</dt><dd>${candleLine}</dd><dt>Observation</dt><dd>${headlineShown}</dd><dt>Validation</dt><dd>${body.validation_status||"unknown"}. ${body.approved?"Approved.":"Not an approved strategy and not a claim of profit."}</dd><dt>Entry condition</dt><dd>${entryLine}</dd><dt>Stop and target</dt><dd>${stopTarget}</dd><dt>Reward/risk</dt><dd class="num">${rr}</dd><dt>Persona eligibility</dt><dd>${persona}</dd><dt>Sizing</dt><dd>${withheld ? "Not calculated." : plainReason(size)}</dd><dt>Why it is waiting or blocked</dt><dd>${why}${gap}${times}</dd></dl>${audit}${chain}<details><summary>Technical record</summary><p class="muted">Request ${requestId}. Requested ${body.requested_symbol||""} ${body.requested_interval||""} ${body.requested_strategy||""}. Resolved ${body.strategy||""}. ${body.evidence_semantics||""} ${body.invalidation||""}</p></details>${paper}</article>`;
      const opener = document.getElementById("openpaper");
      if (opener) {
        opener.onclick = async () => {
          opener.disabled = true;
          const reviewed = await fetch("/api/desk/plan", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({symbol: body.symbol, interval: body.interval})});
          const payload = await reviewed.json().catch(() => ({}));
          const box = document.getElementById("planreview");
          if (!reviewed.ok || !payload.opportunity_id) {
            if (box) box.innerHTML = `<p>No paper plan was saved. ${plainReason(payload.reason || payload.reading_class || "not available")}. No order was opened.</p>`;
            opener.disabled = false;
            return;
          }
          const allow = payload.paper && payload.paper.allowed;
          const sized = payload.paper && payload.paper.size;
          const sizeLine = sized && sized.risk_budget_usd != null
            ? `Risk budget ${Number(sized.risk_budget_usd).toFixed(2)} USD at ${payload.paper.risk_percent} percent. ${sized.ok && sized.quantity != null ? "Quantity " + Number(sized.quantity).toFixed(6) + " is an unrounded estimate, not an exchange lot." : plainReason(sized.note || sized.reason || "Size was not calculated.")}`
            : `Account check: ${plainReason((payload.paper && payload.paper.reason) || "not allowed")}.`;
          if (box) box.innerHTML = `<p>Entry ${priceText(body.symbol, payload.entry)}. Stop ${priceText(body.symbol, payload.stop)}. Target ${priceText(body.symbol, payload.target)}. ${plainReason(payload.explanation || "")} ${sizeLine}</p><p class="muted">Snapshot ${payload.snapshot_id || ""}. Not approved. Not AutoPilot.</p>${allow ? `<p><button id="confirmpaper" type="button">Confirm manual paper order</button></p>` : `<p>The account rules did not allow an order. The plan stays a review.</p>`}`;
          const confirm = document.getElementById("confirmpaper");
          if (confirm) confirm.onclick = async () => {
            confirm.disabled = true;
            const opened = await fetch("/api/paper/orders", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({opportunity_id: payload.opportunity_id})});
            const done = await opened.json().catch(() => ({}));
            confirm.textContent = opened.ok && done.ok ? "Paper trade recorded. It is an estimate, not a broker fill." : ("Not opened. " + plainReason(done.reason || "Try again."));
            loadBook();
          };
        };
      }
      history();
      loadBook();
    } catch (err) {
      if (mine !== ticket) return;
      status.textContent = "The evaluation could not be completed. Please retry.";
    }
  };
  loadWatch();
  loadDeskChart();
  loadBook();
  history();
  bindManualPlan();
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
function dataCoverageCard(payload){
  if (!payload || !payload.coverage) return `<article class="card" id="data-coverage"><h2>Research data coverage</h2><p>The data-rights report could not be read. Historical research is not shown as available.</p></article>`;
  const rows = payload.coverage.map(row => `<div class="row"><span>${row.market} ${row.timeframe}</span><span>${row.rights_label}</span></div>`).join("");
  const sources = (payload.sources || []).map(row => `<div class="row"><span>${row.provider}</span><span>${row.status_label}</span></div><p class="muted">${row.product}. ${row.note}</p>`).join("");
  const held = (payload.retained_files || []).map(row => `${row.name} (${row.bytes} bytes, not re-read)`).join(", ") || "none";
  const bytes = payload.storage ? Math.round(payload.storage.total_bytes / 1000000) : "unknown";
  return `<article class="card" id="data-coverage"><h2>Research data coverage</h2><p>${RIGHTS_MESSAGE}</p><p>${payload.headline}</p><p class="muted">Approved strategies: ${payload.strategy.approved_for_paper}. Holdout from ${payload.holdout.start} is ${payload.holdout.opened ? "open" : "sealed"}. Quote divergence limit remains 0.08 percent. Previously stored files were not re-read.</p><details><summary>Source rights and retained files</summary>${rows}<h3>Source rights</h3>${sources}<p class="muted">Reviewed ${payload.reviewed_on}. Previously stored files, unread this pass: ${held}. A 4h file is not desk history. Estimated size of a later full crypto desk archive: about ${bytes} MB. Collected this pass: ${payload.collected_bytes} bytes. Free space on this workspace: ${payload.disk_free_bytes} bytes. Forward collection: ${payload.forward_collection}.</p></details></article>`;
}
async function researchLab(){
  view.innerHTML = `<div id="res-sum"><article class="card"><p class="muted">Research</p><div class="skeleton lg"></div></article></div><article class="card" id="res-body"><p role="status">Loading the saved research record. No dataset is being re-scored.</p></article>`;
  const [d, qual, platform] = await Promise.all([timed("/api/research-lab"), timed("/api/qualification"), timed("/api/platform")]);
  if (!d) {
    view.innerHTML = `<article class="card"><h2>Research</h2><p>The research record could not be loaded. No result was invented.</p><p><button type="button" id="res-retry">Retry</button></p></article>`;
    const again = document.getElementById("res-retry");
    if (again) again.onclick = () => researchLab();
    return;
  }
  const gates = (d.gates||[]).map(g => `<details><summary>${g.name} — ${g.status}</summary><p class="muted">${g.evidence}</p></details>`).join("");
  const rows = (d.experiments||[]).map(e => `<details><summary>${e.name} — ${e.decision}</summary><p class="muted">${e.id}. ${e.reason}</p></details>`).join("");
  const audit = d.data_audit || {};
  const retained = (audit.retained||[]).map(row => `<div class="row"><span>${row.symbol} ${row.interval}</span><span>${row.bars||0} bars</span></div><p class="muted">${row.start||""} to ${row.end||""}. Gaps ${row.gaps}. Duplicates ${row.duplicates}. Invalid ${row.invalid}. Fingerprint ${row.file_sha256||"none"}. ${row.limitation||""}</p>`).join("");
  const missing = (audit.desk_pairs_missing_history||[]).join(", ");
  const discovery = d.discovery || {};
  const markets = (discovery.markets||[]).map(market => {
    const dev = market.development || {};
    const val = market.validation || {};
    const bench = market.benchmark_prefix || {};
    return `<article class="card"><h3>${market.symbol}</h3><p>${dev.judgment||"n/a"} on development. ${val.judgment||"n/a"} on validation. Holdout ${market.holdout||"NOT_OPENED"}. Approved for paper: no.</p><details><summary>Recorded metrics</summary><p>Development n=${dev.trades==null?"n/a":dev.trades}, net mean ${dev.base_mean==null?"n/a":Number(dev.base_mean).toFixed(5)}, drawdown ${dev.max_drawdown==null?"n/a":Number(dev.max_drawdown).toFixed(3)}. Validation n=${val.trades==null?"n/a":val.trades}, net mean ${val.base_mean==null?"n/a":Number(val.base_mean).toFixed(5)}. Prefix buy-and-hold gross ${bench.buy_and_hold_gross==null?"n/a":Number(bench.buy_and_hold_gross).toFixed(3)}.</p><p class="muted">Failed ${JSON.stringify(dev.failed||[])} / ${JSON.stringify(val.failed||[])}. Blocked ${JSON.stringify(val.blocked||[])}. Long only. Not re-scored.</p></details></article>`;
  }).join("");
  view.innerHTML = `${researchSummary(qual, platform)}<article class="card"><h2>Research summary</h2><p>Promoted strategies: ${d.promoted_count}. Production: ${d.production}. Approved for paper: none. Historical research on withheld sources stays unavailable. Nothing here is a live signal.</p>${gates}</article><article class="card"><h2>Dataset provenance</h2><details><summary>Retained files, not re-read</summary>${retained||"<p>No retained history file was found.</p>"}<p class="muted">Desk pairs with no retained candle file: ${missing||"none listed"}. A missing file is not a sample. Synthetic bars are not used to approve a strategy.</p></details></article><article class="card" id="data-coverage"><h2>Research data coverage</h2><p>Reading data rights.</p></article><article class="card"><h2>Latest pre-registered study</h2><p>${discovery.version||"No discovery file."} Decision: ${discovery.decision||"not scored"}. Holdout opened for: ${(discovery.holdout_opened_for||[]).join(", ")||"nobody"}.</p>${markets||"<p>No scored market.</p>"}<p class="muted">${discovery.multiple_testing||""} Protocol ${discovery.protocol_sha256||""}. This card is research evidence. It is not an approved signal and it is not a performance promise.</p></article><article class="card"><h2>Experiment archive</h2>${rows}<p class="muted">${d.note}</p></article>`;
  fetch("/api/data-coverage", {credentials:"same-origin"}).then(r => r.json()).then(payload => {
    const box = document.getElementById("data-coverage");
    if (box) box.outerHTML = dataCoverageCard(payload);
  }).catch(() => {
    const box = document.getElementById("data-coverage");
    if (box) box.innerHTML = `<h2>Research data coverage</h2><p>The data-rights report could not be read. Historical research is not shown as available.</p>`;
  });
}
async function scannerPage(){
  let lastBody = null;
  view.innerHTML = `<article class="card"><h2>Live Scanner</h2><p id="scanstatus" role="status">Checking which prices can be shown.</p><p class="muted" id="scanwhen">A reading uses the latest completed candle. It is not a tick feed and not an order.</p><p id="scanstale" class="stale-note" hidden></p><div id="scancards"><p class="muted">Loading coverage. No price is invented while this loads.</p></div></article><article class="card" id="scanboard"><h2>Market coverage</h2><div class="skeleton lg"></div></article>`;
  const draw = (body, staleNote) => {
    const cards = (body.markets||[]).map(m => {
      if (m.customer_status === "reading_unavailable") {
        const minute = m.blocked === "xau_minute_unlicensed";
        return `<article class="card" data-symbol="${m.symbol}"><h2>${m.symbol} · ${m.interval||""}</h2><div class="row"><span>${minute ? "Unavailable" : "WAIT"}</span><span class="num">—</span></div><p class="muted">${minute ? "This timeframe is not available." : "A verified live reading is not available."}</p></article>`;
      }
      const headline = m.decision_label || m.scanner_state || m.state || "WAIT";
      if (isRightsHold(headline, m.scanner_state, m.status)) {
        return `<article class="card blocked" data-symbol="${m.symbol}"><p class="badge block">Price withheld</p><h2>${m.symbol} · ${m.interval||""}</h2><div class="row"><span>Not shown</span><span class="num">—</span></div><p>${m.message || RIGHTS_MESSAGE}</p><p class="muted">No rule was run. This is not a missed setup and not a provider outage.</p></article>`;
      }
      if (headline === "UNAVAILABLE" || m.blocked === "xau_minute_unlicensed") {
        return `<article class="card blocked" data-symbol="${m.symbol}"><p class="badge block">Unavailable</p><h2>${m.symbol} · ${m.interval||""}</h2><div class="row"><span>Not available</span><span class="num">—</span></div><p>${plainReason(m.message||"This timeframe is not available.")}</p><p class="muted">No candle was substituted.</p></article>`;
      }
      const blocked = headline === "QUOTE DIVERGENCE" || headline === "BLOCKED" || m.scanner_state === "BLOCKED" || m.scanner_state === "QUOTE_DIVERGENCE" || m.state === "DATA_UNAVAILABLE" || m.blocked;
      const kind = headline === "QUOTE DIVERGENCE" ? "Blocked" : (headline === "WATCH" ? "Watch — no entry" : (String(headline).includes("SELL") || String(headline).includes("BUY") ? "Experimental, not approved" : (headline === "WAIT" ? "No entry yet" : "Research observation")));
      const klass = m.approved ? "approved" : (blocked || kind === "Blocked" ? "blocked" : "research");
      const hideLevels = blocked || kind === "Blocked" || kind === "Watch — no entry" || kind === "No entry yet" || kind === "No qualifying setup" || m.entry == null;
      const levels = hideLevels
        ? `<p>Entry —. Stop —. Target —. ${headline === "QUOTE DIVERGENCE" ? "Withheld. The sources differ by more than 0.08 percent." : "No actionable plan is shown."}</p>`
        : `<p>Hypothetical research levels, not an order. Entry ${priceText(m.symbol, m.entry)}. Stop ${priceText(m.symbol, m.stop)}. Target ${priceText(m.symbol, m.target)}.</p>`;
      const gap = m.quote_gap == null ? "" : ` Observed divergence ${(Number(m.quote_gap)*100).toFixed(2)} percent. Limit 0.08 percent.`;
      const times = headline === "QUOTE DIVERGENCE" ? ` Spot sample ${stamp(m.compared_bar_close_ms)}. Separate quote ${stamp(m.quote_time_ms)}.` : "";
      const source = plainReason(m.quote_label || m.quote || "source not named");
      const lineage = m.snapshot_id ? ` ${m.direction_label || "neutral"}. ${m.reading_class || "observational"}. Candle ${m.candle_close_ms ? when(m.candle_close_ms) : "time unknown"}.` : "";
      const scope = m.reading_class === "unavailable" ? " Unavailable data. Not a missed setup." : (m.reading_class === "insufficient" ? " The candle is not fresh enough to plan. Not a missed setup." : (headline === "WAIT" ? " No qualifying setup on this completed candle." : ""));
      const grade = m.evaluated === false || (blocked && m.evidence_grade == null)
        ? "No candidate evidence grade. The rule was not validly evaluated."
        : "No evidence grade is shown as a probability.";
      return `<article class="card ${klass}" data-symbol="${m.symbol}"><p class="badge ${klass==="blocked"?"block":"research"}">${kind}</p><h2>${m.symbol} · ${m.interval||""}</h2><div class="row"><span>${headline}</span><span class="num">${m.price==null?"—":priceText(m.symbol, m.price)}</span></div><p class="muted">${source}. ${m.evaluated===false?"This market did not complete a valid reading.":"Reading complete."}${lineage}${scope}</p><p>${plainReason(m.message||"No qualifying setup yet.")}${gap}${times}</p>${levels}<p class="muted">${grade} Updated ${m.updated_at||"unknown"}. ${m.snapshot_id || ""}</p><details><summary>Technical evidence</summary><p class="muted">${plainReason(m.diagnostic||"")} State ${m.scanner_state||m.state||"unknown"}. Source code ${m.quote||"unnamed"}.</p></details></article>`;
    }).join("");
    const qualifying = (body.markets||[]).some(m => m.approved || m.scanner_state === "APPROVED_SIGNAL");
    const heldOnly = (body.markets||[]).length > 0 && (body.markets||[]).every(m => isRightsHold(m.decision_label, m.scanner_state, m.status));
    const readingOff = (body.markets||[]).length > 0 && (body.markets||[]).every(m => m.customer_status === "reading_unavailable");
    const box = document.getElementById("scancards");
    if (readingOff) {
      if (box) box.innerHTML = cards;
      const status = document.getElementById("scanstatus");
      if (status) status.textContent = body.notice || "No eligible live reading is available.";
      const when = document.getElementById("scanwhen");
      if (when) when.textContent = "The instruments stay listed. No price was invented. This is not an order.";
      const stale = document.getElementById("scanstale");
      if (stale) { stale.hidden = !staleNote; stale.textContent = staleNote || ""; }
      return;
    }
    if (heldOnly) {
      if (box) box.innerHTML = `<article class="card blocked"><p class="badge block">Rights withheld</p><h2>No reading was performed</h2><p>${RIGHTS_MESSAGE}</p><p class="muted">The rights gate stopped the request before any candle was read. That is not a missed setup and not a provider outage. The twelve pairs are in the table below.</p></article>`;
      const status = document.getElementById("scanstatus");
      if (status) status.textContent = staleNote ? "Scan refresh failed." : "Market data withheld. No evaluation was run.";
      const when = document.getElementById("scanwhen");
      if (when) when.textContent = "No candle was read. Prices stay hidden until commercial use is approved. This is not a tick feed and not an order.";
      const stale = document.getElementById("scanstale");
      if (stale) { stale.hidden = !staleNote; stale.textContent = staleNote || ""; }
      return;
    }
    const emptyNote = qualifying ? "" : `<article class="card"><h2>No qualifying opportunity</h2><p>None of these readings is an approved paper opportunity. Nothing was invented to fill the page.</p></article>`;
    if (box) box.innerHTML = (cards || `<article class="card"><h2>No qualifying opportunity</h2><p>The scan returned no market cards.</p></article>`) + emptyNote;
    const status = document.getElementById("scanstatus");
    if (status) status.textContent = staleNote ? "Scan refresh failed." : (body.notice || "Scan complete.");
    const clock = document.getElementById("scanwhen");
    if (clock) clock.textContent = body.scanned_at ? ("Last successful read " + body.scanned_at + ". A reading uses the latest completed candle. It is not a tick feed and not an order.") : "No completed candle was returned. No price was invented. This is not a tick feed and not an order.";
    const stale = document.getElementById("scanstale");
    if (stale) { stale.hidden = !staleNote; stale.textContent = staleNote || ""; }
  };
  const loadCoverage = () => {
    timed("/api/platform").then(platform => {
      const box = document.getElementById("scanboard");
      if (!box) return;
      if (!platform || !(platform.pairs || []).length) {
        box.innerHTML = `<h2>Market coverage</h2><p>The coverage list could not be read. No prices were invented.</p><p><button type="button" id="scan-retry">Retry</button></p>`;
        const again = document.getElementById("scan-retry");
        if (again) again.onclick = () => loadCoverage();
        return;
      }
      const lines = platform.pairs.map(pair => `<tr><td>${pair.instrument}</td><td>${pair.timeframe}</td><td><span class="badge${pair.evaluation === "Unavailable" ? " block" : ""}">${pair.rights}</span></td><td>${pair.source}</td><td>${pair.history}</td><td>${pair.latest_read}</td><td>${pair.evaluation}</td><td>${pair.approval}</td></tr>`).join("");
      box.innerHTML = `<h2>Market coverage</h2><p class="muted">Gold one-minute and three-minute are not offered. A verified live reading is not available for the other pairs. A row is not an order.</p><div class="tablewrap"><table class="matrix"><thead><tr><th>Instrument</th><th>Time</th><th>Status</th><th>Source</th><th>History</th><th>Latest read</th><th>Evaluation</th><th>Note</th></tr></thead><tbody>${lines}</tbody></table></div>`;
    });
  };
  const fail = (message) => {
    if (lastBody) { draw(lastBody, message + " The cards are the previous read and are not a new price."); return; }
    const box = document.getElementById("scancards");
    if (box) box.innerHTML = `<article class="card"><h2>Scanner unavailable</h2><p>${message} No prices were invented.</p></article>`;
    const status = document.getElementById("scanstatus");
    if (status) status.textContent = "Scan failed.";
  };
  const loadScan = async () => {
    const status = document.getElementById("scanstatus");
    if (status && lastBody) status.textContent = "Refreshing the scan.";
    try {
      const response = await fetch("/api/scanner", {credentials:"same-origin"});
      if (response.status === 401) { view.innerHTML = `<article class="card"><h2>Sign in required</h2><p><a href="/login">Sign in</a></p></article>`; return; }
      if (!response.ok) { fail("The scan did not succeed."); return; }
      const body = await response.json().catch(()=>null);
      if (!body) { fail("The response could not be read."); return; }
      lastBody = body;
      draw(body, null);
      loadCoverage();
    } catch (err) {
      fail("The request failed.");
    }
  };
  await loadScan();
  if (window.__scanTimer) clearInterval(window.__scanTimer);
  window.__scanTimer = setInterval(loadScan, 15000);
}

async function learnPage(){
  const lab = await fetch("/api/lab", {credentials:"same-origin"}).then(r => r.ok ? r.json() : null).catch(()=>null);
  if (!lab) { view.innerHTML = `<article class="card"><h2>Academy</h2><p>Lessons are saved on your account. <a href="/login">Sign in</a> to read them and mark progress. A lesson is not a signal, and no firm rule is stored as verified.</p></article>`; return; }
  const done = new Set(lab.completed_lessons || []);
  const courses = lab.courses || [];
  const total = (lab.lessons || []).length;
  const cards = courses.map(course => {
    const lessons = (course.lessons || []).map(lesson => {
      const sections = (lesson.sections || [lesson.body]).map(part => `<p>${part}</p>`).join("");
      const choices = ((lesson.check || {}).choices || []).map((choice, index) => `<label><input type="radio" name="check-${lesson.id}" value="${index}"> ${choice}</label>`).join("");
      return `<article class="card course" id="lesson-${lesson.id}"><p class="muted">${course.title}</p><h2>${lesson.title}</h2><p><strong>Objective.</strong> ${lesson.objective || ""}</p>${sections}<p class="muted">Exercise: ${lesson.exercise || ""}</p><div class="checks">${choices}</div><p class="checknote muted" id="check-${lesson.id}"></p><div class="bar" aria-hidden="true"><span style="width:${done.has(lesson.id) ? "100%" : "0%"}"></span></div><p class="muted">${done.has(lesson.id) ? "Completed on this account." : "Not completed."} Not a verified firm rule. No video is attached.</p><button type="button" data-lesson="${lesson.id}">${done.has(lesson.id) ? "Completed" : "Mark complete"}</button></article>`;
    }).join("");
    return `<h2>${course.title}</h2>${lessons}`;
  }).join("");
  const custom = ((lab.rules || {}).custom_rules || []).map(rule => `<p>${rule.text}</p><p class="muted">${rule.note}</p>`).join("");
  view.innerHTML = `<article class="card"><h2>Academy</h2><p>${done.size} of ${total} lessons completed on this account.</p><p>${(lab.rules || {}).verified_note || ""}</p><p class="muted">These lessons explain the desk. They do not open a paper trade. Completion is not a skill score.</p></article><div class="courses">${cards}</div><article class="card"><h2>Your own challenge note</h2>${custom || "<p>No personal note yet.</p>"}<label>Note <input id="rule" maxlength="400"></label><button id="saverule" type="button">Save as my note</button><p class="muted">A note you type is not confirmed as a firm's current rule.</p></article>`;
  document.querySelectorAll("[data-lesson]").forEach(button => { button.onclick = async () => {
    const lessonId = button.dataset.lesson;
    const selected = document.querySelector(`input[name="check-${lessonId}"]:checked`);
    const note = document.getElementById("check-" + lessonId);
    const lesson = (lab.lessons || []).find(item => item.id === lessonId) || {};
    const expected = lesson.check ? String(lesson.check.answer) : null;
    if (expected != null && (!selected || selected.value !== expected)) {
      if (note) note.textContent = "The check does not match the lesson. Completion was not saved.";
      return;
    }
    const next = [...done, lessonId];
    await fetch("/api/lab", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({completed_lessons: next})});
    learnPage();
  }; });
  document.getElementById("saverule").onclick = async () => {
    await fetch("/api/lab", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({custom_rule: document.getElementById("rule").value})});
    learnPage();
  };
}
async function labPage(){
  const lab = await fetch("/api/lab", {credentials:"same-origin"}).then(r => r.ok ? r.json() : null).catch(()=>null);
  if (!lab) { view.innerHTML = `<article class="card"><h2>Sign in required</h2><p><a href="/login">Sign in</a> to open your Trading Lab.</p></article>`; return; }
  const persona = lab.persona || {};
  const bot = lab.autopilot || {};
  const figures = lab.performance || {};
  const focus = new Set(lab.focus || []);
  const ideas = (lab.improvement || []).map(item => `<li><a href="/learn#lesson-${item.lesson_id}">${item.lesson_id}</a>: ${item.because}</li>`).join("");
  const journal = (lab.journal || []).map(row => `<p>${row.opened_by === "autopilot" ? "AutoPilot" : "Account"} · ${row.symbol || ""} · ${row.status || ""} · ${row.exit_kind || "no exit"}. ${row.note || ""}</p>`).join("");
  const reflections = (lab.journal_notes || []).map(row => `<p>${row.text}</p>`).join("");
  const botLine = autoSentence(bot);
  view.innerHTML = `<article class="card"><h2>Your desk</h2><p>Experience you stated: ${lab.experience}. Objective: ${lab.objective || "not set"}.</p><p>Persona ${persona.name || "not selected"}. Risk cap ${persona.risk_per_trade_percent ?? "—"}%. Reward floor ${persona.min_rr ?? "—"}. Paper timeframes ${(persona.paper_timeframes || []).join(", ") || "—"}.</p><p>Markets saved on the account: ${((lab.preferences || {}).markets || []).join(", ") || "not set"}.</p><p>AutoPilot ${botLine}</p><p>${lab.observation}</p><p class="muted">${figures.trades ? "Closed paper trades: " + figures.trades + "." : "No completed paper trade."} ${lab.note}</p></article><article class="card"><h2>Journal</h2>${journal || "<p>No paper order is recorded for this account.</p>"}<p class="muted">These lines come from the paper book. They are not a broker history, and they do not diagnose discipline.</p><h3>Your notes</h3>${reflections || "<p>No reflection saved.</p>"}<label>Reflection <input id="journalnote" maxlength="500"></label><button id="savenote" type="button">Save reflection</button><p class="muted">A note is what you wrote. It is not an inferred weakness.</p></article><article class="card"><h2>What to study next</h2><ul>${ideas || "<li>No further suggestion.</li>"}</ul><p class="muted">A suggestion is an unfinished lesson. It is not a skill score. <a href="/learn">Open Academy</a></p></article><form id="labform" class="card"><h2>Learning profile</h2><label>Experience <select id="exp"><option value="new">New</option><option value="developing">Developing</option><option value="independent">Independent</option></select></label><label>Objective <input id="objective" maxlength="160" value="${lab.objective || ""}"></label><div class="checks"><label><input type="checkbox" value="candles" ${focus.has("candles")?"checked":""}> Candles</label><label><input type="checkbox" value="risk" ${focus.has("risk")?"checked":""}> Risk</label><label><input type="checkbox" value="psychology" ${focus.has("psychology")?"checked":""}> Psychology</label><label><input type="checkbox" value="prop" ${focus.has("prop")?"checked":""}> Prop education</label></div><button type="submit">Save lab profile</button><p id="labsaved" class="muted"></p></form>`;
  if (lab.experience && lab.experience !== "not_stated") document.getElementById("exp").value = lab.experience;
  document.getElementById("labform").onsubmit = async (event) => {
    event.preventDefault();
    const chosen = [...document.querySelectorAll("#labform input:checked")].map(box => box.value);
    const saved = await fetch("/api/lab", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({experience: document.getElementById("exp").value, objective: document.getElementById("objective").value, focus: chosen})});
    document.getElementById("labsaved").textContent = saved.ok ? "Saved on this account." : "Could not save.";
  };
  const saveNote = document.getElementById("savenote");
  if (saveNote) saveNote.onclick = async () => {
    const saved = await fetch("/api/lab", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({journal_note: document.getElementById("journalnote").value})});
    if (saved.ok) labPage();
  };
}
async function planPage(){
  const response = await fetch("/api/plan", {credentials:"same-origin"});
  if (response.status === 401) { view.innerHTML = `<article class="card"><h2>Sign in required</h2><p><a href="/login">Sign in</a> to save a plan.</p></article>`; return; }
  const body = await response.json();
  const plan = body.plan || {};
  const week = body.week || {};
  const catalog = await fetch("/api/registry", {credentials:"same-origin"}).then(r => r.json());
  const bucket = (s) => {
    if (s.promoted || s.research_status === "PASS") return "Approved";
    if (s.research_status === "BLOCKED") return "Blocked by market or data";
    if (s.research_status === "RESEARCH" || s.research_status === "OBSERVATION") return "Research observation";
    if (!s.research_status || s.research_status === "UNKNOWN") return "Not yet evaluated";
    return "Not approved";
  };
  const grouped = {};
  (catalog.strategies||[]).forEach(s => {
    const name = bucket(s);
    grouped[name] = grouped[name] || [];
    const primary = String(s.evidence || "No evidence text.").split(". ")[0];
    grouped[name].push(`<div class="plan-group"><label><input type="checkbox" value="${s.id}" ${ (plan.strategies||[]).includes(s.id) ? "checked" : "" }> ${s.name}</label><p class="muted">${primary}.</p><details><summary>${s.research_status}</summary><p class="muted">${s.evidence || "No extra evidence text."} Selecting this does not force a signal and does not make AutoPilot place an order.</p></details></div>`);
  });
  const order = ["Approved", "Research observation", "Blocked by market or data", "Not yet evaluated", "Not approved"];
  const options = order.filter(name => grouped[name]).map(name => `<h3>${name}</h3>${grouped[name].join("")}`).join("");
  view.innerHTML = `<article class="card"><h2>This week ${week.week||""}</h2><p>Chosen aim: ${week.aim_percent==null?"not set":week.aim_percent+"%"}.</p><p>${week.paper_note||""}</p><p class="muted">Approved alerts this week: ${week.approved_alerts}. Simulated trades: ${week.simulated_trades}. A target does not force a signal. The weekly loss limit blocks a new paper order once it is reached.</p></article><form id="planform" class="card"><h2>Plan</h2><p id="plannote" role="status"></p><label>Mode <select id="mode"><option value="auto">Auto: evaluate every compatible strategy</option><option value="selected">Selected strategies only</option></select></label><div class="checks">${options}</div><p>Markets</p><div class="checks"><label><input id="plan-btc" type="checkbox" ${(plan.markets||[]).includes("BTCUSDT")?"checked":""}> BTCUSDT</label><label><input id="plan-eth" type="checkbox" ${(plan.markets||[]).includes("ETHUSDT")?"checked":""}> ETHUSDT</label><label><input id="plan-gold" type="checkbox" ${(plan.markets||[]).includes("XAUUSD")?"checked":""}> XAUUSD</label></div><label>Minimum evidence grade <input id="grade" type="number" min="0" max="100" value="${plan.min_evidence_grade||0}"></label><p class="muted">This is a checklist score, not a probability of profit.</p><label>Weekly aim percent <input id="aim" type="number" min="0" max="100" step="any" value="${plan.weekly_aim_percent??""}"></label><label>Weekly loss limit percent <input id="loss" type="number" min="0" max="100" step="any" value="${plan.weekly_loss_limit_percent??""}"></label><label>Per-trade risk percent <input id="risk" type="number" min="0" max="100" step="any" value="${plan.risk_per_trade_percent??""}"></label><p class="muted">Style cap ${body.style_cap==null?"not set":body.style_cap+"%"}. A higher number is rejected. Currency stays ${body.currency||"unset"} and is not converted. A market you turn off cannot be opened as a paper trade.</p><label><input id="research" type="checkbox" ${plan.research_alerts?"checked":""}> Optional research notes in the app. Off by default. These are not trade alerts.</label><button type="submit">Save plan</button></form>`;
  document.getElementById("mode").value = plan.mode || "auto";
  document.getElementById("planform").onsubmit = async (event) => {
    event.preventDefault();
    const strategies = [...document.querySelectorAll("#planform input[type=checkbox][value]")].filter(box => box.checked).map(box => box.value);
    const markets = [];
    if (document.getElementById("plan-btc").checked) markets.push("BTCUSDT");
    if (document.getElementById("plan-eth").checked) markets.push("ETHUSDT");
    if (document.getElementById("plan-gold").checked) markets.push("XAUUSD");
    const payload = {mode: document.getElementById("mode").value, strategies, markets, min_evidence_grade: document.getElementById("grade").value, weekly_aim_percent: document.getElementById("aim").value, weekly_loss_limit_percent: document.getElementById("loss").value, risk_per_trade_percent: document.getElementById("risk").value, research_alerts: document.getElementById("research").checked};
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
  const list = rows.map(item => {
    const freshness = item.freshness || (item.created_ms ? ((Date.now() - item.created_ms) > 3*86400000 ? "historical" : (Date.now() - item.created_ms) > 86400000 ? "stale" : "current") : "unknown");
    const ageLabel = item.age_label || (item.created_ms ? new Date(item.created_ms).toISOString() : "time unknown");
    const noticeClass = item.notice_class || (item.decision === "WAIT" ? "WAIT notification" : "inbox notice");
    const when = item.created_ms ? new Date(item.created_ms).toISOString() : "";
    const researchLevels = `<p class="muted">Research levels, not a paper order. Entry ${item.entry==null?"—":priceText(item.symbol, item.entry)}. Stop ${item.stop==null?"—":priceText(item.symbol, item.stop)}. Target ${item.target==null?"—":priceText(item.symbol, item.target)}.</p>`;
    return `<article class="card ${noticeClass.includes("WAIT") || noticeClass.includes("blocked") ? "blocked" : "research"}" data-kind="${item.kind||""}" data-symbol="${item.symbol||""}"><p class="badge ${item.read ? "" : "block"}">${item.read_state || (item.read ? "read" : "unread")}</p><p class="badge">${freshness}</p><p class="badge research">${noticeClass}</p><h2>${item.lifecycle==="superseded"||item.lifecycle==="expired" ? item.lifecycle.toUpperCase()+" · " : ""}${item.decision || item.state || "Notice"} · ${item.symbol || "Desk"} ${item.interval || ""}</h2><p>${item.lifecycle_note || item.label || ""}</p><p>${plainReason(item.message || "")}</p>${researchLevels}<p class="muted">${ageLabel}. ${when}. ${item.strategy || "no strategy"}. Validation ${item.validation_status || "n/a"}. ${item.approved?"Approved.":"Not approved."} This inbox notice is not a paper order.</p>${item.decision==="BUY"||item.decision==="SELL"?`<button type="button" data-paper="${item.opportunity_id||""}">Open paper trade</button><p class="muted">Opening a paper trade is a separate action. The notice itself does not create one.</p>`:""}${item.actionable ? "" : "<p>Not an approved trade.</p>"}<button type="button" data-id="${item.id}">Mark read</button></article>`;
  }).join("");
  view.innerHTML = `<p role="status">${body.unread || 0} unread.</p>${list || "<article class='card'><h2>No notifications</h2><p>A quiet scan is recorded once a day. A research note appears only if you opted in. Nothing here is a trade alert unless a strategy has been approved. None has.</p></article>"}<button id="readall" type="button">Mark all read</button>`;
  const refresh = async (id) => { await fetch("/api/notifications/read", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify(id ? {id} : {})}); inboxPage(); };
  document.getElementById("readall").onclick = () => refresh(null);
  document.querySelectorAll("[data-id]").forEach(button => { button.onclick = () => refresh(button.dataset.id); });
  document.querySelectorAll("[data-paper]").forEach(button => { button.onclick = async () => {
    const opened = await fetch("/api/paper/orders", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({opportunity_id: button.dataset.paper})});
    const payload = await opened.json().catch(()=>({}));
    button.textContent = opened.ok && payload.ok ? "Paper trade recorded" : ("Not opened: " + (payload.reason || "unavailable"));
  }; });
}
async function load(){
  if (path === "/notifications") return inboxPage();
  if (path === "/plan") return planPage();
  if (path === "/scanner") return scannerPage();
  if (path === "/learn" || path === "/indicators") return learnPage();
  if (path === "/lab") return labPage();
  if (path === "/trading") return terminal();
  if (path === "/" || path === "/overview") return overview();
  if (path === "/signals") return signals();
  if (path === "/onboarding" || path === "/settings") return settings();
  if (path === "/portfolio" || path === "/activity") return paperPages();
  if (path === "/live") return liveActivities();
  if (path === "/research") return researchLab();
  if (path === "/strategies") {
    view.innerHTML = `<div id="st-sum"><article class="card"><p class="muted">Strategies</p><div class="skeleton lg"></div></article></div><article class="card" id="st-body"><p role="status">Loading the registry. Nothing is being re-scored.</p></article>`;
    const [catalog, qualification, research, platform] = await Promise.all([
      timed("/api/profiles"), timed("/api/qualification"), timed("/api/research-lab"), timed("/api/platform")
    ]);
    const styles = ((catalog && catalog.profiles) || []).map(p => `<article class="card"><h2>${p.name}</h2><p>${p.role}. ${p.purpose}</p><p class="muted">${p.confirmation} Risk cap ${p.risk_per_trade_percent}% per trade. Minimum reward/risk ${p.min_rr}. At most ${p.max_trades_per_day} trades a day in the Awuru account defaults. Not a promoted strategy.</p></article>`).join("");
    const cards = ((qualification && qualification.strategies) || []).map(s => {
      const reason = String(s.failure_reason || s.evidence || "No failure text recorded.");
      const short = reason.split(". ")[0];
      return `<article class="card"><div class="row"><span>${s.name}</span><span>${s.lifecycle}</span></div><p class="muted">${s.version}. ${(s.instruments || []).join(", ")} · ${s.timeframe}. Validation ${s.research_status}. Approved for paper: ${s.approved_for_paper ? "yes" : "no"}.</p><p>${short}.</p><details><summary>Technical evidence</summary><p class="muted">${s.evidence || "No extra evidence."} Last evaluation is the recorded registry result. Not re-scored. Not approved.</p></details></article>`;
    }).join("");
    const study = research && research.discovery;
    const studyCards = study ? (study.markets || []).map(market => {
      const dev = market.development || {};
      const val = market.validation || {};
      return `<details><summary>${market.symbol} development ${dev.judgment || ""} · validation ${val.judgment || ""}</summary><p class="muted">Development n=${dev.trades==null?"n/a":dev.trades}. Net mean ${dev.base_mean==null?"n/a":Number(dev.base_mean).toFixed(5)}. Drawdown ${dev.max_drawdown==null?"n/a":Number(dev.max_drawdown).toFixed(3)}. Cost drag ${dev.cost_drag==null?"n/a":Number(dev.cost_drag).toFixed(3)}. Validation n=${val.trades==null?"n/a":val.trades}. Net mean ${val.base_mean==null?"n/a":Number(val.base_mean).toFixed(5)}. Holdout ${market.holdout}. Not approved.</p></details>`;
    }).join("") : "";
    const studyBlock = study ? `<article class="card"><h3>Latest study, not an approval</h3><p class="muted">${study.version}. ${study.decision}. Holdout opened: ${(study.holdout_opened_for||[]).length?study.holdout_opened_for.join(", "):"no"}. A research candidate is not an approved strategy.</p>${studyCards}</article>` : "";
    view.innerHTML = `${researchSummary(qualification, platform)}<article class="card"><h2>Registered strategies</h2><p class="muted">${(qualification && qualification.note) || "The registry could not be loaded."} Approved count: ${qualification ? qualification.approved_for_paper : "—"}. Failed outcomes stay on record. None is promoted.</p></article>${cards || "<article class='card'><p>The registry could not be loaded.</p></article>"}${studyBlock}<article class="card"><h2>E1 Donchian-20</h2><p>Breakout on the prior 20 completed bars. Failed benchmark on BTC and ETH. Research observation only. Not promoted and not re-tuned.</p></article>${styles}<p class="muted">${(catalog && catalog.note) || ""} ${(catalog && catalog.excluded) || ""}</p>${qualification ? "" : `<p><button type="button" id="st-retry">Retry</button></p>`}`;
    const again = document.getElementById("st-retry");
    if (again) again.onclick = () => load();
    return;
  }
  if (path === "/risk") return riskPage();
  if (path === "/system") return systemPage();
  view.innerHTML = `<article class="card"><h2>${titles[path]||"Aureon"}</h2><p>This page has no separate data source yet.</p></article>`;
}
async function liveActivities(){
  const bot = await fetch("/api/autopilot", {credentials:"same-origin"}).then(r => r.ok ? r.json() : null).catch(()=>null);
  const autoLine = bot ? autoSentence(bot) : "Sign in to read this account's AutoPilot state.";
  const notes = await fetch("/api/notifications", {credentials:"same-origin"}).then(r => r.ok ? r.json() : {items:[]}).catch(()=>({items:[]}));
  const coverage = await fetch("/api/coverage", {credentials:"same-origin"}).then(r => r.ok ? r.json() : {}).catch(()=>({}));
  const age = coverage.evaluated_at_ms ? Math.max(0, Math.round((Date.now() - coverage.evaluated_at_ms) / 1000)) : null;
  const rows = (notes.items || []).filter(item => item.decision === "BUY" || item.decision === "SELL");
  const book = await fetch("/api/paper/book", {credentials:"same-origin"}).then(r => r.ok ? r.json() : {open:[], orders:[]}).catch(()=>({open:[], orders:[]}));
  const positions = (book.open||[]).concat(book.ambiguous||[]).map(row => `<article class="card"><h2>${row.opened_by === "autopilot" ? "AutoPilot paper" : "Account paper"} · ${row.exit_kind||row.status} · ${row.symbol} ${row.direction}</h2><p>Entry ${priceText(row.symbol, row.entry)}. Stop ${priceText(row.symbol, row.stop)}. Target ${priceText(row.symbol, row.target)}. ${row.exit_price==null?"No paper exit.":"Paper exit "+priceText(row.symbol, row.exit_price)+"."}</p><p class="muted">${(row.events&&row.events.length)?row.events[row.events.length-1].note:row.note||""} This is not a broker fill.</p></article>`).join("");
  const list = rows.map(item => `<article class="card"><h2>${item.lifecycle || "active"} · ${item.decision} · ${item.symbol} ${item.interval}</h2><p>${item.lifecycle_note || "Active means the plan is still the visible one. It does not mean an order was opened."}</p><div class="row"><span>Entry ${priceText(item.symbol, item.entry)}</span><span>Stop ${priceText(item.symbol, item.stop)}</span><span>Target ${priceText(item.symbol, item.target)}</span></div><p class="muted">${item.family || item.strategy || ""}</p></article>`).join("");
  view.innerHTML = `<article class="card"><h2>Live Activities</h2><p>AutoPilot ${autoLine}</p><p>Plans come from the inbox. Open positions come from the paper record. Neither is a second signal, and neither is a broker fill.</p><p>Completed candles are judged when the background worker runs, about once a minute. A refresh of this page does not make that scan faster. Last scan ${age==null?"has no recorded time":age+" seconds ago"}.</p></article>${positions}${list || "<article class='card'><p>No open experimental plan for this account.</p></article>"}`;
}
async function paperPages(){
  const response = await fetch("/api/paper/book", {credentials:"same-origin"});
  if (response.status === 401) { view.innerHTML = `<article class="card"><h2>Sign in required</h2><p><a href="/login">Sign in</a> to see paper trades.</p></article>`; return; }
  const book = await response.json().catch(()=>({empty:true, open:[], closed:[], ambiguous:[], note:""}));
  const money = (value) => value==null ? "—" : Number(value).toFixed(2);
  const figures = book.performance || {};
  const headline = figures.trades ? `Closed paper result ${money(figures.pnl_usd)} USD across ${figures.trades} trades. Wins ${figures.wins}. Losses ${figures.losses}. Costs ${money(figures.costs_usd)} USD.` : "No completed paper trade. No win rate is shown.";
  if (path === "/portfolio") {
    const open = (book.open||[]).map(row => `<div class="row"><span>${row.symbol} ${row.direction}</span><span>Entry ${row.entry}</span></div><p class="muted">${row.family||""} ${row.interval}. Risk budget ${money(row.risk_budget_usd)} USD. Quantity ${row.quantity} is an unrounded paper estimate, not an exchange lot. Stop ${row.stop}. Target ${row.target}.</p><label>Exit price <input data-exit="${row.id}" type="number" step="any" min="0"></label> <button type="button" data-close="${row.id}">Close paper trade</button>`).join("");
    const amb = (book.ambiguous||[]).map(row => `<p>${row.symbol} ${row.direction} is unresolved. The candle reached both prices, so it is not a fill and it is not in the result above.</p>`).join("");
    view.innerHTML = `<div class="empty-grid"><article class="card"><h2>Portfolio</h2><div class="markets"><article class="card"><p class="muted">Open paper positions</p><p class="price num">${(book.open||[]).length}</p></article><article class="card"><p class="muted">Closed paper trades</p><p class="price num">${figures.trades || 0}</p></article><article class="card"><p class="muted">Recorded paper result</p><p class="price num">${figures.trades ? money(figures.pnl_usd) : "—"}</p><p class="muted">${figures.trades ? "USD, after the stated paper costs." : "No win rate until a trade is closed."}</p></article></div><p>${headline}</p>${open||"<p>No open paper position.</p>"}${amb}</article>${figures.trades || (book.open||[]).length ? "" : `<article class="card"><h2>No completed paper trades</h2><p>This account has not recorded a completed paper trade. No equity curve is drawn from fictional data, and no win rate is shown.</p><p><a href="/trading">Desk</a> · <a href="/risk">Risk</a> · <a href="/activity">Journal</a></p></article>`}</div><p class="muted">${figures.note||book.note||""} A research observation is not a holding. Estimated paper results are not broker execution.</p>`;
    document.querySelectorAll("[data-close]").forEach(button => { button.onclick = async () => {
      const input = document.querySelector(`[data-exit="${button.dataset.close}"]`);
      const opened = await fetch("/api/paper/close", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({order_id: button.dataset.close, exit_price: input ? input.value : ""})});
      const payload = await opened.json().catch(()=>({}));
      button.textContent = opened.ok && payload.ok ? "Closed" : ("Not closed: " + (payload.reason || "unavailable"));
      if (opened.ok && payload.ok) paperPages();
    }; });
    return;
  }
  const rows = (book.orders||[]).map(row => `<tr><td>${row.status||""}</td><td>${row.symbol||""} ${row.direction||""}</td><td>${row.opened_by === "autopilot" ? "AutoPilot" : "Account"}</td><td>${row.entry==null?"—":row.entry}</td><td>${row.exit_kind||"no exit"}</td><td>${row.exit_price==null?"—":money(row.pnl_usd)+" USD"}</td></tr>`).join("");
  view.innerHTML = `<article class="card"><h2>Journal</h2><p class="muted">Only paper orders recorded for this account. An empty book stays empty. These are not broker fills.</p>${rows ? `<div class="tablewrap"><table><thead><tr><th>Status</th><th>Market</th><th>Opened by</th><th>Entry</th><th>Exit</th><th>Paper result</th></tr></thead><tbody>${rows}</tbody></table></div>` : "<p>No paper orders. Opening one is a separate action from receiving a plan.</p>"}<p class="muted">${book.note||""}</p></article>`;
}
async function riskPage(){
  const me = await fetch("/api/me").then(r=>r.ok?r.json():null);
  const profile = (me && me.profile) || {};
  const book = await fetch("/api/paper/book", {credentials:"same-origin"}).then(r=>r.ok?r.json():{open:[]}).catch(()=>({open:[]}));
  const openRisk = (book.open||[]).reduce((sum, row) => sum + Number(row.risk_budget_usd||0), 0);
  const capital = Number(profile.capital);
  const used = Number.isFinite(capital) && capital > 0 ? (openRisk / capital * 100).toFixed(2) + "%" : "not calculated";
  view.innerHTML = `<article class="card"><h2>Risk</h2><div class="row"><span>Active style</span><span>${profile.signal_style_name||"Not selected"}</span></div><div class="row"><span>Risk posture</span><span>${profile.risk_mode||"unset"}</span></div><div class="row"><span>Max risk per trade</span><span>${profile.max_risk_pct==null?"Not set":profile.max_risk_pct+"%"}</span></div><div class="row"><span>Max daily loss</span><span>${profile.max_daily_loss_percent==null?"Not set":profile.max_daily_loss_percent+"%"}</span></div><div class="row"><span>Max open risk</span><span>${profile.max_open_risk_percent==null?"Not set":profile.max_open_risk_percent+"%"}</span></div><div class="row"><span>Open paper risk now</span><span>${used}</span></div><div class="row"><span>Minimum reward/risk</span><span>${profile.min_rr==null?"Not set":profile.min_rr}</span></div><p class="muted">These caps are enforced when you open a paper trade. Apex allows 2.5% and a 1.7 reward floor. Orion allows 1.5% and 2.0. Aegis allows 0.8% and 2.5. The daily loss figure blocks a new paper order. It does not place a broker order, and it does not change the market reading. Open risk is the sum of risk budgets on open paper orders only.</p></article>`;
}
async function systemPage(){
  view.innerHTML = `<article class="card"><h2>System</h2><p id="sysload">Reading system status. Account pages do not wait on a market feed.</p></article>`;
  const [healthResult, bot, platform] = await Promise.all([
    fetch("/health").then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).catch(error => ({__error: error.message || "request failed"})),
    timed("/api/autopilot"),
    timed("/api/platform")
  ]);
  const stateRows = ((platform && platform.states) || []).map(item => `<div class="row"><span>${item.label}</span><span>${item.value}</span></div>`).join("");
  if (healthResult && healthResult.__error) {
    view.innerHTML = `<article class="card"><h2>System</h2><p>The health report could not be read (${healthResult.__error}). That is not a healthy worker, and it is not a healthy AutoPilot.</p>${stateRows}<p><button type="button" id="sys-retry">Retry</button></p></article>`;
    const again = document.getElementById("sys-retry");
    if (again) again.onclick = () => systemPage();
    return;
  }
  const h = healthResult || {};
  const row = (name, value) => `<div class="row"><span>${name}</span><span>${value}</span></div>`;
  const market = h.market_data && h.market_data.BTCUSDT ? h.market_data.BTCUSDT.status + " / " + (h.market_data.ETHUSDT ? h.market_data.ETHUSDT.status : "unknown") : "unknown";
  const gold = h.market_data && h.market_data.XAUUSD ? (h.market_data.XAUUSD.status || "unknown") + (h.market_data.XAUUSD.reason ? " · " + h.market_data.XAUUSD.reason : "") : "not scanned";
  const note = h.notification && h.notification.reason === "promotion_registry_empty"
    ? "Approved-signal alerts blocked: no promoted strategy. Account notices still exist separately."
    : (h.notification && h.notification.pipeline ? h.notification.pipeline : (typeof h.notification === "string" ? h.notification : "unknown"));
  const qual = h.qualification ? (h.qualification.approved_for_paper + " approved") : "not reported";
  const monitor = h.worker && h.worker.last_monitor;
  const watched = monitor && monitor.evaluations ? monitor.evaluations.map(item => `${item.symbol} ${item.interval}: ${item.decision}`).join("; ") : "not run yet";
  const workerStatus = h.worker && h.worker.status ? h.worker.status : "unknown";
  const workerHealthy = h.worker && h.worker.healthy === true ? "confirmed" : "not confirmed";
  const autoLine = bot ? autoSentence(bot) : "not signed in";
  const rightsLine = h.status === "rights_withheld" ? `<p>${RIGHTS_MESSAGE}</p><p class="muted">The process is up. Market data is withheld because commercial use is not approved. That is not a provider outage and not a stale feed.</p>` : "";
  view.innerHTML = `<article class="card"><h2>System</h2>${rightsLine}${stateRows}${row("Process", h.process||"unknown")}${row("Overall", h.status||"unknown")}${row("BTC / ETH", market)}${row("Gold", gold||"not scanned")}${row("Notifications", note)}${row("Approved strategies", qual)}${row("Ledger", h.ledger||"unknown")}${row("Strategy", h.strategy_status||"unknown")}${row("Broker", String(h.broker))}${row("Build", h.build_commit||"unknown")}${row("Worker status", workerStatus + " · " + workerHealthy)}${row("This account AutoPilot", autoLine)}${row("Worker heartbeat", h.worker && h.worker.last_beat_ms ? new Date(h.worker.last_beat_ms).toISOString() : "unknown")}${row("Background scan", h.worker && h.worker.last_monitor_ms ? new Date(h.worker.last_monitor_ms).toISOString() : "not run yet")}${row("Last scan", watched)}</article><article class="card" id="data-coverage"><h2>Research data coverage</h2><p>Reading data rights.</p></article><p class="muted">A missing, stale or failed heartbeat is not a healthy worker. A rights withhold is not an outage. AutoPilot is not confirmed while the worker is unhealthy. The background scan uses the same decision as the terminal. It does not send Telegram. Gold 1m and 3m are unavailable without a licensed minute feed. AutoPilot is paper only and stays off until the account enables it.</p>`;
  fetch("/api/data-coverage", {credentials:"same-origin"}).then(r => r.json()).then(payload => {
    const box = document.getElementById("data-coverage");
    if (box) box.outerHTML = dataCoverageCard(payload);
  }).catch(() => {
    const box = document.getElementById("data-coverage");
    if (box) box.innerHTML = `<h2>Research data coverage</h2><p>The data-rights report could not be read. Historical research is not shown as available.</p>`;
  });
  fetch("/api/desk", {credentials:"same-origin"}).then(r => r.ok ? r.json() : null).then(body => {
    const host = document.getElementById("data-coverage");
    if (!host || !body || !(body.sources || []).length) return;
    const lines = body.sources.map(row => `<div class="row"><span>${row.instrument} ${row.timeframe}</span><span>${row.quality || "unknown"} · display ${row.display || "closed"}</span></div><p class="muted">${row.provider || "unknown"} · ${row.source_id || "unnamed"}. Retention ${row.retention || "closed"}. Research ${row.research || "closed"}. ${row.snapshot_id || ""}</p>`).join("");
    host.insertAdjacentHTML("afterend", `<article class="card"><h2>Desk sources</h2><p class="muted">One row per instrument and timeframe. Reachable is not the same as approved. Retention and research can stay closed while a live reading still loads. Gold 1-minute and 3-minute stay unlicensed.</p>${lines}</article>`);
  }).catch(() => {});
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
  view.innerHTML = `<article class="card"><h2>${path==="/onboarding"?"Choose a signal style":"Signal style"}</h2><p class="muted">${catalog.note||""}</p><div class="styles">${styles}</div></article><article class="card"><h2>Base currency and capital</h2><div class="field"><span>Currency</span><select id="currency"><option value="">Not set</option>${currencies}</select></div><div class="field"><span>Paper capital</span><input id="capital" type="number" min="0" step="any" value="${profile.capital??""}"></div><p class="muted">Saving a currency does not convert the stored amount. Market quotes stay in USDT or USD/oz.</p></article><article class="card"><h2>Markets</h2><div class="checks"><label><input type="checkbox" id="btc" ${has("BTCUSDT")}> BTCUSDT</label><label><input type="checkbox" id="eth" ${has("ETHUSDT")}> ETHUSDT</label><label><input type="checkbox" id="gold" ${has("XAUUSD")}> XAUUSD</label></div><p class="muted">BTC, ETH, and gold stay on the desk. A verified live reading is not available until that source is approved. Gold 1-minute and 3-minute stay unavailable.</p></article><article class="card"><h2>Experience</h2><label>How you describe your experience <select id="labexp"><option value="">Not stated</option><option value="new">New</option><option value="developing">Developing</option><option value="independent">Independent</option></select></label><p class="muted">This is what you say about yourself. It is stored on this account and is not a skill score.</p></article><article class="card" id="autopilot-card"><h2>AutoPilot</h2><p>Loading paper automation.</p></article><article class="card"><h2>Notifications and risk</h2><div class="checks"><label><input type="checkbox" id="exp" ${profile.experimental_alerts?"checked":""}> Experimental alerts</label><label><input type="checkbox" id="digest" ${profile.daily_report!==false?"checked":""}> Daily digest</label></div><div class="field"><span>Max risk per trade %</span><input id="risk" type="number" step="0.1" min="0" value="${profile.max_risk_pct??""}"></div><p class="muted">Risk cannot be set above the active style cap. These caps do not guarantee protection from losses. Production is WAIT_DEFAULT, so no trade alert is sent until a strategy is promoted. Turning experimental alerts on does not bypass that. In-app experimental matches stay labelled unapproved and never become an approved alert. Telegram is ${me.telegram_verified?"verified":"not verified"}.</p><button id="tglink" type="button">Create a one-time Telegram link</button><p id="tglinkout" class="muted"></p></article><article class="card" id="inbox-settings"><h2>In-app inbox</h2><p class="muted" id="inboxnote">Loading delivery settings.</p></article><p><button id="saveall" type="button">Save</button> <button id="skip" type="button">Continue without optional alerts</button> <button id="out" type="button">Sign out</button></p><p id="savedp" class="muted"></p>`;
  const inbox = await fetch("/api/inbox/settings", {credentials:"same-origin"}).then(r => r.ok ? r.json() : null);
  const box = (inbox && inbox.settings) || {};
  const on = (name) => box[name] ? "checked" : "";
  const tfOn = (tf) => (box.timeframes || ["15m","1h","4h","1d"]).includes(tf) ? "checked" : "";
  const mOn = (m) => (box.markets || ["BTCUSDT","ETHUSDT","XAUUSD"]).includes(m) ? "checked" : "";
  document.getElementById("inbox-settings").innerHTML = `<h2>In-app inbox</h2><p class="muted">These settings control this account's inbox only. They do not approve a strategy, send Telegram, or place an order. Experimental matches stay labelled unapproved.</p><div class="checks"><label><input type="checkbox" id="in-enabled" ${on("enabled")}> Deliver in-app alerts</label><label><input type="checkbox" id="in-btc" ${mOn("BTCUSDT")}> BTCUSDT</label><label><input type="checkbox" id="in-eth" ${mOn("ETHUSDT")}> ETHUSDT</label><label><input type="checkbox" id="in-gold" ${mOn("XAUUSD")}> XAUUSD</label><label><input type="checkbox" id="in-1m" ${tfOn("1m")}> 1m</label><label><input type="checkbox" id="in-3m" ${tfOn("3m")}> 3m</label><label><input type="checkbox" id="in-15m" ${tfOn("15m")}> 15m</label><label><input type="checkbox" id="in-1h" ${tfOn("1h")}> 1h</label><label><input type="checkbox" id="in-4h" ${tfOn("4h")}> 4h</label><label><input type="checkbox" id="in-1d" ${tfOn("1d")}> 1d</label><label><input type="checkbox" id="in-buy" ${on("buy")}> BUY alerts</label><label><input type="checkbox" id="in-sell" ${on("sell")}> SELL alerts</label><label><input type="checkbox" id="in-exp" ${on("experimental")}> Experimental, unapproved matches</label><label><input type="checkbox" id="in-wait" ${on("wait_notices")}> WAIT notices</label></div><button id="saveinbox" type="button">Save inbox delivery</button><p id="inboxsaved" class="muted"></p>`;
  document.getElementById("saveinbox").onclick = async () => {
    const markets = [];
    if (document.getElementById("in-btc").checked) markets.push("BTCUSDT");
    if (document.getElementById("in-eth").checked) markets.push("ETHUSDT");
    if (document.getElementById("in-gold").checked) markets.push("XAUUSD");
    const timeframes = [];
    if (document.getElementById("in-1m").checked) timeframes.push("1m");
    if (document.getElementById("in-3m").checked) timeframes.push("3m");
    if (document.getElementById("in-15m").checked) timeframes.push("15m");
    if (document.getElementById("in-1h").checked) timeframes.push("1h");
    if (document.getElementById("in-4h").checked) timeframes.push("4h");
    if (document.getElementById("in-1d").checked) timeframes.push("1d");
    const payload = {enabled: document.getElementById("in-enabled").checked, markets, timeframes, buy: document.getElementById("in-buy").checked, sell: document.getElementById("in-sell").checked, experimental: document.getElementById("in-exp").checked, wait_notices: document.getElementById("in-wait").checked};
    const saved = await fetch("/api/inbox/settings", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload)});
    document.getElementById("inboxsaved").textContent = saved.ok ? (payload.experimental ? "Inbox delivery saved. Experimental matches are enabled and will be labelled unapproved." : "Inbox delivery saved. Experimental matches stay off.") : "Inbox settings could not be saved.";
  };
  const bot = await fetch("/api/autopilot", {credentials:"same-origin"}).then(r => r.ok ? r.json() : {status:"off", facing:"Disabled", entries_available:false, accepts_new_entries:false, automated_orders:0, rejections:[], note:"", facing_note:"Permission is not active. New automated entries are blocked."});
  function paintAutopilot(current){
    const lastEval = current.last_evaluation_ms ? new Date(current.last_evaluation_ms).toISOString() : "no scan yet";
    const rejected = (current.rejections || []).slice(-3).map(row => `${row.reason}`).join(", ") || "none";
    const entries = current.entries_available === true ? "eligible only when a plan qualifies" : "not eligible";
    const kind = current.state_kind || "disabled";
    const blockers = (current.blockers || []).length ? ` Blockers: ${current.blockers.join(", ")}.` : "";
    const buttons = [];
    if (kind === "disabled") buttons.push(`<button id="auto-on" type="button">Enable AutoPilot</button>`);
    if (kind === "waiting" || kind === "enabled" || kind === "blocked" || kind === "unhealthy") buttons.push(`<button id="auto-pause" type="button">Pause</button> <button id="auto-stop" type="button">Emergency stop</button> <button id="auto-off" type="button">Disable</button>`);
    if (kind === "paused" || kind === "stopped") buttons.push(`<button id="auto-resume" type="button">Resume</button> <button id="auto-stop" type="button">Emergency stop</button> <button id="auto-off" type="button">Disable</button>`);
    document.getElementById("autopilot-card").innerHTML = `<h2>AutoPilot</h2><p id="autostate">State: ${current.facing || "Disabled"}. Automation health: ${current.health || "not confirmed"}. New paper entries: ${entries}.${blockers} Automated orders: ${current.automated_orders || 0}. State updated: ${current.updated_ms ? new Date(current.updated_ms).toISOString() : "not changed"}. Last evaluation: ${lastEval}. Recent rejection: ${rejected}.</p><p class="muted">${current.facing_note || current.health_note || ""} ${current.note || ""} Worker: ${(current.worker && current.worker.status) || "unknown"}. Enabling it requires a confirmation. It can open a paper trade only when a strategy version is approved for paper. None is. Pause and emergency stop do not close an open position. It is not a broker.</p><label>Daily automated cap, optional <input id="autocap" type="number" min="1" value="${current.max_orders_per_day || ""}"></label><p>${buttons.join(" ")}</p><p id="autonote" class="muted"></p>`;
    async function autoAct(action, confirm){
      const cap = document.getElementById("autocap").value;
      const saved = await fetch("/api/autopilot", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body: JSON.stringify({action, confirm, max_orders_per_day: cap || null})});
      const payload = await saved.json().catch(()=>({}));
      if (!(saved.ok && payload.ok)) {
        document.getElementById("autonote").textContent = "Not changed: " + (payload.reason || "unavailable");
        return;
      }
      const fresh = await fetch("/api/autopilot", {credentials:"same-origin"}).then(r => r.ok ? r.json() : payload.autopilot);
      paintAutopilot(fresh);
      const note = document.getElementById("autonote");
      if (note) note.textContent = "Saved. " + (fresh.facing || fresh.status) + ". " + (fresh.facing_note || "");
    }
    const enable = document.getElementById("auto-on");
    if (enable) enable.onclick = () => {
      if (!window.confirm("Enable paper AutoPilot on this account? It will not open an order unless a strategy version is approved for paper. It does not send a broker order.")) return;
      autoAct("enable", true);
    };
    const pause = document.getElementById("auto-pause");
    if (pause) pause.onclick = () => autoAct("pause", false);
    const resume = document.getElementById("auto-resume");
    if (resume) resume.onclick = () => autoAct("resume", false);
    const stop = document.getElementById("auto-stop");
    if (stop) stop.onclick = () => autoAct("emergency_stop", false);
    const off = document.getElementById("auto-off");
    if (off) off.onclick = () => autoAct("disable", false);
  }
  paintAutopilot(bot);
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
    const labexp = document.getElementById("labexp").value;
    if (labexp) await fetch("/api/lab", {method:"POST", headers:{"Content-Type":"application/json"}, credentials:"same-origin", body: JSON.stringify({experience: labexp})});
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
    profile = user.get("profile") or {}
    lines = [
        f"Aureon daily · {profile.get('signal_style_name') or 'no signal style'}",
        f"Base currency {profile.get('currency') or 'not set'}. Amounts are not converted.",
        f"Risk cap {profile.get('max_risk_pct', 'unset')}%. Reward floor {profile.get('min_rr', 'unset')}.",
        "The terminal plan is separate from the old research-state check. Neither is a paper order until you open one.",
        "Production remains WAIT_DEFAULT. This is not an order.",
    ]
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
