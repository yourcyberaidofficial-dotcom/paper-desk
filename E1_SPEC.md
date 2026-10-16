# Experimental pilot E1 — frozen before evaluation

Status: frozen. Not a validated strategy.
Production signal remains WAIT_DEFAULT.
Opt-in only. Default off.

## Rule

Name: E1-donchian-20
Version: e1-20261016
Asset: BTCUSDT, ETHUSDT
Timeframe: closed 15-minute bars
Input: prior 20 completed bars, excluding the decision bar.

Trigger:
- LONG_BIAS if decision close is above the highest high of the prior 20 bars.
- SHORT_BIAS if decision close is below the lowest low of the prior 20 bars.
- WAIT otherwise.

Invalidation: the opposite band.
Entry reference: next bar open. This pilot does not place orders.
Costs for the one evaluation: base 10 bps fee + 1 bps half-spread; stress 10 bps fee + 5 bps half-spread.
No parameter search. No holdout.
