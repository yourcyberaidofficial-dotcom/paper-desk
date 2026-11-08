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
