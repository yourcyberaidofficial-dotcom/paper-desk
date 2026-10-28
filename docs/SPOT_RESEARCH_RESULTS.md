# Spot research, 2026-10-28

Data: Binance spot 1-hour klines, about 400 days, completed bars only. Costs: 11 bps per fill base, 15 bps stress, two fills. No funding. Short sales were not simulated. The last 20 percent of each series was not scored.

| Market | Rule | Trades | Mean net | Judgment |
|---|---|---|---|---|
| BTCUSDT | spot-tsmom-1h-20261028 | 417 | -0.00199 | FAIL |
| BTCUSDT | tight-range-long-1h-20261028 | 45 | -0.00221 | FAIL |
| ETHUSDT | spot-tsmom-1h-20261028 | 420 | -0.00268 | FAIL |
| ETHUSDT | tight-range-long-1h-20261028 | 9 | -0.00078 | BLOCKED, sample |
| XAUUSD | not run | — | — | BLOCKED, no measured bid/ask |

No strategy was approved. The holdout stays sealed. Full rows are in `docs/SPOT_RESEARCH_RESULTS.json`.
