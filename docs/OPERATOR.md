# Operator runbook

This environment could not open SSH to the VPS. Do not paste secrets into a chat.

The deployed health body for `bea2e58` reported an empty promotion registry and a blocked pipeline, while Telegram still showed `EXPERIMENTAL — NOT VALIDATED`. The current source refuses that text before any HTTP call. Two containers created on 17 October, `aureon-desk-run-745559370e7e` and `aureon-desk-run-eb352fb2b77e`, were started with `python -` / `python3 -` and different image digests from the Compose service. They are the remaining process that can still send the old text. `/api/telegram/update` returned 503 because the route required `TELEGRAM_WEBHOOK_SECRET`, which is not set, so Telegram retried the webhook forever and account linking never completed.

Operating mode is long polling inside the Compose service. The public update route now returns 200 and does not link an account unless the webhook secret matches. Polling deletes the webhook once, then reads `getUpdates`. The same `update_id` is stored once.

On the server, after this revision is deployed:

```text
docker ps --format '{{.Names}} {{.Image}} {{.Command}} {{.CreatedAt}}'
```

Stop only a container whose command is `python -` or `python3 -` and whose name starts with `aureon-desk-run-`. Do not remove volumes.

```text
docker stop aureon-desk-run-745559370e7e aureon-desk-run-eb352fb2b77e
```

Leave them stopped so they can be restarted with `docker start` if a rollback is required. Then set polling on for the Compose service only, without printing the bot token:

```text
# in the existing env file, add the name only
# AUREON_TELEGRAM_POLL=1
docker compose up -d
curl -sS http://127.0.0.1:8080/health
```

Accept the host only when `build_commit` is the reviewed SHA, `strategy_status` is `WAIT_DEFAULT`, `promotion_registry` is `empty`, `broker` is false, and `shadow` is `disabled`.
