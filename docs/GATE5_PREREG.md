# Gate 5 preregistration

Committed before any new score. There is no new score in this round.

## Decision

No new tradable hypothesis is registered.

Gate 3 and Gate 4 already inspected this window. The London-range row is the only positive point estimate with a non-trivial count, and it has 24 trades. Changing its sample size, stop, or session after that count would be a second look at the same data. The audit also found that the normal interval is not valid under overlapping trades. That is a reason to stop, not a reason to invent a replacement rule.

E1 stays a failed benchmark. The six Gate 4 rules stay frozen and unqualified. `data/holdout_sealed` stays closed. Nothing here can PASS.

## What may be recorded

`ops/shadow.py` may append observations of the rules already frozen in `docs/GATE4_SPEC.md`.

- A row is `historical_replay` or `unavailable`. It is `prospective` only when the caller marks it prospective and the bar is fresh. A stale or historical bar marked prospective is stored as `DATA_UNAVAILABLE`, not as a live signal.
- States stay distinct: `DATA_UNAVAILABLE`, `WAIT`, `RESEARCH_OBSERVATION`, `PAPER_CANDIDATE`. An attempted `APPROVED_SIGNAL` is stored as `WAIT` / `not_approved` while production is `WAIT_DEFAULT`.
- The same strategy, symbol, timeframe, direction, and anchor are one event.
- The file is not the paper ledger. It does not create holdings, orders, or fills.
- Telegram is not called.
- These rows are not a validation sample and cannot be used as a PASS.

## Stopping rule

Do not add another strategy until a later preregistration names a hypothesis that was not chosen from these results. Even then, the sealed holdout stays closed unless that new candidate passes the unchanged validation gates on data that was not used to pick it.
