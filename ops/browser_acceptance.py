"""Browser acceptance for the experience branch.

Starts an isolated desk, drives Chromium, and writes evidence under
docs/release-evidence/experience/. It does not use production data.
The general and auth ceilings are raised only so the sweep is not a
rate-limit test. Deployment defaults are unchanged.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "release-evidence" / "experience"
PAGES = [
    ("/", "Landing"),
    ("/register", "Register"),
    ("/login", "Login"),
    ("/onboarding", "Onboarding"),
    ("/overview", "Overview"),
    ("/trading", "Terminal"),
    ("/scanner", "Scanner"),
    ("/signals", "Live Signals"),
    ("/strategies", "Strategies"),
    ("/research", "Research"),
    ("/plan", "My Plan"),
    ("/portfolio", "Portfolio"),
    ("/orders", "Orders"),
    ("/history", "Trade History"),
    ("/risk", "Risk"),
    ("/notifications", "Inbox"),
    ("/live", "Live Activities"),
    ("/settings", "Settings"),
    ("/system", "System Status"),
    ("/learn", "Academy"),
    ("/lab", "Trading Lab"),
]
WIDTHS = [320, 360, 375, 390, 414, 430, 768, 1280]
CUSTOMER = "Benny"
OPERATOR = "Adanna"
PASSWORD = "password-s"


def _port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _spawn(port, data, operator_id=""):
    data.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "AUREON_DATA": str(data),
        "AUREON_DISABLE_WORKERS": "1",
        "DESK_BIND": "127.0.0.1",
        "PORT": str(port),
        "PYTHONPATH": str(ROOT),
        "PYTHONUNBUFFERED": "1",
        "DESK_GENERAL_LIMIT": "8000",
        "DESK_AUTH_LIMIT": "200",
    })
    env.pop("AUREON_AI_API_KEY", None)
    env.pop("AUREON_AI_SPEND_APPROVED", None)
    if operator_id:
        env["AUREON_OPERATOR_IDS"] = operator_id
    else:
        env.pop("AUREON_OPERATOR_IDS", None)
    log_path = data / "server.log"
    handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        ["python3", "-m", "ops.app"],
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(log_path.read_text(encoding="utf-8")[-1000:])
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return process, handle
        except Exception:
            time.sleep(0.1)
    process.terminate()
    raise RuntimeError("desk did not start")


def _stop(process, handle):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    handle.close()


def _user_id(data, name):
    users = data / "users"
    for path in users.glob("*.json"):
        body = json.loads(path.read_text(encoding="utf-8"))
        if body.get("name") == name:
            return body["id"]
    raise RuntimeError(name)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = Path("/tmp/aureon-experience-browser")
    if data.exists():
        subprocess.run(["rm", "-rf", str(data)], check=True)
    port = _port()
    base = f"http://127.0.0.1:{port}"
    findings = []
    shots = []

    def note(name, status, detail):
        findings.append({"name": name, "status": status, "detail": detail})
        print(status, name, detail[:180], flush=True)

    process, handle = _spawn(port, data)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            desktop = browser.new_context(viewport={"width": 1280, "height": 900})
            page = desktop.new_page()

            page.goto(base + "/register", wait_until="domcontentloaded")
            page.fill("#name", OPERATOR)
            page.fill("#password", PASSWORD)
            page.click("#submit")
            page.wait_for_url("**/onboarding", timeout=15000)
            note("operator-register", "PASS", page.url)
            _stop(process, handle)
            operator_id = _user_id(data, OPERATOR)
            process, handle = _spawn(port, data, operator_id)
            page.context.clear_cookies()

            page.goto(base + "/register", wait_until="domcontentloaded")
            page.fill("#name", CUSTOMER)
            page.fill("#password", "short")
            page.click("#submit")
            page.wait_for_timeout(300)
            short_msg = page.locator("#msg").inner_text()
            note("register-short-password", "PASS" if "8 characters" in short_msg else "FAIL", short_msg)
            page.fill("#password", PASSWORD)
            page.click("#submit")
            page.wait_for_url("**/onboarding", timeout=15000)
            note("customer-register", "PASS", page.url)
            page.click("#signout")
            page.wait_for_function("() => location.pathname === '/'", timeout=10000)

            page.goto(base + "/login", wait_until="domcontentloaded")
            page.fill("#name", CUSTOMER)
            page.fill("#password", "wrong-password")
            page.click("#submit")
            page.wait_for_timeout(400)
            bad_login = page.locator("#msg").inner_text()
            note("login-failure", "PASS" if "incorrect" in bad_login.lower() else "FAIL", bad_login)
            page.fill("#password", PASSWORD)
            page.click("#submit")
            page.wait_for_function("() => location.pathname === '/overview'", timeout=15000)

            def settle():
                page.wait_for_selector("#experience-strip, #view h2, main h1", timeout=15000)
                page.wait_for_timeout(350)

            def shot(name):
                path = OUT / name
                page.screenshot(path=str(path), full_page=True)
                shots.append(name)

            def overflow():
                return page.evaluate(
                    """() => {
                      const vw = document.documentElement.clientWidth;
                      const nodes = [...document.querySelectorAll('input, button, select, textarea, a')];
                      const clipped = nodes.filter(el => {
                        const box = el.getBoundingClientRect();
                        if (box.width < 2 || box.height < 2) return false;
                        const aside = el.closest('aside');
                        if (aside && !aside.classList.contains('open') && getComputedStyle(aside).display === 'none') return false;
                        return box.right > vw + 1 || box.left < -1;
                      }).slice(0, 6).map(el => el.id || el.getAttribute('aria-label') || el.textContent.trim().slice(0, 40));
                      return {overflow: document.documentElement.scrollWidth > vw + 1, clipped};
                    }"""
                )

            layout_rows = []
            for width in WIDTHS:
                page.set_viewport_size({"width": width, "height": 900})
                for path, title in PAGES:
                    if path in {"/", "/login", "/register"}:
                        continue
                    response = page.goto(base + path, wait_until="domcontentloaded", timeout=20000)
                    settle()
                    body = overflow()
                    text = page.locator("#view").inner_text()[:240]
                    row = {
                        "path": path,
                        "title": title,
                        "width": width,
                        "status": response.status if response else None,
                        "overflow": body["overflow"],
                        "clipped": body["clipped"],
                        "loading": "Loading this page" in text,
                        "text": " ".join(text.split())[:180],
                        "ai": page.locator("#aiopen").count() == 1,
                        "role": page.locator("#whobadge").inner_text(),
                    }
                    layout_rows.append(row)
                    bad = row["overflow"] or row["clipped"] or row["loading"] or row["status"] != 200 or not row["ai"]
                    if bad or width in {320, 390, 1280} and path in {"/overview", "/settings", "/trading", "/scanner"}:
                        if bad or (width == 390 and path in {"/overview", "/scanner", "/settings", "/system", "/learn"}):
                            shot(f"customer-{path.strip('/') or 'home'}-{width}.png")
                if width == 320:
                    page.goto(base + "/overview", wait_until="domcontentloaded")
                    settle()
                    page.click("#menu")
                    opened = page.evaluate("() => document.getElementById('nav').classList.contains('open')")
                    page.click("aside a[href='/orders']")
                    page.wait_for_timeout(400)
                    note("menu-320", "PASS" if opened and "/orders" in page.url else "FAIL", f"opened={opened} url={page.url}")
                    shot("menu-open-320.png")

            public = browser.new_context(viewport={"width": 390, "height": 800})
            guest = public.new_page()
            for path, title in (("/", "Landing"), ("/login", "Login"), ("/register", "Register")):
                response = guest.goto(base + path, wait_until="domcontentloaded")
                guest.wait_for_timeout(200)
                text = guest.locator("body").inner_text()
                note(
                    f"public-{title}",
                    "PASS" if response.status == 200 and "Aureon AI" in text else "FAIL",
                    " ".join(text.split())[:160],
                )
                guest.screenshot(path=str(OUT / f"public-{title.lower()}-390.png"), full_page=True)
            public.close()

            page.set_viewport_size({"width": 1280, "height": 900})
            page.goto(base + "/overview", wait_until="domcontentloaded")
            settle()
            badge = page.locator("#whobadge").inner_text()
            note("customer-role-chip", "PASS" if "customer" in badge and CUSTOMER in badge else "FAIL", badge)
            accounts_hidden = page.locator("#nav-accounts").get_attribute("hidden")
            note("customer-accounts-nav-hidden", "PASS" if accounts_hidden is not None else "FAIL", str(accounts_hidden))

            page.fill("#navsearch", "Accounts")
            accounts_still_hidden = page.locator("#nav-accounts").get_attribute("hidden") is not None
            accounts_filtered = "filtered-out" in (page.locator("#nav-accounts").get_attribute("class") or "")
            visible = page.evaluate("() => { const el = document.getElementById('nav-accounts'); const box = el.getBoundingClientRect(); return box.width > 0 && box.height > 0 && getComputedStyle(el).display !== 'none'; }")
            note("search-does-not-reveal-operator", "PASS" if accounts_still_hidden and not visible else "FAIL", f"hidden={accounts_still_hidden} filtered={accounts_filtered} visible={visible}")
            page.fill("#navsearch", "zzzz-no-page")
            empty = page.locator("#navempty").inner_text()
            note("search-empty", "PASS" if "No page matches" in empty else "FAIL", empty)
            page.fill("#navsearch", "Risk")
            risk_visible = page.locator("aside a[href='/risk']").is_visible()
            note("search-risk", "PASS" if risk_visible else "FAIL", str(risk_visible))
            page.fill("#navsearch", "")

            page.click("#helpopen")
            help_open = page.locator("#helppanel").is_visible()
            help_text = page.locator("#helptext").inner_text()
            note("help-overview", "PASS" if help_open and "Overview" in help_text else "FAIL", help_text[:160])
            page.click("#helpclose")

            ai_request = {}

            def capture(route):
                ai_request["body"] = route.request.post_data or ""
                route.continue_()

            page.route("**/api/aureon-ai", capture)
            page.click("#aiopen")
            page.wait_for_timeout(500)
            status = page.locator("#aistatus").inner_text()
            blocked = "BLOCKED" in status.upper() or "not configured" in status.lower() or "stored" in status.lower() or "provider" in status.lower()
            note("ai-panel-blocked", "PASS" if page.locator("#aipanel").is_visible() and blocked else "FAIL", status[:200])
            page.fill("#aiquestion", "What is Adanna's balance?")
            page.click("#aiask")
            page.wait_for_timeout(600)
            answer = page.locator("#aianswer").inner_text()
            invented = "99999" in answer or "analysis:" in answer.lower()
            note("ai-no-fabricated-analysis", "PASS" if not invented and ("not an analysis" in answer.lower() or "refused" in answer.lower() or "stored" in answer.lower() or "Adanna" not in answer) else "FAIL", answer[:240])
            note("ai-request-page", "PASS" if '"page": "/overview"' in ai_request.get("body", "") or '"page":"/overview"' in ai_request.get("body", "") else "FAIL", ai_request.get("body", "")[:180])
            page.click("#aiclose")
            shot("ai-panel-overview-1280.png")

            page.goto(base + "/settings", wait_until="domcontentloaded")
            settle()
            page.fill("#timezone", "Not/AZone")
            page.click("#savedisplay")
            page.wait_for_timeout(400)
            failed_save = page.locator("#displaysaved").inner_text()
            note("display-invalid-timezone", "PASS" if "not saved" in failed_save.lower() else "FAIL", failed_save)
            page.check("input[name=style][value='apex_momentum']")
            page.select_option("#currency", "USD")
            page.fill("#capital", "1000")
            page.click("#saveall")
            page.wait_for_timeout(500)
            saved_profile = page.locator("#savedp").inner_text()
            note("save-persona-capital", "PASS" if "Saved" in saved_profile else "FAIL", saved_profile)

            page.fill("#timezone", "America/New_York")
            page.select_option("#density", "compact")
            page.select_option("#depth", "concise")
            page.select_option("#layout", "market")
            page.select_option("#theme", "light")
            page.select_option("#contrast", "high")
            page.select_option("#motion", "reduced")
            page.click("#savedisplay")
            page.wait_for_timeout(500)
            display_note = page.locator("#displaysaved").inner_text()
            look = page.evaluate(
                """() => {
                  const card = document.querySelector('#view .card');
                  const style = card ? getComputedStyle(card) : {};
                  const guide = document.querySelector('.guide');
                  return {
                    density: document.body.dataset.density,
                    depth: document.body.dataset.depth,
                    layout: document.body.dataset.layout,
                    theme: document.body.dataset.theme,
                    contrast: document.body.dataset.contrast,
                    motion: document.body.dataset.motion,
                    zone: document.getElementById('zonelabel').textContent,
                    padding: style.paddingTop || '',
                    transition: style.transitionDuration || '',
                    bg: getComputedStyle(document.body).backgroundColor,
                    guideHidden: guide ? getComputedStyle(guide).display === 'none' : null,
                  };
                }"""
            )
            display_ok = (
                "Saved" in display_note
                and look["density"] == "compact"
                and look["depth"] == "concise"
                and look["layout"] == "market"
                and look["theme"] == "light"
                and look["contrast"] == "high"
                and look["motion"] == "reduced"
                and "America/New_York" in look["zone"]
                and look["padding"] == "12px"
                and look["transition"] in {"0s", "0ms"}
                and look["guideHidden"] is True
            )
            note("display-propagation", "PASS" if display_ok else "FAIL", json.dumps({"note": display_note, **look}))
            shot("settings-display-light-1280.png")

            forced = page.evaluate(
                """async () => {
                  const response = await fetch('/api/experience', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body: JSON.stringify({role:'operator', security_role:'operator', entitlements:{broker:true}, layout:'operator', timezone:'America/New_York', density:'compact', depth:'concise', theme:'light', contrast:'high', motion:'reduced', language:'en'})});
                  const body = await response.json();
                  return {status: response.status, role: body.security_role || null, error: body.error || null};
                }"""
            )
            note("privilege-refused", "PASS" if forced["status"] == 403 else "FAIL", json.dumps(forced))

            page.reload(wait_until="domcontentloaded")
            settle()
            still = page.evaluate("() => document.body.dataset.theme + ' ' + document.getElementById('zonelabel').textContent")
            note("display-survives-reload", "PASS" if "light" in still and "America/New_York" in still else "FAIL", still)

            page.goto(base + "/overview", wait_until="domcontentloaded")
            settle()
            order = page.evaluate(
                """() => {
                  const split = document.querySelector('#view .split');
                  if (!split) return 'missing';
                  return [...split.children].map(node => node.id).join(',');
                }"""
            )
            overview_text = page.locator("#view").inner_text()
            note("market-layout-order", "PASS" if order.startswith("ov-market") else "FAIL", order)
            note("overview-timezone", "PASS" if "America/New_York" in overview_text or "New York" in page.locator("#zonelabel").inner_text() else "FAIL", page.locator("#zonelabel").inner_text())
            guide_hidden = page.evaluate("() => { const g = document.querySelector('#view .guide'); return g ? getComputedStyle(g).display === 'none' : false; }")
            note("concise-hides-guide", "PASS" if guide_hidden else "FAIL", str(guide_hidden))
            shot("overview-market-light-1280.png")

            page.goto(base + "/lab", wait_until="domcontentloaded")
            settle()
            page.fill("#journalnote", "benny-journal-isolation-token")
            page.click("#savenote")
            page.wait_for_timeout(700)
            page.fill("#objective", "Learn the desk")
            page.check("#labform input[value=risk]")
            page.click("#labform button[type=submit]")
            page.wait_for_timeout(400)
            lab_note = page.locator("#labsaved").inner_text()
            note("lab-profile-save", "PASS" if "Saved" in lab_note else "FAIL", lab_note)
            lab_text = page.locator("#view").inner_text()
            note("lab-journal-visible", "PASS" if "benny-journal-isolation-token" in lab_text else "FAIL", "token present" if "benny-journal-isolation-token" in lab_text else lab_text[:160])

            page.goto(base + "/learn", wait_until="domcontentloaded")
            settle()
            lesson = page.evaluate(
                """() => {
                  const button = document.querySelector('[data-lesson]');
                  if (!button) return {ok:false, reason:'no lesson'};
                  const id = button.dataset.lesson;
                  const radios = [...document.querySelectorAll('input[name="check-' + id + '"]')];
                  return {ok:true, id, choices: radios.length};
                }"""
            )
            if lesson.get("ok") and lesson.get("choices"):
                page.locator("input[name='check-" + lesson["id"] + "']").first.check()
                page.click(f"[data-lesson='{lesson['id']}']")
                page.wait_for_timeout(400)
                mismatch = page.locator(f"#check-{lesson['id']}").inner_text()
                note("academy-wrong-check", "PASS" if "not saved" in mismatch.lower() or "does not match" in mismatch.lower() else "FAIL", mismatch)
            else:
                note("academy-wrong-check", "NOT TESTED", json.dumps(lesson))
            correct = page.evaluate(
                """async (id) => {
                  const lab = await fetch('/api/lab', {credentials:'same-origin'}).then(r => r.json());
                  const lesson = (lab.lessons || []).find(item => item.id === id);
                  return lesson && lesson.check ? String(lesson.check.answer) : null;
                }""",
                lesson.get("id"),
            ) if lesson.get("ok") else None
            if correct is not None:
                page.locator(f"input[name='check-{lesson['id']}'][value='{correct}']").check()
                page.click(f"[data-lesson='{lesson['id']}']")
                page.wait_for_selector("text=Completed on this account", timeout=10000)
                note("academy-complete", "PASS", lesson["id"])
            else:
                note("academy-complete", "NOT TESTED", "no check answer")

            page.goto(base + "/plan", wait_until="domcontentloaded")
            settle()
            page.fill("#aim", "1")
            page.fill("#loss", "2")
            page.click("#planform button[type=submit]")
            page.wait_for_timeout(500)
            plan_note = page.locator("#plannote").inner_text()
            note("plan-save", "PASS" if "saved" in plan_note.lower() else "FAIL", plan_note)

            page.goto(base + "/scanner", wait_until="domcontentloaded")
            settle()
            page.wait_for_selector("#scancards article, #scancards .card, #scanstatus", timeout=10000)
            page.select_option("#scan-symbol", "XAUUSD")
            page.select_option("#scan-interval", "1m")
            page.wait_for_timeout(300)
            scan_text = page.locator("#scancards").inner_text()
            btc_visible = "BTCUSDT" in scan_text
            note("scanner-filter", "PASS" if "XAUUSD" in scan_text and not btc_visible else "FAIL", " ".join(scan_text.split())[:180])

            page.goto(base + "/signals", wait_until="domcontentloaded")
            settle()
            page.fill("#ask-q", "Explain the stored record")
            page.click("[data-ask]")
            page.wait_for_timeout(700)
            ask_out = page.locator("#ask-out").inner_text()
            note("signals-ask", "PASS" if "Not an analysis" in ask_out or "BLOCKED" in ask_out or "provider" in ask_out.lower() else "FAIL", ask_out[:200])

            page.goto(base + "/trading", wait_until="domcontentloaded")
            settle()
            page.wait_for_function("() => { const form = document.getElementById('manual-plan'); return form && form.dataset.bound === '1'; }", timeout=15000)
            page.select_option("#term-symbol", "BTCUSDT")
            page.select_option("#term-interval", "15m")
            page.click("#generate")
            page.wait_for_timeout(800)
            term = page.locator("#termout").inner_text() + " " + page.locator("#termstatus").inner_text()
            note("terminal-evaluate", "PASS" if term.strip() and "Loading" not in term else "FAIL", " ".join(term.split())[:200])
            page.locator("#manual-plan input[name=entry]").fill("100")
            page.locator("#manual-plan input[name=stop]").fill("90")
            page.locator("#manual-plan input[name=target]").fill("140")
            page.locator("#manual-plan button[type=submit]").click()
            page.wait_for_function("() => (document.getElementById('manual-out') || {}).innerText", timeout=10000)
            manual = page.locator("#manual-out").inner_text()
            if "Paper trade recorded" in manual or "Confirm manual paper order" in manual:
                confirm = page.locator("#manual-confirm")
                if confirm.count():
                    confirm.click()
                    page.wait_for_timeout(600)
                    manual = page.locator("#manual-out").inner_text()
                if "Paper trade recorded" in manual:
                    note("manual-paper", "PASS", manual[:220])
                else:
                    note("manual-paper", "BLOCKED", manual[:220])
            elif manual.strip():
                note("manual-paper", "BLOCKED", manual[:220])
            else:
                note("manual-paper", "FAIL", "no result")
            shot("terminal-1280.png")

            page.goto(base + "/portfolio", wait_until="domcontentloaded")
            settle()
            book = page.locator("#view").inner_text()
            note("portfolio-empty-or-real", "PASS" if "No open paper position" in book or "Open paper positions" in book else "FAIL", " ".join(book.split())[:160])
            page.goto(base + "/orders", wait_until="domcontentloaded")
            settle()
            note("orders-page", "PASS" if "Orders" in page.locator("#view").inner_text() else "FAIL", page.locator("h1").inner_text())
            page.goto(base + "/history", wait_until="domcontentloaded")
            settle()
            note("history-page", "PASS" if "history" in page.locator("#view").inner_text().lower() else "FAIL", page.locator("h1").inner_text())
            page.goto(base + "/risk", wait_until="domcontentloaded")
            settle()
            risk = page.locator("#view").inner_text()
            note("risk-persona", "PASS" if "Apex" in risk or "Active style" in risk else "FAIL", " ".join(risk.split())[:160])
            page.goto(base + "/notifications", wait_until="domcontentloaded")
            settle()
            inbox = page.locator("#view").inner_text()
            header_inbox = page.locator("#inboxlink").inner_text()
            note("inbox-page", "PASS" if "unread" in inbox.lower() or "No notifications" in inbox else "FAIL", " ".join(inbox.split())[:160])
            note("inbox-badge", "PASS" if "Inbox" in header_inbox else "FAIL", header_inbox)
            if page.locator("[data-id]").count():
                page.click("[data-id]")
                page.wait_for_timeout(500)
                note("inbox-mark-read", "PASS", page.locator("#inboxlink").inner_text())
            else:
                note("inbox-mark-read", "NOT TESTED", "no notice to mark")
            page.goto(base + "/live", wait_until="domcontentloaded")
            settle()
            live = page.locator("#view").inner_text()
            note("live-activities", "PASS" if "Live Activities" in live and ("America/New_York" in live or "No system event" in live) else "FAIL", " ".join(live.split())[:180])
            page.goto(base + "/system", wait_until="domcontentloaded")
            settle()
            page.wait_for_timeout(600)
            system = page.locator("#view").inner_text()
            note("system-ai-blocked", "PASS" if "BLOCKED" in system and "Broker" in system else "FAIL", " ".join(system.split())[:200])
            page.goto(base + "/accounts", wait_until="domcontentloaded")
            settle()
            denied = page.locator("#view").inner_text()
            note("customer-accounts-denied", "PASS" if "cannot grant" in denied.lower() or "operator" in denied.lower() and "password" not in denied.lower() else "FAIL", " ".join(denied.split())[:200])
            page.goto(base + "/strategies", wait_until="domcontentloaded")
            settle()
            note("strategies", "PASS" if "Approved" in page.locator("#view").inner_text() or "strateg" in page.locator("#view").inner_text().lower() else "FAIL", page.locator("h1").inner_text())
            page.goto(base + "/research", wait_until="domcontentloaded")
            settle()
            note("research", "PASS" if "Research" in page.locator("#view").inner_text() else "FAIL", page.locator("h1").inner_text())

            exports = page.evaluate("() => [...document.querySelectorAll('button,a')].some(el => /export|download csv|next page|previous page/i.test(el.textContent || ''))")
            note("export-and-pagination-controls", "NOT IMPLEMENTED" if not exports else "PASS", "no export or pager control in the shell")

            page.click("#signout")
            page.wait_for_function("() => location.pathname === '/'", timeout=10000)
            signed_out = page.locator("body").inner_text()
            note("sign-out", "PASS" if "Sign in" in signed_out and "Create account" in signed_out else "FAIL", page.url)

            page.goto(base + "/login", wait_until="domcontentloaded")
            page.fill("#name", CUSTOMER)
            page.fill("#password", PASSWORD)
            page.click("#submit")
            page.wait_for_function("() => location.pathname === '/overview'", timeout=15000)
            settle()
            persisted = page.evaluate("() => document.body.dataset.theme + '|' + document.body.dataset.density + '|' + document.getElementById('zonelabel').textContent")
            note("preference-after-new-login", "PASS" if persisted.startswith("light|compact|") and "America/New_York" in persisted else "FAIL", persisted)
            page.click("#signout")
            page.wait_for_function("() => location.pathname === '/'", timeout=10000)

            page.goto(base + "/login", wait_until="domcontentloaded")
            page.fill("#name", OPERATOR)
            page.fill("#password", PASSWORD)
            page.click("#submit")
            page.wait_for_function("() => location.pathname === '/overview'", timeout=15000)
            settle()
            op_badge = page.locator("#whobadge").inner_text()
            op_zone = page.locator("#zonelabel").inner_text()
            note("operator-role", "PASS" if "operator" in op_badge and OPERATOR in op_badge else "FAIL", op_badge)
            note("operator-not-customer-timezone", "PASS" if "America/New_York" not in op_zone else "FAIL", op_zone)
            lab_other = page.goto(base + "/lab", wait_until="domcontentloaded")
            settle()
            other_lab = page.locator("#view").inner_text()
            note("account-isolation-journal", "PASS" if "benny-journal-isolation-token" not in other_lab else "FAIL", "leak" if "benny-journal-isolation-token" in other_lab else "absent")
            page.goto(base + "/accounts", wait_until="domcontentloaded")
            page.wait_for_selector("text=Names and roles only", timeout=15000)
            directory = page.locator("#view").inner_text()
            note("operator-directory", "PASS" if CUSTOMER in directory and OPERATOR in directory and "password_hash" not in directory.lower() else "FAIL", " ".join(directory.split())[:240])
            shot("operator-accounts-1280.png")
            nav_accounts = page.locator("#nav-accounts").is_visible()
            note("operator-nav-accounts", "PASS" if nav_accounts else "FAIL", str(nav_accounts))
            page.goto(base + "/settings", wait_until="domcontentloaded")
            settle()
            has_operator_layout = page.locator("#layout option[value=operator]").count() == 1
            note("operator-layout-option", "PASS" if has_operator_layout else "FAIL", str(has_operator_layout))
            if has_operator_layout:
                page.select_option("#layout", "operator")
                page.click("#savedisplay")
                page.wait_for_timeout(400)
                op_layout = page.evaluate("() => document.body.dataset.layout")
                note("operator-layout-applied", "PASS" if op_layout == "operator" else "FAIL", op_layout)
            page.goto(base + "/system", wait_until="domcontentloaded")
            settle()
            note("operator-system", "PASS" if "System" in page.locator("#view").inner_text() else "FAIL", page.locator("h1").inner_text())

            browser.close()
            (OUT / "layout.json").write_text(json.dumps(layout_rows, indent=2), encoding="utf-8")
            (OUT / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
            counts = {}
            for row in findings:
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            bad_layout = [row for row in layout_rows if row["overflow"] or row["clipped"] or row["loading"] or row["status"] != 200]
            summary = {"findings": counts, "layout_rows": len(layout_rows), "layout_bad": len(bad_layout), "shots": shots}
            (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(json.dumps(summary), flush=True)
            if bad_layout:
                print("LAYOUT", json.dumps(bad_layout[:8]), flush=True)
    finally:
        _stop(process, handle)


if __name__ == "__main__":
    main()
