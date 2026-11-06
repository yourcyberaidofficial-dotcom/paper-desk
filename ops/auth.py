"""Auth and rate limits for private endpoints."""

import ipaddress
import os
import threading
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


def limits_apply(pytest_loaded, enforce):
    """Production has no pytest. Tests opt in with ENFORCE_RATE_LIMIT."""
    return not (bool(pytest_loaded) and not enforce)


def trust_proxy_enabled():
    return os.environ.get("DESK_TRUST_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}


def _trusted_peer(peer):
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    networks = []
    for item in os.environ.get("DESK_TRUSTED_PROXIES", "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return any(address in network for network in networks)


def _forwarded_client(header):
    """Return the hop the trusted proxy appended, not the client-supplied prefix.

    An appending proxy adds the address it observed at the right. The left
    side is whatever the caller sent. Using the left side lets one client
    rotate the prefix and skip the login ceiling.
    """
    found = None
    for item in (header or "").split(","):
        host = item.strip()
        if not host:
            continue
        if host.startswith("[") and "]" in host:
            host = host[1:host.index("]")]
        elif host.count(":") == 1 and "." in host:
            host = host.split(":", 1)[0]
        try:
            ipaddress.ip_address(host)
        except ValueError:
            continue
        found = host
    return found


def client_identity(remote_addr, forwarded_for=None, trust_proxy=None):
    """Use the socket address unless the peer is a proxy we were told to trust.

    A client-supplied prefix is not a new identity. The trusted proxy's
    appended hop is the only forwarded address that selects a bucket.
    """
    peer = (remote_addr or "").strip() or "unknown"
    if trust_proxy is None:
        trust_proxy = trust_proxy_enabled()
    if not trust_proxy or not _trusted_peer(peer):
        return peer
    return _forwarded_client(forwarded_for) or peer


class RateLimit:
    def __init__(self, per_minute: int = 30):
        self.per_minute = per_minute
        self.hits = {}
        self._lock = threading.Lock()

    def _window(self, key, now):
        return [stamp for stamp in self.hits.get(key, []) if now - stamp < 60]

    def _prune(self, now):
        dead = [key for key, stamps in self.hits.items() if not any(now - stamp < 60 for stamp in stamps)]
        for key in dead:
            self.hits.pop(key, None)

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            self._prune(now)
            window = self._window(key, now)
            if len(window) >= self.per_minute:
                self.hits[key] = window
                return False
            window.append(now)
            self.hits[key] = window
            return True

    def retry_after(self, key: str) -> int:
        now = time.time()
        with self._lock:
            window = self._window(key, now)
            if len(window) < self.per_minute or not window:
                return 0
            return max(1, int(60 - (now - min(window))) + 1)
