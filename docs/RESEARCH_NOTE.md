# Engineering notes used by this change

Binance spot kline streams mark a finished candle with `k.x: true`. A stream connection is valid for 24 hours and must be reopened. A candle with `k.x: false` is still forming and is not passed to a closed-bar strategy. Source: the Binance spot WebSocket streams document.

Telegram accepts updates by long polling or by webhook, not both at once. `getUpdates` does not return updates while a webhook is set. `update_id` identifies an update, and an offset one higher than that id confirms it. This app polls and deletes the webhook. Source: Telegram Bot API, getUpdates.

The two spot rules added on 2026-10-28 are long-only because a spot account is not assumed to be able to short. The time-series rule uses the sign of a 24-hour return, the idea surveyed by Moskowitz, Ooi and Pedersen in the Journal of Financial Economics (2012), plus a 20-bar average as confirmation. It is not their portfolio. The range rule is disabled when the 20-bar range is 1.5 percent or wider, so a broken range does not get a fade. Both were scored once on Binance spot 1-hour bars with the existing 11/15 bps costs. The final 20 percent of bars was not read. Neither rule passed. The normal confidence interval used by the judge is not a multiple-testing correction; two rules and two markets were tried, and a pass would still not have been an approval.

The signal workspace reads one shared ledger and explains it separately for each account. A repeated evaluation of the same bar does not create a second row. Replay walks only bars that had already closed, stores `historical_replay`, and never sets delivered, filled, or a profit. A failed strategy cannot be stored as an approved signal. Gold remains chart OHLC, not a verified bid/ask.



OWASP's authentication guidance is why a typed Telegram id is still rejected and the pairing token is stored only as a hash. WCAG status messages are why save and scan results use a text status, not color alone.

The CFTC's AI trading-bot advisory is why the product does not present an unapproved scan as a trade or imply that a target will be reached.
