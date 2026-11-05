"""Tests for MT5 Read-Only Adapter using mocked MT5 module."""

from __future__ import annotations

from unittest.mock import MagicMock
import numpy as np
import pytest

from aladeen.data.contract import CandleValidationError
from aladeen.data.mt5_adapter import (
    MT5Adapter,
    MT5ConnectionError,
    MT5ConnectionState,
    MT5DataError,
    MT5NotInstalledError,
    MT5SymbolError,
    TIMEFRAME_MAP,
    _cleanup_default_adapter,
)


def _make_mock_rate_record(n: int = 20, base_time: int = 1700000000) -> np.ndarray:
    """Create a mock numpy structured array matching MT5 copy_rates format."""
    dtype = [
        ("time", "<i8"),
        ("open", "<f8"),
        ("high", "<f8"),
        ("low", "<f8"),
        ("close", "<f8"),
        ("tick_volume", "<i8"),
        ("spread", "<i4"),
        ("real_volume", "<i8"),
    ]
    records = []
    for i in range(n):
        t = base_time + i * 3600
        o = 1.1000 + i * 0.001
        h = o + 0.002
        l = o - 0.002
        c = o + 0.001
        records.append((t, o, h, l, c, 100, 10, 0))
    return np.array(records, dtype=dtype)


class TestMT5AdapterMissingDependency:
    """Verify behavior when MetaTrader5 package is not installed."""

    def test_missing_dependency_raises_not_installed_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        adapter = MT5Adapter(mt5_module=None)

        import builtins
        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "MetaTrader5":
                raise ImportError("No module named 'MetaTrader5'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        assert not adapter.is_package_installed()
        with pytest.raises(MT5NotInstalledError, match="package is not installed"):
            adapter.connect()


class TestMT5AdapterConnection:
    """Verify connection lifecycle, broker connectivity distinction, and cleanup."""

    def test_connect_success_broker_connected(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        assert adapter.is_package_installed()
        assert not adapter.is_connected()

        state = adapter.connect()
        assert state == MT5ConnectionState.CONNECTED_TO_BROKER
        assert adapter.is_connected()
        assert adapter.is_terminal_responsive()
        assert adapter.is_broker_connected()
        mock_mt5.initialize.assert_called_once_with()

    def test_connect_success_terminal_only_broker_offline(self) -> None:
        """Terminal API responsive but broker connection is offline."""
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=False)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        state = adapter.connect()
        assert state == MT5ConnectionState.TERMINAL_ONLY
        assert adapter.is_terminal_responsive()
        assert not adapter.is_broker_connected()
        assert adapter.is_connected()

    def test_reconnect_avoidance_when_already_connected(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()
        assert mock_mt5.initialize.call_count == 1

        adapter.connect()
        assert mock_mt5.initialize.call_count == 1

    def test_connect_failure_raises_connection_error(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = False
        mock_mt5.last_error.return_value = (-10004, "Terminal is closed")

        adapter = MT5Adapter(mt5_module=mock_mt5)
        with pytest.raises(MT5ConnectionError, match="Failed to connect to local MT5 terminal"):
            adapter.connect()

        assert not adapter.is_connected()
        assert adapter.get_connection_state() == MT5ConnectionState.DISCONNECTED

    def test_disconnect_and_cleanup_idempotent(self) -> None:
        """Calling disconnect multiple times is safe, idempotent, and never raises."""
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()
        assert adapter.is_connected()

        adapter.disconnect()
        assert not adapter.is_connected()
        assert adapter.get_connection_state() == MT5ConnectionState.DISCONNECTED
        mock_mt5.shutdown.assert_called_once()

        # Repeated disconnect calls must succeed idempotently
        adapter.disconnect()
        adapter.disconnect()
        assert not adapter.is_connected()

    def test_disconnect_after_failed_health_check(self) -> None:
        """Disconnect must remain safe even after terminal_info becomes None."""
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()

        # Terminal closed abruptly
        mock_mt5.terminal_info.return_value = None
        assert not adapter.is_connected()

        # Disconnect should cleanly invoke shutdown without error
        adapter.disconnect()
        assert not adapter.is_connected()

    def test_cleanup_default_adapter_function(self) -> None:
        """Process exit helper executes safely."""
        _cleanup_default_adapter()


class TestMT5AdapterSymbols:
    """Verify symbol fetching and error handling."""

    def test_get_symbols_requires_connection(self) -> None:
        adapter = MT5Adapter(mt5_module=MagicMock())
        with pytest.raises(MT5ConnectionError, match="Not connected"):
            adapter.get_symbols()

    def test_get_symbols_returns_sorted_list(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)

        sym1 = MagicMock(name="sym1", visible=True)
        sym1.name = "XAUUSD"
        sym2 = MagicMock(name="sym2", visible=True)
        sym2.name = "EURUSD"
        sym3 = MagicMock(name="sym3", visible=False)
        sym3.name = "GBPUSD"
        mock_mt5.symbols_get.return_value = (sym1, sym2, sym3)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()
        symbols = adapter.get_symbols()

        assert symbols == ["EURUSD", "XAUUSD"]

    def test_get_symbols_handles_none_or_empty(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)
        mock_mt5.symbols_get.return_value = None

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()
        symbols = adapter.get_symbols()
        assert symbols == []


class TestMT5AdapterDataFetch:
    """Verify data fetching, parameters, validation, and contract compliance."""

    def test_fetch_requires_connection(self) -> None:
        adapter = MT5Adapter(mt5_module=MagicMock())
        with pytest.raises(MT5ConnectionError, match="Not connected"):
            adapter.fetch_candles("EURUSD", "H4")

    def test_unsupported_timeframe_raises_error(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()

        with pytest.raises(MT5DataError, match="Unsupported timeframe"):
            adapter.fetch_candles("EURUSD", "M15")

    @pytest.mark.parametrize("tf,expected_const", [
        ("M1", 1),
        ("M5", 5),
        ("H1", 16385),
        ("H4", 16388),
        ("D1", 16408),
    ])
    def test_correct_timeframe_and_symbol_passed(self, tf: str, expected_const: int) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)
        mock_mt5.symbol_select.return_value = True
        mock_mt5.copy_rates_from_pos.return_value = _make_mock_rate_record(20)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()

        df = adapter.fetch_candles("EURUSD", tf, count=50)
        mock_mt5.symbol_select.assert_called_with("EURUSD", True)
        mock_mt5.copy_rates_from_pos.assert_called_with("EURUSD", expected_const, 0, 50)
        assert len(df) == 20

    def test_candle_count_bounding(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)
        mock_mt5.symbol_select.return_value = True
        mock_mt5.copy_rates_from_pos.return_value = _make_mock_rate_record(15)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()

        # Count < 10 clamped to 10
        adapter.fetch_candles("EURUSD", "H4", count=2)
        mock_mt5.copy_rates_from_pos.assert_called_with("EURUSD", TIMEFRAME_MAP["H4"], 0, 10)

        # Count > 2000 clamped to 2000
        adapter.fetch_candles("EURUSD", "H4", count=5000)
        mock_mt5.copy_rates_from_pos.assert_called_with("EURUSD", TIMEFRAME_MAP["H4"], 0, 2000)

    def test_symbol_select_failure_raises_symbol_error(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)
        mock_mt5.symbol_select.return_value = False

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()

        with pytest.raises(MT5SymbolError, match="not found or could not be selected"):
            adapter.fetch_candles("INVALID_SYM", "H4")

    def test_empty_rates_raises_data_error(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)
        mock_mt5.symbol_select.return_value = True
        mock_mt5.copy_rates_from_pos.return_value = None
        mock_mt5.last_error.return_value = (1, "No history")

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()

        with pytest.raises(MT5DataError, match="No candle data returned"):
            adapter.fetch_candles("EURUSD", "H4")

    def test_forming_and_latest_candle_semantics(self) -> None:
        """Position 0 candle marked as forming/unconfirmed latest, while historical are confirmed."""
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)
        mock_mt5.symbol_select.return_value = True
        mock_mt5.copy_rates_from_pos.return_value = _make_mock_rate_record(10)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()

        df = adapter.fetch_candles("EURUSD", "H4", count=10)
        assert "is_forming" in df.columns
        assert "bar_status" in df.columns
        # Latest bar (index -1)
        assert bool(df["is_forming"].iloc[-1]) is True
        assert df["bar_status"].iloc[-1] == "UNCONFIRMED_LATEST"
        # Preceding bars
        assert not df["is_forming"].iloc[:-1].any()
        assert (df["bar_status"].iloc[:-1] == "CONFIRMED_COMPLETED").all()

    def test_stale_latest_bar_and_closed_market_snapshot(self) -> None:
        """A snapshot taken when the market is closed (stale latest bar) validates without error."""
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=False)  # Broker offline / weekend
        mock_mt5.symbol_select.return_value = True
        # Timestamp from 3 days ago (stale history)
        stale_time = 1600000000
        mock_mt5.copy_rates_from_pos.return_value = _make_mock_rate_record(10, base_time=stale_time)

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()

        df = adapter.fetch_candles("EURUSD", "H4", count=10)
        assert len(df) == 10
        assert bool(df["is_forming"].iloc[-1]) is True
        assert df["bar_status"].iloc[-1] == "UNCONFIRMED_LATEST"

    def test_malformed_rates_fails_contract_validation(self) -> None:
        mock_mt5 = MagicMock()
        mock_mt5.initialize.return_value = True
        mock_mt5.terminal_info.return_value = MagicMock(connected=True)
        mock_mt5.symbol_select.return_value = True

        bad_records = _make_mock_rate_record(10)
        bad_records["high"][0] = bad_records["low"][0] - 1.0
        mock_mt5.copy_rates_from_pos.return_value = bad_records

        adapter = MT5Adapter(mt5_module=mock_mt5)
        adapter.connect()

        with pytest.raises(CandleValidationError, match="High price < Low price"):
            adapter.fetch_candles("EURUSD", "H4")

    def test_no_order_execution_methods_exist(self) -> None:
        adapter = MT5Adapter()
        for forbidden in ("order_send", "order_calc_margin", "order_check", "buy", "sell"):
            assert not hasattr(adapter, forbidden)
