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
            "Unauthenticated access is not a licence. Existing live reads in the desk are operational freshness only "
            "and are not a retained research dataset."
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


def register_public():
    rows = []
    for row in SOURCES:
        rows.append({
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
        })
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
                "An operational spot sample can be read for this timeframe. Rights for keeping it, researching on it, "
                "or presenting it as licensed market data are not confirmed. No new history is being collected. "
                "The separate quote check still uses the 0.08 percent limit and is not a research archive."
            )
            live = "Operational spot sample only"
        else:
            summary = (
                "A live public candle read can refresh this market. That is not retained desk history and it is not "
                "permission to research or redistribute the candles. Forward collection is off until a written licence exists."
            )
            live = "Live read only"
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
