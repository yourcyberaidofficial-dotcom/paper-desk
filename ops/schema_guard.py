"""Schema check for the shared data directory.

A newer file is left untouched. Stamping writes only canonical/schema.json.
Nothing here deletes a volume or rewrites an account file.
"""

from __future__ import annotations

import json
from pathlib import Path

CURRENT = 1
# Paper excursion fields are additive on the existing per-account book (schema 1).
# They do not migrate, rewrite, or add a tenth volume.


def schema_path(root):
    return Path(root) / "canonical" / "schema.json"


def _read_json(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _schema_of(path):
    body = _read_json(path)
    if not body:
        return None
    found = body.get("schema")
    return found if isinstance(found, int) and not isinstance(found, bool) else None


def _stamp(root):
    path = schema_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    body = {
        "schema": CURRENT,
        "stores": {"readings": CURRENT, "paper_orders": CURRENT},
        "rewritten_accounts": False,
    }
    temporary.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return body


def guard(root, apply=False):
    """Report the on-disk schema. apply only creates a missing stamp of the current version."""
    root = Path(root)
    readings_schema = _schema_of(root / "canonical" / "readings.json")
    if readings_schema is not None and readings_schema > CURRENT:
        return {"ok": False, "action": "newer_than_code", "schema": readings_schema, "store": "readings", "rewritten": False}
    stamped = _schema_of(schema_path(root))
    if stamped is not None and stamped > CURRENT:
        return {"ok": False, "action": "newer_than_code", "schema": stamped, "store": "schema", "rewritten": False}
    if readings_schema is not None and readings_schema < CURRENT:
        return {"ok": False, "action": "migration_required", "schema": readings_schema, "store": "readings", "rewritten": False}
    if stamped is not None and stamped < CURRENT:
        return {"ok": False, "action": "migration_required", "schema": stamped, "store": "schema", "rewritten": False}
    if stamped == CURRENT and readings_schema in (None, CURRENT):
        return {"ok": True, "action": "current", "schema": CURRENT, "rewritten": False}
    if stamped is None and readings_schema in (None, CURRENT):
        if apply:
            _stamp(root)
            return {"ok": True, "action": "stamped", "schema": CURRENT, "rewritten": False}
        return {"ok": True, "action": "absent", "schema": None, "rewritten": False}
    return {"ok": False, "action": "unreadable", "schema": stamped, "rewritten": False}
