# Strategy qualification

`ops.qualification` reads `ops.registry` and assigns a lifecycle. It does not rerun a backtest and it does not change a stored result.

| Recorded status | Lifecycle |
| --- | --- |
| FAIL | backtest_failed |
| BLOCKED, including a sample that is too small | insufficient_data |

`approved_for_paper` stays 0. Paper approval would not be broker approval. A rule change would require a new version and a new record; this release has no approval to invalidate.

Costs stated on every record are the existing paper assumptions: 11 basis points per side, and 2 basis points of adverse slippage on a candle-estimated exit. They are assumptions, not measured exchange fees.

AutoPilot calls `autopilot_may_open`. A result with `approved: true` is still refused unless that exact registry version is `approved_for_paper`. None is. Manual paper orders are unchanged and remain explicit account actions.

The evidence chain on a terminal response names the source, candle, rule version, trigger, invalidation, validation and decision. `calibrated_probability` is always null.
