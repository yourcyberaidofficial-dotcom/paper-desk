# Release procedure

Production was not deployed from this change. `https://aureontradelab.tech/health` timed out, and the last health body that was supplied had no `build_commit`. The experimental Telegram text is produced by `ops/worker.py` at `0400ebc`, which calls the sender when the global experimental flag is on. That commit is what a host without `3993c08` is still running. This tree blocks that text even if the sender is invoked.

Reviewed head after this commit is the `gate5-shadow` branch, pull request #81. Do not deploy a SHA that is not the reviewed merge commit.

## Backup

Do not run `docker volume rm` or `docker compose down -v`.

```text
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$HOME/aureon-backup-$stamp/desk-data" "$HOME/aureon-backup-$stamp/desk-users" "$HOME/aureon-backup-$stamp/desk-shadow"
docker run --rm -v paper-desk_desk-data:/from -v "$HOME/aureon-backup-$stamp/desk-data":/to alpine cp -a /from/. /to/
docker run --rm -v paper-desk_desk-users:/from -v "$HOME/aureon-backup-$stamp/desk-users":/to alpine cp -a /from/. /to/
docker run --rm -v paper-desk_desk-shadow:/from -v "$HOME/aureon-backup-$stamp/desk-shadow":/to alpine cp -a /from/. /to/
```

If a volume name differs, use `docker volume ls` and copy that name. A missing `desk-shadow` volume is not an error on the first deploy of this compose file.

## Build and restart

```text
git fetch origin
git checkout <reviewed-merge-sha>
export AUREON_BUILD_COMMIT=$(git rev-parse HEAD)
docker compose build
docker compose up -d
```

Leave `AUREON_SHADOW` unset. Do not put a promotion list in `data/promotions.json`.

## Accept

```text
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/version
```

Accept only when both `build_commit` values equal `AUREON_BUILD_COMMIT`, `strategy_status` is `WAIT_DEFAULT`, `promotion_registry` is `empty`, `broker` is false, `paper_only` is true, and `shadow` is `disabled`. `unknown` is not a match. `notification.pipeline` must be `blocked`.

## Rollback

```text
git checkout <previous-sha>
export AUREON_BUILD_COMMIT=$(git rev-parse HEAD)
docker compose build
docker compose up -d
```

Restore a volume only from the backup copy above, and only if the new container cannot read the existing volume. Do not delete the live volume first.
