# Aureon Trading Lab — backend release readiness

Status: **NO-GO**

Production release status: **DEPLOYMENT_PROHIBITED_PENDING_OWNER_APPROVAL**

PR #97 stays open and unmerged. This document does not authorise a deploy, a merge to `main`, a production container restart, or a change to production secrets or volumes.

Phase 4 checked the deployment bind, the real rate-limit ceilings, the locked dependency tree, and mobile interactions. It did not make the desk releasable. No model was loaded. Customer live signals stay blocked. Docker was not installed here, so a container publish was not run.

## 1. Branch and commits

| Item | Value |
|---|---|
| Repository | `yourcyberaidofficial-dotcom/paper-desk` |
| Branch | `product/recovery` |
| Phase 2 implementation | `3660e3e3f07086a387bc7c98e8a3cceaeb3f4960` |
| Phase 2 report | `04167f5c8301326a6bafcf66a01719ba3482372d` |
| Phase 3 implementation | `b089c88eacc0a80c573079442c5780b99d4091a3` |
| Phase 3 report | `b49aa62ab7955a9e2d7669a8bbd8f2a686802b35` |
| Phase 4 implementation | `3021c650a7e0d833471879bdda5ae4644b2fae53` |
| Phase 4 report | The commit that adds this text. It does not change behaviour. |
| Working tree | `/tmp/aureon-lab`. No other checkout was reset. PR #97 was not merged. |

## 2. Verdict

The suite after the trusted-proxy fix is **302 passed in 79.23s**. That includes the Phase 2 and Phase 3 tests. It is not a production approval.

Customer live signals for BTCUSDT, ETHUSDT, and XAUUSD stay blocked. No display grant is on file.

No candidate model was installed. This host measured 2 CPU cores, 4,024,496 kB RAM, about 2.67 GiB available at the audit, no swap, and no GPU. Disk free was about 43.6 GiB, which clears the disk part of the refusal floor and does not make the host suitable. The 9B, 4B, and 2B Qwen candidates were not benchmarked. A smaller model was not installed to manufacture a score. Private inference is `BLOCKED`.

## 3. Independent review

A separate review agent inspected the Phase 4 tree and was told not to edit files, not to start Docker, and not to use the public network. It returned one defect and otherwise confirmed the bind contract, the 20-login ceiling, untrusted `X-Forwarded-For`, the private Ollama publish line, foreign-evidence rejection, and that a model reply does not write a signal or an order.

The defect was in `ops/auth.py` `_forwarded_client`. With `DESK_TRUST_PROXY` on, a loopback peer was trusted and the leftmost `X-Forwarded-For` value became the bucket. A caller could rotate that prefix and skip the login ceiling. The function now keeps the rightmost address, which is the hop an appending proxy adds. Compose still does not set `DESK_TRUST_PROXY`. With the flag off, a rotated header does not mint a bucket.

This is not a second human reviewer and it is not an external penetration test. The defect above was reproduced by that agent and fixed in this tree. **Independent review of the Phase 4 diff: received. The one confirmed defect is fixed. NO-GO still stands for the blockers in section 14.**

## 4. Requirement matrix

| Requirement | Status | Evidence |
|---|---|---|
| Production deploy, merge, and production data stay untouched | PASS | No compose up, no merge, no production SSH. PR #97 was OPEN at `b49aa62` before this phase. |
| Phase 2 and Phase 3 behaviour still passes | PASS | 302 passed, including `ops/test_phase2_backend.py` and `ops/test_phase3_verify.py`. |
| Docker container reachable on the published loopback port | NOT TESTED | No `docker` binary and no daemon. Process stand-in is in section 5. |
| Compose command listens inside the container on all interfaces and is answered on loopback | PASS | `DESK_BIND=0.0.0.0` process listens `00000000` and returns 200 on `127.0.0.1`. Default bind listens only `0100007F`. |
| Effective login limit is 20/minute, not the third-call test ceiling | PASS | Section 6. The third-login 429 is a lowered test ceiling. |
| Rate limits under the deployment process, including proxy headers, expiry, and a normal account | PASS | `ops/test_phase4_ops.py` on a non-pytest child. Compose does not set limit overrides or `DESK_TRUST_PROXY`. |
| Locked image dependency tree audited | PASS | `requirements-lock.txt`. `pip-audit --no-deps`: no known vulnerabilities. |
| Mobile pages and interactions at 320, 360, 375, 390, 414, 430 | PASS | Section 8. Layout plus menu, save, inbox, live, and sign-out. |
| Local AI loaded and measured | BLOCKED | No suitable host. No download. Benchmark `NOT TESTED`. |
| Real-model acceptance | NOT TESTED | No weights. Fixture suite is not a live model. |
| Evidence bundle, local-only URL, no order authority | PASS | Fake-transport tests. `ops/signal_engine.py` does not import Ollama. |
| Customer live signals | BLOCKED | Rights matrix: all 12 desk rows blocked. |
| Broker and real-money trading disabled | PASS | `broker` stays false. No broker adapter was added. |
| Independent review of the Phase 4 diff | PASS | One defect, fixed: trusted-proxy identity now uses the appended hop. Not a human penetration test. |

## 5. Docker networking

`docker` is not installed. No container was started. No production compose project was touched.

What the files say, and what a process with the same command showed:

| Fact | Evidence |
|---|---|
| Image command | `python -m ops.app` |
| Image dependencies | `requirements-lock.txt`, not the unpinned `requirements.txt` |
| Container listen | `DESK_BIND=0.0.0.0`, `PORT=8080` |
| Why not 127.0.0.1 inside the container | Docker's published port cannot reach a process that listens only on the container's loopback. The healthcheck uses `http://127.0.0.1:8080/health` from inside the container, which works when the process listens on `0.0.0.0`. |
| Host publish | `127.0.0.1:8080:8080` only |
| Direct `python -m ops.app` | Still defaults to `127.0.0.1` when `DESK_BIND` is unset |
| Process proof | `ops/test_phase4_ops.py`: bind `0.0.0.0` shows `/proc/net/tcp` local address `00000000` and `/version` is 200 on `127.0.0.1`. Bind `127.0.0.1` shows `0100007F` and not `00000000`. |
| Private Ollama publish | `deploy/private-inference/ollama-loopback.compose.yml` publishes `127.0.0.1:11434:11434` only. It was not started. Port 11434 was closed. |

A container smoke test remains **NOT TESTED** until a machine with Docker can run the compose file without `-v` and without a production project name.

## 6. Rate-limit effective configuration

Defaults when `DESK_AUTH_LIMIT` and `DESK_GENERAL_LIMIT` are unset: general **300/minute**, login and register **20/minute**. Window is 60 seconds. `docker-compose.yml` does not set either variable and does not set `DESK_TRUST_PROXY`.

Phase 3's "third login is 429" test lowers `AUTH_LIMITER.per_minute` (to 2 in that case) under `ENFORCE_RATE_LIMIT` inside pytest. That is not the deployment ceiling. A production process does not load pytest, so the limiter is on without that flag.

Proved on a child `python3 -m ops.app` with those variables removed from the environment:

| Check | Result |
|---|---|
| Failed logins | 20 responses are 401. The 21st is 429, body `{"error":"rate_limited","scope":"auth"}`, `Retry-After` >= 1. |
| Spoofed auth identity | The same 429 continues when `X-Forwarded-For` is `203.0.113.51`. |
| General bucket | The access log shows 300 `GET` 200 responses, then 429 `scope=general`. The client may see 299 or 300 of those 200s because a sandbox probe can `GET /` once. |
| Spoofed general identity | A further `GET /version` with `X-Forwarded-For: 203.0.113.50` stays 429. |
| Trusted proxy, appended hop | With `DESK_TRUST_PROXY=1` only, 20 logins that rotate the left address and keep `203.0.113.9` on the right are 401, and the 21st is 429. Compose leaves this flag unset. |
| Expiry | After `Retry-After + 1` seconds on that same process, a failed login is 401 again and `/version` is 200. |
| Normal account | Register, login, then `/overview`, `/signals`, `/orders`, `/history`, `/live`, `/api/me`, `/api/activity`, `/api/ai`, `/api/autopilot`, and `/api/signals/lifecycle` are 200. `/api/me` returns the signed-in name. `/health` without a cookie is 200. Two auth calls do not trip the limit of 20. |

Screenshot servers in sections 7 and 8 set `DESK_GENERAL_LIMIT=5000` so the capture itself was not the proof. That override is not in Compose.

Phase 3 still covers the trusted-proxy flag, the lock under eight threads, and password-not-logged, inside pytest with `ENFORCE_RATE_LIMIT`.

## 7. Dependency audit

Fresh image tree, resolved 2026-11-06 with `pip install --dry-run --ignore-installed --report -r requirements.txt flask` and pinned in `requirements-lock.txt`:

blinker 1.9.0, click 8.5.1, Flask 3.1.3, itsdangerous 2.2.0, Jinja2 3.1.6, MarkupSafe 3.0.4, numpy 2.2.6, pandas 2.3.3, python-dateutil 3.0.0, pytz 2026.6, scipy 1.15.3, six 1.17.0, tzdata 2026.6, Werkzeug 3.1.9.

```bash
python3 -m pip_audit -r requirements-lock.txt --no-deps --progress-spinner=off --disable-pip
```

Result: **No known vulnerabilities found.** The lock is not hashed. `pip-audit` warned about that. Hashes were not added in this phase.

The desk package does not import numpy, pandas, or scipy. They stay in the lock because `requirements.txt` names them and a fresh image would install them. This sandbox's interpreter is missing pandas and scipy, and its click is 8.5.0. Those interpreter facts are not the image tree. The sandbox's Pillow, filelock, pip, and setuptools advisories are not product dependencies and were not upgraded.

## 8. Mobile pages and interactions

Routes, 23, which is the historical 21 plus `/orders` and `/history`:

`/`, `/login`, `/register`, `/overview`, `/signals`, `/trading`, `/strategies`, `/indicators`, `/research`, `/portfolio`, `/risk`, `/activity`, `/live`, `/system`, `/settings`, `/scanner`, `/learn`, `/plan`, `/lab`, `/notifications`, `/onboarding`, `/orders`, `/history`.

Phase 3 layout, already recorded: 23 routes at 320, 360, 375, 390, 414, 430 = 138 frames, HTTP 200, overflow 0, clipped controls 0 after the plan select fix. Evidence: `docs/release-evidence/phase3/`.

Phase 4, isolated `AUREON_DATA`, loopback or container-style bind, workers off:

| Check | Result |
|---|---|
| Pages at 390, then again at 320 | 23 and 21 signed-in routes, overflow 0, clipped 0, no "Loading this page" |
| Menu at 390 and 320 | `nav.open` and `aria-expanded=true`. Orders and signals links inside the viewport. |
| Menu to orders | URL ends in `/orders`. Empty paper book. Not a broker fill. |
| Save profile at 390 | Result text `Saved. Active style and currency are stored on this account.` Later 320 overview shows `Paper capital $1,000.00`. |
| Save plan at 390 | Result text `Plan saved.` Plan page shows `Chosen aim: 1%`. |
| Inbox | Renders the stored scanner notice. Not a live price. |
| System | `No verified reading`. Worker not confirmed. Market data not available. |
| Live | AutoPilot disabled. Permission not active. No invented price. |
| Sign out | Lands on the signed-out home (`Sign in` / `Create account`). |
| Six widths again | `widths.json`: 150 rows (138 pages + menu open + menu to orders at each of 6 widths). Bad rows 0. Every menu opened. Every orders navigation ended on `/orders`. |

The HTML login form was shown at 320 and not submitted in the browser. API register and login were submitted on the deployment-limit process in section 6.

Evidence: `docs/release-evidence/phase4/`. Capture limits were raised and are not the deployment ceilings.

## 9. Local AI hardware and benchmarks

Only this process host was visible. No other always-on machine was attached. Nothing was purchased.

| Measurement | Value |
|---|---|
| Host | `hds-f4ob33x3yubd` |
| Dedicated inference host | no |
| CPU cores | 2 |
| MemTotal | 4,024,496 kB (4,121,083,904 bytes) |
| MemAvailable at the Phase 4 audit | 2,796,652 kB |
| SwapTotal | 0 |
| GPU / VRAM | none (`/dev/nvidia0` absent). VRAM not measured. |
| Disk free | about 43.6 GiB |
| Ollama | not installed. Port 11434 closed. |
| Refusal floor | 8 GiB RAM, 4 cores, 20 GiB free disk. This floor is a stop, not a measured Qwen RSS. |
| This host against that floor | RAM and cores fail. Disk passes. `suitable` is false. |
| Download attempted | no |
| Selected model | none |
| Candidates not pulled | `qwen3.5:9b-q4_K_M`, `qwen3.5:4b-q4_K_M`, `qwen3.5:2b-q4_K_M` |
| Load time, latency, peak RSS, context, concurrency, sustained run, restart | NOT TESTED |

Package for a later dedicated host, not started: `deploy/private-inference/`. It binds Ollama to `0.0.0.0` inside the container and publishes only `127.0.0.1:11434:11434`. Do not add it to the production compose.

The desk gateway that is implemented, and tested only with a fake transport:

- Session required. The client body is not the evidence.
- One inference at a time. A second caller gets `busy`.
- Prompt context clipped. Chat `num_predict` 320, temperature 0, timeout 8 seconds.
- Cloud names and non-local URLs refused before a socket. `http://ollama:11434` is refused. `http://127.0.0.1:11434` is allowed.
- Invented numbers, order language, and evidence ids that are not in the stored facts or refs become `ungrounded` and are replaced. `approved` and `order_opened` stay false.
- A model restart recorded by the watch does not write signals.
- The trading cycle does not import the model.

Fixture score from `ops/ai_eval.py` remains **15 passed, 0 failed**, `live_model=NOT TESTED`. Hello-world is not an accepted case.

Real-model cases (multi-timeframe, stale data, contradictory evidence, prompt injection against weights, timeout, restart, concurrent users) are **NOT TESTED**. The analyst is not operational.

## 10. Live data permissions

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

No vendor was contacted. No trial was accepted. Signal generation does not wait for research promotion, AutoPilot, or Ollama. An unavailable reading is not stored as a price.

## 11. Persistence

`data/signals/history.jsonl` SHA-256 `683faa4c33e7580ae133eb184b4514a45ea139186ba9074d157a3a4e2c67b404` (6182 bytes) after the Phase 4 suite. Unchanged from Phase 2.

The full suite appends to `data/paper/ledger.jsonl` and `data/activity/events.jsonl` when `AUREON_DATA` is unset. The suffix was removed. Prefix hashes match:

- `data/paper/ledger.jsonl` `ba56e846b8390efaf8658c4a7cb4145d3f4b981fc64ec84b60a3d9f0fbc1f3cd` (8956 bytes)
- `data/activity/events.jsonl` `8f0b9e68288b3338f72786a85fae8c005ed01c1d00ada391eca69918b11fa3b5` (8675 bytes)
- `data/paper/prefs.json` `a22cf93d608b8608bf7d79b1125fabe77ab8e0626f22dce47606c338d5a3ef1f` (145 bytes)

No earlier paper row was deleted. `data/` is gitignored. No backup file was deleted.

## 12. Tests

```bash
cd /tmp/aureon-lab
PYTHONPATH=. python3 -m pytest ops/test_*.py tests/test_h4.py -q --tb=line -p no:cacheprovider
```

| Run | Result |
|---|---|
| Phase 2, before the Phase 3 edit | 292 passed |
| Phase 3 | 296 passed |
| Phase 4, after the trusted-proxy fix | 302 passed in 79.23s |

Not run: a Docker daemon, a loaded Qwen model, a phone device lab, a live vendor socket, an external human penetration test.

## 13. Backup and rollback

Do not deploy this SHA.

Rollback is still "do not deploy". The previous report commit is `b49aa62ab7955a9e2d7669a8bbd8f2a686802b35`. Checking that commit back out restores the previous code. It does not delete JSONL rows. Do not run `docker compose down -v`.

When a deploy is later approved, and only then: back up `paper-desk_desk-data`, `paper-desk_desk-users`, and `paper-desk_desk-shadow` first. Leave `OLLAMA_MODEL` unset until a private host has been measured and a real model has passed the live evaluation. Keep PR #97 unmerged until the owner says otherwise.

## 14. Remaining blockers

- No authorised customer market-data grant for BTCUSDT, ETHUSDT, or XAUUSD.
- No private inference host and no measured model. Local AI operational status is BLOCKED. Real-model acceptance is NOT TESTED.
- Docker container publish is NOT TESTED. No daemon in this environment.
- `DESK_COOKIE_SECURE` is off until TLS terminates in front of the desk.
- The lockfile has no hashes. The audit found no known vulnerabilities in the pinned names.
- Sandbox image packages outside the desk dependency set still have advisories.
- Evidence citations match by substring. A very short token that already occurs in the facts is not treated as foreign. This does not make the analyst operational.
