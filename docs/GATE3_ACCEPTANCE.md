# Gate 3 acceptance

Recorded after the frozen run in `docs/GATE3_RESULTS.md`. Production is still `WAIT_DEFAULT`. Nothing here is a promotion. Holdout was not opened because no validation window passed.

Base commit for the rules: `a995294` on `gate3-signal-engine`, which contains `3993c08` (PR #78, unmerged). This file is the result record, not a change to the gates.

| Requirement | Method | Observed result | Evidence | Outcome |
|---|---|---|---|---|
| PR #78 safety stays underneath this work | `git` merge-base and `gh pr view 78` | Branch starts at `3993c08`. PR #78 was OPEN and unmerged. Worker send path was not rewritten. | `ops/worker.py` | PASS |
| No close copied into a gold open | `ops/test_engine.py` and `to_chart_candles` | Invalid OHLC is dropped. Chart open stays the provider open. | `ops/bars.py` | PASS |
| Gold weekend is a closed market | Session unit test, America/New_York | Saturday returns `WAIT` / `MARKET_CLOSED`. | `ops/sessions.py` | PASS |
| Gold cash session is explicit | Session unit test | 07:00 New York is `OUTSIDE_SESSION` for `xau-session-20261027`. | `ops/engine_eval.py` | PASS |
| Dukascopy bid/ask when the file decodes | Fixture round-trip | Ask 4066, bid 4065.5. Live hour probe returned HTTP 503, so no ticks were invented. | `docs/GATE3_RESULTS.json` | BLOCKED |
| XAUUSD research path ran | `ops/research_cli.py` | 5695 completed 1h bars, 1233 aggregated 4h bars, quote `ohlc_not_bid_ask`. | `docs/GATE3_RESULTS.md` | PASS |
| Crypto completed candles | Binance public klines | BTC and ETH 35039 fifteen-minute bars, forming bar excluded. | `docs/GATE3_RESULTS.md` | PASS |
| E1 not re-tuned and not approved | Engine snapshot test | Directional E1 is `RESEARCH_OBSERVATION` / `benchmark_failed`. | `ops/engine_eval.py` | PASS |
| No validation pass, so no holdout shopping | Frozen `select_candidate` | BTC, ETH, and XAUUSD: `holdout NOT_OPENED`, `no_validation_pass`. | `docs/GATE3_RESULTS.json` | PASS |
| Gold cannot pass without measured bid/ask | `judge` | Every gold row is `FAIL` or `BLOCKED`, and each carries `no_measured_bid_ask`. | `ops/research_select.py` | PASS |
| A positive point estimate is not enough | Same frozen gates | XAUUSD `vol-break` validation base mean was positive and stress mean was positive, but the normal 95% lower bound was negative, so the judgment stayed `FAIL`. `xau-session` development failed the same uncertainty gate. | `docs/GATE3_RESULTS.json` | PASS |
| No Telegram send for an unapproved event | Routing test with a fake sender | `PAPER_CANDIDATE` under `WAIT_DEFAULT` does not call the sender. | `ops/routing.py` | PASS |
| No bias paper holding | `present_book` and simulate | `LONG_BIAS` open is hidden. Simulator rows have no `paper_open`. | `ops/test_engine.py` | PASS |
| Production and broker | Code constant | `WAIT_DEFAULT`, broker false, approved list empty. | `ops/engine_eval.py` | PASS |
| Tests | `PYTHONPATH=. python3 -m pytest ops/test_*.py tests/test_h4.py -q` | 56 passed. | local pytest | PASS |

Not deployed. No SSH. No production volume change. No real Telegram message.
