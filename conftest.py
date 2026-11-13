"""The suite proves behaviour. CSRF is enforced in a focused test and in the process tests."""

import pytest


@pytest.fixture(autouse=True)
def _csrf_is_explicit_in_one_test():
    from ops.app import app

    previous = app.config.get("CSRF_ENFORCE", True)
    app.config["CSRF_ENFORCE"] = False
    yield
    app.config["CSRF_ENFORCE"] = previous
