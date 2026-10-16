# G1-H4-r2 diagnostics

Run: G1-H4-r2
Code: a8065afc2d6602db59b422e45002cf57f1868c12
Data SHA-256: 3390d4bd75b006a293b864ea03734c95488950b50304549b0e9dd1927f869a6b
Reproducibility: 18/18 expectancies and trade counts match the persisted results. 0 mismatches.
Holdout: not accessed.
Production: unchanged.

## Diagnostics

Trade-level Sharpe is mean/pstdev of non-overlapping trade returns. It is not annualized.

Top-5 trade share of total net is above 0.8 on every positive cell. Performance is concentrated in a few trades.

## Multiple testing

White's Reality Check on the six base-cost series, 1000 bootstrap resamples of demeaned trade PnL, null of zero mean: p = 0.145. Not significant.

Deflated Sharpe Ratio: inputs recorded for the best series (BTC 120, trade Sharpe 0.141, n=98, skew 0.51, kurtosis 3.46, N=6). Full DSR was not computed. Not a pass.

PBO/CSCV: not computed. Unequal calendars and non-overlapping holds do not form a valid return matrix.

## Decision

No candidate clears the gates. Positive point estimates are not evidence of a robust edge. WAIT_DEFAULT remains production.
