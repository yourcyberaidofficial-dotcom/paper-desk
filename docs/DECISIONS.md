# Decisions

2026-10-24: Modular monolith. One process, durable volumes. Microservices rejected for single-VPS scope.

2026-10-24: Separate users volume. Paper ledger stays on its existing volume so account durability does not move the ledger.

2026-10-18: Production remains WAIT_DEFAULT. No strategy has passed promotion gates.

Unresolved: gold OHLC provider, per-user Telegram deep-link, daily digest.
