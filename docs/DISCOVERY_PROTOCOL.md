# Frozen protocol, trend-hold-4h-20261103

This protocol is the `protocol()` value in `ops/discovery.py`. Parameters were not changed after the result was scored.

Hypothesis. A slow long-only 4h trend hold may survive 22 bps of round-turn cost where faster positive-gross rules did not. BTC sweep-reclaim and compression-breakout had positive gross sums that costs erased or nearly erased. This rule enters less often and plans a larger move. It is a follow-up, not a fresh claim.

Entry. On a completed 4h bar, close is above the prior 60 highs and above the 120-bar simple average. The fill is the next bar open. The signal bar is not the fill.

Invalidation. 3 times the prior 14-bar ATR below the entry. No trade if ATR is missing or the reward would not exceed the risk.

Exit. 6 ATR target, the stop, or 42 bars, whichever the existing simulator reaches first.

Split. Chronological 60/20/20 by bar count, same helper as Gate 3. No shuffle.

Purging and embargo. Development is simulated on development bars only. Validation trades are those whose signal bar opens in validation. Signals inside the first 42 4h bars of validation are embargoed.

Holdout. Open a symbol's final 20 percent only if judge() returns PASS on that symbol's purged validation window. Otherwise record NOT_OPENED. Do not use the holdout to pick a parameter.

Approval. A PASS is not paper approval. This version is a follow-up after the recorded families below, 4h is not a desk coverage timeframe, and no forward paper sample exists. promoted stays false.

Costs. Research uses the existing simulator cost once. The paper book's separate 2 bps candle-exit slippage is not added on top. Neither figure is a measured exchange fee. Base 11 bps per fill, stress 15 bps per fill, 2 fills.

Gates are the existing `GATES` values: minimum 30 trades, 10 in each half, max drawdown 0.25, max loss streak 12, positive base and stress means, normal 95 percent lower bound above zero, equity above 1. Gold still requires measured bid/ask. This study does not score gold.

Prior recorded families, which make this a follow-up rather than an independent test:

- E1-donchian-20
- tf-pullback-20261027
- vol-break-20261027
- mr-range-20261027
- xau-session-20261027
- spot-tsmom-1h-20261028
- tight-range-long-1h-20261028
- sweep-reclaim-4h-20261028
- compress-break-4h-20261028
- london-reclaim-1h-20261028
- dip-in-trend-1d-20261028
- quiet-week-reversal-1d-20261028
- fail-break-20261028
- quiet-expand-20261028
- hour-close-drive-20261028
- xau-london-range-20261028
- xau-session-day-20261028
- xau-climax-fade-20261028
