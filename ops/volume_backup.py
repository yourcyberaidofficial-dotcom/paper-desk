"""Copy the host data tree. The source is never deleted.

Restore writes only into an empty directory after every checksum matches.
This does not run docker compose and it does not remove a volume.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ops.backup import create_backup, restore_backup, verify_backup

VOLUMES = (
    ("desk-data", "paper"),
    ("desk-users", "users"),
    ("desk-shadow", "shadow"),
    ("desk-signals", "signals"),
    ("desk-activity", "activity"),
    ("desk-rights", "rights"),
    ("desk-cache", "cache"),
    ("desk-canonical", "canonical"),
    ("desk-ai", "ai"),
)


def backup_root(root, destination):
    root = Path(root)
    destination = Path(destination)
    if not root.is_dir():
        return {"ok": False, "reason": "root_missing", "deleted": False}
    if destination.exists() and any(destination.iterdir()):
        return {"ok": False, "reason": "destination_not_empty", "deleted": False}
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    skipped = []
    for name, relative in VOLUMES:
        source = root / relative
        if not source.is_dir():
            skipped.append(name)
            continue
        result = create_backup(source, destination / name)
        if not result.get("ok"):
            return {"ok": False, "reason": result.get("reason"), "volume": name, "copied": copied, "deleted": False}
        copied.append({"volume": name, "files": result.get("files")})
    index = {"schema": 1, "volumes": copied, "skipped": skipped, "destructive": False}
    schema_file = root / "canonical" / "schema.json"
    if schema_file.is_file():
        try:
            index["data_schema"] = json.loads(schema_file.read_text(encoding="utf-8")).get("schema")
        except json.JSONDecodeError:
            index["data_schema"] = None
    (destination / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return {"ok": True, "copied": copied, "skipped": skipped, "destination": str(destination), "deleted": False}


def restore_volume(backup_volume, destination):
    checked = verify_backup(backup_volume)
    if not checked.get("ok"):
        return dict(checked, deleted=False)
    result = restore_backup(backup_volume, destination)
    result["deleted"] = False
    return result


def _usage():
    return "usage: python -m ops.volume_backup backup --root /opt/aureon --dest /opt/aureon/backups/<stamp> | restore --backup <volume-backup> --dest <empty-dir>"


def main(argv):
    argv = list(argv)
    if len(argv) >= 6 and argv[0] == "backup" and argv[1] == "--root" and argv[3] == "--dest":
        result = backup_root(argv[2], argv[4])
        print(json.dumps(result))
        return 0 if result.get("ok") else 2
    if len(argv) >= 6 and argv[0] == "restore" and argv[1] == "--backup" and argv[3] == "--dest":
        result = restore_volume(argv[2], argv[4])
        print(json.dumps(result))
        return 0 if result.get("ok") else 2
    print(_usage())
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
