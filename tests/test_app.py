"""Tests for app construction, CLI arguments, and UI consistency.

Verifies the Dash app can be created without MT5 installed or running,
that debug mode is disabled by default, and that connection state changes
update all UI components consistently.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock
from dash import Dash
import pandas as pd
import pytest

from aladeen.app import create_app, parse_args
from aladeen.data.fixtures import DEMO_SYMBOL
from aladeen.data.mt5_adapter import (
    MT5Adapter,
    MT5ConnectionError,
    MT5ConnectionState,
    MT5DataError,
)
from aladeen.ui.layout import (
    generate_chart_and_status,
    process_connection_and_banner,
    process_dashboard_update,
)


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

        assert "DEMO DATA" not in fig.layout.title.text
        assert DEMO_SYMBOL not in fig.layout.title.text
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


class TestUIConsistencyAndStateSynchronization:
    """Verify atomic state updates: badge, banner, chart, and errors stay in sync."""

    def test_connection_loss_during_refresh_clears_green_banner_atomically(self) -> None:
        """When connection is lost during refresh, banner must NOT remain green."""
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.fetch_candles.side_effect = MT5ConnectionError("Terminal pipe broken")

        res = process_dashboard_update(
            triggered_id="refresh-btn",
            data_source="mt5",
            current_symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            store_data={"state": "CONNECTED_TO_BROKER", "symbols": ["EURUSD"]},
            adapter=mock_adapter,
        )

        # Badge must be Disconnected
        assert res["badge_text"] == "Disconnected"
        # Banner must be Disconnected (NOT green connected!)
        assert "🔴 MT5 DISCONNECTED" in res["banner_text"]
        assert res["banner_style"]["background"] == "#37474f"
        # Error alert must be visible
        assert res["alert_style"]["display"] == "block"
        assert "Connection Lost" in res["status_text"]
        # Chart must NOT show demo data
        assert "DEMO DATA" not in res["figure"].layout.title.text

    def test_switch_to_demo_distinguishes_source_from_open_mt5_connection(self) -> None:
        """Selecting demo mode keeps MT5 open in background and indicates both clearly."""
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER

        res = process_dashboard_update(
            triggered_id="data-source-selector",
            data_source="demo",
            current_symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            store_data={"state": "CONNECTED_TO_BROKER", "symbols": ["EURUSD"]},
            adapter=mock_adapter,
        )

        # Chart is demo data
        assert "DEMO DATA" in res["figure"].layout.title.text
        assert res["sym_value"] == DEMO_SYMBOL
        assert res["sym_disabled"] is True
        # MT5 connection badge remains Connected
        assert res["badge_text"] == "🟢 Connected to Broker"
        # Banner reflects selected chart source AND background MT5 connection
        assert "DEMO MODE" in res["banner_text"]
        assert "MT5 connected to broker in background" in res["banner_text"]

    def test_terminal_only_broker_offline_distinction(self) -> None:
        """Terminal responsive but broker offline shows distinct yellow/orange badge and banner."""
        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.TERMINAL_ONLY
        mock_adapter.connect.return_value = MT5ConnectionState.TERMINAL_ONLY
        mock_adapter.get_symbols.return_value = ["EURUSD"]

        res = process_dashboard_update(
            triggered_id="connect-btn",
            data_source="mt5",
            current_symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            store_data={"state": "DISCONNECTED", "symbols": []},
            adapter=mock_adapter,
        )

        assert res["badge_text"] == "🟡 Terminal Ready (Broker Offline)"
        assert "Broker Offline" in res["banner_text"]

    def test_broker_state_transition_synchronization(self) -> None:
        """When broker goes offline during refresh, badge and banner update without disconnecting."""
        times = pd.date_range("2026-10-01", periods=5, freq="4h", tz="UTC")
        df_mock = pd.DataFrame(
            {
                "open": [1.1, 1.11, 1.12, 1.13, 1.14],
                "high": [1.15, 1.16, 1.17, 1.18, 1.19],
                "low": [1.05, 1.06, 1.07, 1.08, 1.09],
                "close": [1.12, 1.13, 1.14, 1.15, 1.16],
                "is_forming": [False, False, False, False, True],
                "is_latest_bar": [False, False, False, False, True],
                "bar_status": ["CONFIRMED_COMPLETED"] * 4 + ["UNCONFIRMED_LATEST"],
            },
            index=times,
        )

        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.is_broker_connected.return_value = False
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.TERMINAL_ONLY
        mock_adapter.fetch_candles.return_value = df_mock

        res = process_dashboard_update(
            triggered_id="refresh-btn",
            data_source="mt5",
            current_symbol="GBPUSD",
            timeframe="H4",
            candle_count=100,
            store_data={"state": "CONNECTED_TO_BROKER", "symbols": ["EURUSD", "GBPUSD"]},
            adapter=mock_adapter,
        )

        # State must transition to TERMINAL_ONLY
        assert res["store_data"]["state"] == "TERMINAL_ONLY"
        assert res["badge_text"] == "🟡 Terminal Ready (Broker Offline)"
        assert "Broker Offline" in res["banner_text"]
        # Symbols and current selection must be preserved
        assert res["store_data"]["symbols"] == ["EURUSD", "GBPUSD"]
        assert res["sym_value"] == "GBPUSD"
        # Disconnect must NOT have been called
        mock_adapter.disconnect.assert_not_called()

    def test_symbol_preservation_across_reconnects(self) -> None:
        """When reconnecting or refreshing, existing symbol selection is preserved if present."""
        mock_adapter = MagicMock()
        mock_adapter.connect.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.get_symbols.return_value = ["EURUSD", "GBPUSD", "USDJPY"]
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER

        res = process_connection_and_banner(
            triggered_id="connect-btn",
            data_source="mt5",
            store_data={"state": "DISCONNECTED", "symbols": []},
            current_symbol="GBPUSD",
            adapter=mock_adapter,
        )

        assert res["sym_value"] == "GBPUSD"

    def test_steady_state_refresh_settles_without_trigger(self) -> None:
        """When state does not change during fetch, loss_trigger is None (dash.no_update)."""
        times = pd.date_range("2026-10-01", periods=5, freq="4h", tz="UTC")
        df_mock = pd.DataFrame(
            {
                "open": [1.1, 1.11, 1.12, 1.13, 1.14],
                "high": [1.15, 1.16, 1.17, 1.18, 1.19],
                "low": [1.05, 1.06, 1.07, 1.08, 1.09],
                "close": [1.12, 1.13, 1.14, 1.15, 1.16],
                "is_forming": [False, False, False, False, True],
                "is_latest_bar": [False, False, False, False, True],
                "bar_status": ["CONFIRMED_COMPLETED"] * 4 + ["UNCONFIRMED_LATEST"],
            },
            index=times,
        )

        mock_adapter = MagicMock()
        mock_adapter.is_connected.return_value = True
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.fetch_candles.return_value = df_mock

        from aladeen.ui.layout import generate_chart_and_status_with_trigger
        fig, status, loss_trigger = generate_chart_and_status_with_trigger(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            is_connected=True,
            adapter=mock_adapter,
            current_state="CONNECTED_TO_BROKER",
        )

        assert loss_trigger is None
        assert "Broker Connected" in status
