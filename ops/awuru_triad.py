"""Older combined-desk helper. Not the account-style policy.

Account styles live in ops/profiles.py and come from Awuru's
accounts_personas.py: Apex Momentum, Orion Precision, Aegis Shield.
This function still collapses three research states into one WAIT-biased
summary. It does not mean SMA is the Apex account.
"""

VERSION = "awuru-triad-20261018"


def triad(e1: str, sma: str, rsi: str, fresh: bool) -> dict:
    desks = {
        "apex": sma,
        "orion": e1,
        "aegis": rsi,
    }
    directional = [v for v in desks.values() if v in {"LONG_BIAS", "SHORT_BIAS"}]
    agree = len(set(directional)) == 1 and len(directional) >= 2
    conflict = len(set(directional)) > 1
    if not fresh:
        decision = "WAIT"
        reason = "Stale data. Aegis blocks."
    elif conflict:
        decision = "WAIT"
        reason = "Desk conflict. Protection."
    elif agree and e1 in {"LONG_BIAS", "SHORT_BIAS"}:
        decision = e1
        reason = "Orion confirmed and desks agree."
    else:
        decision = "WAIT"
        reason = "No confirmed agreement."
    return {
        "version": VERSION,
        "desks": desks,
        "decision": decision,
        "reason": reason,
        "agree": agree,
        "conflict": conflict,
    }
