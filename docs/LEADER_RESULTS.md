# Market leaders, scored once on 2026-10-28

Rules were frozen in `ops/leaders.py` before this file was written. The last 20 percent of each series was not simulated. No strategy was approved.

| Market | History | Leader | Result |
|---|---|---|---|
| BTCUSDT | Binance spot 4h, 8,378 bars, 2023-01-01 through the download | compress-break-4h-20261028 | FAIL, median fold mean about -0.00187. Buy-and-hold over the same prefix was largely positive. |
| ETHUSDT | Binance spot 4h, 8,378 bars, same start | sweep-reclaim-4h-20261028 | FAIL, median fold mean about -0.00206. |
| XAUUSD | Dukascopy bid and ask hours, 717 bars, 2024-06-03 to 2024-07-12 | none | BLOCKED, 6 trades. The live chart feed does not run this rule. |

Costs: crypto 11 bps per fill, 15 bps in stress. Gold buys the ask and sells the bid, plus 0.10 USD per side, 0.30 in stress. Spot shorts were not simulated.
