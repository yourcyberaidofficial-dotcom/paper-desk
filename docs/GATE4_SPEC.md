# Gate 4 hypotheses — frozen before this round is scored

Production remains `WAIT_DEFAULT`. Nothing in this file is a promotion.
Base is `gate3-signal-engine` at `3d58cfd`, which contains PR #78 `3993c08` and PR #79 `a995294`.
E1-donchian-20 version `e1-20261016` stays a failed benchmark. It is not re-tuned.
Gate 3 families are replayed for comparison and cannot be selected. Their recorded FAIL and BLOCKED rows in `docs/GATE3_RESULTS.md` are not reclassified.
`data/holdout_sealed` is not opened. The 60/20/20 chronological split below is the only holdout, and it is scored only after a new candidate's validation judgment is `PASS`.

## Data

| Instrument | Decision bars | Regime bars | Provider | Quote |
|---|---|---|---|---|
| BTCUSDT, ETHUSDT | completed 15m, the Gate 3 window | completed 1h, SMA(48) | Binance public klines, no key | last trade OHLC |
| XAUUSD | completed 1h | 4h aggregated from those 1h bars, SMA(12) | Dukascopy public datafeed, no key | separate bid and ask |

Dukascopy instrument is their `XAUUSD` quote, point scale 1000. URL template:

`https://datafeed.dukascopy.com/datafeed/XAUUSD/{year}/{month0}/{day}/{BID|ASK}_candles_min_1.bi5`

Month is zero-based. Each file is one UTC day of 1-minute candles. The record is big-endian `uint32` seconds from UTC midnight, open, close, low, high, then `float32` volume. Open is the file's open, never a copy of close.

An hour is built only when both sides have all 60 minute slots, none duplicated, none crossed (ask open or ask close below the bid), and none invalid. Missing minutes are not filled. Weekly hours outside Sunday 17:00 to Friday 17:00 New York are market closure, not holes. These Dukascopy files are historical. They do not satisfy a live bid/ask feed. `xaus.com` spot remains an indicative mid, not a bid or ask. The requester-pays S3 export was not used.

A long entry pays the ask open and a long exit is marked on the bid. A short entry receives the bid open and a short exit is marked on the ask. Same-bar stop and target: the stop fills. A bar that opens through the stop fills at that side's open when the open is worse.

## Costs, chosen before any Gate 4 return was calculated

Crypto: unchanged Gate 3 costs, 11 bps per fill base and 15 bps per fill stress, two fills.

Gold measured path: the spread is the difference between the bid and ask prints. Extra adverse slippage, which is an assumption and not a measured print, is 0.10 USD per ounce per fill base and 0.30 USD per ounce per fill stress, two fills. The old 0.50 / 1.50 USD per side assumption is kept only as a labeled comparison. It is not called a measured cost, and a comparison that uses it cannot be `PASS`.

## Unchanged gates

At least 30 round trips. Base and stress mean net unit return above 0. Normal 95% lower bound of the base mean above 0. This bound is not Bonferroni, SPA, White, DSR, or PBO, and it treats trades as independent. Both halves of the split need a positive base mean when each half has at least 10 trades. Compounded unit equity above 1. Compounded drawdown at most 25%. Longest losing streak at most 12. Fewer than 30 trades, or a half with fewer than 10, is `BLOCKED`.

This round scores three new crypto rules on two symbols and three new gold rules. That is nine validation tests. No multiple-testing adjustment is applied to the gate. Serial dependence is not removed. A pass would be a request for a separate review, not approval, and would not mean overfitting was ruled out.

## New crypto rules

Eligible instruments are BTCUSDT and ETHUSDT, completed 15m bars. Entry is the next completed bar's last-trade open. One position at a time. The event id is strategy, symbol, interval, direction, and the signal bar's open time. A later bar that merely remains in the same condition is not a new event. No session filter.

### `fail-break-20261028`

Prior 20 decision bars, excluding the signal bar. A failed upside break has high beyond that channel, close back inside it, and close below the open. Direction is short, stop at the signal high. A failed downside break has low beyond the channel, close back inside, and close above the open. Direction is long, stop at the signal low. Both at once is no trade. Target is 1.5 times the stop distance. Time stop is 12 decision bars. The previous bar must not already be the same failed break.

Falsifiable expectation: after costs, validation mean net return is not above 0. Rationale: a probe through the range that closes back inside is a failed auction.

### `quiet-expand-20261028`

ATR(14) is measured through the bar before a quiet window of the previous 8 decision bars. Each of those 8 true ranges must be at most 0.70 times that ATR. The signal true range must be at least 1.80 times that ATR. Long requires the signal close above its open and above the previous bar's high. Short is the mirror. The completed 1h close must be on the same side of its SMA(48). The previous decision bar must not already be the same expansion. Stop is the signal bar's opposite extreme. Target is 2 times the stop distance. Time stop is 16 bars.

This is not the Gate 3 volatility break: there is no 20-bar channel break and the quiet window is required. Falsifiable expectation: validation mean net return is not above 0. Rationale: a compressed range that expands with the higher-timeframe direction continues more often than it reverses.

### `hour-close-drive-20261028`

Only the 15m bar whose open is 45 minutes after the UTC hour. The completed 1h bar's close must sit in the top quarter of its high-low range and above its open for a long, or the bottom quarter and below its open for a short. A zero range is no trade. The 1h close must agree with SMA(48). The previous UTC hour must not already have qualified in the same direction. Stop is the completed hour's opposite extreme. Target is 2 times the stop distance. Time stop is 8 bars.

Falsifiable expectation: validation mean net return is not above 0. Rationale: a close in the outer quarter of the hourly range is a commitment print, not a 20-bar channel break and not an SMA pullback.

## New gold rules

Eligible instrument is Dukascopy XAUUSD, completed 1h bars with both sides present. Signal geometry uses the bid series except where a short stop is named on the ask. Fills use the side-aware rule above. Market-closed hours are `WAIT`.

### `xau-london-range-20261028`

The signal bar's UTC hour must be 07, 08, or 09. The overnight range is the six completed hours from 00:00 through 05:00 UTC the same day. If any of those hours is missing, the state is `overnight_incomplete` and there is no trade. Long when the bid close is above the overnight bid high. Stop is the overnight bid low. Short when the bid close is below the overnight bid low. Stop is the highest overnight ask high. Target is 2 times the stop distance from the side-aware entry. Time stop is 6 hours. The previous hour must not already be the same break.

Falsifiable expectation: validation mean net return, after the measured spread and the frozen slippage, is not above 0. Rationale: London morning breaks of the post-midnight range are a different reference from the New York SMA pullback.

### `xau-session-day-20261028`

The prior New York session runs from 17:00 New York to the next 17:00 New York. It must contain at least 18 contiguous hourly bars. If it does not, the state is `session_incomplete`. Long when the bid close is above that session's bid high. Short when it is below that session's bid low. Stop is the midpoint of that bid range. Target distance from the side-aware entry is the full prior bid range. Reward/risk below 1 is no trade. Time stop is 8 hours. The previous hour must not already be the same break.

Falsifiable expectation: validation mean net return is not above 0. Rationale: the previous session day's extreme is a different range from a rolling 20-bar channel.

### `xau-climax-fade-20261028`

ATR(14) of the decision bars. A long fade requires the bid low at least one ATR below the prior 10-bar low, a close above the open, and the close in the upper half of the bar. Stop is the signal bid low. A short fade requires the high at least one ATR above the prior 10-bar high, a close below the open, and the close in the lower half. Stop is the signal ask high. Target is the 10-bar average of the signal-side closes, fixed at the signal, and it must offer reward/risk of at least 1 from the side-aware entry. Otherwise no trade. Time stop is 8 hours. The previous hour must not already be the same fade. This is not the Gate 3 RSI range rule: the entry is outside the recent range, and the 0.004 quiet switch is not used.

Falsifiable expectation: validation mean net return is not above 0. Rationale: a one-hour climax through the 10-bar extreme that closes rejected often retraces toward that average.

## What this round will not do

No parameter grid. No change to a rule after its validation result is known. No promotion. No Telegram send. No broker order. No change to Awuru risk caps. No use of the sealed G0 holdout file.
