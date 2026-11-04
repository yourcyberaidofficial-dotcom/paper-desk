# Provider entitlements

Reviewed 2026-11-03. A public URL is not a licence. Nothing below is `verified` except an account-typed plan, which is not a market-data source. `DESK_LIVE` is not a permission.

## Customer responses

The registry still allows an internal calculation so a typed plan can be refused when it copies the feed. That calculation is not a customer grant.

Until the exact capability is `verified` for that instrument, timeframe and operation, customer HTTP responses omit provider prices, OHLC, sampled references, indicator values, direction calls, setups, entry/stop/target, and feed opportunity payloads. A stale cache is not returned as a current reading. No number is invented in its place. Research records, system status and diagnostics may keep technical status. They do not receive the price. Historical paper files are not rewritten.

One verified capability does not release the others. Candle display for one pair does not release another pair, a derived reading, retention, notifications, or AutoPilot.

## Capability matrix

States: `verified`, `unverified`, `restricted`, `unavailable`. An unverified capability is not approved. Operational observation means an internal calculation may still run. It does not permit a customer response or retention.

| Source | Quote | Native candle | Sampled reference | Indicators | Customer reading | Opportunity | Manual review of feed levels | Paper ledger | Raw retention | Research | Notifications | AutoPilot |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Binance Spot REST klines | Unavailable | Unverified | Unavailable | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| Binance Vision archives | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted |
| XAUS `/intraday` samples | Unavailable | Unavailable | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| XAUS `/chart` | Unavailable | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| Swissquote public BBO | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted |
| Dukascopy bi5 | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| Twelve Data time_series, XAU/USD only | Unavailable. `/quote` returns an OHLC-style last price, not bid and ask | Not verified. Native 1m, 15m and 1h exist. 3m does not. Stays unverified until the owner records a grant | Not this source | Unverified until a derived grant | Unverified until a derived grant | Unverified until a derived grant | Unverified until a derived grant | Unverified until a derived grant names retention | Unverified | Unverified | Unverified | Unverified. AutoPilot still needs an approved strategy version |
| Account-typed levels | Not a feed | Not a feed | Not a feed | Not a feed | Not a feed | Not a feed | The account's own plan | Allowed for those typed levels only | Not a feed | Not a feed | Not a feed | Still requires an approved strategy version |

Gold 3-minute is `unavailable` on every source. Twelve Data documents 1min, 5min, 15min, 30min, 45min, 1h, 2h, 4h, 8h, 1day, 1week and 1month. It does not document 3min. A 3-minute bar is not built from 1-minute or 5-minute rows. Gold 1-minute stays unavailable until a recorded Twelve Data grant names XAU/USD 1m. Missing five-minute prints are not reconstructed.

## Twelve Data, reviewed 2026-11-04

No API key was created, no account was opened, and no terms were accepted. The public catalog was read without a key.

- `symbol_search` for `BTC/USDT` and `ETH/USDT` returned count 0. `BTC/USD` and `ETH/USD` are listed on Coinbase Pro, Binance and Bitfinex as US Dollar markets. Those are different pairs from BTCUSDT and ETHUSDT and are not used.
- `commodities?symbol=XAU/USD` returned one row: Gold Spot / US Dollar, exchange COMMODITY. That is the only Twelve Data instrument wired for this desk.
- `/time_series` intervals include `1min`, `15min` and `1h`. There is no `3min`.
- `/quote` returns an OHLC-style close. It does not supply bid and ask, so the 0.08 percent quote threshold stays unused.
- A request without an API key returned HTTP 401. The key is not permission.
- Public terms (https://twelvedata.com/terms) allow internal non-display use by default. External display and redistribution require a Redistribution Rights Add-On or a separate written agreement. The free tier is not a commercial grant. The public pricing pages disagree with each other (Venture has been listed at both $149/month and $499/month). Neither page is a signed grant, so neither price is treated as the contract cost.

The adapter is `ops/twelve_data.py`. It fetches only after `candle_display` is verified for XAUUSD at 1m, 15m or 1h, and only when `TWELVE_DATA_API_KEY` is set in the server environment. A failed authorised read is not replaced with XAUS or with any other source. BTCUSDT and ETHUSDT are refused before a socket is opened. Customer responses still withhold numbers until the matching capability is verified. A `time_series` grant can release candles only. Derived readings, paper retention, notifications and AutoPilot each require `time_series+derived` and that capability by name.

### The one owner action still required

Sign the Twelve Data redistribution or external-display add-on that names XAU/USD, the intervals 1min, 15min and 1h, derived use if readings or paper levels will be stored, and the retention term. Then place `TWELVE_DATA_API_KEY` in the server environment, not in git, and write `$AUREON_DATA/rights/twelve_data.json` with `provider` exactly `Twelve Data` plus `product`, `instruments`, `timeframes`, `capabilities`, `terms_version`, `clause`, `verified_by`, `verified_on`, `review_due` and `redistribution`. Until that file validates, the adapter stays off and customer gold stays withheld. BTCUSDT and ETHUSDT still need a source whose catalog lists those exact pairs and whose licence allows this desk to display them. Binance spot REST has the pairs. It does not have that licence here.

## Adapter contract

`ops/provider_adapter.py` describes a future source without changing the Daily Desk:

- `source_id`, instruments, exact timeframes
- `candle_semantics` separate from `quote_semantics`
- source timestamps, freshness, completeness
- `capabilities` taken from `decide_use`, never from a successful HTTP call
- `failure_mode` and the preserved 0.08 percent quote threshold

The current gold reference adapter supplies nothing. Its failure mode is `reference_quote_unavailable`. No vendor socket is opened. Installing a later source means marking the exact capability `verified` after a written grant. The desk pages already render a reading only when that check passes.

## Paper retention

Feed-derived entry, stop, target, and reference close are not written to new inbox, paper, or terminal rows. An unauthored review no longer stores an eligibility row and does not echo the feed numbers. An account may type different entry, stop and target. Those rows are `source_id: user_authored` and `provenance: user_authored`. The anchor is a hash of the typed levels, not the feed candle. Copying the feed's three levels is refused as `feed_copy` without returning those numbers. Existing paper files are not rewritten. XAUUSD quantity stays `contract_unverified`.

## Official-source comparison

No account was opened, no trial was started, and no terms were accepted. "Unclear" means the public page does not settle that use. None of these sources is `verified`.

| Question | Binance Spot REST | Binance Vision | XAUS | Swissquote public BBO | Other candidates |
|---|---|---|---|---|---|
| Customer display | Unclear. The spot API is public. The product-terms file is a pointer, not a display schedule read as a grant for this desk. | Not granted. Dataset terms, last updated 26 Aug 2026, are CC BY-NC-SA 4.0 and say commercial licensing is excluded unless Binance signs a separate enterprise agreement. | Unclear. The public README describes an indicative series. It does not record a signed display grant for a multi-user product. | Not granted. Market Data Access Terms v3.0 (01/2024) say the client will not display or distribute market data outside the API client service or white-label platform. | Not integrated. Databento, Kaiko, CoinAPI, LSEG and CME DataMine publish product pages only. No schedule was accepted. |
| Derived readings | Unclear on the spot REST terms read here. | Not granted for compensated signal distribution. The same terms exclude signal distribution for compensation and commercial financial products. | Unclear. No clause read here authorises customer-facing indicators. | Not granted. The same clause forbids using the data to create an index or a financial, derivative, investment product or strategy based on the values. | Unclear until a contract names derived use. |
| Customer redistribution | Unclear. | Non-commercial redistribution only, and the derivative stays under CC BY-NC-SA 4.0. | Unclear. Attribution is mentioned. Redistribution to desk customers is not granted. | Not granted. Access is not to be given to any other person. | Personal plans at other vendors commonly exclude redistribution. Not treated as permission. |
| Retention of market data | Unclear. | The non-commercial archive may be kept for the permitted non-commercial uses. That is not a commercial retention grant. | Unclear. | Not granted by the public BBO page. | Unclear. |
| Retention of derived paper levels | Unclear, and not inferred from display. | Not granted. A paper history of derived levels in a customer product is a commercial use. | Unclear. | Not granted. Creating a strategy from the values is forbidden. | Unclear. |
| API access | Public REST klines exist for BTCUSDT and ETHUSDT. Reachability is not approval. | Archive files, not a live customer quote. | Public HTTP chart and intraday routes. No key is required. That is not approval. | A public BBO URL exists. The application does not call it. | Not connected. |
| Timeframes and instruments | Spot klines include 1m, 3m, 15m and 1h for BTCUSDT and ETHUSDT. No XAUUSD. | Historical spot klines. Not the live desk. | XAU/USD indicative series. Intraday samples are not 1-minute or 3-minute exchange candles. | A gold BBO was the old reference. It is not a candle source. | Must be named per instrument before use. |
| Gold bid/ask | Not supplied. | Not supplied. | README: spot prices are indicative mid-market rates, not tradable quotes. | BBO exists only under the terms above. It is not authorised here. | CME DataMine is history, not a retail spot quote, until a contract says otherwise. |
| Price and contract | No paid contract is in force. | Commercial use needs a separate written enterprise licence. Price was not requested. | No contract is in force. | The January 2024 terms apply to bank clients. This product is not that client. | No price was requested and no trial was started. |

## Candidate sources

Not integrated. No trial, signup, or terms acceptance.

| Candidate | What to read | Not yet granted |
|---|---|---|
| Binance market-data licence, distinct from Vision | [Spot product terms pointer](https://github.com/binance/binance-spot-api-docs/blob/master/PROD-TERMS-OF-USE.md) and [Vision Dataset Terms](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md) | Commercial display, derived readings, customer distribution, retention |
| Databento | [https://databento.com/docs](https://databento.com/docs) | A written display and redistribution schedule for the exact schemas |
| Kaiko | [https://www.kaiko.com/products/market-data](https://www.kaiko.com/products/market-data) | Customer-facing derived readings and retention |
| CoinAPI | [https://www.coinapi.io/products/market-data-api](https://www.coinapi.io/products/market-data-api) | Commercial redistribution beyond their published plan |
| LSEG / Refinitiv | [https://www.lseg.com/en/data-analytics](https://www.lseg.com/en/data-analytics) | Display, non-display, and derived-use schedules |
| CME DataMine, for gold history rather than a retail spot quote | [https://www.cmegroup.com/market-data/datamine-historical-data.html](https://www.cmegroup.com/market-data/datamine-historical-data.html) | Redistribution and customer-facing derived levels |

XAUS documents an indicative series: [https://github.com/misix-git/xaus-api](https://github.com/misix-git/xaus-api). That is not a signed grant. Swissquote remains closed under the January 2024 Market Data Access Terms unless the owner obtains an agreement that allows this product: [v3.0, 01/2024](https://links.imagerelay.com/cdn/2958/ql/market-data-access-en).

## Owner questions still open

1. Which vendor, instrument, and timeframe is approved for customer display?
2. Does that grant cover derived readings, or only raw display?
3. Does it cover local retention of prices inside a paper ledger?
4. Are notifications and AutoPilot named uses, or excluded?
5. Is any gold source a tradable bid/ask, or only an indicative print?
6. Who signs, and what is the review date?
