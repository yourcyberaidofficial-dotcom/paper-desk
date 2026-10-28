# Gate 6 release identity and shadow switch

No deploy was run. `origin/main` at the start of this change was `1f7f7d2`. Pull request #81 stays open until reviewed. The holdout stays closed. No new strategy was scored.

## What was wrong

`ops/shadow.py` could store a row, but `Worker.evaluate` never called it. A passing unit test was not a prospective process. `/health` did not name the running commit, so `WAIT_DEFAULT` could not prove which tree was deployed.

## Shadow switch

`AUREON_SHADOW` defaults off. Unset, `0`, or any other value does not load market data and does not create the shadow file.

Set `AUREON_SHADOW=1` only after the deployed `build_commit` matches the intended SHA. The worker then asks `evaluate_snapshot` for BTCUSDT 15m, ETHUSDT 15m, and XAUUSD 1h. That is the existing engine. Gate 4 rules are not re-run. Rows go to `data/shadow/observations.jsonl`, which Compose maps to the new `desk-shadow` volume. `desk-data` and `desk-users` are unchanged.

A stale, incomplete, or failed fetch is `DATA_UNAVAILABLE`. A historical window stays `historical_replay` and is not called prospective. E1 remains `RESEARCH_OBSERVATION`. An `APPROVED_SIGNAL` write is stored as `WAIT` / `not_approved` while `data/promotions.json` is absent and production is `WAIT_DEFAULT`. The sender is not called. No `paper_open` is added by this path.

Gold's prospective feed is the existing xaus.com chart. Its quote label stays `ohlc_not_bid_ask`. Dukascopy history is not relabeled as a live bid/ask quote.

## Build identity

The image takes a build argument. It does not read `.git`.

```text
export AUREON_BUILD_COMMIT=$(git rev-parse HEAD)
docker compose build
docker compose up -d
curl -sS http://127.0.0.1:8080/health
```

Accept the process only when `build_commit` is that exact 40-character SHA, `strategy_status` is `WAIT_DEFAULT`, `broker` is false, and `paper_only` is true. `unknown` means the build argument was omitted. Do not treat `unknown` as a match. `/version` returns the same SHA and nothing else useful for this check.

This document does not prove a deployment. The comparison has to be made on the server after a separate authorization.

## Uncertainty

The Gate 4 normal interval is still not a valid interval for overlapping trades. This change does not replace it and does not rescore the old window. A shadow row is an observation, not a profit sample and not a promotion.
