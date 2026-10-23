# Architecture research

Sources consulted: Fowler Monolith First, C4, 12-factor backing services and processes, AWS transactional outbox, Telegram deep links, QuantConnect research notes, Bailey et al. PBO.

Choice: modular monolith.

Reason: single VPS, one Flask process, one Docker volume. Microservices, a message broker, or event sourcing add operational cost without a current need. Domain boundaries (identity, market data, strategy, research, notifications) stay as Python modules with explicit interfaces.

Persistence: mount the entire /app/data tree so user records and paper ledgers survive container replacement. This matches 12-factor backing services treated as attached resources.

Notifications: a durable outbox can be added later as a table under data/. Not required for the current slice.
