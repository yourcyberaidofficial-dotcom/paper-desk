"""Capability registry for one provider use.

Reachability is not a licence. This module does not read DESK_LIVE,
AUREON_DESK_LIVE, or any other environment variable, and it does not open
a network connection. An unverified capability is not approved.
"""

from __future__ import annotations

CAPABILITIES = (
    "quote_display",
    "candle_display",
    "sampled_reference_display",
    "indicator_calculation",
    "customer_reading",
    "opportunity_generation",
    "manual_plan_review",
    "paper_ledger_persistence",
    "raw_data_retention",
    "research_backtest",
    "notifications",
    "autopilot",
)

STATES = frozenset({"verified", "unverified", "restricted", "unavailable"})

# Legacy ops.data_rights.use_permission names. One observation allowance
# does not grant the next capability.
LEGACY_USES = frozenset({
    "connection",
    "memory",
    "display",
    "indicators",
    "strategy",
    "retention",
    "research",
    "notification",
    "autopilot",
    "redistribution",
})

OBSERVE_LEGACY = frozenset({"connection", "memory", "display", "indicators", "strategy"})

PERSISTENCE_CAPABILITIES = frozenset({
    "paper_ledger_persistence",
    "raw_data_retention",
    "research_backtest",
    "notifications",
    "autopilot",
    "opportunity_generation",
    "manual_plan_review",
})

# Internal calculation may still run so a typed plan can be refused when it
# copies the feed. Customer HTTP responses do not render these readings.
# operational_observation is not a customer-display grant.
OBSERVATION_OPERATIONAL = {
    "binance_spot_rest_klines": frozenset({
        "candle_display",
        "indicator_calculation",
        "customer_reading",
    }),
    "xaus_public_chart": frozenset({
        "candle_display",
        "sampled_reference_display",
        "indicator_calculation",
        "customer_reading",
    }),
    "xaus_spot_samples": frozenset({
        "sampled_reference_display",
        "indicator_calculation",
        "customer_reading",
    }),
}

OBSERVE_SOURCES = frozenset(OBSERVATION_OPERATIONAL)

MARKET_SOURCE_IDS = frozenset({
    "binance_spot_rest_klines",
    "binance_vision_klines",
    "xaus_public_chart",
    "xaus_spot_samples",
    "swissquote_public_bbo",
    "dukascopy_datafeed_bi5",
})

MARKET_PROVIDERS = frozenset({
    "binance-public",
    "binance",
    "xaus.com",
    "swissquote-public-bbo",
    "dukascopy",
})

SOURCE_ALIAS = {
    "xaus_spot_samples": "xaus_spot_samples",
}

ELIGIBILITY_NOTE = (
    "Eligibility recorded for this snapshot. Market levels stay on this screen only. "
    "Paper history was not written because paper ledger persistence is unverified."
)


def _decision(allowed, status, reason, *, source_id, use, verified=False, operational=False):
    if status not in STATES:
        status = "unverified"
    return {
        "allowed": bool(allowed) and status == "verified",
        "status": status,
        "reason": reason,
        "use": use,
        "source": source_id,
        "verified": bool(verified) and status == "verified" and bool(allowed),
        "operational_observation": bool(operational) and status == "unverified" and not verified,
    }


def decide_use(source_id, use, *, symbol=None, interval=None):
    """Judge one capability. Never promotes unverified to verified."""
    source_id = SOURCE_ALIAS.get(source_id, source_id)
    if symbol == "XAUUSD" and interval in {"1m", "3m"}:
        return _decision(False, "unavailable", "xau_minute_unlicensed", source_id=source_id, use=use)
    if use not in CAPABILITIES:
        return _decision(False, "unverified", "missing_or_malformed_rights", source_id=source_id, use=use)
    if source_id == "swissquote_public_bbo":
        return _decision(False, "restricted", "restricted", source_id=source_id, use=use)
    if source_id == "binance_vision_klines":
        return _decision(False, "restricted", "prohibited", source_id=source_id, use=use)
    if source_id == "dukascopy_datafeed_bi5":
        return _decision(False, "unverified", "commercial_use_unverified", source_id=source_id, use=use)
    if source_id not in OBSERVE_SOURCES and source_id != "user_authored":
        return _decision(
            False,
            "unverified",
            "unknown_source" if source_id not in MARKET_SOURCE_IDS else "commercial_use_unverified",
            source_id=source_id,
            use=use,
        )
    if source_id == "user_authored":
        if use == "paper_ledger_persistence":
            return _decision(True, "verified", "account_supplied_levels", source_id=source_id, use=use, verified=True)
        return _decision(False, "unavailable", "not_a_market_source", source_id=source_id, use=use)
    if source_id == "binance_spot_rest_klines" and use in {"quote_display", "sampled_reference_display"}:
        return _decision(False, "unavailable", "not_supplied", source_id=source_id, use=use)
    if source_id == "xaus_spot_samples" and use in {"quote_display", "candle_display"}:
        return _decision(False, "unavailable", "not_supplied", source_id=source_id, use=use)
    if source_id == "xaus_public_chart" and use == "quote_display":
        return _decision(False, "unavailable", "not_supplied", source_id=source_id, use=use)
    operational = use in OBSERVATION_OPERATIONAL.get(source_id, frozenset())
    if use in PERSISTENCE_CAPABILITIES or not operational:
        return _decision(False, "unverified", "unverified", source_id=source_id, use=use)
    return _decision(False, "unverified", "unverified_observation", source_id=source_id, use=use, operational=True)


def legacy_decision(source_id, use):
    """Map an old use name. DESK_LIVE is not consulted."""
    source_id = SOURCE_ALIAS.get(source_id, source_id)
    if use not in LEGACY_USES:
        return _decision(False, "unverified", "missing_or_malformed_rights", source_id=source_id, use=use)
    if source_id == "swissquote_public_bbo":
        return _decision(False, "restricted", "restricted", source_id=source_id, use=use)
    if source_id == "binance_vision_klines":
        return _decision(False, "restricted", "prohibited", source_id=source_id, use=use)
    if source_id == "dukascopy_datafeed_bi5":
        return _decision(False, "unverified", "commercial_use_unverified", source_id=source_id, use=use)
    if use not in OBSERVE_LEGACY:
        return _decision(False, "unverified", "unverified", source_id=source_id, use=use)
    if source_id in OBSERVE_SOURCES:
        # Internal observation only. allowed in the legacy audit row lets a
        # calculation run. It does not release a customer response, and
        # verified stays false. DESK_LIVE is not read.
        row = _decision(False, "unverified", "unverified_observation", source_id=source_id, use=use, operational=True)
        row["allowed"] = True
        row["verified"] = False
        return row
    return _decision(False, "unverified", "unknown_source", source_id=source_id, use=use)


def is_feed_derived(row):
    """True when levels came from a market source.

    A row the account authored, with source_id user_authored, is not feed-derived.
    A missing source id is not treated as a market source, so older account rows stay readable.
    """
    row = row or {}
    if row.get("provenance") == "user_authored" and row.get("source_id") == "user_authored":
        return False
    if row.get("levels_persisted") is False:
        return True
    if row.get("source_id") in MARKET_SOURCE_IDS:
        return True
    provider = str(row.get("provider") or "")
    source_name = str(row.get("source_name") or "")
    if provider in MARKET_PROVIDERS or source_name in MARKET_PROVIDERS:
        return True
    return False


def scrub_levels(row):
    """Copy used for storage. Prices are dropped, not renamed."""
    clean = dict(row or {})
    for key in (
        "entry",
        "stop",
        "target",
        "reference_price",
        "watch_entry",
        "watch_stop",
        "watch_target",
        "price",
        "close",
    ):
        if key in clean:
            clean[key] = None
    clean["size"] = None
    match = clean.get("experimental_match")
    if isinstance(match, dict):
        trimmed = dict(match)
        for key in ("entry", "stop", "target", "reward_risk", "size"):
            trimmed.pop(key, None)
        clean["experimental_match"] = trimmed
    if isinstance(clean.get("research_levels"), dict):
        clean["research_levels"] = {"audit_only": True, "persisted": False}
    if isinstance(clean.get("live_quote"), dict):
        clean["live_quote"] = {
            "ok": False,
            "reason": "not_persisted",
            "bid": None,
            "ask": None,
            "not_a_candle": True,
        }
    clean["levels_persisted"] = False
    clean["persistence_capability"] = "paper_ledger_persistence"
    clean["persistence_state"] = "unverified"
    return clean


def persistence_refusal(row):
    if not is_feed_derived(row):
        return None
    return {
        "ok": False,
        "reason": "paper_ledger_persistence",
        "order_opened": False,
        "levels_persisted": False,
        "persistence_capability": "paper_ledger_persistence",
        "persistence_state": "unverified",
    }


def matches_feed_levels(card, entry, stop, target):
    card = card or {}
    if card.get("entry") is None or card.get("stop") is None or card.get("target") is None:
        return False

    def same(left, right):
        try:
            left_f, right_f = float(left), float(right)
        except (TypeError, ValueError):
            return False
        return abs(left_f - right_f) <= max(1e-8, abs(right_f) * 1e-8)

    return same(entry, card.get("entry")) and same(stop, card.get("stop")) and same(target, card.get("target"))
