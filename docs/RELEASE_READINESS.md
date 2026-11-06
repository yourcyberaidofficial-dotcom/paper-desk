# Aureon Trading Lab — backend release readiness

Status: **NO-GO**

Production release status: **DEPLOYMENT_PROHIBITED_PENDING_OWNER_APPROVAL**

PR #97 stays open and unmerged. This document does not authorise a deploy, a merge to `main`, a production container restart, or a change to production secrets or volumes.

Phase 3 verified the Phase 2 backend, closed the rate-limit and file-permission gaps that were only described before, and added a private inference watch. It did not make the desk releasable. Customer live signals stay blocked. No Qwen weights were loaded on this host.

## 1. Branch and commits

| Item | Value |
|---|---|
| Repository | `yourcyberaidofficial-dotcom/paper-desk` |
| Branch | `product/recovery` |
| Phase 2 implementation | `3660e3e3f07086a387bc7c98e8a3cceaeb3f4960` |
| Phase 2 report | `04167f5c8301326a6bafcf66a01719ba3482372d` |
| Phase 3 implementation | `b089c88eacc0a80c573079442c5780b99d4091a3` |
| Phase 3 report | The commit that records this SHA. It does not change behaviour. |
| Working tree | `/tmp/aureon-lab`. No other checkout was reset. PR #97 was not merged. |

## 2. Verdict

The Phase 2 suite was reproduced before any Phase 3 edit: **292 passed**. After the Phase 3 changes the same command passed **296** tests. That is not a production approval.

Customer live signals for BTCUSDT, ETHUSDT, and XAUUSD stay blocked. No display grant is on file. A public HTTP success would not change that.

No candidate model was installed. This host measured 2 CPU cores, 4,024,496 kB RAM, about 2.8 GB available, no swap, and no GPU. The 9B, 4B, and 2B Qwen candidates were not benchmarked. A smaller model was not installed to manufacture a score. Private inference is `not_operational`.

## 3. Independent review

A separate review agent was started against commits `3660e3e` and `04167f5` with instructions to challenge the implementation and not edit the tree. It had not returned a completed report when this document was written. It is **not** marked complete.

The checks below were reproduced by the implementation author. That is not a second human reviewer and it is not an external security audit.

## 4. Requirement matrix

| Requirement | Status | Evidence |
|---|---|---|
| Production deploy, merge, and production data stay untouched | PASS | No compose up, no merge, no production SSH. PR #97 is OPEN. |
| Phase 2 suite reproduced before the edit | PASS | `292 passed in 16.59s` on `04167f5`. |
| Lifecycle route is private, read-only, and account-scoped | PASS | Re-ran `ops/test_phase2_backend.py` and `ops/test_recovery.py`. Anonymous GET is 401. Mutating methods do not write history. |
| Inbox retention, cursor, and concurrent inserts | PASS | Existing `test_inbox_keeps_more_than_200_notices_across_restart` still passes in the 296 run. |
| Profile lock, revision conflict, corrupt file left untouched | PASS | Existing profile test still passes. New writes are mode `0600`. |
| Worker shutdown does not record unfinished work as complete | PASS | Existing runtime test still passes. `/health` sets `worker.status` to `error` when `last_cycle_error` is set, so `healthy` is false. |
| Signal history hash unchanged | PASS | `data/signals/history.jsonl` SHA-256 `683faa4c33e7580ae133eb184b4514a45ea139186ba9074d157a3a4e2c67b404` (6182 bytes) after the final run. |
| Account separation | PASS | Phase 2 lifecycle test plus Phase 3: account B's explanation does not contain account A's persona string. |
| Rate limit enforced, not only configured | PASS | `ops/test_phase3_verify.py` with `ENFORCE_RATE_LIMIT`. See section 5. |
| Production rate-limit configuration | PASS | Limits apply when pytest is not loaded. Compose publishes `127.0.0.1:8080:8080` and does not set `DESK_TRUST_PROXY`. Direct `python -m ops.app` binds `127.0.0.1` unless `DESK_BIND` is set. Compose sets `DESK_BIND=0.0.0.0` inside the container only. |
| Dependency audit of the desk runtime | PASS | `pip-audit` on the installed Flask stack and numpy reported no known vulnerabilities. See section 6. |
| Sandbox packages that the desk does not import | Accepted residual | Pillow, filelock, pip, and setuptools in this image have published advisories. The desk does not import them. They were not upgraded. |
| Mobile layout at 320, 360, 375, 390, 414, 430 | PASS | 23 routes, 138 frames, overflow 0, clipped controls 0. Section 7. |
| AI model loaded and measured | BLOCKED | `model_installed` is false. `download_attempted` is false. `benchmark_status` is `NOT TESTED`. |
| AI fixture evaluation | PASS | 15 labelled cases, 15 passed, live model `NOT TESTED`. A hello-world reply is not an accepted case. |
| AI evaluation on a real private model | NOT TESTED | No weights and no second inference host. |
| Evidence bundle, local-only URL, no order authority | PASS | Existing AI tests plus the fixture suite. `ops/signal_engine.py` does not import Ollama. |
| Customer live signals | BLOCKED | Rights matrix: all 12 desk rows `customer_live_signal` false. |
| Broker and real-money trading disabled | PASS | `broker` stays false. No broker adapter was added. |

## 5. Rate-limit enforcement

Defaults, read at import when the override env vars are unset: general **300/minute**, login and register **20/minute**. The screenshot process set `DESK_GENERAL_LIMIT=5000` so 138 page loads would not trip the limiter. That override is not in `docker-compose.yml`. Compose does not disable the limiter.

Proved with `ENFORCE_RATE_LIMIT` on the real Flask before-request hook:

| Check | Result |
|---|---|
| Login bucket is separate from the general bucket | Third login is 429 with `scope=auth`. `/version` on the general bucket still returns 200. |
| Unauthenticated `/version` and `/health` share the general bucket | Second call from the same socket is 429. |
| Authenticated page and API flow | Register, login, then `/overview`, `/signals`, `/orders`, `/history`, `/live`, `/api/me`, `/api/activity`, `/api/ai`, `/api/autopilot`, `/api/signals/lifecycle` are not 429 while under the ceiling. |
| Client identity | `X-Forwarded-For` from `203.0.113.5` does not open a new bucket. |
| Trusted proxy | Only when `DESK_TRUST_PROXY=1` and the peer is loopback or in `DESK_TRUSTED_PROXIES`. A public peer cannot opt in. |
| 429 body | `{"error":"rate_limited","scope":...}` and `Retry-After` >= 1. |
| Expiry | A 2/minute window rejects, then allows again 61 seconds later. |
| Concurrency | Eight threads cannot record more than 25 allows on a 25/minute key. |
| Password logging | The failed-login body and the activity file do not contain the submitted password. |

`RateLimit.allow` holds a lock and drops keys whose window has expired.

## 6. Dependency and security audit

Command:

```bash
python3 -m pip_audit -r /tmp/aureon-runtime-audit.txt --no-deps --progress-spinner=off
```

Pinned versions audited: numpy 2.2.6, flask 3.1.3, werkzeug 3.1.9, jinja2 3.1.6, markupsafe 3.0.4, itsdangerous 2.2.0, blinker 1.9.0, click 8.5.0.

Result: **No known vulnerabilities found.**

`requirements.txt` also names pandas and scipy. This interpreter does not have them installed, and the desk package does not import numpy, pandas, or scipy. They were not added.

| Finding | Class | Action |
|---|---|---|
| Flask stack CVEs | None found by pip-audit | No upgrade. |
| Pillow, filelock, pip, setuptools advisories in the sandbox image | Not a desk dependency. The application does not import them. | Not upgraded. Accepted residual for this image only. |
| `X-Forwarded-For` accepted from any client | Was a potential limit bypass. | Fixed. Ignored unless the socket peer is a configured proxy. |
| `RateLimit` unsynchronised dict | Potential over-admit under threads. | Fixed with a lock. Tested. |
| User JSON mode inherited from umask | Potential local read of `password_hash`. | `ops/files.py` now writes `0600`. Tested. The hash is Werkzeug's, not the password. |
| Session cookie | `HttpOnly` and `SameSite=Lax`. `Secure` is on only when `DESK_COOKIE_SECURE=1`. | Accepted residual until TLS is in front. Compose publishes loopback, not the public internet. |
| Direct `python -m ops.app` listened on `0.0.0.0` | Potential exposure if the process is started outside Compose. | Default bind is `127.0.0.1`. Compose still sets `DESK_BIND=0.0.0.0` and publishes `127.0.0.1:8080`. |
| Ollama port 11434 | Not installed and not published in Compose. | No change. Client code still refuses public and documentation addresses before a socket. |
| SSRF via hostname | `endpoint_allowed` accepts `localhost` and IP literals that are loopback or RFC1918 only. Userinfo, query, non-HTTP, and other hostnames are refused. | No new hole found in review of that function. Not a full external SSRF test. |
| Unsafe deserialisation | JSON only on the paths reviewed. No pickle on the AI or user-file path. | No change. |
| Worker failure hidden as healthy | Already false when `last_cycle_error` is set. | Reconfirmed by `ops/test_gate6.py`. |

## 7. Mobile regression

The historical list in `ops/test_entitlements.py` is 21 routes and does not include `/orders` or `/history`. Both of those pages exist, so they were included.

Routes: `/`, `/login`, `/register`, `/overview`, `/signals`, `/trading`, `/strategies`, `/indicators`, `/research`, `/portfolio`, `/risk`, `/activity`, `/live`, `/system`, `/settings`, `/scanner`, `/learn`, `/plan`, `/lab`, `/notifications`, `/onboarding`, `/orders`, `/history`.

Widths: 320, 360, 375, 390, 414, 430.

| Result | Value |
|---|---|
| Frames | 138 |
| HTTP status | 200 on every frame after sign-in |
| Horizontal overflow | 0 |
| Controls past the viewport | 0 after the plan select fix |
| Misleading price | Live desk states that no live reading is available. It does not invent a price. |

The first capture clipped `#mode` on `/plan` at 320 because the native select followed its option text. The 900px layout now gives selects `width:100%` and `min-width:0` on the plan form. The second capture is the one recorded.

Frames and `mobile.json` are in `docs/release-evidence/phase3/`. The capture server used an isolated `AUREON_DATA` and did not read production volumes. Its general limit was raised only for the capture, as noted in section 5.

## 8. Local AI

Measured on this host, not assumed:

| Measurement | Value |
|---|---|
| CPU cores | 2 |
| MemTotal | 4,024,496 kB |
| MemAvailable at measurement | 2,813,736 kB |
| SwapTotal | 0 |
| GPU | none (`/dev/nvidia0` absent) |
| Ollama process | not installed, port 11434 closed |
| Download attempted | no |
| Selected model | none |
| Candidates not run | `qwen3.5:9b-q4_K_M`, `qwen3.5:4b-q4_K_M`, `qwen3.5:2b-q4_K_M` |
| Benchmark | NOT TESTED |

The inference gateway that is implemented and tested with a fake loopback transport:

- Session required on `/api/ai/ask` and `/api/explain`. The client body is not the evidence.
- One inference at a time (`inference_concurrency_limit` 1). A second caller gets `busy` and does not open a socket.
- Prompt context is clipped under 4000 characters of evidence JSON.
- Chat timeout is 8 seconds. A timeout is `reason=timeout` and not a price.
- `ops/ai_monitor.py` records RSS and `MemAvailable`, and a transition from offline to online as `model_restarted`. Both flags `signals_modified` and `orders_modified` stay false. The signal ledger is not called.
- Cloud model names and public addresses are refused before a socket.
- Output with `confidence`, `probability`, `win_rate`, `price`, `entry`, `stop`, or `target` is `invalid_output`.
- Prices with commas, scientific notation, or fullwidth digits that are not in the stored facts become `ungrounded` and are replaced.
- Order and approval phrases, including a non-breaking space, are refused.
- The question is not copied into the model payload. A question that names another instrument does not replace the server-selected symbol.
- The trading cycle does not import the model. An offline model does not stop signal evaluation.

Fixture score from `ops/ai_eval.py`: **15 passed, 0 failed**, `live_model=NOT TESTED`, `hello_world_accepted=false`.

This is not a working local analyst. There is no loaded model to score for grounding quality, latency, or concurrency on real weights.

## 9. Live data permissions

`ops/rights_matrix.matrix()` with no grant file: `customer_live_signals=blocked`.

| Instrument | Source adapter | Native intervals present | Customer display | Local AI on the feed |
|---|---|---|---|---|
| BTCUSDT | Kraken public OHLC, not licensed for this desk | 1, 15, 60. No native 3m | false | false |
| ETHUSDT | Kraken public OHLC, not licensed for this desk | 1, 15, 60. No native 3m | false | false |
| XAUUSD | Twelve Data, not licensed for this desk | 1min, 15min, 1h. No native 3m | false | false |

Still required before any customer live reading:

- A written right to display and store Kraken OHLC for XBT/USDT and ETH/USDT at 1m, 15m, and 1h, including derived signal text, or a different source that names those pairs.
- A Twelve Data redistribution or external-display add-on that names XAU/USD at 1min, 15min, and 1h, then `TWELVE_DATA_API_KEY` outside git and a validating `$AUREON_DATA/rights/twelve_data.json`.
- No 3-minute native feed exists for these adapters. None will be synthesised.

Fixtures and a public HTTP 200 are not customer live signals. No vendor was contacted. No trial was accepted.

The Live desk shows permission, freshness, source, research, and AutoPilot as separate facts. An unavailable reading is not labelled as a signal. Signal generation does not wait for research promotion. Confirmed by the existing signal-engine tests in the 296 run and by the live page text in the 390px frame.

## 10. Persistence

`data/signals/history.jsonl` was not rewritten.

The test process appends to `data/paper/ledger.jsonl` and `data/activity/events.jsonl` because those routes use the checkout data directory when `AUREON_DATA` is unset. After the final run the appended suffix was removed. The prefix hashes match the Phase 2 restore:

- `data/paper/ledger.jsonl` `ba56e846b8390efaf8658c4a7cb4145d3f4b981fc64ec84b60a3d9f0fbc1f3cd` (8956 bytes)
- `data/activity/events.jsonl` `8f0b9e68288b3338f72786a85fae8c005ed01c1d00ada391eca69918b11fa3b5` (8675 bytes)
- `data/paper/prefs.json` `a22cf93d608b8608bf7d79b1125fabe77ab8e0626f22dce47606c338d5a3ef1f` (145 bytes)

No earlier paper row was deleted. `data/` is gitignored. No backup file was deleted.

## 11. Tests

```bash
cd /tmp/aureon-lab
PYTHONPATH=. python3 -m pytest ops/test_*.py tests/test_h4.py -q --tb=line -p no:cacheprovider
```

Before the Phase 3 edit: `292 passed in 16.59s`.

After the edit: `296 passed in 15.66s`.

The four new tests are in `ops/test_phase3_verify.py`. They include the enforced rate-limit cases. The rest of the suite still skips the limiter unless `ENFORCE_RATE_LIMIT` is set, which is the point of that flag.

Not run: a loaded Qwen model, a phone device lab, a live vendor socket, an external human penetration test.

## 12. Backup and rollback

Do not deploy this SHA.

Rollback of the branch is still "do not deploy". The previous report commit is `04167f5c8301326a6bafcf66a01719ba3482372d`. Checking that commit back out restores the previous code. It does not delete JSONL rows. New files (`ai/monitor.jsonl`, `ai/watch.json`, inbox archives, `worker/runtime.json`) are additive.

When a deploy is later approved, and only then: back up `paper-desk_desk-data`, `paper-desk_desk-users`, and `paper-desk_desk-shadow` first. Do not run `docker compose down -v`. Leave `OLLAMA_MODEL` unset until a private host has been measured with a real model. Keep PR #97 unmerged until the owner says otherwise.

## 13. Remaining blockers

- No authorised customer market-data grant for BTCUSDT, ETHUSDT, or XAUUSD.
- No private inference host and no measured model. The local analyst is not operational.
- Independent review agent did not return a completed report. No external human review was commissioned.
- `DESK_COOKIE_SECURE` is off until TLS terminates in front of the desk.
- Sandbox image packages outside the desk dependency set still have advisories.
- The full test command appends to the checkout's ignored paper ledger and activity log unless `AUREON_DATA` is set. The suffix from this run was removed. A future run should set `AUREON_DATA` to a temporary directory if those files must stay byte-for-byte still.
