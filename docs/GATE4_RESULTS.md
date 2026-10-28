# Gate 4 results

Production remains WAIT_DEFAULT. No strategy is approved. No Telegram message was sent. The broker was not enabled.
Hypotheses were frozen in docs/GATE4_SPEC.md at commit 703aa08 before these scores. The rules were not edited after the scores.
E1-donchian-20 was not retuned. Gate 3 FAIL and BLOCKED rows were not reclassified.
The holdout was not opened. No validation candidate passed.

## Data that was actually read

- Crypto: Binance public spot klines, no key. BTCUSDT and ETHUSDT, 35039 completed 15m bars and 8879 completed 1h bars. The recorded Gate 3 OHLC sha256 values matched on rerun.
- Gold history: Dukascopy public datafeed, no key, instrument XAUUSD, separate BID and ASK 1-minute candle files. Point scale 1000. 6264 completed 1h bars from 2025-10-28T00:00:00+00:00 to 2026-10-27T23:59:59.999000+00:00. Research series sha256 4068aa073764ae2a7b9cb573171fff467751daae4b5d8a1d5e945c60d489465f. Hour-file sha256 518901dbdce9bbe1ea99da93143499a3e34f6971d72e516073261eef346a383b.
- Gold quote check: bid open is the hour open. Ask is stored separately. No negative open spread in the 6264 hours. Mean ask-minus-bid open is about 0.93 USD. These are Dukascopy quotes, not a claim about another broker.
- One calendar file failed: 2026-10-24, a New York Saturday, ask HTTP 503. No research hour was expected that day. Unexpected gaps inside the weekly market: 0. Weekly-close gaps: 52.
- These files are historical. They do not provide a live bid/ask feed. xaus.com spot remains an indicative mid.
- The Dukascopy historical-data-export URL returned an HTML page. The requester-pays export was not used. Tick-hour bi5 was the Gate 3 HTTP 503 path and was not substituted for these minute candles.

## Gate 3 reproduction

- BTC and ETH OHLC hashes match docs/GATE3_RESULTS.md. Replaying the Gate 3 rules on that window reproduced every stored crypto row. Diffs: 0. Holdout stayed closed.
- XAUUSD xaus.com 1h did not match. Stored 5695 bars from 2025-10-28 00:00, sha256 24cb98a8c1c6e207cfbf3d3962d0a9a2e6c176aba298c4dd43b81f272e3f7b2c. Rerun with the original end clock: 5694 bars from 2025-10-28 01:00, sha256 a5eafb5131a0564d286ecaf0a1db27fcedf44ab2e8c041e5d5744fd1a60f3e57. The 4h count fell from 1233 to 1232. Cause: range=1y is a moving window and the first hour had rolled off. The stored Gate 3 gold judgments were left unchanged.

## New crypto rules

- BTCUSDT fail-break-20261028 development: FAIL n=947 mean=-0.002355 stress=-0.003155 lower=-0.002670 equity=0.10602660668296922 dd=0.8941 streak=16 pf=0.3054777536977014 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- BTCUSDT fail-break-20261028 validation: FAIL n=320 mean=-0.001856 stress=-0.002656 lower=-0.002321 equity=0.5502588818805182 dd=0.4573 streak=16 pf=0.3190427065814301 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- BTCUSDT quiet-expand-20261028 development: BLOCKED n=0 mean=n/a stress=n/a lower=n/a equity=1.0 dd=0.0 streak=0 pf=None failed=[] blocked=['sample', 'half_first', 'half_second']
- BTCUSDT quiet-expand-20261028 validation: BLOCKED n=1 mean=-0.007393 stress=-0.008193 lower=n/a equity=0.9926074757047991 dd=0.0074 streak=1 pf=0.0 failed=[] blocked=['sample', 'half_first', 'half_second']
- BTCUSDT hour-close-drive-20261028 development: FAIL n=1084 mean=-0.001927 stress=-0.002727 lower=-0.002329 equity=0.12057406551999 dd=0.8825 streak=15 pf=0.46279036814176977 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- BTCUSDT hour-close-drive-20261028 validation: FAIL n=375 mean=-0.001900 stress=-0.002700 lower=-0.002430 equity=0.4875103720837552 dd=0.514 streak=14 pf=0.3938306355131808 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT fail-break-20261028 development: FAIL n=752 mean=-0.002347 stress=-0.003147 lower=-0.002859 equity=0.1675394006750284 dd=0.8354 streak=11 pf=0.43166860037096555 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- ETHUSDT fail-break-20261028 validation: FAIL n=280 mean=-0.001857 stress=-0.002657 lower=-0.002484 equity=0.5918912345591688 dd=0.4098 streak=13 pf=0.4055156619477434 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT quiet-expand-20261028 development: BLOCKED n=2 mean=-0.007007 stress=-0.007807 lower=-0.007220 equity=0.9860359860387486 dd=0.014 streak=2 pf=0.0 failed=[] blocked=['sample', 'half_first', 'half_second']
- ETHUSDT quiet-expand-20261028 validation: BLOCKED n=2 mean=-0.006047 stress=-0.006847 lower=-0.027133 equity=0.9878269486832844 dd=0.0168 streak=1 pf=0.28035448287849885 failed=[] blocked=['sample', 'half_first', 'half_second']
- ETHUSDT hour-close-drive-20261028 development: FAIL n=952 mean=-0.001623 stress=-0.002423 lower=-0.002199 equity=0.20488601379499527 dd=0.8014 streak=16 pf=0.6124796254559054 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT hour-close-drive-20261028 validation: FAIL n=332 mean=-0.002625 stress=-0.003425 lower=-0.003430 equity=0.4139572190726802 dd=0.586 streak=11 pf=0.3887855669387736 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]

Selection: BTCUSDT and ETHUSDT holdout NOT_OPENED, no validation pass.

## New gold rules, measured bid/ask plus frozen 0.10/0.30 USD slippage

- XAUUSD xau-london-range-20261028 development: FAIL n=65 mean=-0.000242 stress=-0.000331 lower=-0.003057 equity=0.9800763501407339 dd=0.0875 streak=5 pf=0.9309099289352575 failed=['expectancy', 'uncertainty', 'flat', 'half_first', 'half_second'] blocked=[]
- XAUUSD xau-london-range-20261028 validation: BLOCKED n=24 mean=0.001650 stress=0.001554 lower=-0.001187 equity=1.0397663427402235 dd=0.0162 streak=2 pf=1.8168733206713121 failed=[] blocked=['sample']
- XAUUSD xau-session-day-20261028 development: FAIL n=98 mean=0.001592 stress=0.001504 lower=-0.000646 equity=1.1615669805364148 dd=0.0755 streak=8 pf=1.4990493506941507 failed=['uncertainty'] blocked=[]
- XAUUSD xau-session-day-20261028 validation: FAIL n=40 mean=-0.000525 stress=-0.000621 lower=-0.003421 equity=0.9775666883252724 dd=0.0755 streak=4 pf=0.8740679456956721 failed=['expectancy', 'uncertainty', 'flat', 'half_second'] blocked=[]
- XAUUSD xau-climax-fade-20261028 development: BLOCKED n=2 mean=-0.003857 stress=-0.003942 lower=-0.005382 equity=0.9923001558774188 dd=0.0077 streak=2 pf=0.0 failed=[] blocked=['sample', 'half_first', 'half_second']
- XAUUSD xau-climax-fade-20261028 validation: BLOCKED n=1 mean=-0.003322 stress=-0.003420 lower=n/a equity=0.9966778262652476 dd=0.0033 streak=1 pf=0.0 failed=[] blocked=['sample', 'half_first', 'half_second']

Selection: holdout NOT_OPENED, no validation pass.
xau-london-range validation has a positive base and stress mean and equity above 1, but only 24 round trips, so the frozen sample gate returns BLOCKED. Its normal 95% lower bound is also below zero. That row was not promoted and its holdout was not scored.
xau-session-day development has a positive mean, but the normal 95% lower bound is below zero, so it is FAIL. Validation mean is negative.
xau-climax-fade has 2 development trades and 1 validation trade. BLOCKED.

## Gate 3 gold rules replayed on the measured Dukascopy bars

These rows are a comparison. They cannot be selected. The old xaus judgments stay as published.

- XAUUSD tf-pullback-20261027 development: FAIL n=148 mean=-0.000509 stress=-0.000597 lower=-0.002050 equity=0.9212720243569015 dd=0.1577 streak=13 pf=0.8716035659490352 failed=['expectancy', 'uncertainty', 'flat', 'streak', 'half_first', 'half_second'] blocked=[]
- XAUUSD tf-pullback-20261027 validation: FAIL n=51 mean=-0.000307 stress=-0.000403 lower=-0.002640 equity=0.982704348482258 dd=0.084 streak=6 pf=0.9196224746665239 failed=['expectancy', 'uncertainty', 'flat', 'half_first'] blocked=[]
- XAUUSD vol-break-20261027 development: FAIL n=165 mean=-0.000114 stress=-0.000201 lower=-0.001927 equity=0.9701571975090981 dd=0.123 streak=9 pf=0.9754071771050563 failed=['expectancy', 'uncertainty', 'flat', 'half_first'] blocked=[]
- XAUUSD vol-break-20261027 validation: FAIL n=66 mean=0.001132 stress=0.001036 lower=-0.000930 equity=1.0750039953646993 dd=0.0387 streak=6 pf=1.349693658482056 failed=['uncertainty'] blocked=[]
- XAUUSD mr-range-20261027 development: BLOCKED n=0 mean=n/a stress=n/a lower=n/a equity=1.0 dd=0.0 streak=0 pf=None failed=[] blocked=['sample', 'half_first', 'half_second']
- XAUUSD mr-range-20261027 validation: BLOCKED n=0 mean=n/a stress=n/a lower=n/a equity=1.0 dd=0.0 streak=0 pf=None failed=[] blocked=['sample', 'half_first', 'half_second']
- XAUUSD xau-session-20261027 development: FAIL n=73 mean=-0.000342 stress=-0.000428 lower=-0.002897 equity=0.9710753611376565 dd=0.0867 streak=7 pf=0.9181883807218517 failed=['expectancy', 'uncertainty', 'flat', 'half_first', 'half_second'] blocked=[]
- XAUUSD xau-session-20261027 validation: FAIL n=27 mean=-0.001190 stress=-0.001285 lower=-0.004559 equity=0.9673660698438341 dd=0.0738 streak=5 pf=0.73896099882168 failed=['half_first', 'half_second'] blocked=['sample']

## Assumed 0.50/1.50 USD cost on bid OHLC

This comparison is not a measured cost and cannot be PASS. Holdout was not opened.

- XAUUSD xau-london-range-20261028 validation: BLOCKED n=24 mean=0.001611 stress=0.001130 lower=-0.001225 equity=1.0387813384704514 dd=0.0162 streak=2 pf=1.7915048863155627 failed=[] blocked=['sample', 'no_measured_bid_ask']
- XAUUSD xau-session-day-20261028 validation: FAIL n=40 mean=-0.000495 stress=-0.000976 lower=-0.003382 equity=0.9787315640331115 dd=0.0739 streak=4 pf=0.8801739460408977 failed=['expectancy', 'uncertainty', 'flat', 'half_second'] blocked=['no_measured_bid_ask']
- XAUUSD xau-climax-fade-20261028 validation: BLOCKED n=1 mean=-0.003518 stress=-0.004008 lower=n/a equity=0.9964819722499342 dd=0.0035 streak=1 pf=0.0 failed=[] blocked=['sample', 'half_first', 'half_second', 'no_measured_bid_ask']
- XAUUSD tf-pullback-20261027 validation: FAIL n=51 mean=-0.000430 stress=-0.000910 lower=-0.002730 equity=0.9765740999310157 dd=0.0868 streak=6 pf=0.8881581168601341 failed=['expectancy', 'uncertainty', 'flat', 'half_first'] blocked=['no_measured_bid_ask']
- XAUUSD vol-break-20261027 validation: FAIL n=66 mean=0.000951 stress=0.000470 lower=-0.001112 equity=1.062203486969129 dd=0.0416 streak=6 pf=1.2838631754654588 failed=['uncertainty'] blocked=['no_measured_bid_ask']
- XAUUSD mr-range-20261027 validation: BLOCKED n=0 mean=n/a stress=n/a lower=n/a equity=1.0 dd=0.0 streak=0 pf=None failed=[] blocked=['sample', 'half_first', 'half_second', 'no_measured_bid_ask']
- XAUUSD xau-session-20261027 validation: FAIL n=27 mean=-0.001337 stress=-0.001815 lower=-0.004659 equity=0.9635517528151072 dd=0.0752 streak=5 pf=0.7099846755963523 failed=['half_first', 'half_second'] blocked=['sample', 'no_measured_bid_ask']

## What this does not show

Nine validation tests were scored with no Bonferroni, SPA, White, DSR, or PBO adjustment. Trades were treated as independent. Serial dependence was not removed. Overfitting was not formally ruled out. A pass would only have been a request for a separate review.
No strategy was approved. No paper order was created. No production user record was changed.

