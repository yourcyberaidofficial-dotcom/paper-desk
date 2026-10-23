# Aureon gap matrix

Verified against production commit cfb106b2bd2e27b528bac3545ae630f3faf5c6b5 on 2026-10-24.

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Research lab with promotion gates | VERIFIED COMPLETE | /research renders gates and archive. Promoted count 0. | Metrics from saved reports, not live recompute. |
| Registration and login | PARTIALLY IMPLEMENTED | /settings shows forms. API works. | User files stored outside the persistent volume. Lost on recreate. |
| Market preferences | PARTIALLY IMPLEMENTED | /api/prefs saves against session. | Same persistence gap. |
| Gold price | PARTIALLY IMPLEMENTED | Cached 4166.1 with fresh=false. | Provider returns usage_exceeded. No daily OHLC. |
| Council | VERIFIED COMPLETE | Overview shows WAIT with disagreement reason. | Research only. Not a signal. |
| Telegram per-user linking | MISSING | No verified deep-link flow. | Requires bot webhook and token store. |
| Daily digest | MISSING | No scheduler. | Depends on durable users and Telegram. |
| Risk settings | MISSING | /risk is a placeholder. | No persisted capital or limits. |
| Promotion | VERIFIED COMPLETE | promoted_count = 0. WAIT_DEFAULT. | No strategy has passed gates. |
