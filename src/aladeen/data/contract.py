"""Shared Candle Data Contract for Aladeen / TopG.

Defines the structure and validation rules for OHLC candlestick data used
across the application.

Contract Specification:
-----------------------
1. Representation:
   - A pandas DataFrame indexed by a timezone-aware DatetimeIndex.
   - Index name should be 'time'.
   - The timestamp represents the bar OPEN time in UTC.
   - Timestamps are NOT localized to the user's computer timezone, ensuring
     broker candle boundaries are preserved intact.

2. Chronological Ordering:
   - Index must be strictly monotonically increasing (no duplicate timestamps,
     strictly ascending in time).

3. Required Fields:
   - 'open' (float): opening price (> 0)
   - 'high' (float): highest price (> 0)
   - 'low'  (float): lowest price (> 0)
   - 'close' (float): closing price (> 0)
   - No NaN or null values are allowed in required fields.

4. OHLC Consistency:
   - high >= low
   - high >= open
   - high >= close
   - low <= open
   - low <= close

5. Forming vs Completed Candles:
   - 'is_forming' (bool): True for the currently forming/open candle (typically
     the latest candle in live MT5 feeds); False for completed candles.
   - Historical completed candles must have is_forming = False.
   - At most the final candle may have is_forming = True.

6. Non-Invention:
   - Missing bars (e.g. weekends, holidays, market closures) are NOT filled
     with synthetic or interpolated data. The contract represents true received
     data only.
"""

from __future__ import annotations

import pandas as pd


class CandleValidationError(ValueError):
    """Raised when candle data fails the contract validation rules."""
    pass


REQUIRED_OHLC_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")


def validate_candle_data(
    df: pd.DataFrame,
    *,
    require_timezone: bool = True,
    require_forming_flag: bool = True,
) -> pd.DataFrame:
    """Validate that *df* complies with the Aladeen candle data contract.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to validate.
    require_timezone : bool, default True
        Whether to require a timezone-aware DatetimeIndex.
    require_forming_flag : bool, default True
        Whether to require the boolean 'is_forming' column.

    Returns
    -------
    pd.DataFrame
        The validated DataFrame.

    Raises
    ------
    CandleValidationError
        If any contract requirement is violated.
    """
    if df is None:
        raise CandleValidationError("Candle data cannot be None.")

    if not isinstance(df, pd.DataFrame):
        raise CandleValidationError(f"Expected pandas DataFrame, got {type(df).__name__}.")

    if df.empty:
        raise CandleValidationError("Candle data DataFrame is empty.")

    # 1. Index validation
    if not isinstance(df.index, pd.DatetimeIndex):
        raise CandleValidationError(
            f"DataFrame index must be a DatetimeIndex, got {type(df.index).__name__}."
        )

    if require_timezone and df.index.tz is None:
        raise CandleValidationError(
            "DatetimeIndex must be timezone-aware (UTC). "
            "Timestamps represent bar open time in UTC without local machine bias."
        )

    # 2. Chronological ordering & uniqueness
    if not df.index.is_monotonic_increasing:
        raise CandleValidationError("Candle timestamps must be in strictly ascending chronological order.")

    if not df.index.is_unique:
        duplicates = df.index[df.index.duplicated()].unique()
        raise CandleValidationError(
            f"Duplicate candle timestamps detected: {list(duplicates[:5])}."
        )

    # 3. Required columns
    for col in REQUIRED_OHLC_COLUMNS:
        if col not in df.columns:
            raise CandleValidationError(f"Missing required OHLC column: '{col}'.")

    # 4. Null / NaN checks
    for col in REQUIRED_OHLC_COLUMNS:
        if df[col].isnull().any():
            nan_count = df[col].isnull().sum()
            raise CandleValidationError(f"Column '{col}' contains {nan_count} null/NaN values.")

    # 5. Price positivity
    for col in REQUIRED_OHLC_COLUMNS:
        if (df[col] <= 0).any():
            raise CandleValidationError(f"Column '{col}' contains non-positive values.")

    # 6. OHLC Consistency
    if not (df["high"] >= df["low"]).all():
        invalid = df[df["high"] < df["low"]]
        raise CandleValidationError(f"High price < Low price detected at: {list(invalid.index[:3])}.")

    if not (df["high"] >= df["open"]).all():
        invalid = df[df["high"] < df["open"]]
        raise CandleValidationError(f"High price < Open price detected at: {list(invalid.index[:3])}.")

    if not (df["high"] >= df["close"]).all():
        invalid = df[df["high"] < df["close"]]
        raise CandleValidationError(f"High price < Close price detected at: {list(invalid.index[:3])}.")

    if not (df["low"] <= df["open"]).all():
        invalid = df[df["low"] > df["open"]]
        raise CandleValidationError(f"Low price > Open price detected at: {list(invalid.index[:3])}.")

    if not (df["low"] <= df["close"]).all():
        invalid = df[df["low"] > df["close"]]
        raise CandleValidationError(f"Low price > Close price detected at: {list(invalid.index[:3])}.")

    # 7. Forming flag
    if require_forming_flag:
        if "is_forming" not in df.columns:
            raise CandleValidationError("Missing 'is_forming' boolean column.")
        if not pd.api.types.is_bool_dtype(df["is_forming"]):
            raise CandleValidationError("'is_forming' column must be boolean dtype.")
        # Any candle before the last must be completed
        if len(df) > 1 and df["is_forming"].iloc[:-1].any():
            raise CandleValidationError(
                "Historical candles prior to the latest candle cannot have is_forming=True."
            )

    return df
