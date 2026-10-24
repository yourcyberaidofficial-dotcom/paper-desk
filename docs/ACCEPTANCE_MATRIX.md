# Acceptance matrix

Production browser check, 2026-10-24 19:03 UTC, https://aureontradelab.tech. Not a claim that Gate 1 is complete.

| Workflow | Result | Evidence |
|---|---|---|
| Public landing | PASS | Create account and Sign in. Three styles. No dashboard nav. |
| Registration and login | PASS | Two accounts. Reload kept the session. Logout returned to the public page. |
| Anonymous protection | PASS | `/overview` redirected to login. `/api/me` and `/api/eligibility` returned 401. |
| Style and currency | PASS | Saved style changed the risk cap. Currency and capital stayed put. Accounts did not share settings. |
| Eligibility | PASS | E1 WAIT stayed WAIT for Apex. Response included WAIT_DEFAULT and broker false. |
| Portfolio | FAIL | Live page listed BTCUSDT SHORT_BIAS as an open paper position. |
| Telegram delivery | BLOCKED | No authorized verified test chat was available. |
| Broker off | PASS | `/health` broker false, paper_only true, strategy_status WAIT_DEFAULT. |
