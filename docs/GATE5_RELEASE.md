# Gate 5 release sequence

`origin/main` is now `1f7f7d2`. Pull requests #78, #79, and #80 were merged in that order with merge commits. Pull request #81 was not merged. Nothing was deployed and no SSH session was opened.

| PR | Head | Merge commit | State |
|---|---|---|---|
| #78 | `3993c08` | `ef44f51d4e880701c8c4dd5865ac683d00cde83e` | MERGED into `main` |
| #79 | `3d58cfd` | `424ffdce120f4613289911db2ce088310ec941d4` | MERGED into `main` after #78 |
| #80 | `9cff49d` | `1f7f7d2a46dee37fcfeaf71fb9675e42f8226194` | MERGED into `main` after #79 |
| #81 | `2f40c27` | not merged | OPEN against `main` |

Before those merges, `origin/main` was `0400ebc`. There is no GitHub Actions workflow, so the merges did not deploy the server.

`https://aureontradelab.tech/health` timed out after 20 seconds from this environment. Health was not read. A body that says `WAIT_DEFAULT` would not, by itself, prove which commit is running. This health route does not return a commit id.

## Deploy, operator only

Not run. Do not `docker compose down -v`. Do not delete `desk-data` or `desk-users`.

On the server, copy the volumes first. Replace the volume names if `docker volume ls` shows a different compose prefix. Do not run `docker volume rm`.

```text
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$HOME/aureon-backup-$stamp/desk-data" "$HOME/aureon-backup-$stamp/desk-users"
docker run --rm -v paper-desk_desk-data:/from -v "$HOME/aureon-backup-$stamp/desk-data":/to alpine cp -a /from/. /to/
docker run --rm -v paper-desk_desk-users:/from -v "$HOME/aureon-backup-$stamp/desk-users":/to alpine cp -a /from/. /to/
```

Then fetch the current main commit, build, and recreate the container without removing volumes:

```text
git fetch origin
git checkout 1f7f7d2a46dee37fcfeaf71fb9675e42f8226194
docker compose build
docker compose up -d
curl -sS http://127.0.0.1:8080/health
```

Accept the deploy only if `paper_only` is true, `broker` is false, and `strategy_status` is `WAIT_DEFAULT`, and the running tree is `1f7f7d2` or a descendant that still contains `3993c08`. A healthy body without that commit check is not acceptance. Do not treat this checkout as deployed until that curl is observed on the server.
