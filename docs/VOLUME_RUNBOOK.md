# Volume backup before a deploy

This copies `/opt/aureon` data. It does not delete a file, it does not run `docker compose down -v`, and it does not run `docker volume rm`.

The nine Compose volumes map onto these directories when the host tree is `/opt/aureon`:

| Volume | Host directory |
|---|---|
| desk-data | `/opt/aureon/paper` |
| desk-users | `/opt/aureon/users` |
| desk-shadow | `/opt/aureon/shadow` |
| desk-signals | `/opt/aureon/signals` |
| desk-activity | `/opt/aureon/activity` |
| desk-rights | `/opt/aureon/rights` |
| desk-cache | `/opt/aureon/cache` |
| desk-canonical | `/opt/aureon/canonical` |
| desk-ai | `/opt/aureon/ai` |

`canonical/schema.json` is the data schema stamp. `canonical/readings.json` is the worker's stored market reading. `canonical/worker_status.json` is the worker process heartbeat. `canonical/claims/` is the one-decision-per-candle lock. `canonical/runtime.json` is the worker lifecycle. A heartbeat is not a price. The stamp's `paper_orders` store is still schema 1: excursion, regime, session, and realized R live on the existing paper order rows under `users/paper/`. That file is not a new volume and the guard does not rewrite it.

These files used to sit next to the nine mounts, so a new container lost them. They now sit inside a mounted directory:

| File | Volume |
|---|---|
| `paper/ledger.jsonl`, `paper/promotions.json`, `paper/telegram_inbox.jsonl`, `paper/telegram_offset.txt`, `paper/telegram_updates.jsonl` | desk-data |
| `users/…`, `users/imports/…`, `users/bot/…`, `users/paper/<account>.json` | desk-users |
| `shadow/observations.jsonl` | desk-shadow |
| `canonical/claims/`, `canonical/runtime.json` | desk-canonical |

`DatasetStore` is only given a directory by its caller. It is not a tenth Compose volume.

## Before the image is replaced

1. Leave the current containers running, or pause only the `worker` service if a torn JSON file is not acceptable. Do not remove volumes.
2. If the live data is in named Docker volumes, copy each volume into the matching directory above. A missing volume is skipped, not created and not deleted.
3. Take the checksummed copy:

```text
stamp=$(date -u +%Y%m%dT%H%M%SZ)
python -m ops.volume_backup backup --root /opt/aureon --dest /opt/aureon/backups/$stamp
```

The destination must be empty. The command writes `index.json` plus one directory per volume that existed. Each volume directory has `manifest.json` and `files/`. The source tree is unchanged.

4. Read `index.json`. `data_schema` is the stamp from `canonical/schema.json` when that file was present. Do not deploy an image whose code schema is older than that number. The worker exits without rewriting the files when the on-disk schema is newer than the code.

## Restore

Restore one volume into an empty directory. Then stop writes, replace the live directory only after the copy has been checked, and start the new process. The backup directory itself is not deleted by the script.

```text
python -m ops.volume_backup restore --backup /opt/aureon/backups/$stamp/desk-users --dest /opt/aureon/restore/desk-users
```

A checksum mismatch writes nothing. A destination that already has a file is refused and left as it was.

## What the two containers share

`web` and `worker` mount the same nine volumes. `web` is one gunicorn process with `AUREON_DISABLE_WORKERS=1`. It does not run the desk, Telegram, or digest loops. `worker` runs those loops and writes the canonical reading, the outbox, and the heartbeat file. Customer reads of markets, scanner, desk, workspace, and health use those files.
