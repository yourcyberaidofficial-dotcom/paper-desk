# Paper Desk

Paper-trading intelligence platform. No broker. No live orders. Default strategy is WAIT because no validated edge exists.

## Run

```bash
PYTHONPATH=. python -m ops.app
```

Open http://localhost:8080

## Telegram

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment. Do not commit them. Without them, alerts return FAILED and never create a paper entry.

## Hosting

Render free sleeps and loses disk. Oracle Always Free can be reclaimed when idle. Deploy the Docker image to a VM you control.

## Research

G0 is frozen. G1 is not authorized. Do not open data/holdout_sealed.
