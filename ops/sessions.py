"""XAUUSD spot session clock. Normal closure is not a missing candle."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


def _ny(moment):
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(NEW_YORK)


def gold_market_open(moment):
    """Spot gold follows the New York Sunday 17:00 to Friday 17:00 week."""
    local = _ny(moment)
    weekday = local.weekday()
    minutes = local.hour * 60 + local.minute
    if weekday == 5:
        return False
    if weekday == 6:
        return minutes >= 17 * 60
    if weekday == 4 and minutes >= 17 * 60:
        return False
    return True


def gold_signal_session(moment):
    """Predeclared New York cash window, 08:00 inclusive to 16:00 exclusive."""
    if not gold_market_open(moment):
        return False
    local = _ny(moment)
    if local.weekday() > 4:
        return False
    minutes = local.hour * 60 + local.minute
    return 8 * 60 <= minutes < 16 * 60


def expected_gold_gap(start_ms, end_ms):
    """True when every missing hour sits inside the weekly close."""
    if end_ms <= start_ms:
        return False
    cursor = start_ms + 60 * 60 * 1000
    while cursor < end_ms:
        moment = datetime.fromtimestamp(cursor / 1000, timezone.utc)
        if gold_market_open(moment):
            return False
        cursor += 60 * 60 * 1000
    return True
