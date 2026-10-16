# G1-H4-r2 report

Run: G1-H4-r2
Prior run G1-H4-pass1 is invalidated and preserved.
Tests: tests/test_h4.py, 4 passed.
Data: development bars SHA-256 3390d4bd75b006a293b864ea03734c95488950b50304549b0e9dd1927f869a6b
Registered/executed: 18/18
Cost monotonicity: true on all six asset/lookback groups.
Holdout: not accessed.
Production: unchanged.

## Decision

ETH lookback 20 is rejected. Other cells have positive unit-risk expectancy after costs, but the totals are small, SPA/White/DSR/PBO were not computed, and no regime test was run. No candidate is promoted. WAIT_DEFAULT remains production.

G1-H5 and gold remain blocked.
