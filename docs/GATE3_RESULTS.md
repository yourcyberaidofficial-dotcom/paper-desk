# Gate 3 results

Production remains WAIT_DEFAULT. No strategy is approved. No Telegram message was sent.
E1 was not re-optimized. The prior BTC and ETH 15-minute result stays FAIL.

## Coverage

- BTCUSDT 15m: bars 35039 ok True 2025-10-28T00:45:00+00:00 → 2026-10-28T00:29:59.999000+00:00 sha256 0f51193e619c1c74a1743cba2e5652314d0cc32fb312e3eba65ac569b1d48a5b 
- BTCUSDT 1h: bars 8879 ok True 2025-10-23T01:00:00+00:00 → 2026-10-27T23:59:59.999000+00:00 sha256 bf4d15a203975c7e48b8013323625725629b102e69a4726a8a66d9530dcf1f88 
- ETHUSDT 15m: bars 35039 ok True 2025-10-28T00:45:00+00:00 → 2026-10-28T00:29:59.999000+00:00 sha256 3faf3216a1f7512521367d7422fdd6758a7e2f97e5070950e956527e982de752 
- ETHUSDT 1h: bars 8879 ok True 2025-10-23T01:00:00+00:00 → 2026-10-27T23:59:59.999000+00:00 sha256 406626c4eb833a607e973ad1b0abbad3d002ccf205abc060039ac6df87c0221e 
- XAUUSD 1h: bars 5695 ok True 2025-10-28T00:00:00+00:00 → 2026-10-27T23:59:59.999000+00:00 sha256 24cb98a8c1c6e207cfbf3d3962d0a9a2e6c176aba298c4dd43b81f272e3f7b2c 
- XAUUSD 4h: bars 1233 ok True 2025-10-28T00:00:00+00:00 → 2026-10-27T19:59:59.999000+00:00 sha256 970057ee8677c567c0fab2f3cd41478c5b0a90dbe2ddcf7de3517063654a7f7d 

## Windows

- BTCUSDT tf-pullback-20261027 development: FAIL n=891 mean=-0.002470 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- BTCUSDT tf-pullback-20261027 validation: FAIL n=302 mean=-0.001952 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- BTCUSDT vol-break-20261027 development: FAIL n=977 mean=-0.002411 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- BTCUSDT vol-break-20261027 validation: FAIL n=331 mean=-0.002941 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- BTCUSDT mr-range-20261027 development: FAIL n=97 mean=-0.002275 failed=['expectancy', 'uncertainty', 'flat', 'half_first', 'half_second'] blocked=[]
- BTCUSDT mr-range-20261027 validation: FAIL n=58 mean=-0.002106 failed=['expectancy', 'uncertainty', 'flat', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT tf-pullback-20261027 development: FAIL n=896 mean=-0.001939 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT tf-pullback-20261027 validation: FAIL n=314 mean=-0.002039 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- ETHUSDT vol-break-20261027 development: FAIL n=942 mean=-0.002397 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT vol-break-20261027 validation: FAIL n=307 mean=-0.002231 failed=['expectancy', 'uncertainty', 'flat', 'drawdown', 'half_first', 'half_second'] blocked=[]
- ETHUSDT mr-range-20261027 development: FAIL n=45 mean=-0.002194 failed=['expectancy', 'uncertainty', 'flat', 'streak', 'half_first', 'half_second'] blocked=[]
- ETHUSDT mr-range-20261027 validation: FAIL n=20 mean=-0.002786 failed=['half_second'] blocked=['sample', 'half_first']
- XAUUSD tf-pullback-20261027 development: FAIL n=138 mean=0.000410 failed=['expectancy', 'uncertainty', 'half_second'] blocked=['no_measured_bid_ask']
- XAUUSD tf-pullback-20261027 validation: FAIL n=42 mean=-0.000438 failed=['expectancy', 'uncertainty', 'flat', 'streak', 'half_first', 'half_second'] blocked=['no_measured_bid_ask']
- XAUUSD vol-break-20261027 development: FAIL n=139 mean=-0.000904 failed=['expectancy', 'uncertainty', 'flat', 'half_first'] blocked=['no_measured_bid_ask']
- XAUUSD vol-break-20261027 validation: FAIL n=51 mean=0.001003 failed=['uncertainty'] blocked=['no_measured_bid_ask']
- XAUUSD mr-range-20261027 development: BLOCKED n=0 mean=n/a failed=[] blocked=['sample', 'half_first', 'half_second', 'no_measured_bid_ask']
- XAUUSD mr-range-20261027 validation: BLOCKED n=0 mean=n/a failed=[] blocked=['sample', 'half_first', 'half_second', 'no_measured_bid_ask']
- XAUUSD xau-session-20261027 development: FAIL n=75 mean=0.000656 failed=['uncertainty'] blocked=['no_measured_bid_ask']
- XAUUSD xau-session-20261027 validation: FAIL n=23 mean=0.000160 failed=['half_second'] blocked=['sample', 'no_measured_bid_ask']

## Selection

- BTCUSDT: {"holdout": "NOT_OPENED", "reason": "no_validation_pass", "selected": null}
- ETHUSDT: {"holdout": "NOT_OPENED", "reason": "no_validation_pass", "selected": null}
- XAUUSD: {"holdout": "NOT_OPENED", "reason": "no_validation_pass", "selected": null}

Qualified for review: none.
Approved for production: none.
Dukascopy probe: http_503.
