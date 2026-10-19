"""Persist last good gold data so provider limits do not blank the desk."""

import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("AUREON_DATA", "data")) / "cache"
ROOT.mkdir(parents=True, exist_ok=True)
PATH = ROOT / "gold.json"


def load() -> dict | None:
    if not PATH.exists():
        return None
    try:
        return json.loads(PATH.read_text())
    except Exception:
        return None


def save(payload: dict) -> None:
    PATH.write_text(json.dumps(payload))
