# Discovery result, trend-hold-4h-20261103

This file is the scored result of the frozen protocol in `ops/discovery.py`. It is not an approval.
Protocol sha256: 7e9ac35c1381b9f4801d75ec032c7183bf6a74d51f040c5651c7289094c3595e
Software sha at the run: f0419e5512c15b1096032046838966b27e34d40c
Holdout opened for: nobody.
Approved for paper: none.

The rule is a follow-up to earlier cost-drag failures. It was not selected by looking at the holdout.

## BTCUSDT

- Bars 8378. Development 5026 from 2023-01-01T00:00:00+00:00. Validation from 2025-04-17T16:00:00+00:00. Holdout starts 2026-01-22T00:00:00+00:00 and is NOT_OPENED.
- Dataset fingerprint 14590f5545fbc835e8bec5ccd2b7af0f55fa1f23c2eb4c84839b73ec79c64ec6.
- Embargoed validation signals: 2.
- development: FAIL n=56 mean=0.007425 stress=0.006625 gross=0.538989 net=0.415789 cost=0.123200 drawdown=0.123091 lower=-0.004672 profit_factor=1.453552 win_rate=0.482143 failed=['uncertainty'] blocked=[]
- validation: BLOCKED n=18 mean=-0.001399 stress=-0.002199 gross=0.014427 net=-0.025173 cost=0.039600 drawdown=0.104685 lower=-0.014929 profit_factor=0.898886 win_rate=0.388889 failed=[] blocked=['sample', 'half_second']
- holdout: NOT_OPENED
- Prefix buy-and-hold gross 4.407809, net of one 22 bps round turn 4.405609. No-trade baseline is 0.
- Long trades are the only direction. Short trades: 0. Approved for paper: False.

## ETHUSDT

- Bars 8378. Development 5026 from 2023-01-01T00:00:00+00:00. Validation from 2025-04-17T16:00:00+00:00. Holdout starts 2026-01-22T00:00:00+00:00 and is NOT_OPENED.
- Dataset fingerprint a62762b7f7d3b0e006a9dcb30ff9f7acb7141b5881d0fad19d4777e09fba0897.
- Embargoed validation signals: 1.
- development: FAIL n=46 mean=0.006731 stress=0.005931 gross=0.410847 net=0.309647 cost=0.101200 drawdown=0.180688 lower=-0.009154 profit_factor=1.307325 win_rate=0.478261 failed=['uncertainty'] blocked=[]
- validation: BLOCKED n=24 mean=0.006875 stress=0.006075 gross=0.217788 net=0.164988 cost=0.052800 drawdown=0.311613 lower=-0.024432 profit_factor=1.222188 win_rate=0.416667 failed=[] blocked=['sample', 'half_second']
- holdout: NOT_OPENED
- Prefix buy-and-hold gross 1.493266, net of one 22 bps round turn 1.491066. No-trade baseline is 0.
- Long trades are the only direction. Short trades: 0. Approved for paper: False.

Production was not changed by writing this file.
