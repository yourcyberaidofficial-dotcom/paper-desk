"""Isolated experimental paper book. Not production. Not validated."""

import json
from pathlib import Path


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
