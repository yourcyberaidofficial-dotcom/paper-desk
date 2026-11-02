"""Lessons for the signed-in account. A lesson is not a signal and not a firm rule."""

LESSONS = [
    {
        "id": "candles",
        "track": "desk",
        "title": "Completed candles",
        "body": "A candle records the open, high, low and close of a finished period. Aureon does not turn a candle that is still forming into a plan. A missing high, low or close is not enough.",
    },
    {
        "id": "structure",
        "track": "desk",
        "title": "Market structure",
        "body": "Structure is the sequence of swings. A higher high and higher low is one description of an advance. It is not, by itself, an order.",
    },
    {
        "id": "levels",
        "track": "desk",
        "title": "Support, resistance and the plan",
        "body": "A plan names an entry reference, a stop and a target before the trade. Moving the stop after the fact is a different decision. Aureon keeps the original prices on the paper record.",
    },
    {
        "id": "risk",
        "track": "desk",
        "title": "Risk and size",
        "body": "Risk is the amount you can lose if the stop is hit, not the size of the position. BTC and ETH paper quantity is an unrounded estimate. It is not an exchange lot. Gold is not sized without a verified contract.",
    },
    {
        "id": "psychology",
        "track": "desk",
        "title": "Process over outcome",
        "body": "One winning paper trade does not prove a rule. One loss does not prove the rule is useless. The research registry is still experimental. No strategy on this desk is approved.",
    },
    {
        "id": "journal",
        "track": "desk",
        "title": "Journal the real record",
        "body": "Write what you saw, what you did, and what the candle did later. Do not replace an unresolved candle with a guessed exit. An account exit and a candle exit are different events.",
    },
    {
        "id": "prop-what",
        "track": "prop",
        "title": "What a prop challenge is",
        "body": "A proprietary-trading challenge is the firm's own test. Profit targets, daily loss, drawdown, minimum days, news rules and payout rules differ by firm and by account. Aureon does not store a verified firm rulebook.",
    },
    {
        "id": "prop-limits",
        "track": "prop",
        "title": "Limits people fail",
        "body": "Common failures are a daily loss limit, a maximum drawdown, a trailing drawdown, too few trading days, and a consistency rule. Those words are categories. They are not a named firm's current numbers.",
    },
    {
        "id": "prop-honesty",
        "track": "prop",
        "title": "A simulation is not a pass",
        "body": "Comparing your paper trades with a limit you typed is practice. It does not mean a firm accepted you, and it is not affiliation with that firm.",
    },
    {
        "id": "price-action",
        "track": "desk",
        "title": "Price action",
        "body": "Price action is what the completed candles did, not a prediction. A failed break and a pullback are different observations. Aureon names the written rule that matched. If none matched, the result stays no setup.",
    },
    {
        "id": "indicators",
        "track": "desk",
        "title": "Indicators are not the persona",
        "body": "A moving average or RSI can describe past closes. On this desk, E1, SMA20 and RSI14 are a research check. They do not vote for Apex, Orion or Aegis, and they do not approve a strategy.",
    },
    {
        "id": "sessions",
        "track": "desk",
        "title": "Sessions and freshness",
        "body": "A market can be quiet because the session is closed or because the feed is late. Aureon shows the source and the latest completed candle. A periodic candle is not a tick-by-tick stream.",
    },
    {
        "id": "discipline",
        "track": "desk",
        "title": "Discipline is the written limit",
        "body": "The persona caps risk, reward and how many paper orders can be opened. AutoPilot cannot raise those caps. Pausing it stops new paper entries and leaves an open paper position to be monitored.",
    },
    {
        "id": "testing",
        "track": "desk",
        "title": "Testing is not a promise",
        "body": "A backtest looks at past candles. A forward test watches new candles after the rule was written. Neither result on this desk has been promoted. Research status stays experimental until a separate approval record exists. None does.",
    },
    {
        "id": "performance",
        "track": "desk",
        "title": "Read only closed paper trades",
        "body": "Win rate appears only after a paper trade has a recorded result. An unresolved candle, an open position and a notification are not results. Fees in the paper book are 11 basis points per side, and a market exit assumes 2 basis points of adverse slippage. That assumption is not a broker fill.",
    },
    {
        "id": "prop-payout",
        "track": "prop",
        "title": "Payouts and evaluations are the firm's own rules",
        "body": "Profit targets, trailing drawdown, news bans, weekend bans and payout conditions are defined by each firm for a named account. Aureon does not store those numbers as verified. A comparison with your paper trades is practice, not a pass.",
    },
]


def suggestions(lab, performance):
    """Point at unfinished lessons. Do not score skill."""
    lab = lab or {}
    done = set(lab.get("completed_lessons") or [])
    focus = set(lab.get("focus") or [])
    trades = (performance or {}).get("trades") or 0
    ideas = []
    if trades < 5:
        ideas.append({"lesson_id": "journal", "because": "Fewer than five closed paper trades. No strength or weakness is inferred."})
    if "prop" in focus:
        ideas.append({"lesson_id": "prop-honesty", "because": "You asked for prop education. No firm rule is verified."})
    if "risk" in focus:
        ideas.append({"lesson_id": "risk", "because": "You selected risk as a learning interest."})
    for lesson in LESSONS:
        if lesson["id"] not in done and all(item["lesson_id"] != lesson["id"] for item in ideas):
            ideas.append({"lesson_id": lesson["id"], "because": "This lesson is not completed."})
            break
    return [item for item in ideas if item["lesson_id"] not in done][:4]


def catalog():
    return [{**lesson, "verified_firm_rule": False} for lesson in LESSONS]


def public_rules(user):
    lab = (user or {}).get("lab") if isinstance((user or {}).get("lab"), dict) else {}
    custom = []
    for row in lab.get("custom_rules") or []:
        if not isinstance(row, dict) or not row.get("text"):
            continue
        custom.append({
            "text": str(row.get("text"))[:400],
            "status": "entered_by_account",
            "verified": False,
            "note": "Entered by this account. Not confirmed as a firm's rule.",
        })
    return {
        "verified_firm_rules": [],
        "verified_note": "No firm rule is marked verified. Aureon has not checked a current official rulebook into this release.",
        "custom_rules": custom,
    }
