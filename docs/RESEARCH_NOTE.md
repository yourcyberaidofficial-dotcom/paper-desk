# Engineering notes used by this change

Binance spot kline streams mark a finished candle with `k.x: true`. A stream connection is valid for 24 hours and must be reopened. A candle with `k.x: false` is still forming and is not passed to a closed-bar strategy. Source: the Binance spot WebSocket streams document.

Telegram accepts updates by long polling or by webhook, not both at once. `getUpdates` does not return updates while a webhook is set. `update_id` identifies an update, and an offset one higher than that id confirms it. This app polls and deletes the webhook. Source: Telegram Bot API, getUpdates.

The two spot rules added on 2026-10-28 are long-only because a spot account is not assumed to be able to short. The time-series rule uses the sign of a 24-hour return, the idea surveyed by Moskowitz, Ooi and Pedersen in the Journal of Financial Economics (2012), plus a 20-bar average as confirmation. It is not their portfolio. The range rule is disabled when the 20-bar range is 1.5 percent or wider, so a broken range does not get a fade. Both were scored once on Binance spot 1-hour bars with the existing 11/15 bps costs. The final 20 percent of bars was not read. Neither rule passed. The normal confidence interval used by the judge is not a multiple-testing correction; two rules and two markets were tried, and a pass would still not have been an approval.

A 2026 walk-forward study of machine-learning Bitcoin forecasts found that costs of about 10 bps and a bootstrap comparison left no robust win over buy-and-hold (arXiv:2606.00060). That is why this run stayed with two simple spot rules and did not add a model. The session-effect paper at MDPI 1911-8074/19/9/692 could not be read in full from this environment, so its rules were not copied. The gold sample is Dukascopy bid/ask for 3 June through 12 July 2024, not the chart feed.




OWASP's authentication guidance is why a typed Telegram id is still rejected and the pairing token is stored only as a hash. WCAG status messages are why save and scan results use a text status, not color alone.

The CFTC's AI trading-bot advisory is why the product does not present an unapproved scan as a trade or imply that a target will be reached.
