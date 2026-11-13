2026-11-13. Stage 5 is source only, on `product/stage5-learning` from Stage 4 `dbc014b`. Paper orders now store entry context, running MAE/MFE, bars held, and realized R on the existing book under `users/paper/` (desk-users, schema 1). A sample under 30 completed trades is `not_enough_evidence`. Hypotheses do not promote, and `approved_for_paper` stays 0. Lab, Academy, and Strategies read that diagnostic without calling Ollama. `ops/app.py` keeps the worker loops, session middleware, and health helpers. Customer HTML is in `ops/ui/`, and the page, paper, lab, and qualification routes are blueprints. 394 tests passed. Not deployed. Docker was not started.

2026-11-13. Stage 4 is source only. `web` is one gunicorn process with the desk loops off. `worker` writes the canonical reading, the Telegram outbox, and `canonical/worker_status.json` on the same nine volumes. Customer reads of markets, scanner, desk, workspace, and health use those files when `AUREON_ROLE=web`. `/version` reports the optional `build_commit` label and a separate baked `content_hash`. The schema guard refuses a newer data file and does not rewrite accounts. `/health` still answers when no customer candle is released. The worker check fails if a loop thread is gone, and `SIGTERM` stops the loops instead of dropping them. Promotions, claims, imports, and the bot log sit inside the nine volumes. Not deployed. Docker was not started against a production project.

2026-11-08. Self-audit of `product/backend-recovery`, not an independent review. Imported signal rows are read only for the signed-in account. The private Ollama compose file does not declare a Docker network, because the production desk network was not observed. Local Ollama inference was checked on this host only. Not deployed.

# Implementation status

2026-11-08. Local Ollama `qwen2.5:1.5b` Q4_K_M answers `/api/aureon-ai` from the desk process on this host. The listener stays `127.0.0.1:11434`. The production host `88.223.95.249` did not accept TCP on 22, 80, or 443, and this host has no Docker bridge, so no private gateway was configured and nothing was deployed. A historical CSV evaluation is recorded at the clock time it ran, with the candle time kept as `observed_ms`. Not deployed.

2026-11-03. A daily reading can be reviewed and then confirmed as a manual paper plan. The review stores the snapshot identity and does not open an order. Experimental alerts stay off unless the account turns them on. AutoPilot still needs an approved strategy. Gold 1-minute and 3-minute, Vision archives, retention, the holdout and strategy promotion stay closed. Not deployed.

2026-11-03. The daily desk shares one snapshot across Overview, Scanner and Live Signals. A candle close is not a quote. Gold 1-minute and 3-minute stay unlicensed. Vision archives, historical retention, the holdout and strategy promotion stay closed. A manual paper plan still needs an explicit confirm. AutoPilot still needs an approved strategy. Not deployed.

2026-11-03. The live paper desk reads public spot prices again on `completion/integrated-desk`. Overview, Terminal, Scanner, and Live Signals show those readings. Gold 15-minute and 1-hour are included. Gold 1-minute and 3-minute stay unlicensed. Binance Vision archives, historical retention, the sealed holdout, and strategy promotion stay closed. Approved strategies remain zero, so AutoPilot does not open a paper order. This is not a commercial-archive licence. Production stays on the previous build until that host is updated by hand.

2026-11-03. Restricted-data product recovery is on `completion/integrated-desk`. That presentation pass is what production showed before this desk restore. Approved strategies remain zero.

2026-11-03. Live prices stay withheld. That is the commercial-use gate, not a dead worker and not a provider outage. The desk copy now says “Not shown” / “Price withheld” instead of the internal token RIGHTS, the market-watch column no longer clips the status, and an empty chart is a stated pause rather than a black canvas. Production at `81de54b` still shows the older labels until this presentation change is deployed. No feed was turned back on. Approved strategies remain zero.

Observed on https://aureontradelab.tech at 2026-10-24 19:03 UTC. The running process had been up for about 9.4 hours. `/health` was `WAIT_DEFAULT`, `broker: false`, `paper_only: true`, market data fresh. The live HTML matches the three-style product on main `cd62b27`. This file's later portfolio change is source-only until that commit is deployed.

| Area | Status | Evidence |
|---|---|---|
| Public landing | LIVE | Anonymous page names Apex, Orion, and Aegis. No private nav. |
| Register and login | LIVE | Distinct forms. Browser created two accounts and kept a session across reload. |
| Style, currency, capital | LIVE | Aegis + NGN 250000 saved. Apex switch set risk 2.5% without changing NGN or capital. Second account stayed USD 40. |
| Eligibility | LIVE | Apex on fresh BTC with E1 WAIT returned WAIT. Production WAIT_DEFAULT, validated false, broker false. |
| Portfolio honesty | FAIL on live, fixed in source | Live portfolio showed `BTCUSDT SHORT_BIAS` as an experimental paper position. `present_book` now keeps bias rows out of holdings. Not deployed. |
| Telegram / digest | NOT VERIFIED | Worker notification is configured. No authorized per-user chat was used for a delivery test. |
| Broker | DISABLED | `health.broker` is false. |
