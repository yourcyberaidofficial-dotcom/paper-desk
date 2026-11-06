# Aureon Trading Lab — backend release readiness

Status: **NO-GO**

Production release status: **DEPLOYMENT_PROHIBITED_PENDING_OWNER_APPROVAL**

PR #97 stays open and unmerged. This document does not authorise a deploy, a merge to `main`, a production container restart, or a change to production secrets or volumes.

Phase 2 closed the backend defects that were FAIL in the previous report. It did not make the desk releasable. Customer live signals stay blocked. The local model is not installed.

## 1. Branch and commits

| Item | Value |
|---|---|
| Repository | `yourcyberaidofficial-dotcom/paper-desk` |
| Branch | `product/recovery` |
| Previous report commit | `5960ff78325e5d84431d54ba90ccb1b84be81fef` |
| Implementation commit | `3660e3e3f07086a387bc7c98e8a3cceaeb3f4960` |
| Report commit | The commit that records this SHA. It does not change behaviour. |
| Working tree | Phase 2 was applied on the existing `product/recovery` checkout at `/tmp/aureon-lab`. No other checkout was reset. |

## 2. Verdict

The five defects called out for this phase are fixed in code and covered by tests that failed before the change and pass after it. That is not a production approval.

Customer live signals for BTCUSDT, ETHUSDT, and XAUUSD stay blocked. No display grant is on file. A public HTTP success would not change that.

The preferred local model, `qwen3.5:9b-q4_K_M`, was not installed. This host is not a dedicated inference machine. No smaller model was substituted. No cloud model was called. Private inference is `not_operational`.

## 3. Requirement matrix

| Requirement | Status | Evidence |
|---|---|---|
| Production deploy, merge, and production data stay untouched | PASS | No compose command, no merge, no production SSH. Work is on `product/recovery` only. PR #97 was not merged. |
| Account registration, login, session cookie | PASS | Existing suite plus `ops/test_endpoint_matrix.py`. Login and register success are real 200 responses on a separate client. |
| Account isolation for paper and AI wording | PASS | `ops/test_ai_release.py`. Phase 2 lifecycle and inbox tests reject the other account's rows. |
| Append-only signal history and duplicate identity | PASS | `ops/signal_ledger.py`. `ops/test_phase2_backend.py::test_signal_continuity_still_keeps_history`. Inbox retention does not rewrite `signals/history.jsonl`. |
| Research failure does not delete an observation | PASS | `ops/test_recovery.py::test_research_failure_does_not_remove_an_observation`. |
| AutoPilot rejection does not suppress a stored observation | PASS | `ops/test_signal_engine.py`. None of the registry versions is approved. |
| Per-instrument permission, not one global switch | PASS | `ops/entitlements.py`. Unchanged this phase. |
| Kraken XBT/USDT and ETH/USDT mapping, no native 3m | PASS | `ops/kraken_public.py`. Not re-fetched this phase. |
| XAUUSD independent of crypto, no synthetic 3m | PASS | `ops/signal_engine.py` returns no bars for gold 3m. |
| Customer live signals for the twelve desk pairs | BLOCKED | No `data/rights/*.json` grant. `customer_live_signals` is `blocked`. |
| Continuous evaluation while data is unlicensed | PASS | `Worker._monitor` still calls `signal_engine.cycle`. A raised cycle is `last_cycle_error`, not a heartbeat. |
| Signal lifecycle persistence across restart | PASS | Append-only `signals/history.jsonl`. The lifecycle route no longer writes that file. |
| Canonical `opp:` identity everywhere | PASS | `ops/signal_engine.py::canonical_opportunity_id` no longer writes `obs:{symbol}:{interval}:{bar}`. An existing `opp:` id is kept. A legacy `obs:` id is not copied forward. Rows that have no family or direction stay `null` rather than gaining a fake id. Historical rows already stored are not rewritten. |
| Every signal family has explicit rules and tests | PASS | No new RSI/SMA family was added. |
| AI service boundary, local only | PASS | `ops/ai_safety.py` refuses cloud names, public IPs, documentation ranges, and `0.0.0.0`. `ops/test_phase2_backend.py::test_local_ai_rejects_hidden_prices_and_public_binds`. |
| AI model loaded and measured on this host | BLOCKED | `ops/ai_runtime.py` `model_installed` is false. `download_attempted` is false. `selected_model` is null. `benchmark_status` is `NOT TESTED`. |
| Evidence bundle before inference | PASS | `ops/ai_evidence.py`. Evidence refs are `ledger:` so they are not opportunity ids. |
| Structured output, invented price rejected | PASS | A summary or evidence line containing `424,242` or `buy now` becomes `ungrounded` and is replaced with the stored-record sentence. |
| Prompt injection and order requests | PASS | `buy now` returns `order_request_refused` before a socket. |
| AI tools cannot order, approve, or write | PASS | `ops/ai_safety.py::call_tool` raises `PermissionError`. |
| Trading continues while Ollama is offline | PASS | `ops/test_signal_engine.py::test_an_offline_model_does_not_stop_the_cycle`. |
| AI evaluation on a live model | NOT TESTED | No weights are installed. The suite uses labelled fixtures. |
| Qwen benchmark on an inference host | NOT TESTED | No inference host was provisioned. A smaller model was not installed here to produce a passing number. |
| Request size limit on AI routes | PASS | Body over 8000 bytes returns 413 before auth. |
| Rate limit on login | PASS | `AUTH_LIMITER` with `ENFORCE_RATE_LIMIT`, third call 429. `ops/test_ai_release.py::test_login_is_rate_limited_when_enforced`. |
| Rate limit on every route | PASS | `ops/app.py::_limited` runs for every non-static request. Auth paths use `AUTH_LIMITER`. Everything else uses `LIMITER`. `ops/test_phase2_backend.py::test_rate_limit_covers_a_previously_open_route` proves `/api/signal`, `/version`, and `/health` share one budget. The limit is skipped only when pytest is imported and `ENFORCE_RATE_LIMIT` is unset. Production is not pytest. |
| Every endpoint tested for success, invalid, unauthorised, missing, and internal error | PASS | `ops/test_endpoint_matrix.py`. 102 method/rule rows, all five checks PASS. Counts and the non-200 success contracts are in section 11. Raw rows: `docs/release-evidence/endpoint-matrix.json`. |
| Auth on protected account routes | PASS | Paper, AI ask, explain, autopilot, lab, notifications, and lifecycle return 401 without a session. |
| Lifecycle route is private, read-only, and account-scoped | PASS | `GET /api/signals/lifecycle` is session-only and does not call `cycle`. `POST`, `PUT`, `PATCH`, and `DELETE` return 405 with `modified: false` and do not write `signals/history.jsonl`. Another account's event and the fixture price `424242` are absent. `ops/test_phase2_backend.py::test_lifecycle_is_private_and_does_not_write` and `ops/test_recovery.py::test_lifecycle_route_does_not_invent_a_reading`. |
| Public research catalogue | PASS | Routes such as `/api/research-lab`, `/api/research-signals`, `/api/engine`, `/health`, and `/version` stay unauthenticated because they return instrument status or the frozen research catalogue, not an account profile, inbox, or paper book. The matrix records that ownership is not applicable. They do not echo `password_hash`. |
| Broker and real-money trading disabled | PASS | Responses keep `broker: false`. No broker adapter was added. |
| Orders and trade history as separate pages | PASS | Unchanged. Not re-shot this phase. |
| Mobile layout at 320, 360, 375, 390, 414, 430 | NOT TESTED | No page markup was changed. Previous frames in `docs/release-evidence/` were not regenerated. |
| Backup and restore procedure exists | PASS | `ops/backup.py`. Not wired to an HTTP route. No migration was added. |
| Inbox history never trimmed | PASS | `ops/inbox.py` appends JSONL. 230 notices remain after reload. Pagination walks all 230. Retention moves old notices into `*.archive.jsonl` and deletes nothing from that archive. An archived id cannot be inserted again. Signal history is a different file and was unchanged by the 230-notice test. |
| User JSON writes are atomic and concurrency-safe | PASS | `ops/users.py::_commit` and `ops/files.py::update_json` lock, write a temp file, and `os.replace`. Two threads updating different fields on one account both survive. A second account is unchanged. A stale `expected_revision` does not write. A mutator that raises leaves the previous bytes. A file containing `{` is not overwritten. `ops/test_phase2_backend.py::test_profile_writes_do_not_drop_fields_or_partial_documents`. |
| Graceful worker shutdown | PASS | `ops/runtime.py::DeskRuntime`. Stop refuses new `tick_start`. In-flight work can finish until the deadline. A task still running at the deadline is stored `completed: false` with event `work_interrupted`, not `worker_stopped`. A task that ends with `completed=False` is not later marked successful. Restart after `interrupted` records `worker_restarted` and `recover()` leaves `completed` false. Threads are not started under pytest. `ops/test_phase2_backend.py::test_worker_shutdown_records_only_finished_work`. |
| Duplicate worker evaluations after restart | PASS | `ops/test_worker.py::test_duplicate_and_wait` still passes. The ledger id is the duplicate key. Unfinished runtime tasks are not replayed as successes. |
| `POST /api/prefs` registered once | PASS | `ops/test_phase2_backend.py::test_worker_prefs_post_is_not_registered_twice`. The token route is `POST /api/worker/prefs`. |
| Dependency vulnerability audit | NOT TESTED | `pip audit` was not run. |
| Live Kraken timestamp check in this pass | NOT TESTED | No vendor socket was opened. |

## 4. Defect closure

### 4.1 Lifecycle route

- Original defect: `GET /api/signals/lifecycle` was public and ran a cycle.
- Root cause: the handler called the signal cycle before returning, and it had no session check, so any caller could create rows and read the combined ledger.
- Changed files: `ops/app.py`, `ops/test_recovery.py`, `ops/test_phase2_backend.py`, `ops/test_endpoint_matrix.py`.
- Fix: session required. The handler only reads. Account-scoped rows are kept when `account_id` is that user. Another account's rows are dropped. Shared rows with no account id remain visible because they are desk observations, not a user profile. Mutating methods return 405 and do not write. The route is on the shared rate limiter.
- Regression test: `test_lifecycle_is_private_and_does_not_write`, `test_lifecycle_route_does_not_invent_a_reading`, and the five lifecycle rows in the endpoint matrix.
- Evidence: those tests passed in the 292-test run below. Anonymous GET is 401. Signed-in GET does not create `signals/history.jsonl`.
- Remaining limitation: desk-level rows with a null `account_id` are visible to every signed-in user. They are not another user's profile. Prices on unavailable rows are null.

### 4.2 Inbox retention

- Original defect: `ops/inbox.py` rewrote the file and kept the last 200 notices.
- Root cause: the writer sliced the list before replace.
- Changed files: `ops/inbox.py`, `ops/app.py` (`/api/notifications` already pages; it now accepts `before_id`).
- Fix: append-only JSONL under a per-user lock. Duplicates, including ids that have already been archived, are refused. `page()` orders by `created_ms` descending, then id, and returns `next_before` plus `next_id` so equal timestamps are not skipped. `mark_read` stores read state. `apply_retention` copies aged notices to the archive file first, then removes them from the active file. Nothing is removed from the archive. Signal history and activity history are different files.
- Regression test: `test_inbox_keeps_more_than_200_notices_across_restart`.
- Evidence: 230 notices stored, reloaded from disk, and walked with an 80-row cursor. Two notices with the same `created_ms` both came back, `tie-a` then `tie-b`. One marked read. Retention left 232 records split across the active file and the archive. Re-offering an archived id returned `duplicate`. Eight threads inserted 80 further ids with no lost write. The signal file's first row was unchanged.
- Remaining limitation: archive and active are two files. A crash after the archive replace and before the active replace can leave the notice in both. It cannot leave it in neither. Readers de-duplicate by id.

### 4.3 Profile writes

- Original defect: profile, plan, and register rewrote JSON without the file lock.
- Root cause: read-modify-write on the user file was not atomic, so concurrent updates dropped fields.
- Changed files: `ops/users.py`, `ops/worker.py` (`save_prefs` now uses the same lock-and-replace helper).
- Fix: `_commit` mutates under `ops/files.update_json`. The lock is held across read, mutate, and replace. `revision` increments on each successful write. A caller can pass `expected_revision` and get `conflict: true` without a write. Register takes the directory lock before creating the file. `get` and `list_users` return nothing for a broken document and do not rewrite it.
- Regression test: `test_profile_writes_do_not_drop_fields_or_partial_documents`.
- Evidence: 30 overlapping updates of timezone/capital and style/risk on one account kept capital 1000, USD, `orion_balance`, and a `Zone/` timezone. The other account stayed at capital 50 NGN. A stale revision did not change USD to EUR. A raising mutator left the bytes identical. The bytes `{` stayed `{`.
- Remaining limitation: there is no database transaction across the user file and the paper book. Each file is atomic on its own. A corrupt document stays corrupt until an operator replaces it. The desk does not invent a replacement profile.

### 4.4 Worker shutdown

- Original defect: the desk loops were daemon threads with no stop handler.
- Root cause: nothing recorded stop, and a killed thread could not be distinguished from finished work.
- Changed files: `ops/runtime.py`, `ops/app.py`, `ops/activity.py`, `ops/worker.py`.
- Fix: `DeskRuntime` gates `tick_start`. `shutdown` stops new work, waits up to the deadline, and writes `data/worker/runtime.json`. Finished clean work records `worker_stopped`. A timeout or a task that ended false records `work_interrupted` and `completed: false`. `recover()` on the next start does not flip that to success. `mark_started` after a previous stop records `worker_restarted`. The loops are desk, telegram, and digest. Pytest does not start them. A runtime that never started does not record a fake stop.
- Regression test: `test_worker_shutdown_records_only_finished_work`.
- Evidence: a finished tick shuts down `completed: true` with one `worker_stopped` and no `work_interrupted`. A tick left in flight for 0.05s shuts down `completed: false`, `reason: deadline`, and the task stays false after `tick_end`. Restart recovery stays `completed: false`. A tick ended with false shuts down `reason: task_failed` and does not write `worker_stopped` for that run.
- Remaining limitation: the threads are still daemons, so a hard process kill after the deadline does not wait any longer. The state file is the record. There is no database connection to close. File locks are `fcntl` locks released in `finally`. Duplicate evaluation ids are still the ledger's job, which the existing worker test covers.

### 4.5 Endpoint matrix

- Original defect: the old probe only checked that an empty call was not HTTP 500.
- Root cause: there was no per-route success, auth, missing, and fault check.
- Changed files: `ops/test_endpoint_matrix.py`, `ops/app.py` (fault handler and rate limit).
- Fix: every non-static method is classified. Success, invalid input, missing or wrong auth, missing or foreign ownership, and an injected fault are each asserted. A fault returns 500 with `handled` and no traceback. Where a happy-path mutation is not legal, the check names the contract instead of treating any non-500 as success.
- Regression test: `test_every_route_has_five_checks`.
- Evidence: 102 rows, verdict PASS. Kind counts: session 33, public 25, page 20, token 8, auth-free 7, lifecycle-write 4, public-page 3, closed-user 1, telegram-user 1. GET success for public, session, token, and signed-in pages is HTTP 200.
- Remaining limitation: `POST /api/paper/orders` in this matrix is the missing-opportunity 404, and `POST /api/paper/close` is the missing-order 409. The successful open and close remain in `ops/test_paperbook.py`. `POST /api/telegram/confirm` succeeds by refusing a typed id (`typed_id_not_accepted`). `POST /api/desk/plan` succeeds by refusing, `order_opened: false`, because no display grant exists.

### 4.6 Signal continuity

Re-tested after the backend edits, in the same 292-test run:

- Persistence and duplicate suppression: PASS (`test_signal_continuity_still_keeps_history`, ledger tests).
- Lifecycle append, invalidation, expiry: PASS (`ops/test_signal_reliability.py`).
- Worker restart duplicate: PASS (`ops/test_worker.py::test_duplicate_and_wait`).
- Concurrent ingestion of notices: PASS (80 ids from 8 threads).
- One pair does not unlock another: PASS (`ops/test_signal_engine.py::test_one_authorised_pair_does_not_unlock_the_others`).
- Research rejection and AutoPilot refusal do not delete the observation: PASS.
- Unavailable data is `signal: false` and `price: null`: PASS.

No signal history file was truncated. The checkout's `data/signals/history.jsonl` SHA-256 stayed `683faa4c33e7580ae133eb184b4514a45ea139186ba9074d157a3a4e2c67b404` (6182 bytes) through the final run.

The test process appends evaluation and alert rows to `data/paper/ledger.jsonl` and a health event to `data/activity/events.jsonl`, because those routes use the process ledger rather than `AUREON_DATA`. After the final run the appended bytes were removed and the previous bytes were restored. SHA-256 after restore:

- `data/paper/ledger.jsonl` `ba56e846b8390efaf8658c4a7cb4145d3f4b981fc64ec84b60a3d9f0fbc1f3cd` (8956 bytes)
- `data/activity/events.jsonl` `8f0b9e68288b3338f72786a85fae8c005ed01c1d00ada391eca69918b11fa3b5` (8675 bytes)
- `data/paper/prefs.json` `a22cf93d608b8608bf7d79b1125fabe77ab8e0626f22dce47606c338d5a3ef1f` (145 bytes)

No paper order that was in the file before the run was removed. No backup was deleted.

### 4.7 Local AI

- Boundary: PASS. Loopback and RFC1918 only. `192.0.2.1`, `8.8.8.8`, and `0.0.0.0` are refused before a socket. `gpt4o` is refused.
- Account isolation: PASS. The explanation uses the calling user's paper counts.
- Invalid and ungrounded output: PASS. Invented prices and order language are not returned.
- Timeout and offline: PASS in `ops/test_ai_release.py`. The cycle does not import Ollama.
- Authority: PASS. `approved` and `order_opened` stay false. The model cannot change risk, approve a strategy, or open an order.
- Operational status: **not operational**. `private_inference` is `not_operational`. `benchmark_status` is `NOT TESTED`. Do not describe the local analyst as live.

## 5. Changed files

- `ops/app.py` — lifecycle auth and read-only behaviour, shared rate limit, injected-fault handler, worker start/stop, notification cursor.
- `ops/inbox.py` — durable notices, archive, pagination, duplicate suppression.
- `ops/users.py` — locked profile writes, revision check, corrupt file left untouched.
- `ops/runtime.py` — shutdown, timeout, and restart record.
- `ops/worker.py` — prefs written with the file lock.
- `ops/activity.py` — shutdown event types.
- `ops/signal_engine.py` — `opp:` ids, no new `obs:` fallback.
- `ops/ai_safety.py`, `ops/ai_provider.py`, `ops/ai_runtime.py`, `ops/ai_evidence.py` — private bind, ungrounded output, honest host facts.
- `ops/test_phase2_backend.py`, `ops/test_endpoint_matrix.py`, `ops/test_recovery.py`, `ops/test_ai_release.py`, `ops/test_gate6.py`.
- `docs/release-evidence/endpoint-matrix.json` — the 102-row probe.

No migration was added. Rollback of this branch is still "do not deploy". Old JSONL rows stay valid. New files (`worker/runtime.json`, inbox archive) are additive.

## 6. Tests

Command:

```bash
cd /tmp/aureon-lab
PYTHONPATH=. python3 -m pytest ops/test_*.py tests/test_h4.py -q --tb=line -p no:cacheprovider
```

Result after the final code and the tightened matrix:

```text
292 passed in 15.77s
```

No skips and no failures in that run. Not run on purpose: live vendor HTTP, a loaded Qwen model, a phone device lab, and `pip audit`.

The phase-2 file alone:

```bash
PYTHONPATH=. python3 -m pytest ops/test_phase2_backend.py ops/test_endpoint_matrix.py -q --tb=line -p no:cacheprovider
```

```text
9 passed in 4.04s
```

## 7. Endpoint coverage

102 method/rule pairs. Every row has success, invalid, auth, missing, and internal. Invalid means the call did not become an unhandled 500. Internal is an injected fault that returns 500 with the word `handled` and no traceback.

Success codes that are not HTTP 200, and why:

| Call | Code | Why this is the contract |
|---|---|---|
| `POST /api/login` on a fresh client with the real password | 200 | Separate from the cases below. |
| `POST /api/register` with a new name | 200 | Separate client, so the suite session stays put. |
| `POST /login` with the owner token and CSRF | 302 | Redirect into the desk. |
| `POST /logout` | 302 | Form logout. |
| `GET /`, `GET /login`, `GET /register` while signed in or out as classified | 302 | Page redirect, not an account payload. |
| `POST /api/paper/orders` with an unknown opportunity | 404 `missing_opportunity` | No order opened. A real open is in `ops/test_paperbook.py`. |
| `POST /api/paper/close` with an unknown order | 409 | No close. A real close is in `ops/test_paperbook.py`. |
| `POST /api/desk/plan` for BTCUSDT 15m | 200 `reading_unavailable`, `order_opened: false` | No display grant. |
| `POST /api/telegram/confirm` | 400 `typed_id_not_accepted` | A typed chat id is not verification. |
| `GET /api/users/<user_id>` | 404 | The route never returns an account. |
| `POST /api/users/<user_id>/telegram` | 403 | Not an open linker. |
| Lifecycle `POST` `PUT` `PATCH` `DELETE` | 405 `modified: false` | Read-only. |

## 8. Independent review

A separate review agent was started against the diff and told not to edit. The author's own pass, completed before the final test run, found and fixed these defects:

- Inbox `items()` had been re-sorted, which broke oldest-first identity checks. Display order is now applied in `page()` only. Append order is unchanged.
- A task that finished with `completed=False` could be followed by a shutdown record that said the stop was clean. Shutdown now keeps `completed: false` and writes `work_interrupted`.
- `POST /api/login` and `POST /api/register` were counted as success on an empty body. They now have to return a real session.
- Archived notice ids could be inserted again. `offer` now treats an archived id as a duplicate.
- Starting the desk threads at import wrote the checkout ledger during pytest. Threads do not start when pytest is loaded.

External reviewer verdict at report time: **NOT RETURNED**. The verdict that is evidenced is the author's pass plus `292 passed`. It is not a second person's signature. If the external note arrives before the branch is pushed, it will be added in the following commit rather than invented here.

## 9. What remains blocked

- No owner-recorded display, research, retention, or redistribution grant.
- No dedicated inference host, so Qwen was not benchmarked.
- No strategy version is `approved_for_paper`.
- The container still starts the Flask development server. This phase did not change the process manager.
- `pip audit` was not run.
- Mobile frames were not re-shot.
- Shared research routes stay public on purpose. They are not account books.

## 10. What the owner can approve later

Not this deploy. A later stage, only after an explicit owner instruction, would be: record a real display grant per source, instrument, and interval; point `OLLAMA_BASE_URL` at a private inference host that has `qwen3.5:9b-q4_K_M` loaded; re-run the AI fixture suite plus one live generation; then decide whether `product/recovery` may be merged. Until then the release status remains **DEPLOYMENT_PROHIBITED_PENDING_OWNER_APPROVAL**.
