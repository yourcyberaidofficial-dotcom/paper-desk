# G1-H4-r2 robustness audit

Run: G1-H4-r2
Commit under audit: 0962014b60c6e813ac177496180030966847ae67
Data SHA-256: 3390d4bd75b006a293b864ea03734c95488950b50304549b0e9dd1927f869a6b
Invalidated pass 1: preserved, 20 files.
Reproducibility: 18/18, 0 mismatches.
Holdout: not accessed.
Production: unchanged.

## Concentration

Removing the five largest winning trades is a diagnostic, not a selection rule.

| Asset | Lookback | Base expectancy | After drop-5 | Top-5 share |
|---|---:|---:|---:|---:|
| BTC | 20 | 0.000039 | −0.000003 | 1.08 |
| BTC | 60 | 0.000119 | −0.000037 | 1.30 |
| BTC | 120 | 0.000456 | 0.000067 | 0.86 |
| ETH | 20 | −0.000022 | −0.000075 | n/a (loss) |
| ETH | 60 | 0.000070 | −0.000143 | 2.98 |
| ETH | 120 | 0.000569 | −0.000104 | 1.17 |

Only BTC 120 stays positive after the diagnostic. All positive cells are concentrated.

## White's Reality Check

Method: six base-cost series, demeaned trade-PnL bootstrap, null of zero mean, statistic is the max mean.
Seed: 20261006.
B=1000: p=0.145 (SE 0.011). Matches the prior report.
B=5000: p=0.1456 (SE 0.005). Stable.

## Not computed

Deflated Sharpe: full formula not applied. Trade-level Sharpe, dependent trials, and non-bar sampling do not meet the standard assumptions. Not a pass.
PBO/CSCV: not computed. No synchronized return matrix.

## Gates

| Gate | Result |
|---|---|
| Pre-registered | PASS |
| Positive base and stress expectancy | FAIL for ETH 20; others positive but concentrated |
| At least 30 trades | PASS |
| White / SPA does not reject | FAIL (p=0.145) |
| Not concentrated in a few trades | FAIL |
| Holdout remains sealed | PASS |

## Decision

NO PROMOTION. Validation stage closed for this trial set. WAIT_DEFAULT remains production.
