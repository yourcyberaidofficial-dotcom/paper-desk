"""Browser-style requests carry the session token. Production still checks it."""

import os

from flask.testing import FlaskClient

_OPEN = FlaskClient.open


def _open(self, *args, **kwargs):
    method = str(kwargs.get("method") or (args[0] if args and not str(args[0]).startswith("/") else "GET")).upper()
    if method in {"POST", "PUT", "PATCH", "DELETE"} and not getattr(self, "raw_csrf", False):
        headers = dict(kwargs.get("headers") or {})
        if "X-CSRF-Token" not in headers and "X-CSRF-Token" not in {str(key) for key in headers}:
            with self.session_transaction() as sess:
                token = sess.get("csrf") or os.urandom(16).hex()
                sess["csrf"] = token
            headers["X-CSRF-Token"] = token
            kwargs["headers"] = headers
    return _OPEN(self, *args, **kwargs)


FlaskClient.open = _open
