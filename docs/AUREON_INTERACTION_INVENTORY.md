# Interaction inventory

Statuses: PASS means the behaviour was executed in the automated suite. NOT TESTED means the control is wired in the shell but no browser clicked it. NOT IMPLEMENTED means it does not exist.

The suite has no Playwright browser in this environment. Phone screenshots from earlier phases are not evidence for this branch.

| Control | Page | Purpose | Role | Action | Backend | Persistence | Success | Error | Test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Page search | Nav | Filter nav links | customer, operator | Input filters link text. Empty state if none match. | None | None | Matching links stay visible | "No page matches" | NOT TESTED in a browser. Source contains `#navsearch`. |
| Aureon AI | Header, every page | Explain this page from stored facts | signed-in | Opens panel, `POST /api/aureon-ai` | hosted_ai | Activity event only. No customer toggle. | Blocked note plus stored record, or commentary | Panel says the request failed | PASS for API. Panel click NOT TESTED. |
| Ask Aureon AI | Live Signals | Same route | signed-in | `data-ask` posts the page and question | `/api/aureon-ai` | None | Labelled commentary or stored record | Button re-enables | API PASS. Click NOT TESTED. |
| Help | Header | Page explanation | signed-in | Opens `#helppanel` with a fixed sentence for each of the 21 areas | None | None | Sentence for that path | Generic sentence | NOT TESTED in a browser. Copy is in the shell. |
| Inbox | Header | Open notices | signed-in | `href="/notifications"` | `/api/notifications` | Read state | Existing inbox | Sign-in required | Existing inbox tests. Header click NOT TESTED. |
| Settings | Header and nav | Open settings | signed-in | `href="/settings"` | profile, prefs, experience | See display row | Settings form | Sign-in required | Page route exists. Click NOT TESTED. |
| Account chip | Header | Open settings | signed-in | Button navigates to `/settings` | `/api/experience` | None | Name, role, persona | Falls back if the profile request fails | NOT TESTED in a browser. |
| Sign out | Header | End session | signed-in | `POST /api/logout` | session | Clears session | Returns to `/` | | Existing logout test. |
| Save display | Settings | Persist presentation | signed-in | `POST /api/experience` | user presentation | timezone, density, depth, layout, theme, contrast, motion | "Saved" and data attributes | "Display settings were not saved." Invalid timezone or theme is HTTP 400 | PASS |
| Save persona and capital | Settings | Trading persona | signed-in | `POST /api/profile` | profile | Persona and caps | Existing save note | Invalid input | PASS that Orion stays a persona, not a role. |
| Save markets | Settings | Watchlist | signed-in | Existing prefs save | prefs | Markets | Existing | | Existing product tests. |
| Save inbox | Settings | Delivery filters | signed-in | `POST /api/inbox/settings` | inbox_delivery | This account only | Existing confirmation | | Existing inbox tests. |
| AutoPilot buttons | Settings | Paper automation | signed-in | `POST /api/autopilot` | autopilot state | Permission only | Existing | No approved strategy, so entries stay ineligible | Existing. Not a broker. |
| Accounts | Nav, operator only | Directory | operator | `/accounts` and `GET /api/accounts` | user files | None. Read only. | Names and roles | Customer sees the refusal reason | PASS for API. Rendered page NOT TESTED. |
| Menu | Narrow layout | Open nav | all | Toggles `aside`. Escape closes it. | None | None | | | NOT TESTED at 320px on this branch. |
| Terminal review and confirm | Terminal | Manual paper order | signed-in | `/api/desk/plan` then `/api/paper/orders` | paper book | This account | Existing | Rules can refuse | Existing. Unchanged. |
| Mark read | Inbox | Read notice | signed-in | `/api/notifications/read` | notifications | Read flag | Existing | | Existing. |
| Close paper trade | Portfolio | Paper exit | signed-in | `/api/paper/close` | paper book | This account | Existing | Missing order refused | Existing. |

Header unread badge, global content search, language switching, and drag-and-drop widgets are NOT IMPLEMENTED. They were not given dead buttons.

No customer control disables Aureon AI.
