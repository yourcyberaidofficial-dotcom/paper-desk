"""Auth and rate limits for private endpoints."""

import os
import time
from functools import wraps

from flask import jsonify, request


def api_token() -> str | None:
    raw = os.environ.get("DESK_API_TOKEN", "")
    token = raw.strip()
    if len(token) < 24:
        return None
    return token


def require_token(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = api_token()
        if not expected:
            return jsonify({"error": "private_endpoint_disabled"}), 503
        from flask import session
        if session.get("ok"):
            return view(*args, **kwargs)
        presented = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if presented != expected:
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapped


class RateLimit:
    def __init__(self, per_minute: int = 30):
        self.per_minute = per_minute
        self.hits = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        window = [stamp for stamp in self.hits.get(key, []) if now - stamp < 60]
        if len(window) >= self.per_minute:
            self.hits[key] = window
            return False
        window.append(now)
        self.hits[key] = window
        return True
