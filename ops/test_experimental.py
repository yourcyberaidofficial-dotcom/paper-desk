from ops.experimental import ExperimentalBook, present_book


def test_no_duplicate_open(tmp_path):
    book = ExperimentalBook(tmp_path / "experimental.jsonl")
    row = {"id": "paper:BTC:1", "type": "paper_open", "asset": "BTCUSDT", "side": "LONG_BIAS"}
    assert book.append(row)["id"] == row["id"]
    assert book.append(row)["duplicate"] is True
    assert book.open_position()["id"] == row["id"]
    book.append({"id": "close:BTC:1", "type": "paper_close", "open_id": "paper:BTC:1"})
    assert book.open_position() is None


def test_bias_rows_are_not_holdings():
    rows = [
        {"id": "signal:1", "type": "paper_signal", "asset": "BTCUSDT", "side": "SHORT_BIAS"},
        {"id": "open:1", "type": "paper_open", "asset": "BTCUSDT", "side": "SHORT_BIAS", "entry_price": 80245.75},
        {"id": "close:1", "type": "paper_close", "open_id": "open:1"},
    ]
    shown = present_book(rows, rows[1])
    assert shown["open"] is None
    assert shown["trades"] == []
    assert len(shown["observations"]) == 2
    real = present_book([{"id": "o", "type": "paper_open", "asset": "BTCUSDT", "side": "SHORT"}], {"id": "o", "type": "paper_open", "side": "SHORT"})
    assert real["open"]["side"] == "SHORT"
    assert len(real["trades"]) == 1
