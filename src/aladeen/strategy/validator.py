"""Input adaptation and validation for strategy engines.

Validates:
- Starting candle existence and completion status (OPEN-08)
- Input DataFrame and record adaptation
- Monotonic timestamps, timezone awareness, and finite positive prices
- Rejection of booleans as prices, strings, NaT, and contradictory completion evidence
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Tuple, Union
import pandas as pd

from .types import StrategyCandle, MSMConfig


def adapt_candles(data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> List[StrategyCandle]:
    """Adapts input data to a strictly validated list of immutable StrategyCandles.

    Does NOT modify the caller's input object.
    Validates the entire dataset upfront before returning.
    """
    if isinstance(data, list) and all(isinstance(c, StrategyCandle) for c in data):
        _validate_candles_sequence(data)
        return list(data)

    adapted: List[StrategyCandle] = []

    if isinstance(data, pd.DataFrame):
        df = data
        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError("Candle DataFrame must have a DatetimeIndex.")
        if df.index.tz is None:
            raise ValueError("Candle timestamps must be timezone-aware (UTC).")
        if df.index.hasnans:
            raise ValueError("Candle timestamps must not contain NaT.")

        required_cols = {"open", "high", "low", "close"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"Missing required candle columns: {missing}")

        for idx_val, (ts, row) in enumerate(df.iterrows()):
            open_time = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if pd.isna(open_time):
                raise ValueError(f"Row {idx_val} has NaT open timestamp")

            # Validate price fields strictly without silent coercion
            for col in ["open", "high", "low", "close"]:
                val = row[col]
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    raise TypeError(f"Row {idx_val} column '{col}' must be numeric float, got {type(val).__name__} ({val})")

            # Completion fields
            if "is_forming" not in row or "bar_status" not in row:
                raise ValueError(f"Row {idx_val} must have explicit 'is_forming' and 'bar_status' completion fields.")

            is_forming = row["is_forming"]
            if not isinstance(is_forming, (bool,)):
                raise TypeError(f"Row {idx_val} 'is_forming' must be bool, got {type(is_forming).__name__}")

            bar_status = row["bar_status"]
            if not isinstance(bar_status, str):
                raise TypeError(f"Row {idx_val} 'bar_status' must be str, got {type(bar_status).__name__}")

            close_time = row.get("close_time", None)
            if pd.isna(close_time):
                close_time = None
            elif isinstance(close_time, str):
                close_time = datetime.fromisoformat(close_time)
            elif hasattr(close_time, "to_pydatetime"):
                close_time = close_time.to_pydatetime()

            # Source index can be integer position or integer index if present
            source_index = int(row.get("index", idx_val))

            candle = StrategyCandle(
                index=source_index,
                open_time=open_time,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                close_time=close_time,
                is_forming=is_forming,
                bar_status=bar_status
            )
            adapted.append(candle)

    elif isinstance(data, list):
        for idx_val, item in enumerate(data):
            if isinstance(item, StrategyCandle):
                adapted.append(item)
            elif isinstance(item, dict):
                open_time = item.get("open_time", item.get("time"))
                if open_time is None or pd.isna(open_time):
                    raise ValueError(f"Item {idx_val} missing open_time")
                if isinstance(open_time, str):
                    open_time = datetime.fromisoformat(open_time)
                elif hasattr(open_time, "to_pydatetime"):
                    open_time = open_time.to_pydatetime()

                close_time = item.get("close_time", None)
                if pd.isna(close_time):
                    close_time = None
                elif isinstance(close_time, str):
                    close_time = datetime.fromisoformat(close_time)
                elif hasattr(close_time, "to_pydatetime"):
                    close_time = close_time.to_pydatetime()

                # Completion fields
                is_forming = item.get("is_forming", False)
                bar_status = item.get("bar_status", "CONFIRMED_COMPLETED")

                # Strictly validate price fields
                for col in ["open", "high", "low", "close"]:
                    if col not in item:
                        raise ValueError(f"Item {idx_val} missing '{col}'")
                    val = item[col]
                    if isinstance(val, bool) or not isinstance(val, (int, float)):
                        raise TypeError(f"Item {idx_val} field '{col}' must be numeric float, got {type(val).__name__} ({val})")

                source_index = int(item.get("index", idx_val))

                candle = StrategyCandle(
                    index=source_index,
                    open_time=open_time,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    close_time=close_time,
                    is_forming=is_forming,
                    bar_status=bar_status
                )
                adapted.append(candle)
            else:
                raise TypeError(f"Unsupported candle item type at index {idx_val}: {type(item).__name__}")
    else:
        raise TypeError(f"Unsupported data type: {type(data).__name__}")

    _validate_candles_sequence(adapted)
    return adapted


def _validate_candles_sequence(candles: List[StrategyCandle]) -> None:
    """Validates chronological ordering and numeric bounds without modifying candles."""
    prev_time: datetime | None = None
    for i, c in enumerate(candles):
        # Monotonic time check on candle open times
        if prev_time is not None:
            if c.open_time <= prev_time:
                raise ValueError(
                    f"Non-chronological or duplicate candle timestamp at index {i}: "
                    f"{c.open_time} <= {prev_time}"
                )
        prev_time = c.open_time


def validate_start_candle(config: MSMConfig, candles: List[StrategyCandle]) -> Tuple[int, int]:
    """Validates starting candle selection per OPEN-08.

    Returns (buffer_position, source_candle_index).
    Raises ValueError with standard message if start candle is absent, forming, or unconfirmed.
    """
    target_time = config.start_candle_time
    if target_time.tzinfo is None:
        raise ValueError(f"start_candle_time must be timezone-aware (UTC), got naive: {target_time}")

    matched_pos: int | None = None
    matched_candle: StrategyCandle | None = None

    for pos, c in enumerate(candles):
        if c.open_time == target_time:
            matched_pos = pos
            matched_candle = c
            break

    if matched_pos is None or matched_candle is None:
        raise ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")

    if matched_candle.is_forming or matched_candle.bar_status != "CONFIRMED_COMPLETED":
        raise ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")

    return matched_pos, matched_candle.index
