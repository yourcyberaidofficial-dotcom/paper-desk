"""Isolated experimental paper book. Not production. Not validated."""

import json
from pathlib import Path


BIAS_SIDES = {"LONG_BIAS", "SHORT_BIAS", "WAIT", "NEUTRAL"}


def present_book(rows, open_row=None):
    """Separate research observations from order-like rows.

    The experimental book stores E1 directions as LONG_BIAS and SHORT_BIAS.
    Those are not account holdings or completed trades.
    """
    observations = [
        row for row in rows
        if row.get("type") == "paper_signal" or row.get("side") in BIAS_SIDES
    ]
    trades = [
        row for row in rows
        if row.get("type") in {"paper_open", "paper_close"}
        and row.get("side")
        and row.get("side") not in BIAS_SIDES
    ]
    holding = open_row if open_row and open_row.get("side") not in BIAS_SIDES else None
    return {"open": holding, "trades": trades, "observations": observations}


class ExperimentalBook:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def append(self, row):
        if any(existing.get("id") == row.get("id") for existing in self.read()):
            return {"duplicate": True, "id": row["id"]}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def open_position(self):
        rows = self.read()
        opens = [r for r in rows if r.get("type") == "paper_open"]
        closes = {r.get("open_id") for r in rows if r.get("type") == "paper_close"}
        for row in reversed(opens):
            if row["id"] not in closes:
                return row
        return None
