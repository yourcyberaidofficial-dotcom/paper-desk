# Gate 4 acceptance

Recorded after the frozen run in `docs/GATE4_RESULTS.md`. Production is still `WAIT_DEFAULT`. Nothing here is a promotion. The holdout was not opened because no new validation window passed.

Rules were frozen at `703aa08` on `gate4-bidask`, which contains `3d58cfd` (PR #79, unmerged) and `3993c08` (PR #78, unmerged). This file does not change those gates.

| Requirement | Method | Observed result | Evidence | Outcome |
|---|---|---|---|---|
| PR #78 remains the safety base and is unmerged | `gh pr view 78`, `git merge-base` | PR #78 OPEN at `3993c08`. PR #79 OPEN at `3d58cfd` onto that branch. This branch is not merged and was not deployed. | GitHub PR 78 and 79 | PASS |
| Gold bid and ask stay separate | Dukascopy minute decode and hour builder | 6264 hours. Open is the bid open. Ask open is stored separately. No hour has ask open or ask close below the bid. | `docs/GATE4_XAU_SOURCES.json`, `ops/test_gate4.py` | PASS |
| No synthetic OHLC and no filled minutes | Builder rule and unit tests | An hour is emitted only when both sides have all 60 minutes. Gaps, duplicates, empty files, and crossed prints emit no bar. | `ops/xau_bars.py` | PASS |
| Closed market is not a hole | Session filter on the built hours | 52 gaps, all inside the New York weekly close. Unexpected gaps: 0. Saturday 2026-10-24 file was HTTP 503 and was not invented. | `docs/GATE4_RESULTS.json` | PASS |
| Historical bid/ask is not a live feed | File flag and spot adapter | Built bars are `fresh: false`. xaus.com spot remains `indicative_mid`. | `ops/xau_bars.py`, `ops/feeds.py` | PASS |
| Side-aware fills | Fixture simulation | Long entry is the ask open. Stop is filled before the target. Slippage is two fills. | `ops/test_gate4.py` | PASS |
| Gate 3 crypto reproduced | Binance OHLC sha256 and row compare | All four stored hashes match. All 12 stored crypto judgment rows match. Holdout stayed closed. | `docs/GATE4_RESULTS.json` | PASS |
| Gate 3 xaus gold reproduced | Same chart call and hash | Hash does not match. The 1y window dropped 2025-10-28 00:00 (5695 to 5694 bars). The stored report was not overwritten. | `docs/GATE4_RESULTS.json` | FAIL |
| New rules frozen before scores | Git history | `703aa08` contains `docs/GATE4_SPEC.md` and the hypothesis functions. Scores were written after that commit. | `docs/GATE4_SPEC.md` | PASS |
| No validation pass | Frozen `judge` | Six crypto validation rows are FAIL or BLOCKED. Three gold measured validation rows are FAIL or BLOCKED. | `docs/GATE4_RESULTS.md` | PASS |
| Positive point estimate is not a pass | Same gates | `xau-london-range` validation mean is positive with 24 trades. Sample gate returns BLOCKED. The normal lower bound is also below zero. Holdout was not scored. | `docs/GATE4_RESULTS.json` | PASS |
| Gate 3 families are not reselected | Replay with `selectable=False` | Dukascopy replay selection is `replay_not_selectable`. Old xaus judgments were not edited. | `ops/gate4_research.py` | PASS |
| Assumed gold cost cannot pass | Labeled comparison | 0.50/1.50 USD path is marked not measured and was not allowed to open the holdout. | `docs/GATE4_RESULTS.json` | PASS |
| No holdout shopping | `score_symbol` | Every selection says `holdout NOT_OPENED`. | `docs/GATE4_RESULTS.json` | PASS |
| No promotion, no Telegram, no broker | Constants, routing test, diff | `WAIT_DEFAULT`. `PAPER_CANDIDATE` does not call the sender. `app.py` and `worker.py` were not changed in this round. | `ops/test_gate4.py` | PASS |
| Tests | `PYTHONPATH=. python3 -m pytest ops/test_*.py tests/test_h4.py -q` | 66 passed. | local pytest | PASS |

Not deployed. No SSH. No production volume change. No real Telegram message. No strategy was approved.
