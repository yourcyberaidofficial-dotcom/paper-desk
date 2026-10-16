# G1-H4 development report

Generation: G1
Hypothesis: H4 volatility-scaled time-series momentum (implementation used raw price PnL; vol scaling not applied)
Data: data/development/bars.jsonl SHA-256 3390d4bd75b006a293b864ea03734c95488950b50304549b0e9dd1927f869a6b
Coverage: BTCUSDT and ETHUSDT 4h, 2020-01-01 to 2025-05-30, 11858 bars each, 1 gap each, 0 invalid OHLC
Registered: 18
Executed: 18
Holdout: not accessed
Production: unchanged

## Result

ETH failed on lookbacks 20 and 60 under all cost paths. BTC lookback 20 failed stress. BTC 60/120 and ETH 120 were positive in this pass.

## Defect

PnL is in price units, not volatility-scaled returns. Stress sometimes beat base because the extra bar changes the fill, not because costs helped. This pass is not promotion-ready.

## Decision

No candidate is promoted. WAIT_DEFAULT remains production. G1-H5 and gold remain blocked.
