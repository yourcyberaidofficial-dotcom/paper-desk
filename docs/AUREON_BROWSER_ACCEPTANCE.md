# Aureon browser acceptance

Chromium, driven by Playwright (`ops/browser_acceptance.py`), against an isolated desk. Production data was not mounted. `DESK_GENERAL_LIMIT=8000` and `DESK_AUTH_LIMIT=200` were set only so the sweep itself was not a rate-limit test. The deployment defaults are unchanged.

Accounts: customer `Benny`, operator `Adanna`. The operator id was placed in `AUREON_OPERATOR_IDS` before Adanna's later requests. No production account was used.

## Result

| Check | Result |
| --- | --- |
| Findings | 56 PASS, 0 FAIL, 1 NOT IMPLEMENTED |
| Authenticated pages at 320, 360, 375, 390, 414, 430, 768, 1280 | 144 rows, HTTP 200, overflow 0, clipped controls 0, stuck loading 0 |
| Export and pagination controls | NOT IMPLEMENTED. No button was added for them. |
| Live hosted model | BLOCKED. No key and no spend approval. |

Screenshots and `findings.json` / `layout.json` are in `docs/release-evidence/experience/`.

## What the browser actually did

- Register Adanna and Benny through the register form. A short password shows the validation message and does not create the account.
- A wrong password shows "Name or password is incorrect."
- Benny's chip reads `Benny · customer`. The Accounts nav stays hidden, including after a search for "Accounts".
- Search for a missing word shows "No page matches that search." Search for "Risk" leaves that link visible.
- Help on Overview shows the Overview sentence. Aureon AI opens and says the hosted model is not configured. The posted page is `/overview`. The answer does not invent an analysis. Asking about Adanna does not return her record.
- An invalid time zone shows "Display settings were not saved."
- Saving America/New_York, compact, concise, market, light, high contrast, and reduced motion changes the live attributes: compact padding 12px, light background `rgb(255, 255, 255)`, concise hides `.guide`, reduced motion sets card transition to `0s`, the zone label names America/New_York. Reload and a new login keep it. Adanna stays on Africa/Lagos.
- Posting `role`, `security_role`, and `entitlements` returns HTTP 403.
- Market layout renders `#ov-market` before `#ov-account`.
- Academy rejects a wrong check and then stores the completed lesson.
- My Plan save shows "Plan saved."
- Scanner filters to XAUUSD 1m and does not keep BTCUSDT in the card list.
- Terminal evaluation states that a verified live reading is not available.
- A typed manual plan (entry 100, stop 90, target 140) is confirmed. The button says the paper trade was recorded and is not a broker fill. Benny's isolated paper file has one open BTCUSDT order, `opened_by` account, `executable` false.
- Inbox shows a count. Mark read changes `Inbox (2)` to `Inbox (1)`.
- Customer `/accounts` explains that a preference cannot grant administration.
- Operator `/accounts` lists Benny and Adanna and does not print a password hash. Operator layout is offered only to Adanna and applies as `operator`.
- Benny's journal sentence is absent from Adanna's Trading Lab.
- Sign out returns to the public landing page.
- Landing, login, and register mention Aureon AI and do not pretend to call it.

## Defects found and fixed before this run

The first browser load never called an API. The dashboard script did not parse: the operator layout option was written with escaped quotes that Python removed, so every header control was unbound. That is fixed.

Search used to clear `hidden` on the operator link. It now uses a filter class and leaves the role hide in place.

Inbox, Live Activities, and the system heartbeat ignored the saved time zone. They now use `when()`.

The scanner had no instrument or timeframe filter. It now filters the cards already returned by the scan and does not invent a price.

The header now shows the unread count returned by the inbox API.

Hosted validation, after an independent review of the previous implementation, now rejects a one- or two-digit number that is not in the facts, an order phrase with a hidden format character, and a hyphenated identifier in the summary that is not in the facts. A test transport is not called unless the provider is configured.

## Gate rerun

`AUREON_BROWSER_FOCUS=1` reran the customer and operator journeys and wrote `docs/release-evidence/experience/gate/`. Result: 56 PASS, 1 NOT IMPLEMENTED, 18 layout rows at 1280, 0 overflow. The eight-width sweep was not repeated.

`export-and-pagination-controls` is NOT IMPLEMENTED on purpose. The check searches the shell for export, download csv, next page, or previous page. Those controls are not a product requirement, and no dead button was added.

## Not claimed

- A live model response. Status remains BLOCKED.
- Export or pagination. Those controls do not exist.
- A human sign-off. A separate probe of `complete()` and the route closed the three earlier validation holes. See the acceptance report. The author is not that reviewer.
