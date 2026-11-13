"""Customer HTML. Served by the page routes. Not a second application."""

from pathlib import Path

_UI = Path(__file__).resolve().parent / "ui"
LANDING = (_UI / "landing.html").read_text(encoding="utf-8")
DASHBOARD = (_UI / "dashboard.html").read_text(encoding="utf-8")
