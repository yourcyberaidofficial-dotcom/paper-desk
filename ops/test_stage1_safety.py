"""Stage 1 locks: session token, process completion, and a markup-free name."""

from pathlib import Path

from ops.ai_safety import accept_display_name


def test_markup_is_not_a_display_name():
    assert accept_display_name("Ada") == "Ada"
    assert accept_display_name("<b>Ada</b>") is None
    assert accept_display_name("Ada<script>") is None


def test_the_server_entry_registers_digest_before_it_serves():
    text = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")
    start = text.find("if __name__")
    assert start > text.find("def digest(")
    assert start > text.find('_spawn(_digest_loop, "aureon-digest")')
    assert start > text.find("atexit.register(_shutdown_background)")


def test_a_state_change_without_the_session_token_is_refused():
    from ops.app import app

    app.config["CSRF_ENFORCE"] = True
    client = app.test_client()
    client.raw_csrf = True
    with client.session_transaction() as sess:
        sess["csrf"] = "a" * 32
        sess["user_id"] = "absent"
        sess["user_exp"] = 9_999_999_999
    denied = client.post("/api/logout")
    assert denied.status_code == 403
    assert denied.get_json()["error"] == "csrf"
    allowed = client.post("/api/logout", headers={"X-CSRF-Token": "a" * 32})
    assert allowed.status_code != 403
