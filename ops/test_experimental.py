from ops.experimental import ExperimentalBook


def test_no_duplicate_open(tmp_path):
    book = ExperimentalBook(tmp_path / "experimental.jsonl")
    row = {"id": "paper:BTC:1", "type": "paper_open", "asset": "BTCUSDT", "side": "LONG_BIAS"}
    assert book.append(row)["id"] == row["id"]
    assert book.append(row)["duplicate"] is True
    assert book.open_position()["id"] == row["id"]
    book.append({"id": "close:BTC:1", "type": "paper_close", "open_id": "paper:BTC:1"})
    assert book.open_position() is None
