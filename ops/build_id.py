"""Release identity. A missing build argument is unknown, never a guess."""

import os
import re

_SHA = re.compile(r"[0-9a-f]{40}")


def build_commit():
    value = os.environ.get("AUREON_BUILD_COMMIT", "").strip().lower()
    if _SHA.fullmatch(value):
        return value
    return "unknown"


def shadow_enabled():
    return os.environ.get("AUREON_SHADOW", "").strip().lower() in {"1", "true", "yes", "on"}
