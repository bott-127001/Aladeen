"""MetaTrader 5 (MT5) Read-Only Market Data Adapter.

Provides read-only access to local MT5 market data:
- Connects to an already-running local MT5 terminal using its existing session.
- Fetches symbol lists and recent OHLC candle history.
- Never requests, stores, logs, or commits account credentials.
- Strictly read-only: contains zero order-execution or trading logic.
- Safe when MetaTrader5 package is not installed (optional dependency).
"""

from __future__ import annotations

import logging
from typing import Any
import pandas as pd

from aladeen.data.contract import validate_candle_data

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


# Supported timeframe labels mapped to MT5 standard integer constants.
# These constants correspond to mt5.TIMEFRAME_* values without requiring MT5 import.
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
        self._connected: bool = False

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

    def is_connected(self) -> bool:
        """Check whether the adapter is currently connected to the local MT5 terminal."""
        if not self._connected:
            return False

        try:
            mt5 = self._get_mt5()
            info = mt5.terminal_info()
            if info is None:
                self._connected = False
                return False
            return True
        except Exception:
            self._connected = False
            return False

    def connect(self) -> None:
        """Connect to the running local MT5 terminal using its existing session.

        Does NOT request, store, or accept any user credentials or passwords.
        Connects directly to the existing session via mt5.initialize().

        Raises
        ------
        MT5NotInstalledError
            If MetaTrader5 package is not installed.
        MT5ConnectionError
            If the terminal fails to initialize (e.g. not running or closed).
        """
        mt5 = self._get_mt5()

        # If already connected and terminal is responsive, reuse connection
        if self._connected:
            try:
                if mt5.terminal_info() is not None:
                    return
            except Exception:
                self._connected = False

        # Attempt initialization without credentials
        success = mt5.initialize()
        if not success:
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

        self._connected = True
        logger.info("Connected to local MT5 terminal.")

    def disconnect(self) -> None:
        """Disconnect and cleanup the MT5 terminal connection."""
        if self._connected:
            try:
                mt5 = self._get_mt5()
                mt5.shutdown()
            except Exception as e:
                logger.warning(f"Error during MT5 shutdown: {e}")
            finally:
                self._connected = False
                logger.info("Disconnected from MT5 terminal.")

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

        # Distinguish forming vs completed candles:
        # In copy_rates_from_pos starting from pos 0, the latest candle at index -1
        # is the currently open/forming candle.
        df["is_forming"] = False
        df.iloc[-1, df.columns.get_loc("is_forming")] = True

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
