"""Small JSON files. A lock and a replace keep one account from losing a write."""

import json
import os
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None


def update_json(path, fn, default=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    with open(lock_path, "a+") as handle:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            if path.exists():
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return {"unreadable": True}
            else:
                current = default
            updated = fn(current)
            if updated is None or (isinstance(updated, dict) and updated.get("unreadable")):
                return updated if updated is not None else current
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(json.dumps(updated), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            return updated
        finally:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
