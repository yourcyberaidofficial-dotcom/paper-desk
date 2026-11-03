# Market-data rights register

Reviewed 2026-11-03. No vendor was contacted for a new contract, and no dataset was purchased or downloaded for this review. Public access was not treated as permission.

No use below is approved. A later approval must name the provider, product, data type, permitted purpose, terms version, clause, verifier, verification date and review date. Approval of one use does not approve the others. Missing, expired or unevidenced approval stays closed.

| Source | Status | Connection | Display | Retention | Research | Indicators | Strategy | Notification | AutoPilot | Redistribution |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Binance Vision kline archives | Prohibited | Prohibited | Prohibited | Prohibited | Prohibited | Prohibited | Prohibited | Prohibited | Prohibited | Prohibited |
| Binance Spot public REST klines | Rights not confirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed |
| Dukascopy bi5 spot samples | Rights not confirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed |
| XAUS public chart and spot | Rights not confirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed |
| Swissquote public BBO quote | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted |
| Deterministic fixtures | Fixture only | Not market evidence | Not market evidence | Not market evidence | Not market evidence | Not market evidence | Not market evidence | Not market evidence | Not market evidence | Not market evidence |

Binance Vision Dataset Terms 1.0, dated 26 August 2026, licence the archives under CC BY-NC-SA 4.0. Section 3.4 requires a separate written enterprise licence for commercial use. Section 4.4 prohibits use in a commercial financial product or commercial trading-bot platform. The MIT notice on the software repository does not licence the datasets.

The Spot API product-terms file only points to the general Binance Product Terms. That page did not return the terms during this review. No written grant to request, retain, derive, display or automate from the klines inside Aureon was found. There is no WebSocket client, and opening one is refused while connection rights are unconfirmed.

Dukascopy's XML data licence is non-commercial, requires registration approval, and does not mention the bi5 history files Aureon already knows how to read. Swissquote's Market Data Access Terms v3.0 (January 2024) forbid a client from redistributing market data or using it to build an investment strategy. Aureon has no Swissquote agreement. The public BBO URL is not requested. The 0.08 percent comparison remains for a future authorised independent quote and is not treated as passed while that quote is absent. No written licence for the XAUS chart or spot endpoints was on file. Unverified observation is not approval to retain provider-derived prices.

Gold 1-minute and 3-minute data remain unlicensed. Five-minute samples are not split into those timeframes.

The existing BTCUSDT and ETHUSDT 4-hour files are recorded as `binance-public` in `docs/DATA_AUDIT.json`. That label does not prove a Binance Vision archive and it is not a written commercial licence, so they are `rights_unconfirmed`. They stay on disk, unread by the commercial research path, and the final 20 percent from 2026-01-22 stays sealed. The same quarantine applies to the retained XAUUSD 1-hour file. Owner or legal review is required before deletion or continued retention. No new strategy result was produced from them.

Live REST, chart, quote and cache paths now withhold data instead of describing the block as an outage. The desk says: "Market data access unavailable — commercial use permissions are being verified."

Collection of a real desk-timeframe archive stays switched off until a source in `ops/data_rights.py` is marked approved against written evidence for that exact use.
