# Role and experience matrix

Personas are not security roles. `ops/profiles.py` still defines Apex Momentum, Orion Precision, and Aegis Shield. Those set risk caps and reward floors. `ops/access.py` resolves the security role.

## Security roles that exist

| Role | How it is assigned | Default |
| --- | --- | --- |
| `customer` | Everyone whose account id is not listed in `AUREON_OPERATOR_IDS`. | Yes. Least privilege. |
| `operator` | Server environment only. `AUREON_OPERATOR_IDS` is a comma-separated list of account ids. | No. |

A stored `role` field, a register body, and `POST /api/experience` keys `role`, `security_role`, `entitlements`, `password`, and `id` do not grant anything. The privilege attempt is refused with HTTP 403 and an append-only `privilege_refused` event. Unknown values stay `customer`.

No other security role was invented. Lab values `new`, `developing`, and `independent` remain self-description. They can choose the default layout (`independent` defaults to `market`) and nothing else.

## Entitlements

| Capability | Customer | Operator | Notes |
| --- | --- | --- | --- |
| Paper trading | yes | yes | Still paper only. Broker is false. |
| Academy | yes | yes | |
| Live market display | only if `any_customer_display()` is true | same | The rights gate is unchanged. It is currently false. |
| Hosted AI capability | yes | yes | Capability is not the same as a live model. Live calls are BLOCKED until credentials and spend approval exist. |
| Account administration | no | yes | `GET /api/accounts` returns names and roles. Password hashes are not returned. |
| Broker | no | no | Not a preference. |

## Pages

Customers and operators both receive the 21 customer routes. Operators also receive `/accounts` in navigation. Customers who open `/accounts` are told a display preference cannot grant it. Admin controls are not hidden with an empty button. The reason is in the API body: `allowed: false`.

| Area | Customer | Operator |
| --- | --- | --- |
| Desk, terminal, scanner, signals, research, plan, portfolio, orders, history, risk, inbox, activity, academy, lab | Own account only | Own account only |
| Settings display and persona | Own account | Own account. Operator layout is available only to an operator. |
| System status | Health. Not another customer's book. | Same, plus the directory page. |
| Accounts | Refused, with the reason | Names and roles only. No password, no edits, no entitlement writes. |

There is no in-product screen that changes another account's entitlements. That write path was not added, because the only legitimate role assignment is the server allowlist. Adding a browser form would contradict least privilege.

## Experience profile

`ops/experience.py` `resolve(user)` is the only profile the shell should trust. It includes identity, role, entitlements, persona, markets, timeframes, learning level, onboarding gaps, presentation, accessibility, notification flags, widget order, navigation, AI status, the 21 pages, timestamps, and the migration note.

Widget order is derived, not posted by the browser:

| Layout | Order |
| --- | --- |
| `guided` | account, onboarding, markets, activity, AI |
| `market` | markets, account, activity, AI |
| `operator` | accounts, system, markets, account, AI. Customers who request it are stored as `market`. |

## Preference propagation

| Setting | Stored | Affects | Cannot affect |
| --- | --- | --- | --- |
| Time zone | presentation, and profile when a profile exists | `when()` display | Market candles, signal history |
| Density | presentation | Card padding | Permissions |
| Depth | presentation | Hides `.guide` copy when concise | Risk text that is not marked guide |
| Layout | presentation | Overview card order and the experience strip | Operator tools |
| Theme | presentation | `data-theme` dark, light, or system | |
| Contrast | presentation | Stronger borders and muted colour | |
| Motion | presentation | Disables animation when reduced | |
| Language | `en` only | Other codes are HTTP 400 | No translation catalogue |
| Persona | profile via `/api/profile` | Risk caps and plan eligibility | Security role |
| Markets | prefs | Watchlists already used by the desk | Rights gate |

Another account is not written. Logout and login return the same presentation. Existing user files without `presentation` keep working: the resolver supplies defaults and does not rewrite history until the customer saves.

## Migration and rollback

Migration is additive. Nothing in signal history, the paper ledger, or notifications is rewritten by reading the profile.

Rollback of a display save: delete that user's `presentation` object only. If the save copied `timezone` into an existing `profile.timezone`, restore that one field from backup. Do not delete the user file.
