# Acceptance matrix

| Workflow | Pass condition |
|---|---|
| Public overview | Shows BTC, ETH, and gold price or explicit stale state. |
| Registration | Creates an account that can log in. |
| Login persistence | Account survives container recreate. |
| Preferences | Saved markets reload after refresh and login. |
| Isolation | User A cannot read User B prefs. |
| Research lab | Shows promoted count 0 and real rejection reasons. |
| Gold freshness | Stale quote is not labeled fresh. |
| Broker | health.broker remains false. |
