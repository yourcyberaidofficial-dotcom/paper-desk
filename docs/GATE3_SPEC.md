# Gate 3 hypotheses — frozen before holdout results

Production remains `WAIT_DEFAULT`. Nothing in this file is a promotion.
E1-donchian-20 version `e1-20261016` stays a failed benchmark. It is not re-tuned.
`data/holdout_sealed` is not opened. Parameters below are not a search.

## Data

| Instrument | Decision bars | Regime bars | Provider | Quote |
|---|---|---|---|---|
| BTCUSDT, ETHUSDT | completed 15m | completed 1h, SMA(48) | Binance public klines, no key | last trade OHLC |
| XAUUSD spot | completed 1h | 4h aggregated from those 1h bars, SMA(12) = 48h | xaus.com `/api/v1/chart`, no key | OHLC, not bid/ask |

48 hours is the same regime window on both calendars. Gold uses 1h because the free chart history that has a real open is one year of 1h bars. The 15m gold chart is only about a month, so it is not the research timeframe. Daily `/api/v1/history` has high, low, and close and no open. Open is never copied from close.

Dukascopy tick history is the preferred bid/ask source. If the host is throttled, that adapter returns unavailable and gold cannot be promoted.

A forming bar (`close_time` still in the future, or an unaligned tail print) is dropped. Gaps are not filled. A gold gap that falls entirely inside the Friday 17:00 to Sunday 17:00 New York close is a closed market, not a hole. DST uses `America/New_York`.

## Costs, chosen before any Gate 3 return was calculated

Crypto spot: 11 bps per fill base and 15 bps per fill stress, two fills. This is the existing E-cycle assumption (10 bps taker plus 1 or 5 bps half-spread). Spot candles have no funding. Funding is not zeroed on a perp it was not tested on.

Gold: no bid/ask was measured. Base assumption is 0.50 USD per ounce per side. Stress is 1.50 USD per ounce per side. These are fixed dollar amounts so they do not shrink with price, and they are not a Dukascopy print. A gold result cannot be `PASS` for promotion without measured bid/ask. Numeric failure is still reported as `FAIL`.

Same-bar stop and target: the stop fills. A bar that opens through the stop fills at that open, not at the stop if the open is worse.

## Hypotheses

Shared entry: the next completed bar's open. No signal while a simulated position from that strategy is open. The event id is strategy, symbol, interval, direction, and the confirmation bar's open time. A later bar that merely remains in the same condition is not a new event.

### E1 benchmark

Unchanged `e1_side`. A directional result is `RESEARCH_OBSERVATION` with reason `benchmark_failed`. It is never `PAPER_CANDIDATE` and never `APPROVED_SIGNAL`.

### A. `tf-pullback-20261027`

Long regime when the last completed regime bar's close is above its 48-hour SMA. Short when below. Else no trade.
On the decision bar, SMA(20) of decision closes. At least one of the previous six decision bars must have closed on the wrong side of its own SMA(20). The decision close must cross back through SMA(20) and past the prior close.
Stop: the six-bar swing extreme including the signal bar. Target: entry plus or minus twice the stop distance (reward/risk 2). Time stop: 16 decision bars.
Gold `xau-session-20261027` is this same rule, and the signal bar's open must fall in New York 08:00–16:00. Outside that window the state is `WAIT` / `OUTSIDE_SESSION`.

### B. `vol-break-20261027`

Prior 20 decision bars, excluding the signal bar. Close beyond that channel, and the signal bar's true range is at least the 14-bar true-range average of the bars before it. A break with a smaller true range is `WAIT`, which is the difference from E1.
The previous bar must not already have been the same break. Stop 1.5 times that ATR from entry. Target 3 times that ATR. Time stop 24 decision bars.

### C. `mr-range-20261027`

Disabled unless the last regime bar's close is inside the prior 20 regime-bar range and that regime ATR(14) divided by close is under 0.004. The 0.004 cap is a predeclared quiet-market switch, not a fitted value.
Entry when RSI(14), as implemented in `ops/indicators.py`, crosses to 30 or below, or 70 or above, and the decision close is still inside its own prior 20-bar range. Staying past 30 is not a new event.
Stop is the signal extreme plus or minus half an ATR. Target is SMA(20) if it sits on the profitable side of entry with reward/risk at least 1. Otherwise `WAIT` / `no_mean_target`. Time stop 12 bars, or the first later bar whose RSI has crossed back through 50.

## Splits and gates

After the authentic series is downloaded, cut the decision bars by count, in time order: 60% development, 20% validation, 20% holdout. Record the timestamps and a hash. Development may discard a rule. Validation may select at most one rule per instrument, and only a rule whose validation judgment is `PASS`. The holdout is scored only for that selected rule. If none pass, the holdout is not used to pick a winner.

These gates are not an industry standard:

- At least 30 round trips on the split. Fewer is `BLOCKED`, not a softer pass.
- Base and stress mean net unit return above 0.
- Normal 95% lower bound of the base mean above 0. This is not SPA, White, DSR, or PBO.
- Both halves of that split have a positive base mean when each half has at least 10 trades. A thinner half is `BLOCKED`.
- Compounded unit equity above 1.
- Compounded drawdown at most 25%.
- Longest losing streak at most 12.
- Gold adds: measured bid/ask required for `PASS`. Without it the judgment cannot be `PASS`.

A selected holdout must pass the same gates. Passing research gates still does not set production to anything but `WAIT_DEFAULT` and does not approve Telegram delivery.

## States

`DATA_UNAVAILABLE`, `WAIT`, `RESEARCH_OBSERVATION`, `PAPER_CANDIDATE`, `QUALIFIED_FOR_REVIEW`, `APPROVED_SIGNAL`, `EXPIRED`, `INVALIDATED`.

`APPROVED_SIGNAL` requires an explicit promotion record. The registry ships empty. `PAPER_CANDIDATE` means entry, stop, target, and expiry exist. It is not an order and it does not write `paper_open`.
