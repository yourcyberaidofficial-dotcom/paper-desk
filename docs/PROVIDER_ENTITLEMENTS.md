# Provider entitlements

Reviewed 2026-11-03. A public URL is not a licence. Nothing below is `verified` except an account-typed plan, which is not a market-data source. `DESK_LIVE` is not a permission.

## Capability matrix

States: `verified`, `unverified`, `restricted`, `unavailable`. An unverified capability is not approved. Operational observation means the desk may still render that reading. It does not permit retention.

| Source | Quote | Native candle | Sampled reference | Indicators | Customer reading | Opportunity | Manual review of feed levels | Paper ledger | Raw retention | Research | Notifications | AutoPilot |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Binance Spot REST klines | Unavailable | Unverified observation | Unavailable | Unverified observation | Unverified observation | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| Binance Vision archives | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted |
| XAUS `/intraday` samples | Unavailable | Unavailable | Unverified observation | Unverified observation | Unverified observation | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| XAUS `/chart` | Unavailable | Unverified observation | Unverified observation | Unverified observation | Unverified observation | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| Swissquote public BBO | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted | Restricted |
| Dukascopy bi5 | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified | Unverified |
| Account-typed levels | Not a feed | Not a feed | Not a feed | Not a feed | Not a feed | Not a feed | The account's own plan | Allowed for those typed levels only | Not a feed | Not a feed | Not a feed | Still requires an approved strategy version |

Gold 1-minute and 3-minute are `unavailable` on every source. Missing five-minute prints are not reconstructed.

## Adapter contract

`ops/provider_adapter.py` describes a future source without changing the Daily Desk:

- `source_id`, instruments, exact timeframes
- `candle_semantics` separate from `quote_semantics`
- source timestamps, freshness, completeness
- `capabilities` taken from `decide_use`, never from a successful HTTP call
- `failure_mode` and the preserved 0.08 percent quote threshold

The current gold reference adapter supplies nothing. Its failure mode is `reference_quote_unavailable`. No vendor socket is opened.

## Paper retention

Feed-derived entry, stop, target, and reference close are not written to the inbox, the paper book, or terminal history. Review may keep a compact eligibility row: snapshot id, symbol, interval, side, and `levels_persisted: false`. The prices can remain on the current screen. They are not copied into another JSON file.

An account may type different entry, stop, and target. Those rows are marked `source_id: user_authored` and `provenance: user_authored`. Copying the feed's three levels is refused as `feed_copy`. Existing paper files are not rewritten. XAUUSD quantity stays `contract_unverified`.

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

XAUS documents an indicative series and asks commercial users to make contact: [https://github.com/misix-git/xaus-api](https://github.com/misix-git/xaus-api). That is not a signed grant. Swissquote remains closed under the January 2024 Market Data Access Terms unless the owner obtains an agreement that allows this product.

## Owner questions still open

1. Which vendor, instrument, and timeframe is approved for customer display?
2. Does that grant cover derived readings, or only raw display?
3. Does it cover local retention of prices inside a paper ledger?
4. Are notifications and AutoPilot named uses, or excluded?
5. Is any gold source a tradable bid/ask, or only an indicative print?
6. Who signs, and what is the review date?
