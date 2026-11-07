# Aureon acceptance report

## 1. Git

| Item | Value |
| --- | --- |
| Base | `eaf78b1bc246d2c47dd3cff72b576cfb71721aea` on `product/recovery` |
| Experience implementation | `5b1c77c475798e55c6c913041cb74d417c1562cc` |
| Experience report | `06547d192f4d4533e011270387b32632771cfb95` |
| Verification implementation | `06fa8cf33f6aa3d6777daba89f240e021c6daadb` |
| Verification report | `f462d8556a4b9afa195b69832231aa86856b736c` |
| Final gate | The commit that adds the output-validation closure and this report. |
| Work branch | `product/experience-transformation` |
| Production | Unchanged. Not deployed, not restarted, not reconfigured. Still `eaf78b1`. |
| PR #97 | Left OPEN on `product/recovery`. This branch was not merged. |
| Recovery worktree | `/tmp/aureon-lab` was not used for this verification. |

## 2. Verdict

The customer shell, role boundary, display preferences, and hosted AI refusal rules were exercised in Chromium. See [AUREON_BROWSER_ACCEPTANCE.md](AUREON_BROWSER_ACCEPTANCE.md).

Backend suite on this gate: **312 passed**. The earlier 311 figure is the previous commit, not this one.

Live hosted inference: **BLOCKED**. No provider key and no spend approval. No model text was invented for the customer.

Export and pagination: **NOT IMPLEMENTED**.

Production release remains the previous baseline.

## 3. Roles

`customer` and `operator` only. Operator is `AUREON_OPERATOR_IDS`. Browser proof: Benny cannot reveal Accounts in search, cannot open the directory, and a privilege POST is HTTP 403. Adanna sees both names and no password hash. Personas remain Apex Momentum, Orion Precision, and Aegis Shield. Benny's Apex choice did not change his security role.

## 4. Preferences

| Preference | Browser result |
| --- | --- |
| Time zone America/New_York | PASS. Zone label, and it survives reload and a new login. Adanna stays on Africa/Lagos. |
| Compact density | PASS. Card padding 12px. |
| Concise depth | PASS. `.guide` is `display:none`. |
| Market layout | PASS. Market card is before the account card. |
| Light theme | PASS. Page background `rgb(255, 255, 255)`. |
| High contrast | PASS. Stored and applied with the light theme. |
| Reduced motion | PASS. Card transition duration `0s`. |
| Operator layout from Benny | PASS. HTTP 403 when sent with a role field. Adanna can save `operator`. |

## 5. Pages

All 21 routes were opened. The 18 signed-in routes were measured at eight widths. Public landing, login, and register were shot at 390px. Detail is in the browser report. None of those rows overflowed.

## 6. Journeys

| Journey | Result |
| --- | --- |
| Register, login, onboarding, customer role, persona, Overview, Academy, Aureon AI | PASS |
| Academy check, Trading Lab journal and profile | PASS |
| Overview, Terminal, Scanner filter, Signals ask, Plan, Risk, manual paper trade, Portfolio, History | PASS for the path. The paper trade is one isolated open estimate, not a broker fill. |
| Operator directory and system page | PASS. Read only. |
| Preference save, visual effect, reload, new login, other account unchanged | PASS |
| Provider unavailable | PASS. The panel says the model is not configured. Terminal and portfolio still load. |
| Benny cannot see Adanna's data, and Adanna cannot see Benny's journal sentence | PASS |

## 7. AI

Live provider: **BLOCKED**.

The independent review of `5b1c77c` found that a configured test transport could accept a two-digit win rate, an order phrase split by a format character, and a foreign identifier written in the summary. Those are now `invalid_output` on `complete()`, which is the function `POST /api/aureon-ai` calls. A transport is ignored unless the server is configured. The route does not accept a client transport, summary, or approval flag. `approved` and `order_opened` stay false. A hidden character, a spaced or digit-substituted order phrase, a spelled or Roman win rate, and another account name or id are rejected. A sentence that only restates stored facts can still be shown, labelled as commentary, not a signal.

## 8. Independent review

A separate review agent, not the author, probed `ops.hosted_ai.complete` and `POST /api/aureon-ai` on the uncommitted tree. It did not edit files. Its probe log recorded BLOCKED for the two-digit win rate, spaced digits, the spelled rate "eighty", ASCII "LXXX", a zero-width "buy now", "0rder", "sell n0w", "buy it now", the name Benny, "xBenny", a middle-dot spelling of Benny, and "other customer's ledger". The fact sentence "Stored observation is none. Broker is false." was the only rendered analysis. With spend approval unset, the route did not call the provider. A client-supplied summary of "80" came back `invalid_output` and was not in the response. That reviewer returned CASE1 CLOSED, CASE2 CLOSED, CASE3 CLOSED, FOLLOWUP CLOSED, ROUTE CLOSED, UNCONFIGURED CLOSED, NEW_BYPASS none.

This is not a human sign-off. After that probe, three more strings were rejected in the same validators and in `ops/test_experience_product.py`: "iseight", "viii", and "purchase". Those three were not in the completed probe. An older report under `/tmp/aureon-ai-review/report.json` is from 2026-11-06 23:28 UTC and is not evidence for this tree.

## 9. Persistence

This worktree's ignored data was restored after the suite to the pre-run bytes:

- `data/signals/history.jsonl` `2a6d8404a2740a554c2decb79cad8042d44f4e1d5224e140e7319a60f190b4ea` (5711)
- `data/paper/ledger.jsonl` `39e8ff9d97eebc64b56527101419ae4204bc436de32a6477fb8027ed5d58166a` (1172)
- `data/activity/events.jsonl` `d83dcfb4165cd5581743e8e4ba98dfacaa798ce16bed56176940d3cf75ae8ab9` (5495)
- `data/paper/prefs.json` `a22cf93d608b8608bf7d79b1125fabe77ab8e0626f22dce47606c338d5a3ef1f` (145)

The paper trade in the browser report is in `/tmp/aureon-experience-browser`, not in this checkout.

## 10. Tests

```bash
cd /tmp/aureon-experience
PYTHONPATH=. python3 -m pytest ops/test_*.py tests/test_h4.py -q --tb=line -p no:cacheprovider
PYTHONPATH=. python3 -m pytest ops/test_experience_product.py -q --tb=line
AUREON_BROWSER_FOCUS=1 PYTHONPATH=. python3 ops/browser_acceptance.py
```

Pytest for this gate: `312 passed in 80.07s`. Experience file: `10 passed`. The previous commit's `311 passed` is historical.

Chromium for this gate, customer Benny and operator Adanna, isolated data under `/tmp/aureon-experience-browser`: `56 PASS`, `1 NOT IMPLEMENTED`, `18` layout rows at 1280, `0` bad. Evidence is in `docs/release-evidence/experience/gate/`. The earlier eight-width sweep (`144` rows, `0` bad) was not repeated.

## 11. Blockers

- No hosted AI credentials and no `AUREON_AI_SPEND_APPROVED=1`. Live inference stays BLOCKED.
- No customer live-market grant.
- Export and pagination are an intentional exclusion. See the browser report. They are not a failed test.
- Production deployment is not approved. PR #97 stays open and unmerged.

## 12. NOT IMPLEMENTED

`export-and-pagination-controls` is the only non-PASS browser row. The harness looks for a button or link whose text matches export, download csv, next page, or previous page. None is in the shell. Export and pagination were not approved requirements. No placeholder control was added. Disposition: intentional product-scope exclusion, not a missing workflow and not an unrun test.

## Gate

READY FOR MERGE REVIEW of `product/experience-transformation`. Do not merge and do not deploy under this assignment. Live AI is BLOCKED. Production stays `eaf78b1`. PR #97 stays OPEN on `product/recovery`.
