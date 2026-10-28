# Gate 5 statistical audit

This file does not change Gate 3 or Gate 4 judgments and does not open `data/holdout_sealed`.
The frozen scores in `docs/GATE4_RESULTS.json` stay as recorded at `9cff49d`.
No Bonferroni, SPA, White, DSR, or PBO procedure was run in this audit.

## Confirmed defects

The field `normal_95_lower` is not a valid 95% confidence interval for these trades.
`ops/simulate.py` uses the normal interval for an independent sample, `mean - 1.96 * s / sqrt(n)`.
Gate 4 trades overlap in calendar time because a strategy holds a position for up to 16 bars and the next entry waits for the exit. That is serial dependence. The formula ignores it, so the interval is too narrow if nearby trades move together.

Two recorded rows use that bound as their only failure while the sample mean is positive:

- `xau-session-day-20261028` development on measured Dukascopy bars: mean about +0.00159, judgment FAIL, failed `["uncertainty"]`.
- The non-selectable Gate 3 replay `vol-break-20261027` XAUUSD validation: mean about +0.00113, judgment FAIL, failed `["uncertainty"]`.

Those two uncertainty rejections are invalid as evidence that the mean is below zero. They are also not evidence that the mean is above zero. Neither row is a PASS. The historical JSON was not rewritten, and the same sample was not reused for a new rule.

No PASS in Gate 4 depended on this interval. Every crypto FAIL also failed the mean, the stress mean, drawdown, or a half. Those reasons do not use the interval.

## Limitations, not silent passes

Nine validation tests were scored with no multiple-testing adjustment. That can inflate a pass. It cannot manufacture the result that nothing passed. The "none qualified" conclusion is harsher, not softer, than an adjusted test.

`halves` splits one sample at the midpoint of entry timestamps. The two halves do not overlap. They are not independent samples, and they are not a second trial. No rolling window was used as a gate. A position opened near the end of development can still be open at the start of validation because the simulator allows one position at a time, so the windows are operationally coupled. That is dependence, not look-ahead: the holdout bars were not passed into the validation simulation.

Gold costs match the frozen spec. The spread is the bid/ask print. Extra slippage is the stated 0.10 / 0.30 USD assumption, not a measured print. The old 0.50 / 1.50 path is labeled and cannot pass. Stops are checked before targets. A long pays the ask and exits on the bid. A short does the reverse. The unit equity path does not apply the Awuru 2.5% / 1.5% / 0.8% caps. Those caps were not changed. Weekly closes are gaps, not filled hours. Saturday 2026-10-24 remained a missing file, not a synthetic bar.

`xau-london-range-20261028` validation still has 24 trades. The frozen rule blocks a sample under 30 before it looks at the mean. Its normal lower bound is also below zero, but that bound is the defective interval above, so it is not extra proof. The row stays BLOCKED. The holdout stays closed.

## Acceptable as frozen evidence

The rules and thresholds were committed at `703aa08` before the score commit `9cff49d`. E1 was not retuned. Crypto Gate 3 hashes and judgment rows were reproduced before Gate 4 scoring. The xaus.com hash mismatch was reported and the old file was left in place.

Promotion still requires a later, separate review. This audit does not qualify any candidate.

## New research

A new backtest is not justified. Any new rule fitted on this same window would reuse a sample that has already been inspected, including the 24-trade London-range row. No Deflated Sharpe, PBO, or other selection test was implemented. The prospective record in `ops/shadow.py` only stores observations. It is not a score and it cannot promote.
