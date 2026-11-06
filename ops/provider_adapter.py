"""Provider adapter contract.

A later owner-approved source implements this shape. Pages and the Daily
Desk calculation model stay the same. A spot quote is not OHLC. A sampled
reference bar is not a tradable exchange candle. This module does not
contact a vendor and does not open a socket.
"""

from __future__ import annotations

CONTRACT_FIELDS = (
    "source_id",
    "supplies",
    "does_not_supply",
    "instruments",
    "timeframes",
    "candle_semantics",
    "quote_semantics",
    "source_timestamps",
    "freshness_policy",
    "completeness_policy",
    "failure_mode",
    "capabilities",
)

QUOTE_THRESHOLD = 0.0008


def independent_reference_quote(now_ms=None):
    """The only production gold reference-quote path. No bid or ask is invented."""
    from ops.gold_live import reference_quote_unavailable

    return reference_quote_unavailable(now_ms)


def describe(adapter):
    missing = [name for name in CONTRACT_FIELDS if name not in adapter]
    return {"ok": not missing, "missing": missing, "adapter": {key: adapter.get(key) for key in CONTRACT_FIELDS}}


def current_reference_adapter():
    from ops.entitlements import decide_use

    return {
        "source_id": "independent_reference_quote",
        "supplies": (),
        "does_not_supply": (
            "bid",
            "ask",
            "mid",
            "ohlc",
            "xau_1m",
            "xau_3m",
            "xaus_spot_as_bid_ask",
            "swissquote_bbo",
        ),
        "instruments": ("XAUUSD",),
        "timeframes": ("15m", "1h"),
        "candle_semantics": "none",
        "quote_semantics": "independent_reference_unavailable",
        "source_timestamps": "none_until_an_authorised_quote_adapter_is_configured",
        "freshness_policy": "not_checked_until_a_rights_cleared_quote_adapter_is_configured",
        "completeness_policy": "a quote is absent until both bid and ask arrive from that adapter",
        "failure_mode": "reference_quote_unavailable",
        "quote_threshold": QUOTE_THRESHOLD,
        "capabilities": {
            "quote_display": decide_use("swissquote_public_bbo", "quote_display"),
            "paper_ledger_persistence": decide_use("xaus_public_chart", "paper_ledger_persistence"),
        },
    }


def kraken_public_adapter():
    from ops.entitlements import decide_use

    source = "kraken_public_ohlc"
    return {
        "source_id": source,
        "supplies": ("native_trade_ohlc",),
        "does_not_supply": ("bid_ask", "native_3m", "xauusd", "btc_usd", "websocket_stream"),
        "instruments": ("BTCUSDT", "ETHUSDT"),
        "venue_pairs": ("XBT/USDT", "ETH/USDT"),
        "timeframes": ("1m", "15m", "1h"),
        "derived_timeframes": ("3m",),
        "candle_semantics": "native_trade_ohlc_not_bid_ask",
        "quote_semantics": "not_supplied",
        "source_timestamps": "unix seconds on the OHLC row, converted to open_time_ms; close is open plus the interval",
        "freshness_policy": "drop the final forming row; keep close_time at or before now",
        "completeness_policy": "do not fill gaps; 3m exists only when every native 1m bar in the bucket is present",
        "failure_mode": "not_verified_until_owner_grant",
        "rate_limit": "public REST has no documented per-call token cost; a failure is not filled from another venue",
        "licence": "public route only; redistribution and customer display are not granted",
        "capabilities": {name: decide_use(source, name, symbol="BTCUSDT", interval="15m") for name in (
            "candle_display",
            "customer_reading",
            "quote_display",
            "paper_ledger_persistence",
        )},
    }


def binance_rest_adapter():
    from ops.entitlements import decide_use

    source = "binance_spot_rest_klines"
    return {
        "source_id": source,
        "supplies": ("native_spot_kline",),
        "does_not_supply": ("bid_ask", "sampled_reference", "vision_archive"),
        "instruments": ("BTCUSDT", "ETHUSDT"),
        "timeframes": ("1m", "3m", "15m", "1h"),
        "candle_semantics": "native_kline_last_trade",
        "quote_semantics": "not_supplied",
        "source_timestamps": "open_time_ms and close_time_ms from the kline row",
        "freshness_policy": "completed bar only, close inside two intervals",
        "completeness_policy": "drop the forming bar; do not fill gaps",
        "failure_mode": "missing_feed",
        "capabilities": {name: decide_use(source, name) for name in (
            "candle_display",
            "indicator_calculation",
            "customer_reading",
            "paper_ledger_persistence",
            "raw_data_retention",
        )},
    }


def xaus_sample_adapter():
    from ops.entitlements import decide_use

    source = "xaus_spot_samples"
    return {
        "source_id": source,
        "supplies": ("indicative_spot_samples",),
        "does_not_supply": ("bid_ask", "native_exchange_ohlc", "xau_1m", "xau_3m"),
        "instruments": ("XAUUSD",),
        "timeframes": ("15m", "1h"),
        "candle_semantics": "sampled_indicative_reference",
        "quote_semantics": "not_a_bid_ask",
        "source_timestamps": "sample t, aggregated to bar open and close",
        "freshness_policy": "completed bucket only, close inside two intervals",
        "completeness_policy": "15m needs 3 prints and 1h needs 12; missing prints are not reconstructed",
        "failure_mode": "incomplete_sample_bucket",
        "capabilities": {name: decide_use(source, name) for name in (
            "sampled_reference_display",
            "candle_display",
            "quote_display",
            "paper_ledger_persistence",
        )},
    }


def twelve_data_adapter():
    """Prepared gold OHLC adapter. It does not open a socket and it is not approved by itself."""
    from ops.entitlements import CAPABILITIES, decide_use

    source = "twelve_data"
    return {
        "source_id": source,
        "supplies": ("native_xauusd_ohlc",),
        "does_not_supply": (
            "bid",
            "ask",
            "native_3m",
            "btcusdt",
            "ethusdt",
            "btcusd_as_btcusdt",
            "ethusd_as_ethusdt",
            "xaus_failover",
        ),
        "instruments": ("XAUUSD",),
        "timeframes": ("1m", "15m", "1h"),
        "candle_semantics": "native_xauusd_ohlc",
        "quote_semantics": "bid_ask_not_supplied",
        "source_timestamps": "vendor datetime interpreted as UTC open; close is open plus the native interval minus 1ms",
        "freshness_policy": "completed bar only; close inside two intervals; forming bar dropped",
        "completeness_policy": "duplicates and gaps are counted; gaps are not filled; 3m is not synthesized",
        "failure_mode": "authorised_read_failed_no_failover",
        "quote_threshold": QUOTE_THRESHOLD,
        "capabilities": {name: decide_use(source, name, symbol="XAUUSD", interval="1h") for name in CAPABILITIES},
    }
