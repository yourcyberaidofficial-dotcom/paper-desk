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
]


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
