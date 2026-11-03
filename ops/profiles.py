"""Recovered Awuru account styles for one Aureon user.

Source: yourcyberaidofficial-dotcom/awuru-goal-signal-engine
backend/app/accounts_personas.py and backend/app/accounts/transformation.py.

The original three selectable identities are Apex Momentum, Orion Precision,
and Aegis Shield. account_number is capped at 3 and the persona index hint
is clamped to 0..2. Titan Structured exists later in that file as a fourth
desk and is not offered here.

Aureon does not run Awuru's VWAP, MACD, ADX, or ATR stack. These profiles
change risk posture and whether the existing E1, SMA20, and RSI14 research
states are eligible to be shown. They never create a production order.
Production remains WAIT_DEFAULT.
"""

PROFILES = {
    "apex_momentum": {
        "key": "apex_momentum",
        "name": "Apex Momentum",
        "role": "Aggressive Momentum Scalper",
        "risk_mode": "aggressive",
        "purpose": "Faster risk budget. The terminal does not use an E1 vote.",
        "confirmation": "Sizes a buy or a sell when reward/risk is at least 1.7, up to 2.5% of capital. Paper orders are allowed on 1m, 3m, 15m and 1h. The entry rule is the same one Orion and Aegis read. The plan stays visible below the floor. The three candle families are not votes.",
        "risk_per_trade_percent": 2.5,
        "max_daily_loss_percent": 4.0,
        "max_open_risk_percent": 5.0,
        "min_rr": 1.7,
        "max_trades_per_day": 5,
        "paper_timeframes": ["1m", "3m", "15m", "1h"],
    },
    "orion_precision": {
        "key": "orion_precision",
        "name": "Orion Precision",
        "role": "Precision Swing Confirmation",
        "risk_mode": "balanced",
        "purpose": "A higher reward floor. A single candle family is not treated as a second vote.",
        "confirmation": "Sizes a buy or a sell when reward/risk is at least 2.0, up to 1.5% of capital. Paper orders are allowed on 15m and 1h, not on the 1m or 3m scalps. The entry rule is not a different strategy. Below the floor the levels stay visible and unsized.",
        "risk_per_trade_percent": 1.5,
        "max_daily_loss_percent": 2.5,
        "max_open_risk_percent": 3.0,
        "min_rr": 2.0,
        "max_trades_per_day": 3,
        "paper_timeframes": ["15m", "1h"],
    },
    "aegis_shield": {
        "key": "aegis_shield",
        "name": "Aegis Shield",
        "role": "Defensive Macro Preservation",
        "risk_mode": "conservative",
        "purpose": "The strictest risk budget. Incomplete evidence is not turned into a hidden veto of the market fact.",
        "confirmation": "Sizes a buy or a sell when reward/risk is at least 2.5, up to 0.8% of capital. Paper orders are allowed on 15m and 1h only. The entry rule is the same shared setup, still experimental. Below the floor the levels stay visible and unsized.",
        "risk_per_trade_percent": 0.8,
        "max_daily_loss_percent": 1.5,
        "max_open_risk_percent": 2.0,
        "min_rr": 2.5,
        "max_trades_per_day": 2,
        "paper_timeframes": ["15m", "1h"],
    },
}

CURRENCIES = ("USD", "NGN", "EUR", "GBP")


def catalog():
    return list(PROFILES.values())


ALIASES = {"orion_balance": "orion_precision"}


def canonical_style(key):
    return ALIASES.get(key, key)


def get_profile(key):
    return PROFILES.get(canonical_style(key))


def risk_cap(key):
    profile = get_profile(key)
    if not profile:
        return None
    return profile["risk_per_trade_percent"]


def evaluate(style, e1, sma, rsi, fresh, symbol="BTCUSDT"):
    """Return a research eligibility decision. Never a production order."""
    spec = PROFILES.get(style)
    result = {
        "style": style if spec else None,
        "name": spec["name"] if spec else None,
        "risk_mode": spec["risk_mode"] if spec else None,
        "production": "WAIT_DEFAULT",
        "validated": False,
        "classification": "research_eligibility",
        "broker": False,
        "votes": {
            "E1-donchian-20": e1,
            "SMA20-state": sma,
            "RSI14-state": rsi,
        },
        "symbol": symbol,
        "fresh": bool(fresh),
        "eligible": False,
        "decision": "WAIT",
    }
    if not spec:
        result["reason"] = "No signal profile selected."
        return result
    if not fresh:
        result["reason"] = "Stale or missing data. No profile may act."
        return result
    directional = [d for d in (e1, sma, rsi) if d in {"LONG_BIAS", "SHORT_BIAS"}]
    conflict = len(set(directional)) > 1
    result["conflict"] = conflict
    if style == "aegis_shield":
        if conflict or len(directional) < 3 or len(set(directional)) != 1:
            result["reason"] = "Research check only. Not the paper-trade rule. The research states do not agree, so this check stays WAIT."
            return result
        result.update(decision=directional[0], eligible=True, reason="Research check only. Not the paper-trade rule. The three research states agree. This does not approve a trade.")
        return result
    if style == "orion_precision":
        if e1 not in {"LONG_BIAS", "SHORT_BIAS"} or conflict or not any(d == e1 for d in (sma, rsi)):
            result["reason"] = "Research check only. Not the paper-trade rule. E1 does not have a matching research state, so this check stays WAIT."
            return result
        result.update(decision=e1, eligible=True, reason="Research check only. Not the paper-trade rule. E1 matches another research state. This does not approve a trade.")
        return result
    if symbol == "XAUUSD" and (conflict or e1 not in {"LONG_BIAS", "SHORT_BIAS"} or len(set(directional)) != 1 or len(directional) < 3):
        result["reason"] = "Apex Momentum does not take gold without full agreement. Aureon has no ATR-expansion check."
        return result
    if e1 in {"LONG_BIAS", "SHORT_BIAS"}:
        note = " Desk conflict is shown and is not hidden." if conflict else ""
        result.update(
            decision=e1,
            eligible=True,
            reason="Research check only. Not the paper-trade rule. Apex can follow an E1 research state. This does not approve a trade." + note,
        )
        return result
    result["reason"] = "E1 is WAIT, so Apex Momentum does not invent a direction."
    return result
