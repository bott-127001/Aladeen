"""MetaTrader 5 (MT5) Read-Only Market Data Adapter.

Provides read-only access to local MT5 market data:
- Connects to an already-running local MT5 terminal using its existing session.
- Distinguishes local terminal API responsiveness from trade broker connectivity.
- Fetches symbol lists and recent OHLC candle history.
- Never requests, stores, logs, or commits account credentials or balances.
- Strictly read-only: contains zero order-execution or trading logic.
- Safe when MetaTrader5 package is not installed (optional dependency).
- Safe and idempotent disconnect / cleanup.
"""

from __future__ import annotations

import atexit
from enum import Enum
import logging
from typing import Any
import pandas as pd

from aladeen.data.contract import BarStatus, validate_candle_data

logger = logging.getLogger(__name__)


class MT5Error(Exception):
    """Base exception for all MT5 adapter errors."""
    pass


class MT5NotInstalledError(MT5Error):
    """Raised when the MetaTrader5 Python package is not installed."""
    pass


class MT5ConnectionError(MT5Error):
    """Raised when connection to the local MT5 terminal fails."""
    pass


class MT5SymbolError(MT5Error):
    """Raised when a symbol is unavailable or cannot be selected."""
    pass


class MT5DataError(MT5Error):
    """Raised when market data retrieval fails or returns empty/invalid data."""
    pass


class MT5ConnectionState(str, Enum):
    """Detailed connection state distinguishing local terminal from broker server."""
    DISCONNECTED = "DISCONNECTED"                      # Terminal API not running or closed
    TERMINAL_ONLY = "TERMINAL_ONLY"                    # Terminal API responsive, but broker connection is offline
    CONNECTED_TO_BROKER = "CONNECTED_TO_BROKER"        # Terminal API responsive AND connected to broker


# Supported timeframe labels mapped to MT5 standard integer constants.
TIMEFRAME_MAP: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}


class MT5Adapter:
    """Read-only adapter for MetaTrader 5 terminal.

    Parameters
    ----------
    mt5_module : Any | None
        Optional reference to the MetaTrader5 module. If None, it will be
        imported dynamically on demand. Allows injecting mock modules for tests.
    """

    def __init__(self, mt5_module: Any = None) -> None:
        self._mt5 = mt5_module
        self._initialized: bool = False

    def _get_mt5(self) -> Any:
        """Return the MetaTrader5 module or raise MT5NotInstalledError."""
        if self._mt5 is not None:
            return self._mt5

        try:
            import MetaTrader5 as mt5  # type: ignore
            self._mt5 = mt5
            return self._mt5
        except ImportError as exc:
            raise MT5NotInstalledError(
                "The 'MetaTrader5' package is not installed. "
                "To enable MT5 integration, install it via: pip install -e \".[mt5]\" "
                "or pip install MetaTrader5 (Windows only)."
            ) from exc

    def is_package_installed(self) -> bool:
        """Check whether the MetaTrader5 package is installed and importable."""
        try:
            self._get_mt5()
            return True
        except MT5NotInstalledError:
            return False

    def get_connection_state(self) -> MT5ConnectionState:
        """Inspect the terminal's reported connection health.

        Distinguishes local terminal API responsiveness from broker server connectivity:
        - DISCONNECTED: Local terminal process is not initialized or closed.
        - TERMINAL_ONLY: Local terminal is responsive, but broker server is disconnected.
        - CONNECTED_TO_BROKER: Local terminal is responsive AND connected to broker server.
        """
        if not self._initialized:
            return MT5ConnectionState.DISCONNECTED

        try:
            mt5 = self._get_mt5()
            info = mt5.terminal_info()
            if info is None:
                self._initialized = False
                return MT5ConnectionState.DISCONNECTED

            # Inspect the terminal's reported connected status to the trade server
            is_broker_connected = getattr(info, "connected", False)
            if is_broker_connected:
                return MT5ConnectionState.CONNECTED_TO_BROKER
            else:
                return MT5ConnectionState.TERMINAL_ONLY
        except Exception:
            self._initialized = False
            return MT5ConnectionState.DISCONNECTED

    def is_terminal_responsive(self) -> bool:
        """Check whether the local MT5 terminal process is responsive."""
        return self.get_connection_state() != MT5ConnectionState.DISCONNECTED

    def is_broker_connected(self) -> bool:
        """Check whether the terminal is actively connected to the broker server."""
        return self.get_connection_state() == MT5ConnectionState.CONNECTED_TO_BROKER

    def is_connected(self) -> bool:
        """Check whether the adapter is connected and terminal API is responsive."""
        return self.is_terminal_responsive()

    def connect(self) -> MT5ConnectionState:
        """Connect to the running local MT5 terminal using its existing session.

        Does NOT request, store, or accept any user credentials or passwords.
        Connects directly to the existing session via mt5.initialize().

        Returns
        -------
        MT5ConnectionState
            The resulting connection state (TERMINAL_ONLY or CONNECTED_TO_BROKER).

        Raises
        ------
        MT5NotInstalledError
            If MetaTrader5 package is not installed.
        MT5ConnectionError
            If the terminal fails to initialize (e.g. not running or closed).
        """
        mt5 = self._get_mt5()

        # If already initialized and terminal is responsive, reuse connection
        if self._initialized:
            state = self.get_connection_state()
            if state != MT5ConnectionState.DISCONNECTED:
                return state

        # Attempt initialization without credentials
        success = mt5.initialize()
        if not success:
            self._initialized = False
            err_code, err_msg = (None, None)
            try:
                last_err = mt5.last_error()
                if isinstance(last_err, (tuple, list)) and len(last_err) >= 2:
                    err_code, err_msg = last_err[0], last_err[1]
                else:
                    err_msg = str(last_err)
            except Exception:
                pass

            err_details = f" (MT5 Error: {err_code} - {err_msg})" if err_msg else ""
            raise MT5ConnectionError(
                "Failed to connect to local MT5 terminal. "
                "Please ensure the MetaTrader 5 desktop application is running, "
                "logged into a trading account, and permits local API connections."
                + err_details
            )

        self._initialized = True
        state = self.get_connection_state()
        logger.info(f"Connected to local MT5 terminal. State: {state.value}")
        return state

    def disconnect(self) -> None:
        """Disconnect and cleanup the MT5 terminal connection.

        This method is strictly safe and idempotent: it can be called multiple
        times or after a failed health check without raising errors.
        """
        try:
            if self._mt5 is not None and hasattr(self._mt5, "shutdown"):
                self._mt5.shutdown()
        except Exception as e:
            logger.warning(f"Error during MT5 shutdown: {e}")
        finally:
            self._initialized = False
            logger.info("Disconnected from MT5 terminal (state reset).")

    def get_symbols(self) -> list[str]:
        """Fetch list of available symbols from the connected MT5 terminal.

        Returns
        -------
        list[str]
            Sorted list of symbol names.

        Raises
        ------
        MT5ConnectionError
            If not connected to MT5.
        """
        if not self.is_connected():
            raise MT5ConnectionError(
                "Not connected to MT5 terminal. Please click 'Connect MT5' first."
            )

        mt5 = self._get_mt5()
        symbols = mt5.symbols_get()
        if symbols is None or len(symbols) == 0:
            return []

        # Prioritize visible symbols (MarketWatch) if available
        visible_names = [s.name for s in symbols if getattr(s, "visible", True)]
        all_names = [s.name for s in symbols]

        result = sorted(set(visible_names if visible_names else all_names))
        return result

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        count: int = 100,
    ) -> pd.DataFrame:
        """Fetch recent OHLC candlestick data from the local MT5 terminal.

        Bar Position Zero Semantics:
        ----------------------------
        In MT5 copy_rates_from_pos(symbol, tf, 0, count):
        - Index pos = 0 returns the latest candle known to the terminal.
        - Historical rows (pos >= 1) are verified completed historical candles
          (is_forming = False, bar_status = 'CONFIRMED_COMPLETED').
        - The latest row (pos = 0) represents the current bar.
        - In a static snapshot or manual refresh, whether this latest bar is
          still developing or closed depends on broker market session hours,
          weekend closures, and live tick delivery. It CANNOT be verified
          solely from the snapshot without real-time broker session confirmation.
        - The adapter marks the latest row with is_forming = True and
          bar_status = 'UNCONFIRMED_LATEST' to explicitly represent that its
          completion is uncertified.

        Parameters
        ----------
        symbol : str
            Instrument symbol (e.g. 'EURUSD', 'XAUUSD').
        timeframe : str
            Timeframe key ('D1', 'H4', 'H1', 'M5', 'M1').
        count : int, default 100
            Number of recent candles to fetch (bounded between 10 and 2000).

        Returns
        -------
        pd.DataFrame
            DataFrame complying with the shared candle data contract.

        Raises
        ------
        MT5ConnectionError
            If not connected to MT5.
        MT5SymbolError
            If the symbol is invalid or unavailable.
        MT5DataError
            If timeframe is unsupported or no rates are returned.
        """
        if not self.is_connected():
            raise MT5ConnectionError(
                "Not connected to MT5 terminal. Please click 'Connect MT5' first."
            )

        if timeframe not in TIMEFRAME_MAP:
            raise MT5DataError(
                f"Unsupported timeframe '{timeframe}'. "
                f"Supported timeframes are: {list(TIMEFRAME_MAP.keys())}."
            )

        # Bound count between 10 and 2000
        count = max(10, min(count, 2000))

        mt5 = self._get_mt5()

        # Ensure symbol is selected in MarketWatch
        if hasattr(mt5, "symbol_select"):
            selected = mt5.symbol_select(symbol, True)
            if not selected:
                raise MT5SymbolError(
                    f"Symbol '{symbol}' was not found or could not be selected in MT5."
                )

        tf_val = TIMEFRAME_MAP[timeframe]
        rates = mt5.copy_rates_from_pos(symbol, tf_val, 0, count)

        if rates is None or len(rates) == 0:
            err_info = ""
            try:
                err_info = f" (Error details: {mt5.last_error()})"
            except Exception:
                pass
            raise MT5DataError(
                f"No candle data returned for '{symbol}' on {timeframe}. "
                "Ensure history is loaded in your MT5 terminal for this timeframe."
                + err_info
            )

        df = pd.DataFrame(rates)

        # Required fields in MT5 rate record: time, open, high, low, close
        required = ("time", "open", "high", "low", "close")
        for req in required:
            if req not in df.columns:
                raise MT5DataError(f"Malformed MT5 rate record: missing column '{req}'.")

        # Convert epoch seconds to timezone-aware UTC datetime
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")

        # Sort ascending chronologically
        if not df.index.is_monotonic_increasing:
            df = df.sort_index()

        # Explicit candle completion flags:
        # Preceding rows are completed historical bars
        df["is_forming"] = False
        df["bar_status"] = "CONFIRMED_COMPLETED"

        # The latest row (pos 0) is the latest known bar (unconfirmed completion)
        if len(df) > 0:
            df.iloc[-1, df.columns.get_loc("is_forming")] = True
            df.iloc[-1, df.columns.get_loc("bar_status")] = "UNCONFIRMED_LATEST"

        # Validate against the contract
        validated = validate_candle_data(df)
        return validated


# Default module-level singleton adapter
_default_adapter: MT5Adapter | None = None


def get_mt5_adapter() -> MT5Adapter:
    """Return the global default MT5Adapter instance."""
    global _default_adapter
    if _default_adapter is None:
        _default_adapter = MT5Adapter()
    return _default_adapter


def _cleanup_default_adapter() -> None:
    """Process exit handler to ensure clean terminal disconnection."""
    global _default_adapter
    if _default_adapter is not None:
        try:
            _default_adapter.disconnect()
        except Exception:
            pass


# Register clean shutdown at Python process exit
atexit.register(_cleanup_default_adapter)
