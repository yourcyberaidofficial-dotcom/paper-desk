# Market-data rights register

Reviewed 2026-11-03. No vendor was contacted for a new contract, and no dataset was purchased or downloaded for this review. Public access was not treated as permission.

| Source | Status | Commercial research retention |
| --- | --- | --- |
| Binance Vision kline archives | Prohibited | No |
| Binance Spot public REST klines | Rights not confirmed | No |
| Dukascopy bi5 spot samples | Rights not confirmed | No |
| Swissquote public BBO quote | Restricted | No |
| Deterministic fixtures | Fixture only | No |

Binance Vision Dataset Terms 1.0, dated 26 August 2026, licence the archives under CC BY-NC-SA 4.0. Section 3.4 requires a separate written enterprise licence for commercial use. Section 4.4 prohibits use in a commercial financial product or commercial trading-bot platform. The MIT notice on the software repository does not licence the datasets.

The Spot API product-terms file only points to the general Binance Product Terms. That page did not return the terms during this review. No written grant to retain, derive, or display the klines inside Aureon was found.

Dukascopy's XML data licence is non-commercial, requires registration approval, and does not mention the bi5 history files Aureon already knows how to read. Swissquote's Market Data Access Terms v3.0 (January 2024) forbid a client from redistributing market data or using it to build an investment strategy. Aureon has no Swissquote agreement. The 0.08 percent quote-divergence check is unchanged and is not a research archive.

Gold 1-minute and 3-minute data remain unlicensed. Five-minute samples are not split into those timeframes.

The existing BTCUSDT and ETHUSDT 4-hour files were not opened. Their final 20 percent, from 2026-01-22, stays sealed. No strategy was promoted.

Collection of a real desk-timeframe archive stays switched off until a source in `ops/data_rights.py` is marked approved against a written licence.
