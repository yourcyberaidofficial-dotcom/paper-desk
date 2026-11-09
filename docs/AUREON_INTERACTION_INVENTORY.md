# Interaction inventory

Statuses after the Chromium run in [AUREON_BROWSER_ACCEPTANCE.md](AUREON_BROWSER_ACCEPTANCE.md). PASS means the control was used in that browser session or, where noted, by the existing API suite. NOT IMPLEMENTED means the control was not added.

| Control | Page | Purpose | Role | Action | Backend | Persistence | Success | Error | Test |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Page search | Nav | Filter nav links | customer, operator | Input filters link text and does not clear a role hide. | None | None | "Risk" stays visible | "No page matches that search." | PASS. Accounts stays hidden for Benny. |
| Aureon AI | Header, every signed-in page | Explain this page from stored facts | signed-in | Opens panel, `POST /api/aureon-ai` | hosted_ai | Activity event only. No customer toggle. | Blocked note. Not an analysis. | Panel says the request failed | PASS. Page in the body was `/overview`. |
| Ask Aureon AI | Live Signals | Same route | signed-in | `data-ask` posts the page and question | `/api/aureon-ai` | None | "Stored record. Not an analysis." and BLOCKED | Button re-enables | PASS |
| Help | Header | Page explanation | signed-in | Opens `#helppanel` | None | None | Overview sentence | Generic sentence | PASS |
| Inbox | Header | Open notices and show the unread count | signed-in | `href="/notifications"` plus count from `/api/notifications` | inbox | Read state | Count fell from 2 to 1 after mark read | Sign-in required | PASS |
| Settings | Header and nav | Open settings | signed-in | `href="/settings"` | profile, prefs, experience | Display and persona | Saved notes | Invalid time zone is not saved | PASS |
| Account chip | Header | Open settings | signed-in | Button navigates to `/settings` | `/api/experience` | None | Name, role, persona | | PASS. Chip read `Benny · customer`. |
| Sign out | Header | End session | signed-in | `POST /api/logout` | session | Clears session | Public landing with Sign in | | PASS |
| Save display | Settings | Persist presentation | signed-in | `POST /api/experience` | user presentation | timezone, density, depth, layout, theme, contrast, motion | Saved, and the attributes changed | "Display settings were not saved." | PASS |
| Save persona and capital | Settings | Trading persona | signed-in | `POST /api/profile` | profile | Apex and USD 1000 | "Saved. Active style..." | Invalid input | PASS. Role stayed customer. |
| Save markets | Settings | Watchlist | signed-in | Existing prefs save | prefs | Markets | Existing | | Existing product tests. |
| Save inbox | Settings | Delivery filters | signed-in | `POST /api/inbox/settings` | inbox_delivery | This account only | Existing confirmation | | Existing inbox tests. |
| AutoPilot buttons | Settings | Paper automation | signed-in | `POST /api/autopilot` | autopilot state | Permission only | Existing | No approved strategy, so entries stay ineligible | Existing. Not a broker. |
| Accounts | Nav, operator only | Directory | operator | `/accounts` and `GET /api/accounts` | user files | None. Read only. | Benny and Adanna, no password hash | Customer sees the refusal | PASS |
| Menu | Narrow layout | Open nav | all | Toggles `aside`. | None | None | Orders opened from the menu at 320px | | PASS |
| Scanner filters | Scanner | Limit the cards | signed-in | Instrument and timeframe selects | None. Filters the loaded scan. | None | XAUUSD 1m only | "No matching card" when nothing matches | PASS |
| Terminal selectors and Evaluate | Terminal | Request a reading | signed-in | `/api/terminal/signal` | terminal | This account | Unavailable reading stated, no invented price | | PASS |
| Manual paper plan | Terminal | Typed paper order | signed-in | `/api/desk/plan` then `/api/paper/orders` | paper book | This account | Paper trade recorded, not a broker fill | Rules can refuse | PASS on the isolated Benny account |
| Mark read | Inbox | Read notice | signed-in | `/api/notifications/read` | notifications | Read flag | Unread count decreased | | PASS |
| Save plan | My Plan | Checklist | signed-in | `POST /api/plan` | plan | This account | "Plan saved." | | PASS |
| Academy complete | Academy | Lesson progress | signed-in | `/api/lab` | lab | This account | Wrong check refused. Correct check stored. | | PASS |
| Lab profile and journal | Trading Lab | Notes | signed-in | `/api/lab` | lab | This account | Saved. Other account does not see the note. | | PASS |
| Close paper trade | Portfolio | Paper exit | signed-in | `/api/paper/close` | paper book | This account | Existing | Missing order refused | Existing. Not clicked in this pass. |

Header language switching, export, pagination, and drag-and-drop widgets are NOT IMPLEMENTED. They were not given dead buttons.

No customer control disables Aureon AI.
