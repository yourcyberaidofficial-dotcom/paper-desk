# Deployment

Not deployed. No public URL.

Inside the container the app listens on 0.0.0.0:8080. Compose forces DESK_BIND.
On the host, Compose publishes only 127.0.0.1:8080. Port 8080 is not open to the internet.

Access from your laptop:

    ssh -L 8080:127.0.0.1:8080 user@your-vps

Then open http://127.0.0.1:8080 on your laptop.

HTTPS later: Caddy or nginx on the VPS proxies to 127.0.0.1:8080. Do not change the Compose mapping to 0.0.0.0:8080.

Required in .env on the server only:
- DESK_API_TOKEN at least 24 characters. Shorter or empty disables private routes (503).
- TELEGRAM_BOT_TOKEN optional.
- TELEGRAM_CHAT_ID optional.

Do not set DESK_BIND in .env.

Hetzner CX23 is about 5.99 EUR/month. Render free is unsuitable.

## Current release

The public site is https://aureontradelab.tech. Do not deploy while that host does not answer. Restore it from the Hostinger console. Do not open SSH to the public internet, and do not change this Compose file to publish port 8080 on 0.0.0.0.

Before replacing the container:

1. Back up the named volumes `desk-data`, `desk-users` and `desk-shadow`. Do not run `docker compose down -v`.
2. Leave the server `.env` untouched.
3. Build from a clean worktree with `AUREON_BUILD_COMMIT` set to the full commit SHA.
4. Recreate only the app container. The volumes stay mounted.
5. Confirm `https://aureontradelab.tech/version` reports that same SHA.

Rollback is the previous image on the same volumes.

Paper orders live in the users volume at `paper/{user}.json`. A file that is still a JSON list is read as schema 1. Stored entry prices are not rewritten. Gold 1-minute and 3-minute data stay unavailable until a licence allows this desk to display them.
