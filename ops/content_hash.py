"""Image content identity. This is not the optional build label.

The hash covers ops/, desk/, and requirements-lock.txt in path order.
A Docker build writes the digest beside the tree. /version reports that
baked digest when the file is present, and never calls it a commit SHA.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

_HEX = re.compile(r"[0-9a-f]{64}")
_CACHED = None


def _root():
    return Path(__file__).resolve().parents[1]


def baked_path():
    raw = os.environ.get("AUREON_CONTENT_HASH_FILE", "").strip()
    if raw:
        return Path(raw)
    return Path("/app/IMAGE_CONTENT_HASH")


def _files(root):
    found = []
    for folder in ("ops", "desk"):
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            found.append(path)
    lock = root / "requirements-lock.txt"
    if lock.is_file() and not lock.is_symlink():
        found.append(lock)
    found.sort(key=lambda path: path.relative_to(root).as_posix())
    return found


def compute_content_hash(root=None):
    """Same bytes in, same digest. Directory order and timestamps are ignored."""
    root = Path(root) if root is not None else _root()
    hasher = hashlib.sha256()
    for path in _files(root):
        hasher.update(path.relative_to(root).as_posix().encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def write_baked(path, root=None):
    path = Path(path)
    digest = compute_content_hash(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest + "\n", encoding="utf-8")
    return digest


def baked_hash():
    path = baked_path()
    if not path.is_file() or path.is_symlink():
        return None
    text = path.read_text(encoding="utf-8").strip().lower()
    if not _HEX.fullmatch(text):
        return None
    return text


def content_hash():
    baked = baked_hash()
    if baked:
        return baked
    global _CACHED
    if _CACHED is None:
        _CACHED = compute_content_hash()
    return _CACHED


def content_hash_baked():
    return baked_hash() is not None
