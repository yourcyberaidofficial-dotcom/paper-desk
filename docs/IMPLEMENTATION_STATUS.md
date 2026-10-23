# Implementation status

Verified against production commit 275a985ee5db83b7e4cedcd195c0580c3aede202.

| Area | Status | Evidence |
|---|---|---|
| Research lab | VERIFIED | /research shows gates and archive. Promoted count 0. |
| Durable accounts | VERIFIED | durableA logged in after container recreate. |
| Market preferences | PARTIAL | API saves prefs. Persistence not retested after volume change. |
| Gold price | PARTIAL | Cached last known price. Provider limited. |
| Council | VERIFIED | Overview shows WAIT with disagreement reason. |
| Telegram linking | MISSING | No deep-link flow. |
| Daily digest | MISSING | No scheduler. |
| Risk settings | MISSING | Placeholder page. |
| Broker | DISABLED | health.broker is false. |
