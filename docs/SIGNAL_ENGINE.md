# Signal engine and local AI

Not deployed. No source below is a customer display grant.

Completed candles are described as rising or falling, momentum up, down or mixed, and range wide, ordinary or narrow. Those words are not a score. A candle older than two intervals is stale: the price is not shown as current and a `reading_stale` event is stored. A close through a stored stop appends `invalidated` and leaves the original row. After 48 candles the row is marked `expired` the same way. Kraken retries one failed request, then stops. It does not change venue.

## Engine

`ops/signal_engine.py` walks BTCUSDT, ETHUSDT and XAUUSD at 1m, 3m, 15m and 1h independently. A pair with no verified candle capability is stored as `data_unavailable` with no price. That does not blank another pair. History is append-only in `$AUREON_DATA/signals/history.jsonl`. The same identity is stored once. A later state is appended. Research failure, a blocked notification and an AutoPilot rejection do not delete the row.

A confirmed signal is only whatever the existing interval reader returns from completed bars. The engine does not invent a daily signal. `approved` stays false.

## Adapters

| Source | Pairs | Native intervals | 3m | Socket | Customer display |
|---|---|---|---|---|---|
| Kraken public REST OHLC | BTCUSDT is XBT/USDT. ETHUSDT is ETH/USDT. Both quote USDT, not USD. No gold. | 1, 15, 60 minutes. Docs also list 5, 30, 240, 1440, 10080, 21600. | Not native. Derived only from a complete 1m bucket when a grant says `ohlc+derived` and names 1m and 3m. | Only after `candle_display` is verified | Not granted. Public route, no key. Redistribution was not found and was not accepted. |
| Kraken WebSocket v2 `ohlc` | Same public channels | Same minute enum, no 3 | Not native | Not opened | Same unverified licence as REST |
| Kraken downloadable OHLCVT | CSV archives, not the live desk | 1, 5, 15, 60, 240, 720, 1440. Gaps are not zero-filled by Kraken. | Not included | Not downloaded | Archive is not a live reading and is not a display grant |
| Binance Spot REST and WebSocket | BTCUSDT, ETHUSDT | 1m, 3m, 15m, 1h exist | Native on REST | Not opened for customers | Still `commercial_use_unverified`. A rights file cannot verify this source. |
| XAUS | XAUUSD indicative samples | 15m and 1h when the bucket is complete | Not a native exchange candle | Existing path stays gated | Indicative mid is not an executable quote |
| Twelve Data | XAU/USD only | 1m, 15m, 1h | Never native and not derived here | Only after a Twelve Data grant and API key | Unverified until the owner records the grant |

Kraken was probed on 2026-11-06: `AssetPairs` returned `XBTUSDT` (`XBT/USDT`, online) and `ETHUSDT` (`ETH/USDT`, online). No OHLC body was stored.

## Local AI

`ops/ai_provider.py` is the replaceable boundary. Ollama is the first provider, via `ops/ollama.py`. `OLLAMA_MODEL` is unset here, so the model stays offline. No model was downloaded. This sandbox is not the VPS (2 CPUs, about 4 GB RAM, about 2.8 GB available). Qwen 3.5 2B was not installed. A 2B model wants about 8 GB RAM; 4B wants about 16 GB. Context should stay 4096 or 8192, with one inference at a time, bound to loopback. If the VPS is smaller, use a separate host or a 0.8B model, not a second model on this box.

Ask Aureon reads stored observations and the account's paper book. The model cannot approve a strategy, change risk, or open an order. Offline, the stored sentence is returned and the engine keeps running.

## Production

Not executed.
