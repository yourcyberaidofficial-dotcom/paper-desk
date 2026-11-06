# Aureon acceptance report

## 1. Git

| Item | Value |
| --- | --- |
| Base | `eaf78b1bc246d2c47dd3cff72b576cfb71721aea` on `product/recovery` |
| Experience implementation | `5b1c77c475798e55c6c913041cb74d417c1562cc` |
| Experience report | `06547d192f4d4533e011270387b32632771cfb95` |
| Verification implementation | `06fa8cf33f6aa3d6777daba89f240e021c6daadb` |
| Verification report | The commit that adds this update. It does not change behaviour. |
| Work branch | `product/experience-transformation` |
| Production | Unchanged. Not deployed, not restarted, not reconfigured. Still `eaf78b1`. |
| PR #97 | Left OPEN on `product/recovery`. This branch was not merged. |
| Recovery worktree | `/tmp/aureon-lab` was not used for this verification. |

## 2. Verdict

The customer shell, role boundary, display preferences, and hosted AI refusal rules were exercised in Chromium. See [AUREON_BROWSER_ACCEPTANCE.md](AUREON_BROWSER_ACCEPTANCE.md).

Backend suite after the fixes: **311 passed**.

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

The independent review of `5b1c77c` found that a configured test transport could accept a two-digit win rate, an order phrase split by a format character, and a foreign identifier written in the summary. Those are now `invalid_output`. A transport is ignored unless the server is configured. The product route still does not accept a transport.

## 8. Independent review

A separate review of `5b1c77c` reported the validation holes above and the search control that cleared `hidden` on the operator link. Both were fixed. That review did not re-run against the fix. The author's browser run is not an independent sign-off of the fix.

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
PYTHONPATH=. python3 ops/browser_acceptance.py
```

Pytest: `311 passed in 79.79s`.

Browser: `56 PASS`, `1 NOT IMPLEMENTED`, `144` layout rows, `0` bad.

## 11. Blockers

- No hosted AI credentials and no `AUREON_AI_SPEND_APPROVED=1`.
- No customer live-market grant.
- No export or pagination control.
- No second independent review of the verification commit.
- Production deployment is not approved. PR #97 stays open and unmerged.

## Gate

The experience branch is verified in a browser for the controls it has. It is not a production release. Live AI is BLOCKED. Do not merge and do not deploy.
