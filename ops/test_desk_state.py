"""Platform presentation while market data stays withheld. No price is produced."""

from ops.desk_state import pair_board, platform_state, product_gates


def test_gates_withhold_display_and_evaluation():
    gates = product_gates()
    assert gates["market_data"] == "rights_withheld"
    assert gates["approved_for_paper"] == 0
    assert gates["evaluation"] == "unavailable"
    assert gates["historical_research"] == "unavailable"
    assert "commercial use permissions are being verified" in gates["message"]


def test_platform_state_names_each_capability_without_a_price():
    body = platform_state({"status": "beating", "healthy": True})
    assert body["application"] == "operational"
    assert body["worker"] == "operational"
    assert body["market_data"] == "rights_withheld"
    assert body["market_data_technical"] == "not_checked"
    assert body["historical_research"] == "unavailable"
    assert body["approved_strategies"] == 0
    assert body["qualifying_opportunity"] == "none"
    assert body["evaluation"] == "unavailable"
    assert body["paper_trading"] == "available"
    assert body["education"] == "available"
    assert body["broker"] is False
    labels = {row["label"]: row["value"] for row in body["states"]}
    assert labels["Application"] == "Operational"
    assert labels["Market data"] == "Rights withheld"
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
    withheld = [row for row in pairs if not (row["instrument"] == "XAUUSD" and row["timeframe"] in {"1m", "3m"})]
    assert withheld and all(row["rights"] == "Rights unconfirmed" for row in withheld)
    assert all(row["approval"] == "No approved strategy" for row in pairs)
    assert all(row["latest_read"] == "Not read" for row in pairs)
    assert pair_board() == pairs


def test_platform_route_matches_the_same_model():
    from ops.app import app
    client = app.test_client()
    body = client.get("/api/platform").get_json()
    assert body["market_data"] == "rights_withheld"
    assert body["evaluation"] == "unavailable"
    assert len(body["pairs"]) == 12
    assert "price" not in body
