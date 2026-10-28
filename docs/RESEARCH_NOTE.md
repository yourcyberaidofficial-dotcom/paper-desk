# Engineering notes used by this change

Binance spot kline streams mark a finished candle with `k.x: true`. A stream connection is valid for 24 hours and must be reopened. A candle with `k.x: false` is still forming and is not passed to a closed-bar strategy. Source: the Binance spot WebSocket streams document.

Telegram accepts updates by long polling or by webhook, not both at once. `getUpdates` does not return updates while a webhook is set. `update_id` identifies an update, and an offset one higher than that id confirms it. This app polls and deletes the webhook. Source: Telegram Bot API, getUpdates.

The evidence grade adds fixed checklist weights. It is not a calibrated probability of profit. No separated outcome study was run for it. A weekly aim is stored and displayed. It does not change a strategy result.

OWASP's authentication guidance is why a typed Telegram id is still rejected and the pairing token is stored only as a hash. WCAG status messages are why save and scan results use a text status, not color alone.

The CFTC's AI trading-bot advisory is why the product does not present an unapproved scan as a trade or imply that a target will be reached.
