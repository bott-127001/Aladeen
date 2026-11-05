"""Direct-call tests of registered Dash callback functions using mocked adapters.

Tests the actual registered callback functions from `register_callbacks(app)`:
- `handle_connection_and_options` (Callback 1)
- `update_chart` (Callback 2)

Scope & Verification Boundary:
------------------------------
These tests manually invoke the registered callback functions in a chosen sequence
with mocked adapter states and dash.no_update assertions. They verify callback logic
and state synchronization in Python without launching a browser.
They do NOT run the browser's client-side JavaScript dependency scheduler or
independently prove asynchronous graph convergence in the browser runtime.
(Browser runtime behavior and console error absence are separately verified in
`tests/browser_check.py`).

Transitions Covered:
1. Initial Connect
2. Steady-State Refresh
3. Broker Connected -> Terminal Only (Broker Offline)
4. Terminal Only -> Broker Connected (Broker Online)
5. Connection Loss during Fetch
6. Reconnect after Failure
"""

from __future__ import annotations

from unittest.mock import MagicMock
import dash
from dash import Dash
import pandas as pd
import pytest

from aladeen.data.contract import BarStatus
from aladeen.data.mt5_adapter import MT5ConnectionError, MT5ConnectionState
from aladeen.ui.layout import build_layout, register_callbacks


def _make_mock_candles(n: int = 10) -> pd.DataFrame:
    """Generate a valid contract-compliant candle DataFrame."""
    times = pd.date_range("2026-10-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [1.100 + i * 0.001 for i in range(n)],
            "high": [1.105 + i * 0.001 for i in range(n)],
            "low": [1.095 + i * 0.001 for i in range(n)],
            "close": [1.102 + i * 0.001 for i in range(n)],
            "is_forming": [False] * (n - 1) + [True],
            "is_latest_bar": [False] * (n - 1) + [True],
            "bar_status": [BarStatus.CONFIRMED_COMPLETED.value] * (n - 1) + [BarStatus.UNCONFIRMED_LATEST.value],
        },
        index=times,
    )
    return df


class TestActualCallbackSettling:
    """Test actual registered application callbacks for settling and convergence."""

    @pytest.fixture
    def setup_app_and_callbacks(self):
        """Create a Dash app and extract actual registered callback functions with mock adapter."""
        app = Dash(__name__)
        app.layout = build_layout()

        mock_adapter = MagicMock()
        mock_adapter.is_package_installed.return_value = True
        mock_adapter.connect.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_symbols.return_value = ["EURUSD", "GBPUSD", "USDJPY"]
        mock_adapter.fetch_candles.return_value = _make_mock_candles(20)

        handle_conn, update_chart = register_callbacks(app, adapter=mock_adapter)
        return app, mock_adapter, handle_conn, update_chart

    def test_steady_state_refresh_settles_immediately(self, setup_app_and_callbacks) -> None:
        """Steady-state refresh executes one fetch, outputs dash.no_update, and terminates callback chain."""
        _, mock_adapter, handle_conn, update_chart = setup_app_and_callbacks

        store = {"state": "CONNECTED_TO_BROKER", "symbols": ["EURUSD", "GBPUSD"]}

        # Call update_chart on refresh
        fig, status, trigger = update_chart(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            _n_clicks=1,
            store_data=store,
        )

        # Must return dash.no_update to prevent firing handle_conn
        assert trigger is dash.no_update
        assert "Broker Connected" in status
        assert mock_adapter.fetch_candles.call_count == 1

        # Because trigger is no_update, handle_conn is NOT invoked by Dash
        # Calling handle_conn with no_update is a no-op that preserves state
        res = handle_conn(
            _connect_clicks=0,
            _disconnect_clicks=0,
            data_source="mt5",
            loss_trigger=None,
            store_data=store,
            current_symbol="EURUSD",
            triggered_id="",
        )
        assert res[0]["state"] == "CONNECTED_TO_BROKER"
        assert res[6] == "EURUSD"  # Symbol preserved
        assert mock_adapter.fetch_candles.call_count == 1  # No secondary fetch

    def test_broker_connected_to_terminal_only_transition_converges(self, setup_app_and_callbacks) -> None:
        """When broker goes offline, state_change trigger updates UI and settles in exactly 2 passes without loop."""
        _, mock_adapter, handle_conn, update_chart = setup_app_and_callbacks

        # Broker goes offline
        mock_adapter.is_broker_connected.return_value = False
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.TERMINAL_ONLY

        store = {"state": "CONNECTED_TO_BROKER", "symbols": ["EURUSD", "GBPUSD"]}

        # Pass 1: update_chart detects broker transition
        fig1, status1, trigger1 = update_chart(
            data_source="mt5",
            symbol="GBPUSD",
            timeframe="H4",
            candle_count=100,
            _n_clicks=1,
            store_data=store,
        )
        assert trigger1 is not dash.no_update
        assert trigger1["type"] == "state_change"
        assert trigger1["new_state"] == "TERMINAL_ONLY"
        assert "Broker Offline - Cached" in status1

        # Pass 2: handle_conn processes state_change trigger
        res2 = handle_conn(
            _connect_clicks=0,
            _disconnect_clicks=0,
            data_source="mt5",
            loss_trigger=trigger1,
            store_data=store,
            current_symbol="GBPUSD",
            triggered_id="connection-loss-trigger",
        )
        new_store = res2[0]
        badge_text = res2[1]
        banner_text = res2[3]
        sym_value = res2[6]

        assert new_store["state"] == "TERMINAL_ONLY"
        assert badge_text == "🟡 Terminal Ready (Broker Offline)"
        assert "Broker Offline" in banner_text
        assert sym_value == "GBPUSD"  # Preserved!
        mock_adapter.disconnect.assert_not_called()  # Did not disconnect!

        # Pass 3: Dash feeds new_store back to update_chart
        fig3, status3, trigger3 = update_chart(
            data_source="mt5",
            symbol="GBPUSD",
            timeframe="H4",
            candle_count=100,
            _n_clicks=0,
            store_data=new_store,
        )

        # In pass 3, current_state matches adapter state (TERMINAL_ONLY == TERMINAL_ONLY)
        # So trigger3 MUST be dash.no_update, terminating the cycle!
        assert trigger3 is dash.no_update
        assert "Broker Offline - Cached" in status3

    def test_terminal_only_to_broker_connected_transition_converges(self, setup_app_and_callbacks) -> None:
        """When broker comes back online, state_change trigger updates UI and terminates with dash.no_update."""
        _, mock_adapter, handle_conn, update_chart = setup_app_and_callbacks

        # Broker comes back online
        mock_adapter.is_broker_connected.return_value = True
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER

        store = {"state": "TERMINAL_ONLY", "symbols": ["EURUSD", "GBPUSD"]}

        # Pass 1: update_chart detects transition back to broker connected
        fig1, status1, trigger1 = update_chart(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            _n_clicks=1,
            store_data=store,
        )
        assert trigger1 is not dash.no_update
        assert trigger1["type"] == "state_change"
        assert trigger1["new_state"] == "CONNECTED_TO_BROKER"

        # Pass 2: handle_conn processes transition
        res2 = handle_conn(
            _connect_clicks=0,
            _disconnect_clicks=0,
            data_source="mt5",
            loss_trigger=trigger1,
            store_data=store,
            current_symbol="EURUSD",
            triggered_id="connection-loss-trigger",
        )
        new_store = res2[0]
        assert new_store["state"] == "CONNECTED_TO_BROKER"
        assert res2[1] == "🟢 Connected to Broker"
        assert "Broker Connected" in res2[3]

        # Pass 3: update_chart receives new_store with CONNECTED_TO_BROKER
        fig3, status3, trigger3 = update_chart(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            _n_clicks=0,
            store_data=new_store,
        )
        # Must be dash.no_update, terminating cycle!
        assert trigger3 is dash.no_update

    def test_connection_loss_during_fetch_converges_to_disconnected(self, setup_app_and_callbacks) -> None:
        """When terminal connection drops during fetch, UI cleanly converges to disconnected without recursion."""
        _, mock_adapter, handle_conn, update_chart = setup_app_and_callbacks

        mock_adapter.fetch_candles.side_effect = MT5ConnectionError("Terminal pipe broke")
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.DISCONNECTED

        store = {"state": "CONNECTED_TO_BROKER", "symbols": ["EURUSD", "GBPUSD"]}

        # Pass 1: update_chart catches error, disconnects adapter, and emits connection_loss
        fig1, status1, trigger1 = update_chart(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            _n_clicks=1,
            store_data=store,
        )
        assert trigger1 is not dash.no_update
        assert trigger1["type"] == "connection_loss"
        assert "Connection Lost" in status1
        mock_adapter.disconnect.assert_called()

        # Pass 2: handle_conn sets state to DISCONNECTED
        res2 = handle_conn(
            _connect_clicks=0,
            _disconnect_clicks=0,
            data_source="mt5",
            loss_trigger=trigger1,
            store_data=store,
            current_symbol="EURUSD",
            triggered_id="connection-loss-trigger",
        )
        new_store = res2[0]
        badge_text = res2[1]
        banner_text = res2[3]

        assert new_store["state"] == "DISCONNECTED"
        assert new_store["symbols"] == []
        assert badge_text == "Disconnected"
        assert "🔴 MT5 DISCONNECTED" in banner_text

        # Pass 3: update_chart receives DISCONNECTED
        fig3, status3, trigger3 = update_chart(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            _n_clicks=0,
            store_data=new_store,
        )
        assert trigger3 is dash.no_update
        assert "🔴 MT5 Disconnected" in status3

    def test_reconnect_after_failure_settles_atomically(self, setup_app_and_callbacks) -> None:
        """Clicking Connect MT5 after failure transitions state back to CONNECTED and settles with dash.no_update."""
        _, mock_adapter, handle_conn, update_chart = setup_app_and_callbacks

        mock_adapter.fetch_candles.side_effect = None
        mock_adapter.connect.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.get_connection_state.return_value = MT5ConnectionState.CONNECTED_TO_BROKER
        mock_adapter.is_broker_connected.return_value = True

        disconnected_store = {"state": "DISCONNECTED", "symbols": []}

        # Step 1: User clicks Connect MT5
        res1 = handle_conn(
            _connect_clicks=1,
            _disconnect_clicks=0,
            data_source="mt5",
            loss_trigger=None,
            store_data=disconnected_store,
            current_symbol="EURUSD",
            triggered_id="connect-btn",
        )
        connected_store = res1[0]
        assert connected_store["state"] == "CONNECTED_TO_BROKER"
        assert connected_store["symbols"] == ["EURUSD", "GBPUSD", "USDJPY"]
        assert res1[1] == "🟢 Connected to Broker"
        assert res1[6] == "EURUSD"

        # Step 2: Dash triggers update_chart with new connected_store
        fig2, status2, trigger2 = update_chart(
            data_source="mt5",
            symbol="EURUSD",
            timeframe="H4",
            candle_count=100,
            _n_clicks=0,
            store_data=connected_store,
        )
        assert trigger2 is dash.no_update
        assert "Broker Connected" in status2
