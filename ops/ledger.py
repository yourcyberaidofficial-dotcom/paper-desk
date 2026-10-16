"""Append-only paper ledger. Strategies cannot write it."""

import json
import time
from pathlib import Path

class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict) -> dict:
        row = dict(event)
        row.setdefault("ts_ms", int(time.time() * 1000))
        row.setdefault("id", f"{row['ts_ms']}-{row.get('type', 'event')}-{row.get('symbol', '')}")
        if any(existing.get("id") == row["id"] for existing in self.read()):
            return {"duplicate": True, "id": row["id"]}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def balances(self) -> dict:
        balances = {"aggressive": 10000.0, "balanced": 10000.0, "defensive": 10000.0}
        for row in self.read():
            if row.get("type") == "fill":
                balances[row["sleeve"]] = balances.get(row["sleeve"], 10000.0) + float(row.get("pnl", 0))
        return balances
