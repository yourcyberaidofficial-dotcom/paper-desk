"""Auditable market-data rights register.

A public URL is not a licence. Nothing in this register is approved for
commercial historical retention, strategy qualification, or customer-facing
redistribution. Reviewed against the cited documents on 2026-11-03.
Re-check those documents before any later collection. This module does not
download market data and does not open a research holdout.
"""

from __future__ import annotations

REVIEWED_ON = "2026-11-03"
REVIEWED_BY = "Aureon engineering review"

DESK = (
    ("BTCUSDT", "1m"),
    ("BTCUSDT", "3m"),
    ("BTCUSDT", "15m"),
    ("BTCUSDT", "1h"),
    ("ETHUSDT", "1m"),
    ("ETHUSDT", "3m"),
    ("ETHUSDT", "15m"),
    ("ETHUSDT", "1h"),
    ("XAUUSD", "1m"),
    ("XAUUSD", "3m"),
    ("XAUUSD", "15m"),
    ("XAUUSD", "1h"),
)

USES = (
    "connection",
    "memory",
    "display",
    "retention",
    "research",
    "indicators",
    "strategy",
    "notification",
    "autopilot",
    "redistribution",
)

KNOWN_STATES = {"approved", "restricted", "prohibited", "rights_unconfirmed", "fixture_only"}
MESSAGE = "Market data access unavailable — commercial use permissions are being verified."
_AUDIT = []

STATUS_LABELS = {
    "approved": "Rights approved",
    "restricted": "Restricted",
    "rights_unconfirmed": "Rights not confirmed",
    "prohibited": "Prohibited",
    "fixture_only": "Fixture only",
}

SOURCES = (
    {
        "id": "binance_vision_klines",
        "provider": "Binance Vision",
        "product": "data.binance.vision historical kline archives",
        "data_type": "Historical spot kline archives",
        "intended_use": "Desk-timeframe crypto history for research and display",
        "retention": False,
        "historical_research": False,
        "derivative_indicators": False,
        "customer_display": False,
        "commercial_use": False,
        "attribution": "CC BY-NC-SA 4.0 attribution would apply to a permitted non-commercial copy. It does not authorise Aureon.",
        "terms_url": "https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md",
        "terms_version": "Vision Dataset Terms 1.0, last updated 26 August 2026",
        "written_approval": None,
        "status": "prohibited",
        "block_reason": "prohibited",
        "note": (
            "Datasets are CC BY-NC-SA 4.0. Section 3.4 excludes commercial licensing. "
            "Section 4.4 prohibits integration into commercial financial products and commercial trading-bot platforms. "
            "The repository MIT licence covers the download software, not the datasets. "
            "No Binance enterprise data licence is on file."
        ),
    },
    {
        "id": "binance_spot_rest_klines",
        "provider": "Binance",
        "product": "Spot public REST GET /api/v3/klines and data-api.binance.vision market-data host",
        "data_type": "Public spot klines",
        "intended_use": "Live desk candles and, if licensed, historical retention",
        "retention": False,
        "historical_research": False,
        "derivative_indicators": False,
        "customer_display": False,
        "commercial_use": False,
        "attribution": "Not established",
        "terms_url": "https://github.com/binance/binance-spot-api-docs/blob/master/PROD-TERMS-OF-USE.md",
        "terms_version": "PROD-TERMS-OF-USE pointer, reviewed 2026-11-03; Product Terms page https://www.binance.com/en/terms was not retrievable (HTTP 503)",
        "written_approval": None,
        "status": "rights_unconfirmed",
        "block_reason": "rights_unconfirmed",
        "note": (
            "The endpoint is reachable without an API key. The Spot product terms file only points at "
            "https://www.binance.com/en/terms and states no market-data redistribution, retention, or commercial-display grant. "
            "Unauthenticated access is not a licence. Live desk requests stay off until a written grant covers the exact use."
        ),
    },
    {
        "id": "dukascopy_datafeed_bi5",
        "provider": "Dukascopy Bank SA",
        "product": "datafeed.dukascopy.com XAUUSD bi5 spot samples",
        "data_type": "Spot bid/ask candle samples",
        "intended_use": "Gold 15m and 1h operational samples; not a new research archive",
        "retention": False,
        "historical_research": False,
        "derivative_indicators": False,
        "customer_display": False,
        "commercial_use": False,
        "attribution": "The XML licence requires a Dukascopy banner and registration approval. That licence was not granted to Aureon and does not mention bi5 files.",
        "terms_url": "https://www.dukascopy.com/plugins/cont.php?ref_id=1273",
        "terms_version": "License agreement for XML data use, copyright notice 2026; no bi5 schedule",
        "written_approval": None,
        "status": "rights_unconfirmed",
        "block_reason": "rights_unconfirmed",
        "note": (
            "The published XML grant is non-exclusive, non-transferable, non-commercial and temporary, and it forbids retransmission of the XML. "
            "It does not cover datafeed bi5 history. No written Dukascopy approval for Aureon was found. "
            "The existing 0.08 percent quote-divergence check stays a live comparison. It is not stored research evidence."
        ),
    },
    {
        "id": "swissquote_public_bbo",
        "provider": "Swissquote Bank Ltd",
        "product": "Public BBO quote check for XAU/USD",
        "data_type": "Top-of-book quote snapshot, not a candle history",
        "intended_use": "Compare a live gold quote with a spot sample",
        "retention": False,
        "historical_research": False,
        "derivative_indicators": False,
        "customer_display": False,
        "commercial_use": False,
        "attribution": "Not established",
        "terms_url": "https://links.imagerelay.com/cdn/2958/ql/market-data-access-en",
        "terms_version": "Market Data Access Terms and Conditions v3.0, January 2024",
        "written_approval": None,
        "status": "restricted",
        "block_reason": "restricted",
        "note": (
            "Those terms bind the bank's client and API client service. They forbid giving market data to another person "
            "and using it to create an investment strategy or financial product. Aureon has no Swissquote market-data agreement. "
            "The public quote URL is not a historical source and is not approved for retention or redistribution."
        ),
    },
    {
        "id": "xaus_public_chart",
        "provider": "XAUS public chart",
        "product": "xaus.com spot and chart endpoints used for XAUUSD samples",
        "data_type": "Indicative gold spot and chart OHLC",
        "intended_use": "Gold display, comparison and research",
        "retention": False,
        "historical_research": False,
        "derivative_indicators": False,
        "customer_display": False,
        "commercial_use": False,
        "attribution": "Not established",
        "terms_url": None,
        "terms_version": "No applicable written licence was on file at review",
        "written_approval": None,
        "status": "rights_unconfirmed",
        "block_reason": "rights_unconfirmed",
        "note": "These endpoints were used as an operational gold sample. No written permission to request, display, retain or derive a commercial signal from them was found.",
    },
    {
        "id": "deterministic_fixture",
        "provider": "Aureon fixture",
        "product": "Deterministic test candles",
        "data_type": "Synthetic rows with no market meaning",
        "intended_use": "Test normalisation, storage and manifests",
        "retention": False,
        "historical_research": False,
        "derivative_indicators": False,
        "customer_display": False,
        "commercial_use": False,
        "attribution": "None",
        "terms_url": None,
        "terms_version": "Internal fixture, not a data vendor",
        "written_approval": None,
        "status": "fixture_only",
        "block_reason": "fixture_not_market_evidence",
        "note": "Fixtures can prove the store. They cannot approve a strategy or count as market evidence.",
    },
)


def source(source_id):
    for row in SOURCES:
        if row["id"] == source_id:
            return row
    return None


def ingestion_allowed(source_id, purpose):
    row = source(source_id)
    if row is None:
        return {"allowed": False, "status": "rights_unconfirmed", "reason": "unknown_source", "research_eligible": False}
    if row["id"] == "deterministic_fixture" and purpose == "fixture_test":
        return {
            "allowed": True,
            "status": "fixture_only",
            "reason": "fixture_not_market_evidence",
            "research_eligible": False,
        }
    return {
        "allowed": False,
        "status": row["status"],
        "reason": row["block_reason"],
        "research_eligible": False,
    }


def _audit(source_id, use, allowed, status, reason):
    _AUDIT.append({
        "source": source_id,
        "use": use,
        "allowed": allowed,
        "status": status,
        "reason": reason,
        "reviewed_on": REVIEWED_ON,
    })
    del _AUDIT[:-200]
    return {"allowed": allowed, "status": status, "reason": reason, "use": use, "source": source_id}


def audit_log():
    return list(_AUDIT)


def uses_for(row):
    declared = row.get("uses") if isinstance(row.get("uses"), dict) else {}
    base = row.get("status") if row.get("status") in KNOWN_STATES else "rights_unconfirmed"
    if row.get("id") == "deterministic_fixture":
        base = "fixture_only"
    return {use: declared.get(use, base) for use in USES}


def use_permission(source_id, use, *, record=None, today=REVIEWED_ON):
    row = source(source_id) if record is None else record
    if not isinstance(row, dict) or use not in USES:
        return _audit(source_id, use, False, "rights_unconfirmed", "missing_or_malformed_rights")
    raw = uses_for(row).get(use)
    if raw not in KNOWN_STATES:
        return _audit(source_id, use, False, "rights_unconfirmed", "malformed_permission")
    if raw == "fixture_only":
        return _audit(source_id, use, False, "fixture_only", "fixture_not_market_evidence")
    if raw != "approved":
        return _audit(source_id, use, False, raw, raw)
    evidence = {}
    bundle = row.get("use_evidence") if isinstance(row.get("use_evidence"), dict) else {}
    item = bundle.get(use)
    if isinstance(item, dict):
        evidence = item
    required = ("provider", "product", "data_type", "permitted_purpose", "terms_version", "clause", "verified_by", "verified_on")
    if any(not evidence.get(key) for key in required):
        return _audit(source_id, use, False, "rights_unconfirmed", "approval_without_evidence")
    if evidence.get("review_due") and str(evidence["review_due"]) < str(today):
        return _audit(source_id, use, False, "rights_unconfirmed", "rights_review_expired")
    return _audit(source_id, use, True, "approved", "evidenced")


def network_block(source_id, use="connection"):
    decision = use_permission(source_id, use)
    if decision["allowed"]:
        return None
    return {
        "ok": False,
        "allowed": False,
        "bars": [],
        "candles": [],
        "price": None,
        "close": None,
        "fresh": False,
        "blocked": decision["status"],
        "rights_status": decision["status"],
        "display_permission": use_permission(source_id, "display")["status"],
        "retention_permission": use_permission(source_id, "retention")["status"],
        "research_permission": use_permission(source_id, "research")["status"],
        "decision_permission": use_permission(source_id, "strategy")["status"],
        "source_reachable": "not_checked",
        "feed_freshness": "not_applicable",
        "reason": "commercial_use_unverified",
        "message": MESSAGE,
    }


def open_market_stream(source_id="binance_spot_rest_klines"):
    """No WebSocket client is connected. Unconfirmed connection rights refuse the socket."""
    blocked = network_block(source_id, "connection")
    if blocked:
        blocked["stream"] = False
        return blocked
    return {"ok": False, "stream": False, "reason": "no_stream_client"}


def retained_research_status(path):
    name = str(path).rsplit("/", 1)[-1]
    if name in {"BTCUSDT-4h.csv", "ETHUSDT-4h.csv"}:
        status = "rights_unconfirmed"
        provenance = (
            "Recorded as binance-public in docs/DATA_AUDIT.json. "
            "That does not prove a Binance Vision archive, and it is not a written commercial licence."
        )
    elif name.startswith("XAUUSD"):
        status = "rights_unconfirmed"
        provenance = "Recorded Dukascopy or spot-sample gold history. No written commercial research licence is on file."
    else:
        status = "rights_unconfirmed"
        provenance = "Provenance was not established."
    return {
        "path": name,
        "provenance": provenance,
        "status": status,
        "commercial_research": False,
        "holdout_opened": False,
        "deleted": False,
        "owner_decision_required": "Whether this file may remain stored. It was not deleted and its candles were not read for a new result.",
    }


class RightsDenied(PermissionError):
    """A market-data call stopped before the network because the use is not approved."""

    def __init__(self, block):
        self.block = block if isinstance(block, dict) else {}
        super().__init__(self.block.get("reason") or "commercial_use_unverified")


RIGHTS_REASONS = frozenset({
    "commercial_use_unverified",
    "rights_unconfirmed",
    "prohibited",
    "restricted",
    "fixture_only",
    "fixture_not_market_evidence",
    "approval_without_evidence",
    "rights_review_expired",
    "missing_or_malformed_rights",
    "malformed_permission",
    "unknown_source",
})


def is_rights_reason(value):
    return value in RIGHTS_REASONS


def source_for_url(url):
    text = str(url or "").lower()
    if "binance" in text:
        if "/data/spot/" in text or "vision" in text and "klines" in text and "api/v3" not in text:
            return "binance_vision_klines"
        return "binance_spot_rest_klines"
    if "dukascopy" in text:
        return "dukascopy_datafeed_bi5"
    if "xaus.com" in text:
        return "xaus_public_chart"
    if "swissquote" in text:
        return "swissquote_public_bbo"
    return None


def refuse_url(url, use="connection"):
    source_id = source_for_url(url)
    if source_id is None:
        blocked = network_block("unknown_market_host", use)
        if blocked:
            blocked["reason"] = "commercial_use_unverified"
        return blocked
    return network_block(source_id, use)


def screen_bars(source_id, bars, use="indicators"):
    """Derived calculations receive no rows unless that exact use is approved."""
    if not use_permission(source_id, use)["allowed"]:
        return []
    return list(bars or [])


def register_public():
    rows = []
    for row in SOURCES:
        public = {
            "id": row["id"],
            "provider": row["provider"],
            "product": row["product"],
            "data_type": row["data_type"],
            "intended_use": row["intended_use"],
            "retention": row["retention"],
            "historical_research": row["historical_research"],
            "derivative_indicators": row["derivative_indicators"],
            "customer_display": row["customer_display"],
            "commercial_use": row["commercial_use"],
            "attribution": row["attribution"],
            "terms_url": row["terms_url"],
            "terms_version": row["terms_version"],
            "written_approval": row["written_approval"],
            "status": row["status"],
            "status_label": STATUS_LABELS[row["status"]],
            "note": row["note"],
            "reviewed_on": REVIEWED_ON,
            "reviewed_by": REVIEWED_BY,
            "uses": uses_for(row),
        }
        rows.append(public)
    return rows


def _rights_for_pair(symbol, interval):
    if symbol == "XAUUSD" and interval in ("1m", "3m"):
        return "xau_minute_unlicensed", "Minute data unlicensed"
    if symbol == "XAUUSD":
        return source("dukascopy_datafeed_bi5")["status"], STATUS_LABELS["rights_unconfirmed"]
    return source("binance_spot_rest_klines")["status"], STATUS_LABELS["rights_unconfirmed"]


def coverage_rows():
    rows = []
    for symbol, interval in DESK:
        status, label = _rights_for_pair(symbol, interval)
        if symbol == "XAUUSD" and interval in ("1m", "3m"):
            summary = (
                "No licensed one-minute gold feed. This timeframe is not built by splitting a five-minute sample. "
                "Historical research and forward collection are off."
            )
            live = "No minute source"
        elif symbol == "XAUUSD":
            summary = (
                "Current gold information is withheld. Dukascopy samples, the XAUS chart and the Swissquote quote "
                "check are not approved for commercial display, retention or strategy use. No new history is being collected. "
                "The separate quote check still uses the 0.08 percent limit and is not a research archive."
            )
            live = "Withheld — rights not confirmed"
        else:
            summary = (
                "Binance spot candles are not requested for this market. Connection, display, retention, indicators "
                "and strategy use are rights_unconfirmed. Forward collection is off until a written licence covers the exact use."
            )
            live = "Withheld — rights not confirmed"
        rows.append({
            "market": symbol,
            "timeframe": interval,
            "live_source": live,
            "rights_status": status,
            "rights_label": "Minute data unlicensed" if status == "xau_minute_unlicensed" else label,
            "historical_retained": False,
            "coverage_start": None,
            "coverage_end": None,
            "bar_count": 0,
            "last_collection": None,
            "forward_collection": "inactive",
            "research_usable": False,
            "summary": summary,
        })
    return rows


CONSUMERS = {
    "binance_spot_rest_klines": (
        "ops.market.fetch_last_closed",
        "ops.market.fetch_klines",
        "ops.market.snapshot",
        "ops.feeds.binance_bars",
        "ops.history.fetch_history",
        "ops.leaderboard.leaderboard",
        "ops.replay.replay",
        "ops.deepboard.deep_board",
        "ops.terminal_route.load_crypto_bars",
        "ops.app._remember",
        "ops.app._engine_view",
        "ops.shadow_bridge.load_live_windows",
        "ops.worker._monitor_windows",
    ),
    "dukascopy_datafeed_bi5": (
        "ops.feeds.dukascopy_hour",
        "ops.xau_pull.fetch_day",
        "ops.terminal_route.gold_session",
    ),
    "swissquote_public_bbo": ("ops.gold_live.swissquote_xau", "ops.worker._monitor_windows"),
    "xaus_public_chart": (
        "ops.feeds.xaus_chart",
        "ops.feeds.xaus_spot",
        "ops.feeds.xaus_spot_bars",
        "ops.app._gold",
        "ops.app._gold_bars",
        "ops.terminal_route.load_gold_ohlc",
    ),
    "binance_vision_klines": ("ops.history.fetch_history",),
    "websocket": ("ops.data_rights.open_market_stream",),
}
