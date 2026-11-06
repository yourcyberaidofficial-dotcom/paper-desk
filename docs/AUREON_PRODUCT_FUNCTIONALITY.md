# Aureon product functionality

Branch `product/experience-transformation`, based on production baseline `eaf78b1bc246d2c47dd3cff72b576cfb71721aea`. Production was not deployed, merged, or restarted. PR #97 stays on `product/recovery` at that same baseline.

The customer product is the Flask desk in [ops/app.py](/tmp/aureon-experience/ops/app.py). It is one authenticated shell. Pages are not separate front-end apps. The signal engine, rights gate, paper book, and personas already existed. This change adds one server-resolved experience profile and a hosted AI boundary. It does not replace those engines.

## Pages

| Page | Route | Implementation | Result |
| --- | --- | --- | --- |
| Landing | `/` | Public marketing page | Existing. Not re-shot. |
| Register | `/register`, `POST /api/register` | Creates an account. Role fields in the body are ignored. | PASS for least privilege. |
| Login | `/login`, `POST /api/login` | Session cookie, HttpOnly, SameSite Lax. | Existing tests still pass. |
| Onboarding | `/onboarding` | Same settings form as Settings, persona and currency first. | Existing. |
| Overview | `/overview` | Account, market, activity. Layout `guided` puts the account first. Layout `market` puts the market card first. | API PASS. Browser arrangement NOT TESTED. |
| Terminal | `/trading` | Manual paper plan. Empty fields are not copied from a feed. | Existing. |
| Scanner | `/scanner` | Coverage only. No invented price. | Existing. |
| Live Signals | `/signals` | Rights gate. Ask Aureon AI card. | Existing plus hosted AI route. |
| Strategies | `/strategies` | Registry. Selection is not approval. | Existing. |
| Research | `/research` | Stored study. Not rescored in the page. | Existing. |
| My Plan | `/plan` | Account checklist. | Existing. |
| Portfolio | `/portfolio` | This account's paper book. | Existing. |
| Orders | `/orders` | Open paper orders only. | Existing. |
| Trade History | `/history` | Closed paper results only. | Existing. |
| Risk | `/risk` | Persona caps already enforced by the paper desk. | Existing. |
| Inbox | `/notifications` | Account notices. Not orders. | Existing. |
| Live Activities | `/live` | Append-only events. | Existing. |
| Settings | `/settings` | Persona, capital, markets, inbox, and display. | Display persistence PASS. |
| System Status | `/system` | Health, worker, hosted AI status. | Hosted status is BLOCKED without credentials. |
| Academy | `/learn` | Lessons on this account. | Existing. |
| Trading Lab | `/lab` | Self-described experience. Not a security role. | Existing. |

`/accounts` is an operator surface, not a twenty-second customer page. A customer who opens it gets the shell and, once the page script runs, the reason administration is refused. That rendered state was not executed in a browser.

## What a customer can change

Display preferences persist on `user["presentation"]` and are returned by `GET /api/experience`. Time zone is also copied onto `profile.timezone` when a profile object already exists. Density, depth, layout, theme, contrast, and motion are stored. The desk script applies them as `data-*` attributes. Overview times go through `when()`, which uses the saved time zone. Concise depth hides elements with class `guide`. Market layout moves the market card before the account card.

A preference cannot change `security_role`, entitlements, broker access, or the rights gate.

## What was not rebuilt

Each of the 21 pages still loads its own existing endpoint. They share the experience strip and the Aureon AI panel. They do not each have a separately designed role theme. There is no widget drag-and-drop editor. English is the only accepted language. Unread count is not shown in the header. Visual acceptance at 320–430px was not repeated for this branch. Older screenshots under `docs/release-evidence/` are the previous build, not this one.
