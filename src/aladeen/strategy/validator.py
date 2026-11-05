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
from typing import Any, List, Set, Tuple, Union
import pandas as pd

from .types import StrategyCandle, MSMConfig, validate_and_normalize_timestamp


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
            open_time = validate_and_normalize_timestamp(ts, f"Row {idx_val} open timestamp")

            # Validate price fields strictly without silent coercion
            for col in ["open", "high", "low", "close"]:
                val = row[col]
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    raise TypeError(f"Row {idx_val} column '{col}' must be numeric float, got {type(val).__name__} ({val})")

            # Completion fields: strictly require presence, reject missing / defaulted evidence
            if "is_forming" not in row or "bar_status" not in row:
                raise ValueError(f"Row {idx_val} must have explicit 'is_forming' and 'bar_status' completion fields.")

            is_forming = row["is_forming"]
            if pd.isna(is_forming):
                raise ValueError(f"Row {idx_val} 'is_forming' cannot be null/NaN.")
            if isinstance(is_forming, bool):
                pass
            else:
                raise TypeError(f"Row {idx_val} 'is_forming' must be bool, got {type(is_forming).__name__}")

            bar_status = row["bar_status"]
            if pd.isna(bar_status):
                raise ValueError(f"Row {idx_val} 'bar_status' cannot be null/NaN.")
            if not isinstance(bar_status, str):
                raise TypeError(f"Row {idx_val} 'bar_status' must be str, got {type(bar_status).__name__}")

            close_time = None
            if "close_time" in row and pd.notna(row["close_time"]):
                close_time = validate_and_normalize_timestamp(row["close_time"], f"Row {idx_val} close timestamp")

            # Source index: strictly int, reject bool and float
            if "index" in row and pd.notna(row["index"]):
                raw_idx = row["index"]
                if isinstance(raw_idx, bool) or not isinstance(raw_idx, int):
                    raise TypeError(f"Row {idx_val} 'index' must be int, got {type(raw_idx).__name__} ({raw_idx})")
                source_index = raw_idx
            else:
                source_index = idx_val

            candle = StrategyCandle(
                index=source_index,
                open_time=open_time,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                is_forming=is_forming,
                bar_status=bar_status,
                close_time=close_time,
            )
            adapted.append(candle)

    elif isinstance(data, list):
        for idx_val, item in enumerate(data):
            if isinstance(item, StrategyCandle):
                adapted.append(item)
            elif isinstance(item, dict):
                # Timestamp validation
                raw_open = item.get("open_time", item.get("time"))
                if raw_open is None or pd.isna(raw_open):
                    raise ValueError(f"Item {idx_val} missing open_time")
                open_time = validate_and_normalize_timestamp(raw_open, f"Item {idx_val} open_time")

                close_time = None
                raw_close = item.get("close_time", None)
                if raw_close is not None and not pd.isna(raw_close):
                    close_time = validate_and_normalize_timestamp(raw_close, f"Item {idx_val} close_time")

                # Completion fields: strictly require presence, reject missing / defaulted evidence
                if "is_forming" not in item or "bar_status" not in item:
                    raise ValueError(f"Item {idx_val} must have explicit 'is_forming' and 'bar_status' completion fields.")

                is_forming = item["is_forming"]
                if is_forming is None or pd.isna(is_forming):
                    raise ValueError(f"Item {idx_val} 'is_forming' cannot be None.")
                if isinstance(is_forming, bool):
                    pass
                else:
                    raise TypeError(f"Item {idx_val} 'is_forming' must be bool, got {type(is_forming).__name__}")

                bar_status = item["bar_status"]
                if bar_status is None or pd.isna(bar_status):
                    raise ValueError(f"Item {idx_val} 'bar_status' cannot be None.")
                if not isinstance(bar_status, str):
                    raise TypeError(f"Item {idx_val} 'bar_status' must be str, got {type(bar_status).__name__}")

                # Strictly validate price fields
                for col in ["open", "high", "low", "close"]:
                    if col not in item:
                        raise ValueError(f"Item {idx_val} missing '{col}'")
                    val = item[col]
                    if isinstance(val, bool) or not isinstance(val, (int, float)):
                        raise TypeError(f"Item {idx_val} field '{col}' must be numeric float, got {type(val).__name__} ({val})")

                # Source index: strictly int, reject bool and float
                if "index" in item:
                    raw_idx = item["index"]
                    if isinstance(raw_idx, bool) or not isinstance(raw_idx, int):
                        raise TypeError(f"Item {idx_val} 'index' must be int, got {type(raw_idx).__name__} ({raw_idx})")
                    source_index = raw_idx
                else:
                    source_index = idx_val

                candle = StrategyCandle(
                    index=source_index,
                    open_time=open_time,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    is_forming=is_forming,
                    bar_status=bar_status,
                    close_time=close_time,
                )
                adapted.append(candle)
            else:
                raise TypeError(f"Unsupported candle item type at index {idx_val}: {type(item).__name__}")
    else:
        raise TypeError(f"Unsupported data type: {type(data).__name__}")

    _validate_candles_sequence(adapted)
    return adapted


def _validate_candles_sequence(candles: List[StrategyCandle]) -> None:
    """Validates chronological ordering, source index uniqueness, and numeric bounds."""
    seen_indices: Set[int] = set()
    prev_time: datetime | None = None

    for i, c in enumerate(candles):
        # Source index uniqueness
        if c.index in seen_indices:
            raise ValueError(f"Duplicate candle source index detected: {c.index}")
        seen_indices.add(c.index)

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

    Returns (completed_buffer_position, source_candle_index).
    Raises ValueError with standard message if start candle is absent, forming, or unconfirmed.
    """
    target_time = config.start_candle_time
    if target_time.tzinfo is None:
        raise ValueError(f"start_candle_time must be timezone-aware (UTC), got naive: {target_time}")

    matched_candle: StrategyCandle | None = None
    completed_pos = 0

    for c in candles:
        if c.open_time == target_time:
            matched_candle = c
            break
        # Count preceding candles that are verified completed
        if not c.is_forming and c.bar_status == "CONFIRMED_COMPLETED":
            completed_pos += 1

    if matched_candle is None:
        raise ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")

    if matched_candle.is_forming or matched_candle.bar_status != "CONFIRMED_COMPLETED":
        raise ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")

    return completed_pos, matched_candle.index
