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

1. Back up every named volume under `/opt/aureon` with `python -m ops.volume_backup`. The runbook is `docs/VOLUME_RUNBOOK.md`. The nine volumes are `desk-data`, `desk-users`, `desk-shadow`, `desk-signals`, `desk-activity`, `desk-rights`, `desk-cache`, `desk-canonical`, and `desk-ai`. Do not run `docker compose down -v`.
2. Leave the server `.env` untouched.
3. Build from a clean worktree with `AUREON_BUILD_COMMIT` set to the full commit SHA. That value is a label. `/version` also reports `content_hash`, which is the digest baked from `ops/`, `desk/`, and `requirements-lock.txt`. The two fields are not the same thing.
4. Recreate the `web` and `worker` containers. The volumes stay mounted. `web` is one gunicorn process and does not run the desk loops. `worker` does.
5. Confirm `https://aureontradelab.tech/version` reports that same SHA in `build_commit`, and a 64-character `content_hash` with `content_hash_baked` true. `build_commit_kind` is `label`. `content_hash_kind` is `image`.

Rollback is the previous image on the same volumes.

Paper orders live in the users volume at `paper/{user}.json`. A file that is still a JSON list is read as schema 1. Stored entry prices are not rewritten. Gold 3-minute data stays unavailable. Gold 1-minute, 15-minute and 1-hour Twelve Data candles stay off until `$AUREON_DATA/rights/twelve_data.json` validates. `TWELVE_DATA_API_KEY` belongs in the server environment only. A key, and a grant file, are not a substitute for the signed vendor add-on. This commit is not deployed.
