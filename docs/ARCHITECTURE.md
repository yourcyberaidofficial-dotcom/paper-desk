# Architecture

Modular monolith. One Flask process on a Hostinger VPS behind Caddy.

Data:
- desk-data volume: paper ledger at /app/data/paper.
- desk-users volume: user JSON files at /app/data/users.

Modules in ops/: market data, strategy evaluation, council, research lab, users, paper ledger.

No microservices. No billing. No broker adapter.
