"""Signed-in and public HTML routes. Markup lives in ops/ui."""

import json

from flask import Blueprint, make_response, redirect, request

from ops.desk_ui import DASHBOARD, LANDING

bp = Blueprint("desk_pages", __name__)


@bp.get("/")
def landing():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    if _gate():
        return redirect("/overview")
    return make_response(LANDING)


@bp.get("/login")
def login_page():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    nxt = _safe_next(request.args.get("next"))
    if _gate():
        return redirect(nxt)
    return make_response(_auth_page("login", nxt))


@bp.get("/register")
def register_page():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    raw = request.args.get("next")
    nxt = _safe_next(raw) if raw else "/onboarding"
    if _gate():
        return redirect(nxt)
    return make_response(_auth_page("register", nxt))


@bp.get("/accounts")
@bp.get("/overview")
@bp.get("/signals")
@bp.get("/trading")
@bp.get("/strategies")
@bp.get("/indicators")
@bp.get("/research")
@bp.get("/portfolio")
@bp.get("/risk")
@bp.get("/activity")
@bp.get("/live")
@bp.get("/system")
@bp.get("/settings")
@bp.get("/scanner")
@bp.get("/learn")
@bp.get("/plan")
@bp.get("/lab")
@bp.get("/notifications")
@bp.get("/onboarding")
@bp.get("/orders")
@bp.get("/history")
def index():
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
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
        "/orders": "Orders",
        "/history": "Trade History",
        "/accounts": "Accounts",
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
    from ops.app import _csrf, _gate, _safe_next, _session_user, _worker_public
    title = "Create account" if kind == "register" else "Sign in"
    button = "Create account" if kind == "register" else "Sign in"
    alt = '<a href="/login">Already have an account? Sign in</a>' if kind == "register" else '<a href="/register">Need an account? Create one</a>'
    endpoint = "/api/register" if kind == "register" else "/api/login"
    csrf = _csrf()
    fail = "That name is taken or the details are invalid." if kind == "register" else "Name or password is incorrect."
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="csrf" content="{csrf}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Aureon Trading Lab</title>
<style>
html,body{{max-width:100%;overflow-x:hidden}}
body{{margin:0;font-family:system-ui;background:#0b1220;color:#e8eef7}}
header{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;padding:16px;border-bottom:1px solid #1e293b}}
a{{color:#99f6e4;text-decoration:none}}
.brand{{font-weight:700;color:#e8eef7}}
.muted{{color:#94a3b8;font-size:12px}}
main{{max-width:420px;margin:24px auto;padding:0 16px}}
h1{{font-size:1.6rem;line-height:1.2}}
form{{background:#111827;border:1px solid #1e293b;border-radius:12px;padding:20px;display:grid;gap:12px;min-width:0}}
label{{display:grid;gap:6px;font-size:14px;min-width:0}}
input{{width:100%;max-width:100%;box-sizing:border-box;background:#0b1220;color:#e8eef7;border:1px solid #334155;border-radius:8px;padding:12px;font-size:16px}}
button{{background:#0f766e;color:white;border:0;padding:12px 16px;border-radius:8px;cursor:pointer;font-size:16px}}
button:disabled{{opacity:.6}}
.err{{color:#fda4af;min-height:1.2em}}
.pw{{display:flex;gap:8px;align-items:center;min-width:0}}
.pw input{{flex:1;min-width:0}}
.pw button{{flex:0 0 auto;background:#152033;border:1px solid #334155}}
@media(max-width:360px){{header{{padding:12px}}main{{margin:12px auto;padding:0 12px}}form{{padding:16px}}}}
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
  <p class="muted">Aureon AI is on every signed-in page. This form does not call it, and it cannot be switched off.</p>
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
      headers: {{"Content-Type": "application/json", "X-CSRF-Token": "{csrf}"}},
      credentials: "same-origin",
      body: JSON.stringify({{name, password}})
    }});
    if (!response.ok) {{
      msg.textContent = (response.status === 401 || response.status === 400) ? "{fail}" : "The request could not be completed. Try again.";
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
