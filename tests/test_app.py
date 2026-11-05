"""Tests for app construction.

Verifies the Dash app can be created without MT5 installed or running.
"""

from __future__ import annotations

from dash import Dash

from aladeen.app import create_app


class TestAppConstruction:
    """Verify the app can be built in any environment."""

    def test_create_app_returns_dash_instance(self) -> None:
        app = create_app()
        assert isinstance(app, Dash)

    def test_app_title(self) -> None:
        app = create_app()
        assert app.title == "Aladeen / TopG"

    def test_layout_is_set(self) -> None:
        app = create_app()
        assert app.layout is not None

    def test_no_mt5_import_required(self) -> None:
        """App construction must not import MetaTrader5."""
        import sys
        app = create_app()
        assert app is not None
        assert "MetaTrader5" not in sys.modules
