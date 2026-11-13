# Backup and restore

Aureon stores account JSON on the volumes named `desk-users`, `desk-data` and `desk-shadow`, and the rest of the desk on `desk-signals`, `desk-activity`, `desk-rights`, `desk-cache`, `desk-canonical`, and `desk-ai`. This procedure copies those directories and checks every file before a restore. It does not delete the source, and it does not run `docker compose down -v`.

The code path is `ops.backup`. The host tree at `/opt/aureon` is copied by `ops.volume_backup`. The steps are in `docs/VOLUME_RUNBOOK.md`.

1. Copy one volume directory into an empty backup directory with `create_backup(source, destination)`.
2. `verify_backup(destination)` recomputes SHA-256 for every file in `manifest.json`.
3. Restore only into an empty directory with `restore_backup(backup, destination)`.
4. A checksum mismatch refuses the restore and does not write a partial tree.

Recovery point is the moment the copy was taken. Recovery time is the time to copy the files and recheck the checksums. Those times have not been measured on the production host, so no recovery-time target is claimed.

Do not restore over `/opt/aureon` or a live volume until the public host is reachable and a fresh verified copy exists.
