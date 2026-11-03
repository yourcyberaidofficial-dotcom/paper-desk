# Strategy diagnosis

This note reads the stored result files. It does not rescore them and it does not open a holdout.
Costs in the research simulator are 11 bps per fill at the base case and 15 bps under stress, two fills, deducted once.
That is an assumption, not a measured exchange fee. The paper book separately assumes 2 bps of adverse slippage on a candle-estimated exit. Those 2 bps are not added again inside the research simulator.
A same-candle stop and target stays unresolved in the paper book. The research simulator checks the stop before the target. Historical results were not rewritten to change that.
No registered strategy is approved for paper. AutoPilot still requires an exact approved version.

## Data that can and cannot support a new study

Retained in this checkout: BTCUSDT and ETHUSDT Binance spot 4h from 2023-01-01, 8,378 bars, no gaps in the stored validation. The last 20 percent, from 2026-01-22, was not simulated by the leader study or by the new follow-up.
Retained gold: Dukascopy bid/ask hours, 717 bars, 2024-06-03 to 2024-07-12. The series has closed-market gaps. It was already used. It is not a fresh sample and it is not a licence for 1-minute or 3-minute gold.
Not retained: crypto 1m, 3m, 15m and 1h history, and the longer Gate 4 Dukascopy gold pull. Those earlier results stay as recorded. They are not replayed from memory and the missing files are not invented.
XAUUSD 1m and 3m stay `xau_minute_unlicensed`. Synthetic fixtures are not an approval source.
The twelve desk pairs therefore have no retained candle file long enough for a new holdout study. The only new study this checkout can support is on the already-used 4h crypto prefix.

## Registry strategies

### E1-donchian-20 (`e1-20261016`)

Hypothesis: a close beyond the prior 20 completed bars continues. Invalidation is the other side of that channel. Timeframe 15m, BTC and ETH.
Recorded status: FAIL. `docs/GATE2_RESULTS.md` is not in this checkout, so trade counts are not restated from memory and the rule was not retuned.
Mechanism from the later record: the benchmark stayed failed after costs. This is a recorded failure, not a new measurement.

### Trend pullback, volatility breakout, range reversion, gold session (`20261027`)

Gate 3, chronological development and validation, holdout not opened because nothing passed validation.
Crypto rows have hundreds of trades and means near -0.2 percent per trade after the 22 bps round turn. Gross edge was not large enough for that turnover. Both directions and both regime buckets in the later Gate 4 reproduction were negative. That is a no-edge or cost-dominated failure, not an implementation defect that was later corrected.
Gold rows used chart OHLC without measured bid/ask, so they are blocked on that point even where a point estimate was positive. The gold session validation sample was 23 trades. Positive gold point estimates are not approval.
- BTCUSDT tf-pullback-20261027 validation: FAIL n=302 gross=n/a net=n/a cost_drag=n/a mean=-0.001952 stress=-0.002752 lower=-0.002663 equity=0.551025 drawdown=0.471743 streak=9 win_rate=0.337748 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- BTCUSDT vol-break-20261027 validation: FAIL n=331 gross=n/a net=n/a cost_drag=n/a mean=-0.002941 stress=-0.003741 lower=-0.003465 equity=0.375802 drawdown=0.624198 streak=12 win_rate=0.287009 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- BTCUSDT mr-range-20261027 validation: FAIL n=58 gross=n/a net=n/a cost_drag=n/a mean=-0.002106 stress=-0.002906 lower=-0.002563 equity=0.884824 drawdown=0.115176 streak=16 win_rate=0.172414 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT tf-pullback-20261027 validation: FAIL n=314 gross=n/a net=n/a cost_drag=n/a mean=-0.002039 stress=-0.002839 lower=-0.002930 equity=0.521577 drawdown=0.549165 streak=12 win_rate=0.312102 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- ETHUSDT vol-break-20261027 validation: FAIL n=307 gross=n/a net=n/a cost_drag=n/a mean=-0.002231 stress=-0.003031 lower=-0.002998 equity=0.500201 drawdown=0.530966 streak=10 win_rate=0.335505 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- ETHUSDT mr-range-20261027 validation: FAIL n=20 gross=n/a net=n/a cost_drag=n/a mean=-0.002786 stress=-0.003586 lower=-0.003480 equity=0.945717 drawdown=0.054283 streak=15 win_rate=0.050000 profit_factor=n/a failed=['half_second'] blocked=['sample', 'half_first']
- XAUUSD tf-pullback-20261027 validation: FAIL n=42 gross=n/a net=n/a cost_drag=n/a mean=-0.000438 stress=-0.000914 lower=-0.003447 equity=0.979798 drawdown=0.115905 streak=13 win_rate=0.404762 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'streak', 'half_first', 'half_second'] blocked=['no_measured_bid_ask']
- XAUUSD vol-break-20261027 validation: FAIL n=51 gross=n/a net=n/a cost_drag=n/a mean=0.001003 stress=0.000523 lower=-0.001527 equity=1.050241 drawdown=0.043303 streak=5 win_rate=0.372549 profit_factor=n/a failed=['uncertainty'] blocked=['no_measured_bid_ask']
- XAUUSD mr-range-20261027 validation: BLOCKED n=0 gross=n/a net=n/a cost_drag=n/a mean=n/a stress=n/a lower=n/a equity=1.000000 drawdown=0.000000 streak=0 win_rate=n/a profit_factor=n/a failed=[] blocked=['sample', 'half_first', 'half_second', 'no_measured_bid_ask']
- XAUUSD xau-session-20261027 validation: FAIL n=23 gross=n/a net=n/a cost_drag=n/a mean=0.000160 stress=-0.000312 lower=-0.004486 equity=1.002260 drawdown=0.053014 streak=6 win_rate=0.347826 profit_factor=n/a failed=['half_second'] blocked=['sample', 'no_measured_bid_ask']

### spot-tsmom-1h-20261028

Hypothesis: long only after a higher 24-hour close that is also above the 20-bar average. Stop 1.5 ATR, hold 24 bars. BTC and ETH 1h, about 400 days starting 2025-09-23. Holdout of 1,920 bars was not opened.
BTC: 417 trades, gross sum +0.088, cost drag 0.917, net sum -0.829, mean -0.00199. The gross sum is positive and smaller than the cost. Failure mechanism: excessive turnover relative to the gross move, then the existing expectancy, uncertainty, flat and drawdown gates.
ETH: 420 trades, gross sum already -0.201, net -1.125, mean -0.00268. Failure mechanism: no positive gross edge, plus costs.
XAUUSD was not run. Reason recorded: no measured bid/ask. That is insufficient data, not a proven gold failure of this rule.

### tight-range-long-1h-20261028

Hypothesis: long near the bottom of a 20-bar range narrower than 1.5 percent. Spot shorts are not taken.
BTC: 45 trades, gross sum about 0, cost drag 0.099, mean -0.00221. FAIL. The range rule did not produce a gross edge that could pay 22 bps.
ETH: 9 trades. BLOCKED for sample size. The point estimate is not a result.

### sweep-reclaim-4h-20261028 and compress-break-4h-20261028

Scored once on the retained 4h prefix (6,702 bars, 2023-01-01 through 2026-01-21). Holdout 1,676 bars not opened. Long only. Buy-and-hold on that prefix was largely positive (BTC gross about +4.41, ETH about +1.49) after one 22 bps round turn.
- BTCUSDT leader rank: {"approved": false, "judgment": "FAIL", "median_fold_mean": -0.0018739268702522818, "status": "research_leader_failed", "strategy": "compress-break-4h-20261028"}. Rank is not approval.
- BTCUSDT sweep-reclaim-4h-20261028 pre-holdout: FAIL n=323 gross=0.173038 net=-0.537562 cost_drag=0.710600 mean=-0.001664 stress=-0.002464 lower=-0.002905 equity=0.571953 drawdown=0.429991 streak=13 win_rate=0.352941 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- BTCUSDT compress-break-4h-20261028 pre-holdout: FAIL n=68 gross=0.138359 net=-0.011241 cost_drag=0.149600 mean=-0.000165 stress=-0.000965 lower=-0.003254 equity=0.983272 drawdown=0.093312 streak=9 win_rate=0.382353 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'half_second'] blocked=[]
- ETHUSDT leader rank: {"approved": false, "judgment": "FAIL", "median_fold_mean": -0.0020641112122359753, "status": "research_leader_failed", "strategy": "sweep-reclaim-4h-20261028"}. Rank is not approval.
- ETHUSDT sweep-reclaim-4h-20261028 pre-holdout: FAIL n=330 gross=-0.037828 net=-0.763828 cost_drag=0.726000 mean=-0.002315 stress=-0.003115 lower=-0.003834 equity=0.450585 drawdown=0.572233 streak=12 win_rate=0.333333 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- ETHUSDT compress-break-4h-20261028 pre-holdout: FAIL n=41 gross=-0.071955 net=-0.162155 cost_drag=0.090200 mean=-0.003955 stress=-0.004755 lower=-0.009316 equity=0.844854 drawdown=0.180095 streak=7 win_rate=0.268293 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'half_first', 'half_second'] blocked=['unstable_folds']
- XAUUSD leader rank: {"approved": false, "status": "none", "strategy": null}. Rank is not approval.
- XAUUSD london-reclaim-1h-20261028 pre-holdout: BLOCKED n=6 gross=-0.002891 net=-0.003402 cost_drag=0.000511 mean=-0.000567 stress=-0.000737 lower=-0.001525 equity=0.996600 drawdown=0.004135 streak=4 win_rate=0.166667 profit_factor=n/a failed=[] blocked=['sample', 'half_first', 'half_second', 'unstable_folds']
BTC sweep gross sum was positive (+0.173) and cost drag was 0.711 across 323 trades. Same cost-versus-turnover mechanism as the 1h momentum rule. Compression breakout was the least-bad BTC rank and still failed uncertainty and the second half; its gross sum (+0.138) did not clear costs (net -0.011) on 68 trades.
ETH sweep gross sum was already negative. ETH compression was negative and blocked for unstable folds. These are failures against a rising market, not a claim that every long rule must lose.

### london-reclaim-1h-20261028

Gold only, Dukascopy bid/ask, buy the ask and sell the bid, plus 0.10 USD per side. 6 trades. BLOCKED for sample. Mean was negative. Insufficient evidence, not a precise performance claim. The live chart feed does not run this rule.

### dip-in-trend-1d-20261028 and quiet-week-reversal-1d-20261028

Daily bars were built only from complete UTC 4h groups. Holdout not opened. The 4h failures were not retuned.
- BTCUSDT dip-in-trend-1d-20261028: FAIL n=72 gross=-0.028846 net=-0.187246 cost_drag=0.158400 mean=-0.002601 stress=-0.003401 lower=n/a equity=n/a drawdown=0.310417 streak=None win_rate=0.291667 profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- BTCUSDT quiet-week-reversal-1d-20261028: BLOCKED n=9 gross=0.141671 net=0.121871 cost_drag=0.019800 mean=0.013541 stress=0.012741 lower=n/a equity=n/a drawdown=n/a streak=None win_rate=n/a profit_factor=n/a failed=[] blocked=['sample', 'half_first', 'half_second', 'unstable_folds']
- ETHUSDT dip-in-trend-1d-20261028: FAIL n=97 gross=-0.285560 net=-0.498960 cost_drag=0.213400 mean=-0.005144 stress=-0.005944 lower=n/a equity=n/a drawdown=n/a streak=None win_rate=n/a profit_factor=n/a failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- ETHUSDT quiet-week-reversal-1d-20261028: BLOCKED n=4 gross=n/a net=-0.041612 cost_drag=n/a mean=-0.010403 stress=-0.011203 lower=n/a equity=n/a drawdown=n/a streak=None win_rate=n/a profit_factor=n/a failed=[] blocked=['sample', 'half_first', 'half_second', 'unstable_folds']
The daily dip failed after costs on both markets, with a negative median fold, while buy-and-hold on the same prefix was positive. Quiet-week had 9 BTC trades and 4 ETH trades. BLOCKED. The positive BTC point estimate is not evidence.

## Recorded experiments that are not live registry rows

Gate 4 added fail-break, quiet-expand and hour-close-drive on crypto, and three gold rules on a Dukascopy pull that is not retained here. Holdout was not opened (`no_validation_pass`).
- BTCUSDT fail-break-20261028 validation: FAIL n=320 gross=n/a net=n/a cost_drag=n/a mean=-0.001856 stress=-0.002656 lower=-0.002321 equity=0.550259 drawdown=0.457251 streak=16 win_rate=0.287500 profit_factor=0.319043 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- BTCUSDT quiet-expand-20261028 validation: BLOCKED n=1 gross=n/a net=n/a cost_drag=n/a mean=-0.007393 stress=-0.008193 lower=n/a equity=0.992607 drawdown=0.007393 streak=1 win_rate=0.000000 profit_factor=0.000000 failed=[] blocked=['sample', 'half_first', 'half_second']
- BTCUSDT hour-close-drive-20261028 validation: FAIL n=375 gross=n/a net=n/a cost_drag=n/a mean=-0.001900 stress=-0.002700 lower=-0.002430 equity=0.487510 drawdown=0.513997 streak=14 win_rate=0.261333 profit_factor=0.393831 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT fail-break-20261028 validation: FAIL n=280 gross=n/a net=n/a cost_drag=n/a mean=-0.001857 stress=-0.002657 lower=-0.002484 equity=0.591891 drawdown=0.409830 streak=13 win_rate=0.342857 profit_factor=0.405516 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT quiet-expand-20261028 validation: BLOCKED n=2 gross=n/a net=n/a cost_drag=n/a mean=-0.006047 stress=-0.006847 lower=-0.027133 equity=0.987827 drawdown=0.016805 streak=1 win_rate=0.500000 profit_factor=0.280354 failed=[] blocked=['sample', 'half_first', 'half_second']
- ETHUSDT hour-close-drive-20261028 validation: FAIL n=332 gross=n/a net=n/a cost_drag=n/a mean=-0.002625 stress=-0.003425 lower=-0.003430 equity=0.413957 drawdown=0.586043 streak=11 win_rate=0.262048 profit_factor=0.388786 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- XAUUSD xau-london-range-20261028 validation: BLOCKED n=24 gross=n/a net=n/a cost_drag=n/a mean=0.001650 stress=0.001554 lower=-0.001187 equity=1.039766 drawdown=0.016236 streak=2 win_rate=0.583333 profit_factor=1.816873 failed=[] blocked=['sample']
- XAUUSD xau-session-day-20261028 validation: FAIL n=40 gross=n/a net=n/a cost_drag=n/a mean=-0.000525 stress=-0.000621 lower=-0.003421 equity=0.977567 drawdown=0.075507 streak=4 win_rate=0.500000 profit_factor=0.874068 failed=['expectancy', 'uncertainty', 'flat', 'half_second'] blocked=[]
- XAUUSD xau-climax-fade-20261028 validation: BLOCKED n=1 gross=n/a net=n/a cost_drag=n/a mean=-0.003322 stress=-0.003420 lower=n/a equity=0.996678 drawdown=0.003322 streak=1 win_rate=0.000000 profit_factor=0.000000 failed=[] blocked=['sample', 'half_first', 'half_second']
xau-london-range validation n=24 had a positive point estimate and was BLOCKED for sample. xau-session-day validation failed expectancy. xau-climax-fade had one validation trade. None is approved. The gold file used for that study is not in this checkout, so it was not rerun.

## New candidate, trend-hold-4h-20261103

Declared before this scoring as one configuration: long only when a completed 4h close is above the prior 60 highs and above the 120-bar average; stop 3 ATR; target 6 ATR; maximum hold 42 bars; next-bar entry. It is not a parameter edit of compression-breakout (10-bar high, quiet ATR, 1 ATR stop, hold 12) or of E1 (20-bar, 15m).
Reason to test it once: several earlier BTC rules had a small positive gross sum that 11 bps per fill erased. A slower hold was the mechanism suggested by that diagnosis. Because the idea came from those comparisons, it is a follow-up. A pass would not have been an independent discovery.
Development was simulated without validation prices. Validation signals in the first 42 bars were embargoed. The final 20 percent stayed sealed because validation did not PASS.
The existing judge was not edited. A positive mean with a 95 percent lower bound below zero is a FAIL on uncertainty. A window under 30 trades is BLOCKED, not a success.
Protocol sha256 7e9ac35c1381b9f4801d75ec032c7183bf6a74d51f040c5651c7289094c3595e. Parent software sha f0419e5512c15b1096032046838966b27e34d40c. Approved list: []. Holdout opened for: nobody.
- BTCUSDT development: FAIL n=56 gross=0.538989 net=0.415789 cost_drag=0.123200 mean=0.007425 stress=0.006625 lower=-0.004672 equity=1.429431 drawdown=0.123091 streak=4 win_rate=0.482143 profit_factor=1.453552 failed=['uncertainty'] blocked=[]
- BTCUSDT validation: BLOCKED n=18 gross=0.014427 net=-0.025173 cost_drag=0.039600 mean=-0.001399 stress=-0.002199 lower=-0.014929 equity=0.968096 drawdown=0.104685 streak=4 win_rate=0.388889 profit_factor=0.898886 failed=[] blocked=['sample', 'half_second']
- BTCUSDT holdout: NOT_OPENED. Prefix buy-and-hold gross 4.407809. Folds [{'base_mean': 0.0037708996084100496, 'fold': 1, 'net_sum': 0.08673069099343111, 'trades': 23}, {'base_mean': 0.009324484087583015, 'fold': 2, 'net_sum': 0.28905900671507345, 'trades': 31}, {'base_mean': 0.003981779836348388, 'fold': 3, 'net_sum': 0.08759915639966452, 'trades': 22}].
- ETHUSDT development: FAIL n=46 gross=0.410847 net=0.309647 cost_drag=0.101200 mean=0.006731 stress=0.005931 lower=-0.009154 equity=1.273714 drawdown=0.180688 streak=5 win_rate=0.478261 profit_factor=1.307325 failed=['uncertainty'] blocked=[]
- ETHUSDT validation: BLOCKED n=24 gross=0.217788 net=0.164988 cost_drag=0.052800 mean=0.006875 stress=0.006075 lower=-0.024432 equity=1.101079 drawdown=0.311613 streak=4 win_rate=0.416667 profit_factor=1.222188 failed=[] blocked=['sample', 'half_second']
- ETHUSDT holdout: NOT_OPENED. Prefix buy-and-hold gross 1.493266. Folds [{'base_mean': -0.0049913586920031635, 'fold': 1, 'net_sum': -0.10980989122406959, 'trades': 22}, {'base_mean': 0.019988733628148125, 'fold': 2, 'net_sum': 0.4597408734474069, 'trades': 23}, {'base_mean': 0.00724094672319076, 'fold': 3, 'net_sum': 0.1882646148029598, 'trades': 26}].
Development on both markets had a positive cost-adjusted point estimate and still failed the pre-registered uncertainty gate. The lower bound of the normal interval was below zero. That interval assumes independent trades; overlapping trends make it a screen, not a proof of skill either way.
BTC validation, 18 trades, mean -0.00140 after costs. Blocked for sample. The point estimate is on the wrong side of the no-trade baseline and the window is too small to call that a measured failure of expectancy.
ETH validation, 24 trades, mean +0.00687. Blocked for sample and for the second half count. The recorded drawdown on that window is about 0.312, above the 0.25 cap, but the frozen judge does not apply the drawdown cap until the sample gate is clear. The judgment is left as BLOCKED. The positive mean is not promoted.
ETH prefix folds are not stable (the first fold mean is negative). BTC prefix folds are positive and still do not override the failed development uncertainty gate or the blocked validation window.
Neither symbol beat the decision rule. The holdout that starts 2026-01-22 was not opened. The version is not approved for paper and it is not a live desk signal.

## What this does not show

It does not show that no slower rule could ever pass. It shows that this pre-registered follow-up did not. Another configuration would be a new version and would carry the same multiple-testing warning. It would still have to pass development, untouched validation, and only then the sealed holdout.
Desk 1m, 3m, 15m and 1h research cannot be advanced from files in this checkout without a new retained download, and a download is not a reason to tune a rule that has already seen this 4h sample.

