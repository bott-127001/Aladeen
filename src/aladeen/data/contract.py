"""Shared Candle Data Contract for Aladeen / TopG.

Defines the structure, validation rules, and completion semantics for OHLC
candlestick data across the application.

Contract Specification:
-----------------------
1. Representation:
   - A pandas DataFrame indexed by a timezone-aware DatetimeIndex.
   - Index name must be 'time' or represent bar open timestamps.
   - Timestamps represent the bar OPEN time.
   - All timestamps must be timezone-aware and are normalized to UTC.
   - Naive timestamps and NaT (Not-a-Time) values are strictly rejected.
   - Timestamps are NOT localized to the user's computer timezone, ensuring
     broker candle boundaries are preserved intact.

2. Chronological Ordering:
   - Index must be strictly monotonically increasing (strictly ascending in time).
   - Duplicate timestamps are strictly rejected.

3. Required Fields & Value Constraints:
   - 'open'  (numeric, finite, > 0)
   - 'high'  (numeric, finite, > 0)
   - 'low'   (numeric, finite, > 0)
   - 'close' (numeric, finite, > 0)
   - No NaN, null, string, boolean, or infinite (+/- inf) values allowed.

4. OHLC Consistency:
   - high >= low
   - high >= open
   - high >= close
   - low <= open
   - low <= close

5. Candle Completion & Bar Position Semantics:
   - In MT5 market feeds (`copy_rates_from_pos(..., 0, count)`), bar position 0
     returns the latest bar known to the terminal.
   - Historical rows (`iloc[:-1]`) are verified completed historical candles
     (`is_forming = False`, `bar_status = 'CONFIRMED_COMPLETED'`).
   - The final row (`iloc[-1]`) represents the latest/current bar known to the
     feed (`is_latest_bar = True`).
   - IMPORTANT LIMITATION: In a static snapshot or manual refresh, position 0
     cannot be independently verified as completed or incomplete. While the
     market is open, it develops with incoming ticks; when the market is closed,
     stagnant, or disconnected, it remains static.
   - The contract represents this bar as `is_forming = True` (or status
     `UNCONFIRMED_LATEST`) to denote that its completion cannot be certified.
     The software NEVER attempts to guess broker close boundaries using the
     local computer's clock.

6. Non-Invention:
   - Missing bars (e.g. weekends, holidays, market closures) are NOT filled
     with synthetic or interpolated data. The contract represents true received
     data only.
"""

from __future__ import annotations

import enum
import numpy as np
import pandas as pd


class BarStatus(str, enum.Enum):
    """Completion status of a candle bar in the shared contract."""
    CONFIRMED_COMPLETED = "CONFIRMED_COMPLETED"
    UNCONFIRMED_LATEST = "UNCONFIRMED_LATEST"


class CandleValidationError(ValueError):
    """Raised when candle data fails contract validation rules."""
    pass


REQUIRED_OHLC_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")


def validate_candle_data(
    df: pd.DataFrame,
    *,
    require_timezone: bool = True,
    require_forming_flag: bool = True,
) -> pd.DataFrame:
    """Validate that *df* complies with the Aladeen candle data contract.

    If timestamps are timezone-aware in a non-UTC timezone, they will be
    explicitly normalized to UTC.

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
        The validated DataFrame (with index normalized to UTC).

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

    # Reject NaT in timestamps
    if df.index.isna().any():
        raise CandleValidationError("Index contains NaT (Not-a-Time) timestamps.")

    if require_timezone:
        if df.index.tz is None:
            raise CandleValidationError(
                "DatetimeIndex must be timezone-aware. Naive timestamps are rejected. "
                "Timestamps must represent bar open time without local machine bias."
            )
        # Explicitly normalize timezone-aware timestamps to UTC
        if str(df.index.tz) != "UTC":
            df = df.copy()
            try:
                df.index = df.index.tz_convert("UTC")
            except Exception as e:
                raise CandleValidationError(f"Failed to normalize timestamps to UTC: {e}") from e

    # 2. Chronological ordering & uniqueness
    if not df.index.is_monotonic_increasing:
        raise CandleValidationError("Candle timestamps must be in strictly ascending chronological order.")

    if not df.index.is_unique:
        duplicates = df.index[df.index.duplicated()].unique()
        raise CandleValidationError(
            f"Duplicate candle timestamps detected: {list(duplicates[:5])}."
        )

    # 3. Required columns presence
    for col in REQUIRED_OHLC_COLUMNS:
        if col not in df.columns:
            raise CandleValidationError(f"Missing required OHLC column: '{col}'.")

    # 4. Numeric, finite, and positivity checks
    for col in REQUIRED_OHLC_COLUMNS:
        series = df[col]

        # Reject non-numeric types (e.g. object, string, boolean, complex)
        if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series) or pd.api.types.is_complex_dtype(series):
            raise CandleValidationError(
                f"Column '{col}' must be numeric, got dtype '{series.dtype}'."
            )

        # Reject complex-valued numbers in numeric or object arrays
        try:
            arr = series.to_numpy()
            if not np.isrealobj(arr):
                raise CandleValidationError(f"Column '{col}' contains complex numbers.")
        except CandleValidationError:
            raise
        except Exception:
            pass

        # Reject nulls / NaNs
        if series.isnull().any():
            nan_count = int(series.isnull().sum())
            raise CandleValidationError(f"Column '{col}' contains {nan_count} null/NaN values.")

        # Reject infinities
        try:
            if np.isinf(series).any():
                raise CandleValidationError(f"Column '{col}' contains infinite values (+/- inf).")
        except TypeError as e:
            raise CandleValidationError(f"Column '{col}' contains non-numeric values: {e}") from e

        # Check price positivity
        try:
            if (series <= 0).any():
                raise CandleValidationError(f"Column '{col}' contains non-positive values.")
        except TypeError as e:
            raise CandleValidationError(f"Column '{col}' contains non-comparable values: {e}") from e

    # 5. OHLC Consistency checks (wrapped to ensure CandleValidationError)
    try:
        high_lt_low = df["high"] < df["low"]
        if high_lt_low.any():
            invalid = df[high_lt_low]
            raise CandleValidationError(f"High price < Low price detected at: {list(invalid.index[:3])}.")

        high_lt_open = df["high"] < df["open"]
        if high_lt_open.any():
            invalid = df[high_lt_open]
            raise CandleValidationError(f"High price < Open price detected at: {list(invalid.index[:3])}.")

        high_lt_close = df["high"] < df["close"]
        if high_lt_close.any():
            invalid = df[high_lt_close]
            raise CandleValidationError(f"High price < Close price detected at: {list(invalid.index[:3])}.")

        low_gt_open = df["low"] > df["open"]
        if low_gt_open.any():
            invalid = df[low_gt_open]
            raise CandleValidationError(f"Low price > Open price detected at: {list(invalid.index[:3])}.")

        low_gt_close = df["low"] > df["close"]
        if low_gt_close.any():
            invalid = df[low_gt_close]
            raise CandleValidationError(f"Low price > Close price detected at: {list(invalid.index[:3])}.")
    except TypeError as e:
        raise CandleValidationError(f"Malformed OHLC data prevents consistency comparison: {e}") from e

    # 6. Forming flag validation
    if require_forming_flag:
        if "is_forming" not in df.columns:
            raise CandleValidationError("Missing 'is_forming' boolean column.")
        if df["is_forming"].isna().any():
            raise CandleValidationError("Column 'is_forming' contains null/NaN values.")
        if not pd.api.types.is_bool_dtype(df["is_forming"]):
            raise CandleValidationError("'is_forming' column must be boolean dtype.")
        # Any candle before the last must be completed
        if len(df) > 1 and df["is_forming"].iloc[:-1].any():
            raise CandleValidationError(
                "Historical candles prior to the latest candle cannot have is_forming=True."
            )

    # 7. Bar status validation (if present)
    if "bar_status" in df.columns:
        if df["bar_status"].isna().any():
            raise CandleValidationError("Column 'bar_status' contains null/NaN values.")
        valid_statuses = {s.value for s in BarStatus} | set(BarStatus)
        invalid_statuses = [v for v in df["bar_status"] if v not in valid_statuses]
        if invalid_statuses:
            raise CandleValidationError(
                f"Unknown bar_status value(s) detected: {invalid_statuses[:5]}."
            )
        # Preceding candles must be confirmed completed
        if len(df) > 1:
            historical_statuses = df["bar_status"].iloc[:-1]
            non_completed = [
                s for s in historical_statuses
                if s != BarStatus.CONFIRMED_COMPLETED.value and s != BarStatus.CONFIRMED_COMPLETED
            ]
            if non_completed:
                raise CandleValidationError(
                    "Historical candles prior to the latest candle must have bar_status='CONFIRMED_COMPLETED'."
                )

        # Contradictory combinations if is_forming is also present
        if "is_forming" in df.columns:
            for idx, row in df.iterrows():
                is_forming = bool(row["is_forming"])
                status_val = (
                    row["bar_status"].value
                    if isinstance(row["bar_status"], BarStatus)
                    else str(row["bar_status"])
                )
                if is_forming and status_val == BarStatus.CONFIRMED_COMPLETED.value:
                    raise CandleValidationError(
                        f"Contradictory candle status at {idx}: is_forming=True but bar_status=CONFIRMED_COMPLETED."
                    )
                if not is_forming and status_val == BarStatus.UNCONFIRMED_LATEST.value:
                    raise CandleValidationError(
                        f"Contradictory candle status at {idx}: is_forming=False but bar_status=UNCONFIRMED_LATEST."
                    )

    # 8. Latest bar flag validation (if present)
    if "is_latest_bar" in df.columns:
        if df["is_latest_bar"].isna().any():
            raise CandleValidationError("Column 'is_latest_bar' contains null/NaN values.")
        if not pd.api.types.is_bool_dtype(df["is_latest_bar"]):
            raise CandleValidationError("'is_latest_bar' column must be boolean dtype.")
        if len(df) > 1 and df["is_latest_bar"].iloc[:-1].any():
            raise CandleValidationError(
                "Historical candles prior to the latest candle cannot have is_latest_bar=True."
            )
        if len(df) > 0 and not bool(df["is_latest_bar"].iloc[-1]):
            raise CandleValidationError(
                "The final candle must have is_latest_bar=True."
            )

    return df
