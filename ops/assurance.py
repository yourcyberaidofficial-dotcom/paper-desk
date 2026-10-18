"""Transparent assurance score for E1 directional results.

This is not a win probability. It classifies a qualifying directional
result based on available evidence only.
"""

VERSION = "assurance-20261018"


def score_e1(result: str, fresh: bool, bars: int) -> dict:
    if result not in {"LONG_BIAS", "SHORT_BIAS"}:
        return {"score": None, "level": None, "reasons": ["No directional entry."], "version": VERSION}
    score = 50
    reasons = ["E1 entry rule met (+50)."]
    if fresh:
        score += 15
        reasons.append("Market data fresh (+15).")
    else:
        reasons.append("Stale data excluded from higher levels.")
    if bars >= 21:
        score += 10
        reasons.append("Warm-up satisfied (+10).")
    # Single-strategy, unvalidated research cannot reach high.
    score = min(score, 74)
    reasons.append("Not validated research, capped below high.")
    if score >= 85:
        level = "high"
    elif score >= 70:
        level = "medium"
    elif score >= 50:
        level = "watch"
    else:
        level = None
    return {"score": score, "level": level, "reasons": reasons, "version": VERSION}
