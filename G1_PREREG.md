# G1 preregistration — development only

Status: registered, not run.
Holdout: sealed. G0 holdout at data/holdout_sealed is inaccessible to this generation.
Production: WAIT_DEFAULT remains active. Nothing here is an approved signal.

## Why this generation exists

G0 tested H1 trend continuation, H2 volatility expansion, and H3 range fade on BTCUSDT and ETHUSDT. All three failed development. The registry recorded only the selected H1 lookback, so G0 is a protocol-defective historical result. It is immutable.

G1 does not reuse those rules. It tests two independent economic hypotheses.

## Hypotheses

### G1-H4 — volatility-scaled time-series momentum

Claim: the sign of the trailing excess return, scaled by trailing realized volatility, predicts the next holding period in the same direction for BTC, ETH, and gold observation bars.

Pre-registered variants, each a separate experiment:

- lookback: 20, 60, 120 bars
- holding period: equal to lookback
- markets: BTCUSDT 4h, ETHUSDT 4h, gold observation 4h if a defensible series exists
- cost paths: optimistic, base, stress (same economic model as G0)
- benchmark: no-trade and buy-and-hold

Falsifier: net expectancy under base costs is not positive after SPA/White, or the edge is concentrated in one regime or fewer than 30 trades.

### G1-H5 — funding extreme as a separate carry track

Claim: extreme perpetual funding predicts the opposite next-24h spot return. This is not a price-only trend rule.

Pre-registered variants:

- thresholds: 0.01% and 0.03% funding, separate experiments
- markets: BTCUSDT, ETHUSDT only
- blocked unless a historical funding series is collected and versioned

Falsifier: direction is wrong after costs, or the result depends on a few funding spikes.

### Gold

Gold is observation/research only. No gold paper order is permitted. G1-H4 on gold is blocked until a single instrument series (spot or futures, not mixed) is stored and documented.

## Splits

- Development only.
- Walk-forward inside development.
- Embargo of one holding period between train and test.
- G0 holdout is not a G1 partition and is not read.

## Promotion gates

A candidate is not production until all of these are true:

1. Pre-registered.
2. Net expectancy positive on base and stress cost paths.
3. At least 30 trades.
4. SPA or White does not reject the candidate at the pre-registered threshold.
5. Not concentrated in one year or one regime.
6. Holdout remains sealed until a later authorized generation.

Until then, production remains WAIT_DEFAULT.
