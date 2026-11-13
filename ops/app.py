"""Aureon Trading Lab dashboard. Paper only. Public health is coarse."""

import json
import os
import sys
import time
import hmac
import urllib.request
import atexit
import threading
from pathlib import Path

from flask import Flask, jsonify, request, session, redirect, make_response
from werkzeug.exceptions import HTTPException

from ops.auth import RateLimit, api_token, require_token
from ops.engine import PaperEngine
from ops.ledger import Ledger
from ops.signals import research_states
from ops.experimental import ExperimentalBook, present_book
from ops.replay import replay, yesterday_ms, period
from ops.leaderboard import leaderboard
from ops.deepboard import deep_board
from ops.market import snapshot as market_snapshot, fetch_klines
from ops.notify import send_alert
from ops.strategy import WaitStrategy
from ops.build_id import build_commit, shadow_enabled
from ops.paths import ledger_path, shadow_observations_path
from ops.worker import Worker
from ops.desk_ui import DASHBOARD, LANDING
from ops.runtime import DeskRuntime

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ledger_path()
STARTED = time.time()
LIMITER = RateLimit(int(os.environ.get("DESK_GENERAL_LIMIT", "300")))
AUTH_LIMITER = RateLimit(int(os.environ.get("DESK_AUTH_LIMIT", "20")))
_FEED_CACHE = {}

def _session_secret():
    """A production process must be given a stable secret. A random fallback logs everyone out on restart."""
    secret = os.environ.get("DESK_SESSION_SECRET", "").strip()
    if len(secret) >= 32:
        return secret
    if "pytest" in sys.modules:
        return api_token() or "test-session-secret-not-for-production-use"
    raise SystemExit("DESK_SESSION_SECRET must be at least 32 characters")


app = Flask(__name__)
app.secret_key = _session_secret()
app.config["CSRF_ENFORCE"] = True


def _customer_failure(exc):
    """Safe customer body. The caller is responsible for HTTP 500. No traceback or path."""
    sys.stderr.write("request failed: " + type(exc).__name__ + "\n")
    return jsonify({
        "error": "unavailable",
        "handled": True,
        "message": "This action could not be completed.",
        "analysis": None,
        "approved": False,
        "order_opened": False,
    })


app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("DESK_COOKIE_SECURE", "0") == "1",
)
ledger = Ledger(LEDGER_PATH)
engine = PaperEngine(ledger, WaitStrategy())
worker = Worker(ledger, LEDGER_PATH.parent / "prefs.json", shadow_path=shadow_observations_path())
desk_runtime = DeskRuntime(deadline_s=5)


def _workers_enabled():
    return "pytest" not in sys.modules and os.environ.get("AUREON_DISABLE_WORKERS") != "1"


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
    "/scanner", "/learn", "/plan", "/notifications", "/orders", "/history",
}


def _safe_next(value):
    if value in ALLOWED_NEXT:
        return value
    return "/overview"


def _start_user_session(user):
    session["user_id"] = user["id"]
    session["user_exp"] = time.time() + SESSION_TTL


def _csrf():
    try:
        token = session.get("csrf")
        if not token:
            token = os.urandom(16).hex()
            session["csrf"] = token
        return token
    except RuntimeError:
        return "0" * 32

def _limited():
    from ops.auth import client_identity, limits_apply

    if not limits_apply("pytest" in sys.modules, bool(app.config.get("ENFORCE_RATE_LIMIT"))):
        return None
    if request.method in {"GET", "HEAD", "OPTIONS"} and request.path in {"/login", "/register"}:
        return None
    auth_paths = {"/login", "/register", "/api/login", "/api/register"}
    limiter = AUTH_LIMITER if request.method not in {"GET", "HEAD", "OPTIONS"} and request.path in auth_paths else LIMITER
    key = client_identity(request.remote_addr, request.headers.get("X-Forwarded-For"))
    if not limiter.allow(key):
        response = jsonify({"error": "rate_limited", "scope": "auth" if limiter is AUTH_LIMITER else "general"})
        response.status_code = 429
        response.headers["Retry-After"] = str(limiter.retry_after(key))
        return response
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
    if request.endpoint == "static":
        return None
    limited = _limited()
    if limited is not None:
        return limited
    if not _csrf_ok():
        return jsonify({"error": "csrf", "approved": False, "order_opened": False}), 403
    return None


def _csrf_ok():
    if not app.config.get("CSRF_ENFORCE", True):
        return True
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True
    if request.path == "/api/telegram/update":
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and not session.get("user_id") and not session.get("ok"):
        return True
    expected = str(session.get("csrf") or "")
    supplied = request.headers.get("X-CSRF-Token") or ""
    if not supplied:
        payload = request.get_json(silent=True) if request.is_json else None
        if isinstance(payload, dict):
            supplied = str(payload.get("csrf") or "")
    if not supplied:
        supplied = request.form.get("csrf") or ""
    if not expected or not supplied:
        return False
    return hmac.compare_digest(expected, supplied)


class InjectedFault(RuntimeError):
    """Test-only fault. Production code does not raise this."""


@app.before_request
def _inject_fault():
    fault = app.config.get("INJECT_FAULT")
    method = app.config.get("INJECT_FAULT_METHOD")
    if fault and request.path == fault and (method in (None, request.method)):
        raise InjectedFault("injected")


@app.errorhandler(InjectedFault)
def _handle_injected(_exc):
    if request.path.startswith("/api"):
        return jsonify({"error": "internal", "handled": True}), 500
    return make_response("internal handled", 500)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    if isinstance(exc, InjectedFault):
        return _handle_injected(exc)
    from werkzeug.exceptions import HTTPException

    if isinstance(exc, HTTPException):
        return exc
    if request.path.startswith("/api"):
        response = _customer_failure(exc)
        payload = response.get_json(silent=True) or {}
        payload["request_id"] = request.environ.get("aureon_request_id", "")
        return jsonify(payload), 500
    return make_response("internal handled", 500)


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


def _worker_view(beat, monitor_ms, monitor, monitor_error, cycle_error, source):
    beat = int(beat or 0)
    heartbeat_age = None if not beat else max(0, int(time.time() * 1000) - beat)
    if not beat:
        worker_status = "unknown"
    elif monitor_error or cycle_error:
        worker_status = "error"
    elif heartbeat_age > 180_000:
        worker_status = "stale"
    else:
        worker_status = "beating"
    from ops.customer_release import diagnostic_monitor
    return {
        "last_beat_ms": beat or None,
        "heartbeat_age_ms": heartbeat_age,
        "status": worker_status,
        "last_monitor_ms": int(monitor_ms or 0) or None,
        "last_monitor": diagnostic_monitor(monitor),
        "last_monitor_error": monitor_error,
        "last_cycle_error": cycle_error,
        "healthy": worker_status == "beating",
        "source": source,
    }


def _worker_public():
    if os.environ.get("AUREON_ROLE", "").strip().lower() == "web":
        from ops.worker_status import read_status

        disk = read_status()
        return _worker_view(
            disk.get("last_beat_ms"),
            disk.get("last_monitor_ms"),
            disk.get("last_monitor"),
            disk.get("last_monitor_error"),
            disk.get("last_cycle_error"),
            "worker_file",
        )
    return _worker_view(
        worker.last_beat_ms,
        getattr(worker, "last_monitor_ms", 0),
        getattr(worker, "last_monitor", None),
        getattr(worker, "last_monitor_error", None),
        getattr(worker, "last_cycle_error", None),
        "process",
    )


def _ollama_public():
    """Discovery only. inference stays false until a validated completion is returned."""
    from ops.ollama import health as ollama_health

    model = ollama_health()
    return {
        "available": model.get("available") is True,
        "reason": model.get("reason"),
        "model": model.get("model"),
        "installed": list(model.get("installed") or []),
        "reachable": model.get("reachable"),
        "inference": False,
        "customer_toggle": False,
    }


@app.get("/health")
def health():
    from ops.customer_release import candles_released

    promoted = _promotion_state()
    crypto_released = candles_released("BTCUSDT", "15m") or candles_released("ETHUSDT", "15m")
    if crypto_released:
        if os.environ.get("AUREON_ROLE", "").strip().lower() == "web":
            report = _canonical_health_report()
        else:
            markets = market_snapshot()
            report = _market_report(markets)
        fresh = report["BTCUSDT"]["status"] == "fresh" and report["ETHUSDT"]["status"] == "fresh"
        withheld = report["BTCUSDT"]["status"] == "withheld" or report["ETHUSDT"]["status"] == "withheld"
        status = "rights_withheld" if withheld else ("ok" if fresh else "degraded")
    else:
        report = {
            "BTCUSDT": _reading_not_shown(),
            "ETHUSDT": _reading_not_shown(),
            "XAUUSD": _gold_health_row(),
        }
        status = "reading_unavailable"
    if status == "reading_unavailable":
        try:
            from ops.activity import record
            record(
                "source_unavailable",
                component="health",
                entity="desk",
                detail={"note": "No authorised customer reading. Not a worker failure and not a research result."},
            )
        except Exception:
            pass
    return jsonify({
        "status": status,
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
        "runtime": _runtime_public(),
        "ollama": _ollama_public(),
        "qualification": _qualification_public(),
        "data_schema": _schema_public(),
    })


def _canonical_health_report():
    """Stored worker readings only. This does not call a market host."""
    from ops.desk_pulse import health_label, latest

    now_ms = int(time.time() * 1000)
    out = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        stored = latest(symbol)
        if not stored:
            out[symbol] = {
                "status": "unknown",
                "last_close_time_ms": None,
                "source": "canonical",
                "kind": "canonical_reading",
                "not_a_quote": True,
                "note": "No stored worker reading. This request did not fetch a market.",
            }
            continue
        label = health_label(stored, now_ms)
        out[symbol] = {
            "status": "fresh" if label == "live" else ("stale" if label == "cached" else label),
            "feed": label,
            "last_close_time_ms": stored.get("bar_close_ms"),
            "snapshot_id": stored.get("snapshot_id"),
            "source": "canonical",
            "kind": "canonical_reading",
            "not_a_quote": True,
            "desk_snapshot": True,
            "note": "Stored worker reading. This request did not fetch a market.",
        }
    out["XAUUSD"] = _gold_health_row()
    return out


def _runtime_public():
    local = desk_runtime.operational_view()
    if os.environ.get("AUREON_ROLE", "").strip().lower() != "web":
        return local
    from ops.worker_status import read_status

    runtime = read_status().get("runtime")
    if isinstance(runtime, dict):
        shown = dict(runtime)
        shown["source"] = "worker_file"
        return shown
    local = dict(local)
    local["source"] = "web_process"
    return local


def _schema_public():
    from ops.paths import data_root
    from ops.schema_guard import CURRENT, guard

    state = guard(data_root(), apply=False)
    return {"version": CURRENT, "status": state.get("action"), "ok": state.get("ok") is True}


def _reading_not_shown():
    from ops.customer_release import STATUS

    return {
        "status": "not_shown",
        "last_close_time_ms": None,
        "kind": "not_a_customer_reading",
        "source": "not_shown",
        "note": STATUS,
    }


def _gold_health_row():
    from ops.customer_release import STATUS, candles_released
    from ops.desk_pulse import health_label, latest

    released = any(candles_released("XAUUSD", interval) for interval in ("15m", "1h"))
    stored = latest("XAUUSD")
    if stored:
        label = health_label(stored, int(time.time() * 1000))
        return {
            "status": label,
            "source_reachable": "worker",
            "last_close_time_ms": stored.get("bar_close_ms"),
            "snapshot_id": stored.get("snapshot_id"),
            "kind": "canonical_reading",
            "note": "Worker gold reading. Not a paid vendor and not a bid or ask.",
        }
    return {
        "status": "source_authorised" if released else "not_shown",
        "source_reachable": "not_checked",
        "last_close_time_ms": None,
        "kind": "not_a_customer_reading",
        "note": "Gold health does not call a paid vendor and does not report a price. A public chart is not a bid or ask." if released else STATUS,
    }


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
        from ops.desk_pulse import health_label, latest

        stored = latest(symbol)
        if stored:
            out[symbol]["feed"] = health_label(stored, now_ms)
            out[symbol]["snapshot_id"] = stored.get("snapshot_id")
            if stored.get("bar_close_ms") is not None:
                out[symbol]["last_close_time_ms"] = stored.get("bar_close_ms")
    out["XAUUSD"] = _gold_health_row()
    return out


@app.get("/version")
def version():
    from ops.content_hash import content_hash, content_hash_baked

    baked = content_hash_baked()
    return jsonify({
        "build_commit": build_commit(),
        "build_commit_kind": "label",
        "content_hash": content_hash(),
        "content_hash_kind": "image" if baked else "source",
        "content_hash_baked": baked,
        "strategy_status": "WAIT_DEFAULT",
        "paper_only": True,
        "broker": False,
        "shadow": "enabled" if shadow_enabled() else "disabled",
        "data_schema": _schema_public(),
    })


@app.get("/api/klines")
def klines():
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
        try:
            snap = observe(symbol, interval, now_ms)
        except Exception:
            return jsonify(unavailable_candles(symbol, interval))
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
    posted = request.form.get("csrf")
    if not posted or posted != session.get("csrf"):
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
    posted = request.form.get("csrf")
    if not posted or posted != session.get("csrf"):
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
    try:
        at_ms = yesterday_ms() if not at or at == "yesterday" else int(at)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_input"}), 400
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
    try:
        at_ms = yesterday_ms() if not at or at == "yesterday" else int(at)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_input"}), 400
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


@app.get("/api/broker")
def broker_status():
    from ops.live_broker import status
    user_id = session.get("user_id")
    body = status()
    if user_id:
        from ops.users import get
        user = get(user_id) or {}
        body["account_live"] = False
    else:
        body["account_live"] = False
    body["broker"] = False
    body["armed"] = False
    return jsonify(body)








@app.get("/api/activity")
def activity_api():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.activity import present

    try:
        limit = request.args.get("limit")
        before = request.args.get("before")
        rows = present(user_id, limit=int(limit) if limit else None, before=int(before) if before else None)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_input", "message": "We could not load your activity history. Please retry."}), 400
    unread = sum(1 for row in rows if row.get("read") is False and row.get("account_id") == user_id)
    return jsonify({"events": rows, "count": len(rows), "unread": unread, "truncated": False, "broker": False})


@app.post("/api/activity/read")
def activity_read():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.activity import mark_read

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "invalid_input", "message": "This action could not be completed."}), 400
    result = mark_read(user_id, body.get("event_ids"))
    return jsonify(result)


@app.get("/api/signals/lifecycle")
def signal_lifecycle():
    """Read the stored lifecycle. This request does not run a cycle or write history."""
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized", "modified": False}), 401
    return jsonify(_lifecycle_view(user_id))


@app.route("/api/signals/lifecycle", methods=["POST", "PUT", "DELETE", "PATCH"])
def signal_lifecycle_mutate():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized", "modified": False}), 401
    return jsonify({"error": "method_not_allowed", "modified": False, "read_only": True}), 405


def _lifecycle_view(user_id):
    from ops.activity import read as read_activity
    from ops.customer_release import unavailable_card
    from ops.data_rights import DESK
    from ops.signal_continuity import classify_card
    from ops.signal_ledger import read as read_signals

    history = []
    for row in read_signals():
        owner = row.get("account_id")
        if owner not in (None, "", user_id):
            continue
        history.append({key: value for key, value in row.items() if key != "account_id" or value in (None, user_id)})
    latest = {}
    for row in history:
        latest[(row.get("symbol"), row.get("interval"))] = row
    markets = []
    for symbol, interval in DESK:
        row = latest.get((symbol, interval))
        if row:
            markets.append(row)
            continue
        card = classify_card(unavailable_card(symbol, interval))
        card["permission"] = "not_granted"
        card["freshness"] = "not_retrieved"
        card["price"] = None
        card["entry"] = None
        card["stop"] = None
        card["target"] = None
        card["persisted"] = False
        markets.append(card)
    account_events = []
    for row in read_activity(account_id=user_id):
        if row.get("account_id") not in (None, user_id):
            continue
        account_events.append(row)
    return {
        "markets": markets,
        "history": history,
        "history_count": len(history),
        "account_events": account_events,
        "pipeline": __import__("ops.signal_pipeline", fromlist=["read_pipeline"]).read_pipeline(user_id),
        "truncated": False,
        "broker": False,
        "read_only": True,
        "modified": False,
        "account_id": user_id,
        "note": "This read does not create a signal. Another account's events are not included.",
    }


@app.get("/api/ai")
def ai_status():
    from ops.ai_runtime import host_facts
    from ops.ollama import health

    body = health()
    body["broker"] = False
    body["runtime"] = host_facts()
    body["analysis_label"] = "ai_analysis_not_a_signal"
    body["trading_blocked"] = False
    return jsonify(body)


@app.post("/api/ai/ask")
def ai_ask():
    raw = request.get_data(cache=True) or b""
    if len(raw) > 8000:
        return jsonify({"error": "payload_too_large"}), 413
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.ai_provider import ask

    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol") if isinstance(body.get("symbol"), str) else None
    interval = body.get("interval") if isinstance(body.get("interval"), str) else None
    signal_id = body.get("signal_id") if isinstance(body.get("signal_id"), str) else None
    lesson_id = body.get("lesson_id") if isinstance(body.get("lesson_id"), str) else None
    question = body.get("question") if isinstance(body.get("question"), str) else None
    result = ask(
        user_id,
        str(body.get("task") or ""),
        symbol=symbol,
        interval=interval,
        signal_id=signal_id,
        lesson_id=lesson_id,
        question=question,
    )
    result["approved"] = False
    result["order_opened"] = False
    return jsonify(result)


@app.post("/api/explain")
def explain_api():
    raw = request.get_data(cache=True) or b""
    if len(raw) > 8000:
        return jsonify({"error": "payload_too_large"}), 413
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.ai_provider import ask

    result = ask(user_id, "explain_signal")
    result["approved"] = False
    result["order_opened"] = False
    result["client_evidence_ignored"] = True
    return jsonify(result)


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
    if os.environ.get("AUREON_ROLE", "").strip().lower() == "web":
        snaps, readings = [], []
    else:
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
        from ops.desk_pulse import get as canonical_reading

        stored = canonical_reading(symbol, frame) if reading_released(symbol, frame, sample) else None
        if stored and stored.get("snapshot_id"):
            payload["snapshot_id"] = stored.get("snapshot_id")
            payload["bar_close_ms"] = stored.get("bar_close_ms")
            price = stored.get("reference_price")
            if price is None:
                price = stored.get("price")
            display = dict(display)
            display["bar_close_ms"] = stored.get("bar_close_ms")
            display["timeframe"] = frame
            if price is not None:
                display["price"] = price
                display["close"] = price
            payload["data"] = display
            if isinstance(shown, dict):
                shown = dict(shown)
                shown["decision"] = stored.get("decision_label") or stored.get("decision")
                shown["entry"] = stored.get("entry")
                shown["stop"] = stored.get("stop")
                shown["target"] = stored.get("target")
                shown["snapshot_id"] = stored.get("snapshot_id")
                shown["candle_close_ms"] = stored.get("bar_close_ms")
                payload["reading"] = shown
        if os.environ.get("AUREON_ROLE", "").strip().lower() == "web":
            payload["fetched_upstream"] = False
            if not stored:
                display = dict(payload.get("data") or {})
                display.setdefault("price", None)
                display["note"] = "No stored worker reading. This request did not fetch a market."
                payload["data"] = display
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
    try:
        data = fetch_klines(symbol, "15m", limit=50)
    except Exception:
        data = {"candles": [], "reason": "feed_unavailable"}
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
    from ops.ai_safety import accept_display_name
    from ops.users import update_profile
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "invalid_input"}), 400
    if "name" in body:
        from ops.users import update_display_name
        if accept_display_name(body.get("name")) is None or update_display_name(user_id, body.get("name")) is None:
            return jsonify({"error": "invalid or duplicate"}), 400
    expected = body.get("expected_revision")
    user = update_profile(user_id, body, expected_revision=expected)
    if isinstance(user, dict) and user.get("conflict"):
        return jsonify({"error": "conflict", "revision": user.get("revision"), "profile": None}), 409
    if not user:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "profile": user.get("profile")})


@app.post("/api/telegram/link")
def telegram_link():
    from ops.users import start_telegram_link
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    result = start_telegram_link(user_id)
    if not result:
        return jsonify({"error": "not_found"}), 404
    from ops.telegram_in import bot_username

    import re

    name = bot_username() or os.environ.get("TELEGRAM_BOT_USERNAME") or "AureonLabBot"
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", str(name)):
        name = "AureonLabBot"
    token = result.get("token") or ""
    result["username"] = name
    result["state"] = "pending"
    result["deep_link"] = f"https://t.me/{name}?start={token}"
    result["start_command"] = f"/start {token}"
    result["bot"] = "@" + name
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
    from ops.telegram_in import apply_update, intake_mode
    if intake_mode() != "webhook":
        return jsonify({"ok": True, "ignored": True, "reason": "polling_mode"})
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not secret or request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return jsonify({"ok": True, "ignored": True, "reason": "webhook_secret"})
    result = apply_update(request.json or {})
    return jsonify({"ok": bool(result.get("ok")), "ignored": bool(result.get("ignored") or result.get("duplicate")), "error": result.get("error")})


@app.post("/api/telegram/test")
def telegram_test():
    from ops.inbox_notify import enabled
    from ops.notify import send_alert
    from ops.users import get

    user_id = session.get("user_id")
    if not user_id or not _user_ok():
        return jsonify({"error": "unauthorized"}), 401
    user = get(user_id) or {}
    if not enabled(user):
        return jsonify({"ok": False, "delivered": False, "reason": "not_connected"}), 400
    chat_id = str((user.get("telegram") or {}).get("chat_id"))
    result = send_alert("Aureon connection test. This is not a trade and not a fill.", chat_id=chat_id)
    delivered = bool(result.get("delivered")) and result.get("telegram_message_id") is not None and str(result.get("telegram_chat_id")) == chat_id
    return jsonify({"ok": delivered, "delivered": delivered, "reason": None if delivered else result.get("reason")})


@app.post("/api/telegram/unlink")
def telegram_unlink():
    from ops.users import unlink_telegram
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    ok = unlink_telegram(user_id)
    return jsonify({"ok": ok})


def _reject_typed_telegram():
    """The signed-in page must not bind a typed id. The bot update does that."""
    from ops.users import TYPED_MESSAGE, USERNAME_MESSAGE

    user_id = session.get("user_id")
    if not user_id or not _user_ok():
        return jsonify({"error": "unauthorized"}), 401
    raw = str((request.get_json(silent=True) or {}).get("telegram_id") or "")
    if raw.strip().startswith("@") or "@" in raw:
        return jsonify({"ok": False, "error": "username_not_accepted", "message": USERNAME_MESSAGE}), 400
    return jsonify({"ok": False, "error": "typed_id_not_accepted", "message": TYPED_MESSAGE}), 400


@app.post("/api/telegram/connect")
def telegram_connect():
    return _reject_typed_telegram()


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
    from ops.users import telegram_state
    return jsonify({
        "id": user["id"],
        "name": user["name"],
        "telegram_linked": bool(telegram),
        "telegram_verified": bool(telegram.get("verified")) and not telegram.get("revoked"),
        "telegram_state": telegram_state(user),
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
        try:
            data = fetch_klines(symbol, "15m", limit=50)
        except Exception:
            data = {"candles": [], "reason": "feed_unavailable"}
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
    from ops.desk_pulse import get as canonical_reading

    stored = canonical_reading("XAUUSD", "1h")
    if stored and stored.get("bar_close_ms") is not None:
        decision = stored.get("decision_label") or stored.get("decision") or "WAIT"
        return jsonify({
            "symbol": "XAUUSD",
            "interval": "1h",
            "strategy": stored.get("strategy"),
            "state": "canonical",
            "reason": stored.get("runtime_status"),
            "result": decision,
            "direction": decision,
            "decision": decision,
            "entry": stored.get("entry"),
            "stop": stored.get("stop"),
            "target": stored.get("target"),
            "candle_close_ms": stored.get("bar_close_ms"),
            "bar_close_ms": stored.get("bar_close_ms"),
            "snapshot_id": stored.get("snapshot_id"),
            "production": "WAIT_DEFAULT",
            "approved": False,
            "validated": False,
            "broker": False,
            "quote_semantics": "ohlc_not_bid_ask",
            "note": "Same completed-candle paper reading as the worker. Not bid/ask, not a broker fill, and not an approved signal.",
        })
    from ops.desk_snapshot import headline_board, public_reading

    shown = {}
    semantics = "ohlc_not_bid_ask"
    try:
        snaps, readings = headline_board(int(time.time() * 1000))
    except Exception:
        snaps, readings = [], []
    for snap, reading in zip(snaps, readings):
        if snap.get("instrument") == "XAUUSD":
            semantics = snap.get("candle_semantics") or semantics
            shown = public_reading(reading) if reading else {}
            break
    sample = "spot_sample_not_bid_ask" if semantics == "spot_sample_not_bid_ask" else None
    if shown and not reading_released("XAUUSD", "1h", sample):
        shown = {}
    if not shown:
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
            "decision": head.get("direction") or "WAIT",
            "entry": None,
            "stop": None,
            "target": None,
            "production": "WAIT_DEFAULT",
            "approved": False,
            "validated": False,
            "broker": False,
            "quote_semantics": view.get("quote_semantics") or "ohlc_not_bid_ask",
            "rows": view.get("rows") or [],
            "note": "XAUUSD 1-hour reading from the desk source. A sampled reference bar is not exchange OHLC. Not a paper order, not bid/ask, and not an approved signal.",
        })
    decision = shown.get("decision") or "WAIT"
    return jsonify({
        "symbol": "XAUUSD",
        "interval": "1h",
        "strategy": shown.get("reading_class") or "gold-ohlc-reading",
        "state": shown.get("setup_state") or "confirmed",
        "reason": shown.get("explanation"),
        "result": decision,
        "direction": decision,
        "decision": decision,
        "entry": shown.get("entry"),
        "stop": shown.get("stop"),
        "target": shown.get("target"),
        "candle_close_ms": shown.get("candle_close_ms"),
        "snapshot_id": shown.get("snapshot_id"),
        "production": "WAIT_DEFAULT",
        "approved": False,
        "validated": False,
        "broker": False,
        "quote_semantics": semantics,
        "note": "Same completed-candle paper reading as the market board. Not bid/ask, not a broker fill, and not an approved signal.",
    })


@app.get("/api/gold/candles")
def gold_candles():
    from ops.bars import to_chart_candles

    interval = request.args.get("interval", "1h")
    from ops.customer_release import candles_released, unavailable_candles
    if interval in {"1m", "3m"} and not candles_released("XAUUSD", interval):
        return jsonify({
            "symbol": "XAUUSD",
            "interval": interval,
            "candles": [],
            "blocked": "xau_minute_unlicensed",
            "error": "xau_minute_unlicensed",
            "quote_semantics": "unavailable",
            "note": "A native gold minute candle was not returned. A coarser candle was not split to fill it.",
        })
    sample = "spot_sample_not_bid_ask" if interval in {"15m", "1h"} else None
    chart_released = candles_released("XAUUSD", interval)
    sample_released = bool(sample) and candles_released("XAUUSD", interval, sample)
    if not chart_released and not sample_released:
        return jsonify(unavailable_candles("XAUUSD", interval))
    if interval in {"1m", "3m", "15m", "1h"}:
        from ops.desk_snapshot import observe
        try:
            snap = observe("XAUUSD", interval, int(time.time() * 1000))
        except Exception:
            return jsonify(unavailable_candles("XAUUSD", interval))
        series = list(snap.get("_loaded") or [])
        semantics = snap.get("candle_semantics") or "ohlc_not_bid_ask"
        provider = snap.get("provider") or "none"
        sampled = semantics == "spot_sample_not_bid_ask" and provider != "twelve-data"
        if not series:
            return jsonify({
                "symbol": "XAUUSD",
                "interval": interval,
                "candles": [],
                "source": provider,
                "error": snap.get("blocked_reason") or "GOLD_FEED_UNAVAILABLE",
                "quote_semantics": semantics,
                "snapshot_id": snap.get("snapshot_id"),
                "reading_version": snap.get("reading_version"),
                "kind": "sampled_reference" if sampled else "chart_ohlc",
                "note": "No bar was returned from the authorised source. Another source was not substituted." if provider == "twelve-data" else ("No complete sampled reference bar was returned. Nothing was invented." if sampled else "No chart bar was returned. Nothing was invented."),
            }), 502
        candles = to_chart_candles(series)[-180:]
        if provider == "twelve-data":
            note = "Native XAU/USD OHLC from Twelve Data. Not a bid or ask and not an execution price. A different source was not substituted."
            kind = "chart_ohlc"
        elif sampled:
            note = "Sampled indicative reference bars from five-minute spot prints. Not exchange OHLC, not a bid or ask, and not an execution price. Reference quote unavailable."
            kind = "sampled_reference"
        else:
            note = "Chart OHLC from xaus.com. Not a bid or ask and not an execution price. Reference quote unavailable."
            kind = "chart_ohlc"
        return jsonify({
            "symbol": "XAUUSD",
            "instrument": "XAUUSD_SPOT",
            "interval": interval,
            "source": provider,
            "kind": kind,
            "quote_semantics": semantics,
            "count": len(candles),
            "candles": candles,
            "snapshot_id": snap.get("snapshot_id"),
            "reading_version": snap.get("reading_version"),
            "not_a_quote": True,
            "execution_grade": False,
            "reference_quote": "reference_quote_unavailable",
            "note": note,
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
    try:
        view = _engine_view(symbol)
    except Exception:
        return jsonify(derived_withheld(symbol, interval))
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
    try:
        view = _engine_view(symbol)
        e1, sma, rsi, fresh = _research_votes(symbol)
    except Exception:
        body = derived_withheld(symbol, interval)
        body["kind"] = "research_observation"
        body["label"] = "RESEARCH OBSERVATION — NOT VALIDATED"
        body["note"] = "The market feed did not return a reading. No price was invented."
        return jsonify(body)
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


@app.post("/api/worker/prefs")
@require_token
def set_prefs():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "invalid_input"}), 400
    return jsonify(worker.save_prefs(body))


@app.get("/api/desk/pulse")
def desk_pulse():
    user_id = session.get("user_id")
    if not user_id or not _user_ok():
        return jsonify({"error": "unauthorized"}), 401
    from ops.desk_pulse import account_view
    from ops.users import get

    return jsonify(account_view(get(user_id) or {}))


def _loop():
    def work():
        worker.evaluate()
        worker.monitor()

    _service(work, 60, "desk")


def _telegram_loop():
    from ops.inbox_notify import flush, wait_for_work
    from ops.telegram_in import intake_mode, poll_if_enabled

    while desk_runtime.tick_start("telegram"):
        completed = False
        pause = 20
        try:
            if intake_mode() == "polling":
                poll_if_enabled()
            summary = flush() or {}
            completed = True
            pause = summary.get("retry_after") or 20
        except Exception:
            completed = False
            pause = 20
        finally:
            desk_runtime.tick_end("telegram", completed)
        if wait_for_work(pause, desk_runtime._stop):
            return


def _service(work, pause_s, name):
    while desk_runtime.tick_start(name):
        completed = False
        try:
            work()
            completed = True
        except Exception:
            completed = False
        finally:
            desk_runtime.tick_end(name, completed)
        if desk_runtime.wait(pause_s):
            return


def _spawn(target, name):
    if not _workers_enabled():
        return None
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    return thread


if _workers_enabled():
    desk_runtime.mark_started()
_spawn(_loop, "aureon-desk")
_spawn(_telegram_loop, "aureon-telegram")








@app.get("/api/scanner")
def scanner_api():
    if not _user_ok() and not _owner_ok():
        return jsonify({"error": "unauthorized"}), 401
    from ops.customer_release import any_customer_display, empty_desk, release_scan
    now_ms = int(time.time() * 1000)
    if not any_customer_display():
        body = empty_desk()
    elif os.environ.get("AUREON_ROLE", "").strip().lower() == "web":
        from ops.canonical_read import stored_desk
        body = stored_desk(now_ms)
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
                "customer_status": "reading_unavailable",
                "scanner_state": "UNAVAILABLE",
                "decision_label": "UNAVAILABLE",
                "status": "unavailable",
                "blocked": "xau_minute_unlicensed" if minute else None,
                "message": "Gold 1-minute and 3-minute are not licensed." if minute else "A verified live reading is not available. This is not a zero-setup scan.",
                "reading_class": "unavailable",
                "autopilot_eligible": False,
                "probability": None,
            })
        body["notice"] = "The scan did not return a reading. No price was invented."
    from ops.desk_pulse import project_markets

    body = project_markets(body)
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
    if os.environ.get("AUREON_ROLE", "").strip().lower() == "web":
        from ops.canonical_read import stored_desk
        from ops.desk_pulse import project_markets
        return jsonify(project_markets(stored_desk(now_ms)))
    try:
        body = release_scan(desk_scan(now_ms))
    except Exception as exc:
        body = {"markets": [], "notice": "The scan did not return a reading. No price was invented.", "broker": False, "snapshots": []}
    from ops.desk_pulse import project_markets

    return jsonify(project_markets(body))


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
            "fields": built.get("fields") or {},
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
        "fields": {},
    })


@app.get("/api/candles/import")
def candle_import_history():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.candle_import import history

    return jsonify({"imports": history(user_id), "live": False, "source": "user_provided_historical", "broker": False})


@app.post("/api/candles/import")
def candle_import_post():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.candle_import import import_rows, parse_csv

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "invalid_input", "message": "The import could not be read."}), 400
    parsed = parse_csv(body.get("csv") if isinstance(body.get("csv"), str) else "")
    if not parsed.get("ok"):
        return jsonify({"ok": False, "reason": parsed.get("reason"), "fields": parsed.get("fields") or {}, "live": False, "stored": 0, "broker": False}), 400
    result = import_rows(user_id, parsed["rows"])
    result["errors"] = parsed.get("errors") or []
    return jsonify(result)


@app.post("/api/candles/evaluate")
def candle_import_evaluate():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.candle_import import INSTRUMENTS, INTERVALS, evaluate

    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol") if isinstance(body, dict) else None
    interval = body.get("interval") if isinstance(body, dict) else None
    if symbol not in INSTRUMENTS or interval not in INTERVALS:
        return jsonify({"ok": False, "reason": "unsupported", "live": False, "signal": False, "broker": False}), 400
    if symbol == "XAUUSD" and interval in {"1m", "3m"}:
        return jsonify({"ok": False, "reason": "xau_minute_unlicensed", "live": False, "signal": False, "broker": False}), 400
    result = evaluate(user_id, symbol, interval)
    result["approved"] = False
    result["order_opened"] = False
    return jsonify(result)


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
    elif os.environ.get("AUREON_ROLE", "").strip().lower() == "web":
        from ops.canonical_read import stored_desk
        body = stored_desk(now_ms)
    else:
        try:
            body = release_scan(desk_scan(now_ms))
        except Exception:
            body = empty_desk()
    from ops.desk_pulse import project_markets

    body = project_markets(body)
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
    from ops.inbox import notice_view, page as inbox_page
    now_ms = int(time.time() * 1000)
    raw_limit = request.args.get("limit")
    try:
        limit = None if raw_limit in (None, "") else int(raw_limit)
    except ValueError:
        return jsonify({"error": "invalid_input"}), 400
    if limit is not None and limit < 1:
        return jsonify({"error": "invalid_input"}), 400
    before = request.args.get("before")
    try:
        if before not in (None, ""):
            int(before)
    except ValueError:
        return jsonify({"error": "invalid_input"}), 400
    import os as _os
    retain = _os.environ.get("AUREON_INBOX_ARCHIVE_AFTER_MS")
    if retain and str(retain).isdigit() and int(retain) > 0:
        from ops.inbox import apply_retention
        apply_retention(user_id, now_ms, int(retain))
    body = inbox_page(
        user_id,
        limit=limit,
        before_ms=None if before in (None, "") else int(before),
        before_id=request.args.get("before_id"),
        include_archived=request.args.get("include_archived") == "1",
    )
    body["items"] = [redact_feed_view(notice_view(item, now_ms)) for item in body["items"]]
    return jsonify(body)


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
    from ops.inbox import inbox_settings, primary_inbox
    from ops.users import get
    account = get(user_id) or {}
    style = ((account.get("profile") or {}).get("signal_style"))
    return jsonify({"settings": inbox_settings(account), "primary": primary_inbox(style)})


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
    try:
        status, payload = handle_signal(user_id, body)
    except Exception:
        payload = customer_terminal(symbol, interval)
        payload["request_id"] = str(body.get("request_id") or "")
        return jsonify(payload), 200
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


@app.get("/api/experience")
def experience_profile():
    user_id, user = _session_user()
    if not user_id or not user:
        return jsonify({"error": "unauthorized"}), 401
    from ops.experience import resolve

    return jsonify(resolve(user))


@app.post("/api/experience")
def experience_save():
    user_id, user = _session_user()
    if not user_id or not user:
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "invalid_input"}), 400
    if any(key in body for key in ("role", "security_role", "entitlements", "password", "id")):
        try:
            from ops.activity import record

            record("privilege_refused", account_id=user_id, component="experience", detail={"refused": True})
        except Exception:
            pass
        return jsonify({"error": "not_permitted"}), 403
    from ops.ai_safety import accept_display_name
    if "name" in body and accept_display_name(body.get("name")) is None:
        return jsonify({"error": "invalid or duplicate"}), 400
    from ops.access import resolve_role
    from ops.experience import resolve
    from ops.users import update_presentation

    saved = update_presentation(user_id, body, role=resolve_role(user))
    if not saved:
        return jsonify({"error": "invalid_input"}), 400
    try:
        from ops.activity import record

        record("experience_saved", account_id=user_id, component="experience", detail={"saved": True})
    except Exception:
        pass
    from ops.users import get

    return jsonify(resolve(get(user_id)))


@app.get("/api/accounts")
def account_directory():
    user_id, user = _session_user()
    if not user_id or not user:
        return jsonify({"error": "unauthorized"}), 401
    from ops.access import resolve_role
    from ops.users import ROOT
    import json as _json

    role = resolve_role(user)
    if role != "operator":
        return jsonify({
            "allowed": False,
            "security_role": role,
            "reason": "Account administration is limited to an operator named on the server. A preference cannot grant it.",
        })
    rows = []
    if ROOT.exists():
        for path in sorted(ROOT.glob("*.json")):
            try:
                record = _json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            rows.append({
                "id": record.get("id"),
                "name": record.get("name"),
                "security_role": resolve_role(record),
            })
    return jsonify({"allowed": True, "security_role": role, "accounts": rows, "broker": False})


def _accept_local_model(result, question=None):
    """Use the existing Ollama client only when discovery says the selected model is installed.

    A missing model does not open a socket and does not become an analysis.
    Hosted commentary that already passed is left unchanged.
    """
    from ops.ollama import explain, health as ollama_health

    model = ollama_health()
    status = {
        "available": model.get("available") is True,
        "reason": model.get("reason"),
        "model": model.get("model"),
        "installed": list(model.get("installed") or []),
        "reachable": model.get("reachable"),
        "inference": False,
        "customer_toggle": False,
    }
    refused = result.get("reason") in {"order_request_refused", "other_account_refused"}
    if result.get("analysis") or refused or model.get("available") is not True:
        return status
    facts = [item for item in (result.get("stored_record") or []) if isinstance(item, str)]
    refs = [item for item in (result.get("evidence_refs") or []) if isinstance(item, str)]
    evidence = {
        "observation": next((item for item in facts if item.startswith("latest observation")), "none"),
        "research": next((item for item in facts if item.startswith("latest research")), "not_promoted"),
        "execution": next((item for item in facts if item.startswith("latest execution")), "not_eligible"),
        "note": " ".join(item for item in facts if item.startswith(("latest observation", "latest research", "latest execution")))[:400],
    }
    if isinstance(question, str) and question.strip():
        evidence["question"] = question.strip()[:280]
    from ops.ai_provider import _LOCK

    if not _LOCK.acquire(blocking=False):
        status["reason"] = "busy"
        return status
    try:
        explained = explain(evidence, timeout=20)
    finally:
        _LOCK.release()
    summary = None
    used = []
    if explained.get("ok") and isinstance(explained.get("explanation"), dict):
        summary = explained["explanation"].get("summary")
        used = [item for item in explained["explanation"].get("evidence_used") or [] if isinstance(item, str)]
    from ops.hosted_ai import _validate

    if isinstance(summary, str) and _validate(summary, facts, refs, used):
        result["analysis"] = summary
        result["label"] = "ai_commentary_not_a_signal"
        result["ok"] = True
        result["approved"] = False
        result["order_opened"] = False
        status["inference"] = True
        status["reason"] = None
        return status
    status["inference"] = False
    status["reason"] = explained.get("reason") or "invalid_output"
    return status


@app.post("/api/aureon-ai")
def aureon_ai():
    raw = request.get_data(cache=True) or b""
    if len(raw) > 8000:
        return jsonify({"error": "payload_too_large"}), 413
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized"}), 401
    from ops.hosted_ai import complete

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    page = body.get("page") if isinstance(body.get("page"), str) else "/overview"
    question = body.get("question") if isinstance(body.get("question"), str) else None
    symbol = body.get("symbol") if isinstance(body.get("symbol"), str) else None
    interval = body.get("interval") if isinstance(body.get("interval"), str) else None
    try:
        result = complete(user_id, page, question=question, symbol=symbol, interval=interval)
    except Exception:
        app.logger.exception("aureon-ai failed")
        result = {
            "ok": False,
            "analysis": None,
            "approved": False,
            "order_opened": False,
            "reason": "unavailable",
            "message": "Aureon AI is temporarily unavailable.",
            "operational": "BLOCKED",
        }
    result["approved"] = False
    result["order_opened"] = False
    result["customer_toggle"] = False
    asked = isinstance(question, str) and bool(question.strip())
    if asked:
        result["ollama"] = _accept_local_model(result, question)
        local = result.get("ollama") or {}
        if local.get("inference") is True and result.get("analysis") and result.get("reason") == "provider_not_configured":
            result["reason"] = None
            result["note"] = "Local commentary from the installed model. Not a signal and not an order. The hosted provider was not called."
    else:
        from ops.ollama import health as ollama_health

        model = ollama_health()
        result["ollama"] = {
            "available": model.get("available") is True,
            "reason": model.get("reason"),
            "model": model.get("model"),
            "installed": list(model.get("installed") or []),
            "reachable": model.get("reachable"),
            "inference": False,
            "customer_toggle": False,
        }
    from ops.bot_thread import append, history

    if asked:
        append(user_id, "customer", question)
        if result.get("analysis"):
            reply = result["analysis"]
        elif result.get("stored_record"):
            reply = "No model analysis was completed. Stored record: " + " ".join(str(item) for item in result["stored_record"])[:900]
        else:
            reply = result.get("message") or "Aureon AI is temporarily unavailable."
        append(user_id, "aureon", reply)
    result["thread"] = [
        {key: value for key, value in row.items() if key != "account_id"}
        for row in history(user_id, limit=20)
    ]
    import hashlib

    from ops.activity import record_once

    token = hashlib.sha256((question or page).encode()).hexdigest()[:12]
    record_once(
        "bot_request",
        entity=f"bot:{user_id}:{page}:{token}",
        component="aureon_bot",
        account_id=user_id,
        detail={"note": "Aureon Bot handled a request for this account. The reply is not a signal.", "page": page},
    )
    return jsonify(result)


@app.get("/api/bot/thread")
def bot_thread():
    user_id, _user = _session_user()
    if not user_id:
        return jsonify({"error": "unauthorized", "message": "Your account does not have permission for this action."}), 401
    from ops.bot_thread import history

    return jsonify({
        "messages": [{key: value for key, value in row.items() if key != "account_id"} for row in history(user_id)],
        "broker": False,
        "approved": False,
    })







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
    def work():
        from ops.users import list_users
        for user in list_users():
            _deliver_digest(user)

    while desk_runtime.tick_start("digest"):
        completed = False
        try:
            work()
            completed = True
        except Exception:
            completed = False
        finally:
            desk_runtime.tick_end("digest", completed)
        if desk_runtime.wait(3600):
            return


_spawn(_digest_loop, "aureon-digest")


def _shutdown_background():
    try:
        desk_runtime.shutdown(deadline_s=2)
    except Exception:
        return None


atexit.register(_shutdown_background)


def _boot_web_schema():
    """Stamp the shared schema only in the web role. A newer file is not rewritten."""
    if os.environ.get("AUREON_ROLE", "").strip().lower() != "web":
        return None
    try:
        from ops.paths import data_root
        from ops.schema_guard import guard

        app.config["SCHEMA_GUARD"] = guard(data_root(), apply=True)
    except Exception as exc:
        app.config["SCHEMA_GUARD"] = {"ok": False, "action": "error", "reason": type(exc).__name__}
    return app.config.get("SCHEMA_GUARD")


_boot_web_schema()


from ops.routes import register as register_routes
from ops.routes.pages import _auth_page

register_routes(app)


if __name__ == "__main__":
    _bind = os.environ.get("DESK_BIND", "127.0.0.1")
    _port = int(os.environ.get("PORT", "8080"))
    app.run(host=_bind, port=_port)
