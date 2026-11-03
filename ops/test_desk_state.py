"""Platform presentation for the operating desk. This module still does not fetch a price."""

from ops.desk_state import pair_board, platform_state, product_gates


def test_gates_keep_the_desk_open_and_research_closed():
    gates = product_gates()
    assert gates["market_data"] == "available"
    assert gates["approved_for_paper"] == 0
    assert gates["evaluation"] == "available"
    assert gates["historical_research"] == "unavailable"
    assert "Research approval is separate" in gates["message"]
    assert "commercial use permissions are being verified" not in gates["message"]


def test_platform_state_names_each_capability_without_a_price():
    body = platform_state({"status": "beating", "healthy": True})
    assert body["application"] == "operational"
    assert body["worker"] == "operational"
    assert body["market_data"] == "available"
    assert body["market_data_technical"] == "not_checked"
    assert body["historical_research"] == "unavailable"
    assert body["approved_strategies"] == 0
    assert body["qualifying_opportunity"] == "none"
    assert body["evaluation"] == "available"
    assert body["paper_trading"] == "available"
    assert body["education"] == "available"
    assert body["broker"] is False
    labels = {row["label"]: row["value"] for row in body["states"]}
    assert labels["Application"] == "Operational"
    assert labels["Market data"] == "Live"
    assert labels["Feed health"] == "Not checked"
    assert labels["Approved strategies"] == "0"
    assert labels["Paper trading"] == "Available for eligible account actions"
    blob = repr(body)
    for banned in ("candles", "entry", "target", "\"price\"", "'price'"):
        assert banned not in blob
    pairs = body["pairs"]
    assert len(pairs) == 12
    minutes = [row for row in pairs if row["instrument"] == "XAUUSD" and row["timeframe"] in {"1m", "3m"}]
    assert [row["timeframe"] for row in minutes] == ["1m", "3m"]
    assert all(row["rights"] == "Gold minute unlicensed" for row in minutes)
    assert all(row["evaluation"] == "Unavailable" for row in minutes)
    live = [row for row in pairs if not (row["instrument"] == "XAUUSD" and row["timeframe"] in {"1m", "3m"})]
    assert live and all(row["rights"] == "Live" for row in live)
    assert all(row["latest_read"] == "Live" and row["evaluation"] == "Ready" for row in live)
    assert {row["source"] for row in live if row["instrument"] == "XAUUSD"} == {"Gold chart"}
    assert {row["source"] for row in live if row["instrument"] == "BTCUSDT"} == {"Binance spot"}
    assert all(row["approval"] == "Reading, not a promoted strategy" for row in pairs)
    assert "Rights unconfirmed" not in blob
    assert "Withheld" not in blob
    assert pair_board() == pairs


def test_platform_route_matches_the_same_model():
    from ops.app import app
    client = app.test_client()
    body = client.get("/api/platform").get_json()
    assert body["market_data"] == "available"
    assert body["evaluation"] == "available"
    assert body["approved_strategies"] == 0
    assert body["historical_research"] == "unavailable"
    assert len(body["pairs"]) == 12
    assert "price" not in body
