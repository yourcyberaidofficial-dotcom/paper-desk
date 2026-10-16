# G1-H4 correction record

Run: G1-H4-pass1
Status: invalidated
Preserved at: data/generations/G1/invalidated_pass1/
New run id: G1-H4-r2

## Defects

1. Volatility scaling was not implemented. PnL was raw price difference.
2. Stress used an extra execution bar. That changed the trade set, so higher cost could produce higher PnL.

## Remediation

- Same signal timestamps and same entry/exit bars for optimistic, base, and stress.
- Costs differ only in fee and half-spread.
- Volatility is the standard deviation of trailing lookback returns, computed from bars strictly before the decision close.
- Size is 1 / volatility, clipped to existing sleeve risk. Zero or non-finite volatility skips the trade.
- No future bar enters the signal, the volatility estimate, or the fill.

Preregistration text is unchanged. This is a corrected implementation of the existing claim, not a new hypothesis.
