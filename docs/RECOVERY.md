# Recovery notes for product/recovery

Not deployed. This host is not the production VPS.

## What changed

Market observation, research, and AutoPilot execution are separate labels. A failed study does not delete an observation. Customer prices stay withheld until a recorded grant exists. No candle was invented.

Live Activities reads an append-only file at `$AUREON_DATA/activity/events.jsonl`. Signal identity history is a second append-only file at `$AUREON_DATA/signals/history.jsonl`. Neither file is trimmed. The same observation identity is stored once. A later state is appended and does not rewrite the earlier row. A data-unavailable row has `signal: false` and no price. Notifications being blocked does not remove those events. Heartbeats are stored at most once every five minutes and are not market readings. `worker_started` is stored once.

Local AI is `ops/ollama.py`. It is off unless `OLLAMA_MODEL` is set and that model answers on `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`). A reply cannot approve a strategy or open an order. Client-supplied numbers are not forwarded. If the model is offline, the desk continues.

## Resources measured here

This sandbox, not the VPS: 2 CPUs, about 4 GB RAM, about 2.8 GB available. No Ollama process was installed and no model was downloaded. On the VPS, install one small model only after `MemAvailable` stays above 2 GB with the desk running. Do not install a second model.

## Rollback

The previous commit on `completion/integrated-desk` is `0e61b6f1e4a64cd5b16c9a9e434e9a6e71763258`. Check that branch out and rebuild the same volumes. Do not run `docker compose down -v`. Do not delete `aureon_desk-data`, `aureon_desk-users`, or `aureon_desk-shadow`. The activity file is new. Leaving it in place is safe. Deleting only that file does not change paper orders.

## Production

Not executed. When approved: back up the three named volumes, set `AUREON_BUILD_COMMIT` to the reviewed SHA, rebuild only the app container, and accept `/health` plus `/version`. Leave `OLLAMA_MODEL` unset until the VPS measurement above is done.
