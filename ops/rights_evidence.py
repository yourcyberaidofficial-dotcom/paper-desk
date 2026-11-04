"""Owner-recorded market-data grants. A missing file is not a grant.

This module does not contact a vendor and does not treat an API key as permission.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = (
    "provider",
    "product",
    "instruments",
    "timeframes",
    "capabilities",
    "terms_version",
    "clause",
    "verified_by",
    "verified_on",
    "review_due",
    "redistribution",
)


def grant_path(source_id):
    root = Path(os.environ.get("AUREON_DATA") or "data")
    return root / "rights" / f"{source_id}.json"


def recorded_grant(source_id):
    """Return a grant only when every required field is present and the review date is still ahead."""
    path = grant_path(source_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if any(not raw.get(key) for key in REQUIRED):
        return None
    if not isinstance(raw.get("instruments"), list) or not isinstance(raw.get("timeframes"), list):
        return None
    if not isinstance(raw.get("capabilities"), list):
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    if str(raw.get("review_due")) < today:
        return None
    if str(raw.get("verified_on")) > today:
        return None
    return {
        "provider": str(raw["provider"]),
        "product": str(raw["product"]),
        "instruments": [str(item) for item in raw["instruments"]],
        "timeframes": [str(item) for item in raw["timeframes"]],
        "capabilities": [str(item) for item in raw["capabilities"]],
        "terms_version": str(raw["terms_version"]),
        "clause": str(raw["clause"]),
        "verified_by": str(raw["verified_by"]),
        "verified_on": str(raw["verified_on"]),
        "review_due": str(raw["review_due"]),
        "redistribution": str(raw["redistribution"]),
    }
