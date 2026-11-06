# Aureon acceptance report

## 1. Git

| Item | Value |
| --- | --- |
| Base | `eaf78b1bc246d2c47dd3cff72b576cfb71721aea` on `product/recovery` |
| Work branch | `product/experience-transformation` |
| Production | Not deployed, not restarted, not reconfigured. Still the reported release `eaf78b1`. |
| PR #97 | Left OPEN. Head remains `product/recovery` at `eaf78b1`. This branch was not merged into it. |
| Recovery worktree | `/tmp/aureon-lab` stayed clean at `eaf78b1`. |

The final commit SHA is recorded in the commit that adds this report. It is not `eaf78b1`.

## 2. Roles and entitlements

`customer` and `operator` only. Operator is `AUREON_OPERATOR_IDS`. Everyone else is a customer, including a user record that says `role: operator`. Personas remain Apex Momentum, Orion Precision, and Aegis Shield. Broker entitlement is false for both roles. Live market display follows the existing rights gate and is not granted by a preference.

## 3. Role-to-page matrix

See [ROLE_EXPERIENCE_MATRIX.md](ROLE_EXPERIENCE_MATRIX.md). Customers get the 21 pages. Operators also get `/accounts`. Restricted administration is explained. It is not an empty control.

## 4. Experience profile

`GET /api/experience` returns the server profile: customer id, account id, membership, security role, status, entitlements, persona, markets, timeframes, learning level, onboarding gaps, presentation, accessibility, notifications, widgets, navigation, AI status, pages, timestamps, migration, and `broker: false`. The browser is not the authority.

## 5. Preference propagation

| Preference | Automated result | Visible UI |
| --- | --- | --- |
| Time zone, density, depth, layout, theme, contrast, motion | PASS. Saved, reloaded after a new login, other account unchanged. | NOT TESTED. No browser rendered the attributes. |
| Persona | PASS. Orion Precision changes the profile and does not change the security role. | NOT TESTED. |
| Operator layout from a customer | PASS. Stored as `market`. | NOT TESTED. |

## 6. Control inventory

See [AUREON_INTERACTION_INVENTORY.md](AUREON_INTERACTION_INVENTORY.md). API-backed controls that already had tests still pass. New header controls are wired. Their clicks were NOT TESTED in a browser.

## 7. Top bar

| Control | Result |
| --- | --- |
| Search | Wired to nav labels. NOT TESTED visually. |
| Aureon AI | API PASS. Opens a panel in the shell. Click NOT TESTED. |
| Inbox | Link to `/notifications`. Existing inbox tests PASS. Header click NOT TESTED. |
| Help | Copy for all 21 areas is in the shell. Click NOT TESTED. |
| Settings | Link. Display save PASS. |
| Account chip | Navigates to settings in script. Click NOT TESTED. |
| Sign out | Existing logout PASS. |
| Unread badge | NOT IMPLEMENTED. |

## 8. Backend integrations

New routes: `GET /api/experience`, `POST /api/experience`, `GET /api/accounts`, `POST /api/aureon-ai`, `GET /accounts`. The endpoint matrix includes them. Anonymous session routes return 401. `/accounts` redirects anonymous users to login. Invalid JSON does not 500.

## 9. AI architecture

See [AUREON_AI_ARCHITECTURE.md](AUREON_AI_ARCHITECTURE.md). Evidence is loaded before inference. The product route cannot inject a transport.

## 10. AI security tests

PASS in `ops/test_experience_product.py`: blocked provider does not call the network; invented price `99999` is rejected; order language is rejected; a foreign evidence citation is rejected; another account id and the name Benny are refused with an empty stored record; `approved` and `order_opened` stay false; the API key is not in the response; the product route with credentials still does not invent an analysis when the socket fails.

## 11. Live provider

**BLOCKED.** No approved credentials and no spend approval. No real model response was evaluated.

## 12. The 21 pages

Routes and existing data loaders remain. They now share the experience strip and the hosted AI panel in the shell source. End-to-end browser proof for every page on this branch: **NOT TESTED**.

## 13. Journeys

| Journey | Result |
| --- | --- |
| A. Register and least-privilege profile | PASS |
| B. Learner dashboard, academy, lab | NOT TESTED as a browser journey. Lab is still not a role. |
| C. Trader terminal through paper history | NOT TESTED as a new browser journey. Existing paper tests still pass. |
| D. Administrator directory | PASS for the read-only API. No entitlement editor was added. |
| E. Preference save, reload, other account | PASS |
| F. AI isolation | PASS against the harness, not a live model |
| G. AI unavailable | PASS. Trading routes were not made to depend on the provider. Market rights gate unchanged. Worker health unchanged. |

## 14. Screenshots

**NOT TESTED.** No Chromium or Playwright was available. Do not use `docs/release-evidence/phase4` as evidence for this branch.

## 15. Persistence and isolation

PASS. Ada's presentation survives a new login. Ben's account stays on the default time zone. Password hashes are absent from the experience and directory payloads. Signal history in this worktree was not a customer history file. The local `data/paper` ledger and prefs were restored after the suite to their pre-run hashes.

## 16. Unresolved defects

- Overview arrangement, theme, contrast, and concise copy are implemented in CSS and script, but no rendered screenshot was inspected.
- Header has no unread count.
- Language cannot be switched. Unsupported codes are rejected rather than translated.
- Operator directory is read-only. There is no audited entitlement editor, because role assignment stays on the server.
- Durable AI spend accounting is not implemented. Counters reset with the process.
- A customer name of four or more characters inside an ordinary question is refused. That is deliberate and can false-positive.
- High-contrast and light theme do not restyle every hard-coded chart colour.

## 17. External approvals still required

Hosted AI provider URL, model, API key, and `AUREON_AI_SPEND_APPROVED=1`. Live market display grants are still unapproved. Production deployment is still not approved. This assignment did not authorise a merge or a restart.

## 18. Migration and rollback

Read-time defaults. History is not rewritten. Rollback: remove the `presentation` object for that user and, if a profile timezone was overwritten by a display save, restore that field from backup. Do not delete ledger, signal, or notification rows. Reverting the git branch removes the routes. The production process is still on `eaf78b1` and does not need a rollback.

## 19. Tests and change summary

`PYTHONPATH=. python3 -m pytest ops/test_*.py tests/test_h4.py -q --tb=line -p no:cacheprovider`

Result: **311 passed**.

Files: `ops/access.py`, `ops/experience.py`, `ops/hosted_ai.py`, `ops/test_experience_product.py`, `ops/users.py`, `ops/activity.py`, `ops/app.py`, `ops/test_endpoint_matrix.py`, `ops/test_signal_reliability.py`, and these docs.

Signal engine source does not import hosted AI. Customer copy no longer says the desk is waiting on "Local AI offline".

## Gate

Engineering of the profile, the role boundary, the display save, and the hosted adapter is in the branch and tested. Live AI is BLOCKED. Visual acceptance is NOT TESTED. Production remains on the previous release.
