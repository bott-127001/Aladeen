"""Deterministic synthetic OHLC fixtures for development.

These fixtures are hard-coded demo data used only for UI prototyping.
They do NOT represent live, historical, or broker-sourced market data.
Refresh operations return the same data every time.
"""

from __future__ import annotations

import pandas as pd

from aladeen.data.contract import BarStatus, validate_candle_data

# ---------------------------------------------------------------------------
# Available fixture metadata
# ---------------------------------------------------------------------------

#: The single demo symbol available in fixture mode.
DEMO_SYMBOL = "DEMO_XAUUSD"

#: Timeframes that have fixture data. Others are unsupported in demo mode.
SUPPORTED_TIMEFRAMES: list[str] = ["H4", "D1"]

# ---------------------------------------------------------------------------
# Raw fixture data — 20 deterministic H4 candles
# ---------------------------------------------------------------------------

_H4_DATA: list[dict] = [
    {"time": "2026-10-01 00:00", "open": 1920.0, "high": 1928.0, "low": 1918.0, "close": 1926.0},
    {"time": "2026-10-01 04:00", "open": 1926.0, "high": 1932.0, "low": 1924.0, "close": 1930.0},
    {"time": "2026-10-01 08:00", "open": 1930.0, "high": 1935.0, "low": 1927.0, "close": 1928.0},
    {"time": "2026-10-01 12:00", "open": 1928.0, "high": 1929.0, "low": 1920.0, "close": 1922.0},
    {"time": "2026-10-01 16:00", "open": 1922.0, "high": 1930.0, "low": 1919.0, "close": 1929.0},
    {"time": "2026-10-01 20:00", "open": 1929.0, "high": 1936.0, "low": 1928.0, "close": 1934.0},
    {"time": "2026-10-02 00:00", "open": 1934.0, "high": 1940.0, "low": 1932.0, "close": 1938.0},
    {"time": "2026-10-02 04:00", "open": 1938.0, "high": 1942.0, "low": 1935.0, "close": 1936.0},
    {"time": "2026-10-02 08:00", "open": 1936.0, "high": 1937.0, "low": 1928.0, "close": 1930.0},
    {"time": "2026-10-02 12:00", "open": 1930.0, "high": 1938.0, "low": 1929.0, "close": 1937.0},
    {"time": "2026-10-02 16:00", "open": 1937.0, "high": 1944.0, "low": 1936.0, "close": 1942.0},
    {"time": "2026-10-02 20:00", "open": 1942.0, "high": 1948.0, "low": 1940.0, "close": 1946.0},
    {"time": "2026-10-03 00:00", "open": 1946.0, "high": 1950.0, "low": 1943.0, "close": 1944.0},
    {"time": "2026-10-03 04:00", "open": 1944.0, "high": 1945.0, "low": 1936.0, "close": 1938.0},
    {"time": "2026-10-03 08:00", "open": 1938.0, "high": 1946.0, "low": 1937.0, "close": 1945.0},
    {"time": "2026-10-03 12:00", "open": 1945.0, "high": 1952.0, "low": 1944.0, "close": 1950.0},
    {"time": "2026-10-03 16:00", "open": 1950.0, "high": 1955.0, "low": 1948.0, "close": 1948.0},
    {"time": "2026-10-03 20:00", "open": 1948.0, "high": 1949.0, "low": 1940.0, "close": 1942.0},
    {"time": "2026-10-04 00:00", "open": 1942.0, "high": 1950.0, "low": 1941.0, "close": 1949.0},
    {"time": "2026-10-04 04:00", "open": 1949.0, "high": 1956.0, "low": 1947.0, "close": 1954.0},
]

# ---------------------------------------------------------------------------
# Raw fixture data — 10 deterministic D1 candles
# ---------------------------------------------------------------------------

_D1_DATA: list[dict] = [
    {"time": "2026-10-01", "open": 1920.0, "high": 1936.0, "low": 1918.0, "close": 1934.0},
    {"time": "2026-10-02", "open": 1934.0, "high": 1948.0, "low": 1928.0, "close": 1946.0},
    {"time": "2026-10-03", "open": 1946.0, "high": 1955.0, "low": 1936.0, "close": 1950.0},
    {"time": "2026-10-04", "open": 1950.0, "high": 1960.0, "low": 1947.0, "close": 1958.0},
    {"time": "2026-10-05", "open": 1958.0, "high": 1962.0, "low": 1950.0, "close": 1952.0},
    {"time": "2026-10-06", "open": 1952.0, "high": 1954.0, "low": 1940.0, "close": 1942.0},
    {"time": "2026-10-07", "open": 1942.0, "high": 1956.0, "low": 1940.0, "close": 1955.0},
    {"time": "2026-10-08", "open": 1955.0, "high": 1964.0, "low": 1953.0, "close": 1962.0},
    {"time": "2026-10-09", "open": 1962.0, "high": 1968.0, "low": 1958.0, "close": 1960.0},
    {"time": "2026-10-10", "open": 1960.0, "high": 1961.0, "low": 1948.0, "close": 1950.0},
]


def load_fixture(symbol: str, timeframe: str) -> pd.DataFrame | None:
    """Return deterministic OHLC demo data for *symbol* and *timeframe*.

    Returns ``None`` when the requested combination has no fixture data.
    The returned DataFrame complies with the shared candle data contract:
    - Timezone-aware DatetimeIndex in UTC
    - Required columns: open, high, low, close
    - 'is_forming' column (False for completed historical demo candles)
    The same call always returns the same data (deterministic).
    """
    if symbol != DEMO_SYMBOL:
        return None

    raw: list[dict] | None = None
    if timeframe == "H4":
        raw = _H4_DATA
    elif timeframe == "D1":
        raw = _D1_DATA
    else:
        return None

    df = pd.DataFrame(raw)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time")
    df["is_forming"] = False
    df["is_latest_bar"] = False
    if len(df) > 0:
        df.iloc[-1, df.columns.get_loc("is_latest_bar")] = True
    df["bar_status"] = BarStatus.CONFIRMED_COMPLETED.value

    return validate_candle_data(df)


def available_symbols() -> list[str]:
    """Return the list of symbols with fixture data."""
    return [DEMO_SYMBOL]


def available_timeframes() -> list[str]:
    """Return all timeframes offered by the UI.

    Not all of these have fixture data — callers must handle the
    unsupported-demo case (see ``SUPPORTED_TIMEFRAMES``).
    """
    return ["D1", "H4", "H1", "M5", "M1"]
