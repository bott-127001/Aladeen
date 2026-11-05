"""Data loading, contracts, MT5 adapter, and unified market snapshots."""

from .contract import BarStatus, CandleValidationError, validate_candle_data
from .fixtures import (
    DEMO_SYMBOL,
    SUPPORTED_TIMEFRAMES,
    available_symbols,
    available_timeframes,
    load_fixture,
)
from .market_snapshot import MarketDataSnapshot, fetch_market_snapshot
from .mt5_adapter import (
    MT5Adapter,
    MT5ConnectionError,
    MT5ConnectionState,
    MT5DataError,
    MT5Error,
    MT5NotInstalledError,
    MT5SymbolError,
    get_mt5_adapter,
)

__all__ = [
    "BarStatus",
    "CandleValidationError",
    "validate_candle_data",
    "DEMO_SYMBOL",
    "SUPPORTED_TIMEFRAMES",
    "available_symbols",
    "available_timeframes",
    "load_fixture",
    "MarketDataSnapshot",
    "fetch_market_snapshot",
    "MT5Adapter",
    "MT5ConnectionError",
    "MT5ConnectionState",
    "MT5DataError",
    "MT5Error",
    "MT5NotInstalledError",
    "MT5SymbolError",
    "get_mt5_adapter",
]
