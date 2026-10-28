# Gate 5 release sequence

Verified on 2026-10-28 from this checkout, before any merge was attempted.

| PR | Head | Base | State |
|---|---|---|---|
| #78 | `3993c08` `stop-unvalidated-alerts` | `main` | OPEN, mergeable, no GitHub checks |
| #79 | `3d58cfd` `gate3-signal-engine` | `stop-unvalidated-alerts` | OPEN, mergeable, no GitHub checks |
| #80 | `9cff49d` `gate4-bidask` | `gate3-signal-engine` | OPEN, mergeable, no GitHub checks |

`origin/main` was `0400ebc`. `9cff49d` contains `3993c08` and `3d58cfd`. There is no GitHub Actions workflow. Merging a pull request does not deploy the server by itself.

`https://aureontradelab.tech/health` timed out after 20 seconds from this environment. Health was not read. `strategy_status: WAIT_DEFAULT` on an older payload does not prove that #78 is the running code. This health route also does not return a commit id. `experimental_alerts: true` would only show a saved preference.

## Required merge order

Do not merge #79 or #80 into `main` before #78.

```text
gh pr merge 78 --merge
gh pr edit 79 --base main
gh pr merge 79 --merge
gh pr edit 80 --base main
gh pr merge 80 --merge
```

The Gate 5 branch stays a separate pull request. Retarget it to `main` only after #80 is on `main`.

## Deploy, operator only

Not run from this task. Do not `docker compose down -v`. Do not delete `desk-data` or `desk-users`.

On the server, copy the volumes first. Replace the volume names if `docker volume ls` shows a different compose prefix. Do not run `docker volume rm`.

```text
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$HOME/aureon-backup-$stamp/desk-data" "$HOME/aureon-backup-$stamp/desk-users"
docker run --rm -v paper-desk_desk-data:/from -v "$HOME/aureon-backup-$stamp/desk-data":/to alpine cp -a /from/. /to/
docker run --rm -v paper-desk_desk-users:/from -v "$HOME/aureon-backup-$stamp/desk-users":/to alpine cp -a /from/. /to/
```

Then fetch the merge commit, build, and recreate the container without removing volumes:

```text
git fetch origin
git checkout <merge-sha>
docker compose build
docker compose up -d
curl -sS http://127.0.0.1:8080/health
```

Accept the deploy only if `paper_only` is true, `broker` is false, and `strategy_status` is `WAIT_DEFAULT`, and the running tree contains `3993c08` or a descendant. A healthy body without that commit check is not acceptance.
