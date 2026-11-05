"""Tests for app construction, CLI arguments, and mode independence.

Verifies the Dash app can be created without MT5 installed or running,
and that debug mode is disabled by default.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock
from dash import Dash
import pytest

from aladeen.app import create_app, parse_args
from aladeen.data.fixtures import DEMO_SYMBOL
from aladeen.data.mt5_adapter import MT5Adapter, MT5ConnectionError, MT5DataError
from aladeen.ui.layout import generate_chart_and_status


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
        app = create_app()
        assert app is not None
        assert "MetaTrader5" not in sys.modules


class TestCommandLineArgs:
    """Verify CLI argument parsing and default security boundaries."""

    def test_debug_disabled_by_default(self) -> None:
        args = parse_args([])
        assert args.debug is False
        assert args.host == "127.0.0.1"
        assert args.port == 8050

    def test_debug_enabled_explicitly(self) -> None:
        args = parse_args(["--debug"])
        assert args.debug is True

    def test_custom_host_and_port(self) -> None:
        args = parse_args(["--host", "localhost", "--port", "9000"])
        assert args.host == "localhost"
        assert args.port == 9000


class TestModeIsolationAndFallbackRejection:
    """Verify demo mode isolation and strict prohibition of silent demo fallback."""

    def test_demo_mode_unaffected_by_mt5(self) -> None:
        """In demo mode, chart generator returns demo data without contacting MT5."""
        fig, status = generate_chart_and_status(
            data_source="demo",
            symbol=DEMO_SYMBOL,
            timeframe="H4",
            candle_count=100,
            is_connected=False,
        )
        assert "DEMO DATA" in fig.layout.title.text
        assert "Source: Demo" in status

    def test_mt5_failure_does_not_silently_fallback_to_demo(self) -> None:
        """In MT5 mode, a fetch failure must display an error/empty chart, NOT fallback to demo."""
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.fetch_candles.side_effect = MT5DataError("Network timeout connecting to broker history")

        fig, status = generate_chart_and_status(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            is_connected=True,
            adapter=mock_adapter,
        )

        # Must NOT contain demo data or demo symbol
        assert "DEMO DATA" not in fig.layout.title.text
        assert DEMO_SYMBOL not in fig.layout.title.text
        # Must show error status
        assert "❌ Data Fetch Error" in status
        assert "Network timeout" in status

    def test_mt5_disconnected_shows_disconnected_state_not_demo(self) -> None:
        """When MT5 is disconnected, it must not display demo data."""
        fig, status = generate_chart_and_status(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            is_connected=False,
        )
        assert "DEMO DATA" not in fig.layout.title.text
        assert "MT5 Terminal: Disconnected" in fig.layout.title.text
        assert "🔴 MT5 Disconnected" in status
