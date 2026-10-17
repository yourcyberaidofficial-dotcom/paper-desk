# E3/E4 preregistration

Timestamp: 2026-10-17, before any E3/E4 results.
Cycle: one bounded generation. No parameter search.

## Ruled out
G0 H1 trend continuation, G0 H2 volatility expansion, G0 H3 range fade, G1-H4 volatility-scaled TSMOM, E1 Donchian-20, E2 SMA-20 cross.
Do not retune them.

## E3 relative value
Rationale: BTC and ETH are correlated. Extreme relative pricing may revert. Long-only, so no funding model is required.
Signal: 96-bar z-score of ETH close / BTC close.
Long BTC when z > 1.5. Long ETH when z < -1.5. Cash otherwise.
Entry: next bar open. Exit when z crosses 0, or after 96 bars.
Size: 1 unit return. One position at a time.
Costs: base 10 bps fee + 1 bps half-spread per fill. Stress 10 + 5.
Reject if base or stress expectancy is not positive, or profit factor is not above 1.

## E4 spike fade
Rationale: a very large down 15-minute move may overshoot and partially revert. Long-only.
Signal: 15-minute return below -2 times the prior 20-bar ATR.
Entry: next open. Exit after 8 bars, or when close recovers to the entry price.
Size: 1 unit return.
Same costs.
Reject if base or stress expectancy is not positive, or profit factor is not above 1.

## Data
Existing two-year Binance 15-minute BTCUSDT and ETHUSDT development set.
No holdout. No new strategy if both fail.
