"""Copy a data directory and prove the copy before anyone restores it.

This does not touch a live volume. Restore writes only into the destination
the caller names, and only after every checksum matches.
"""

import hashlib
import json
from pathlib import Path


def _files(root):
    root = Path(root)
    found = []
    if not root.exists():
        return found
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            found.append(path)
    return found


def _digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def create_backup(source, destination):
    source = Path(source)
    destination = Path(destination)
    if not source.is_dir():
        return {"ok": False, "reason": "source_missing"}
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        return {"ok": False, "reason": "destination_not_empty"}
    manifest = []
    for path in _files(source):
        relative = path.relative_to(source).as_posix()
        target = destination / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        target.write_bytes(data)
        manifest.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    document = {"source_name": source.name, "files": manifest, "verified": False}
    (destination / "manifest.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    checked = verify_backup(destination)
    document["verified"] = checked["ok"] is True
    (destination / "manifest.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    return {"ok": checked["ok"], "files": len(manifest), "destination": str(destination), "reason": checked.get("reason")}


def verify_backup(destination):
    destination = Path(destination)
    manifest_path = destination / "manifest.json"
    if not manifest_path.is_file():
        return {"ok": False, "reason": "manifest_missing"}
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "reason": "manifest_unreadable"}
    for row in document.get("files") or []:
        path = destination / "files" / row["path"]
        if not path.is_file() or path.is_symlink():
            return {"ok": False, "reason": "file_missing", "path": row["path"]}
        if _digest(path) != row["sha256"]:
            return {"ok": False, "reason": "checksum_mismatch", "path": row["path"]}
    return {"ok": True, "files": len(document.get("files") or [])}


def restore_backup(backup, destination):
    """Write a verified backup into an empty destination. Never deletes the source backup."""
    checked = verify_backup(backup)
    if not checked["ok"]:
        return checked
    destination = Path(destination)
    if destination.exists() and any(destination.rglob("*")):
        return {"ok": False, "reason": "destination_not_empty"}
    destination.mkdir(parents=True, exist_ok=True)
    document = json.loads((Path(backup) / "manifest.json").read_text(encoding="utf-8"))
    for row in document["files"]:
        source = Path(backup) / "files" / row["path"]
        target = destination / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        if _digest(target) != row["sha256"]:
            return {"ok": False, "reason": "restore_mismatch", "path": row["path"]}
    return {"ok": True, "files": len(document["files"])}
