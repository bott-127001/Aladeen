"""Input adaptation and validation for strategy engines.

Validates:
- Starting candle existence and completion status (OPEN-08)
- Input DataFrame and record adaptation
- Monotonic timestamps and finite positive prices
- Duplicate and out-of-order sequential candle handling
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import List, Union
import pandas as pd

from .types import StrategyCandle, MSMConfig


def adapt_candles(data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]) -> List[StrategyCandle]:
    """Adapts input data to a strictly validated list of immutable StrategyCandles.

    Does NOT modify the input object.
    """
    if isinstance(data, list) and all(isinstance(c, StrategyCandle) for c in data):
        # Validate chronology
        _validate_candles_sequence(data)
        return list(data)

    adapted: List[StrategyCandle] = []

    if isinstance(data, pd.DataFrame):
        df = data.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError("Candle DataFrame must have a DatetimeIndex.")
        if df.index.tz is None:
            raise ValueError("Candle timestamps must be timezone-aware (UTC).")

        for idx, (ts, row) in enumerate(df.iterrows()):
            open_val = float(row["open"])
            high_val = float(row["high"])
            low_val = float(row["low"])
            close_val = float(row["close"])
            is_forming = bool(row.get("is_forming", False))
            bar_status = str(row.get("bar_status", "CONFIRMED_COMPLETED"))
            close_time = row.get("close_time", None)
            if pd.isna(close_time):
                close_time = None
            elif isinstance(close_time, str):
                close_time = datetime.fromisoformat(close_time)

            candle = StrategyCandle(
                index=idx,
                open_time=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                open=open_val,
                high=high_val,
                low=low_val,
                close=close_val,
                close_time=close_time,
                is_forming=is_forming,
                bar_status=bar_status
            )
            adapted.append(candle)

    elif isinstance(data, list):
        for idx, item in enumerate(data):
            if isinstance(item, StrategyCandle):
                adapted.append(item)
            elif isinstance(item, dict):
                open_time = item["open_time"] if "open_time" in item else item.get("time")
                if isinstance(open_time, str):
                    open_time = datetime.fromisoformat(open_time)
                close_time = item.get("close_time")
                if isinstance(close_time, str):
                    close_time = datetime.fromisoformat(close_time)

                candle = StrategyCandle(
                    index=item.get("index", idx),
                    open_time=open_time,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    close_time=close_time,
                    is_forming=bool(item.get("is_forming", False)),
                    bar_status=str(item.get("bar_status", "CONFIRMED_COMPLETED"))
                )
                adapted.append(candle)
            else:
                raise TypeError(f"Unsupported candle item type: {type(item)}")
    else:
        raise TypeError(f"Unsupported data type: {type(data)}")

    _validate_candles_sequence(adapted)
    return adapted


def _validate_candles_sequence(candles: List[StrategyCandle]) -> None:
    """Validates chronological ordering and numeric bounds without modifying candles."""
    prev_time: datetime | None = None
    for i, c in enumerate(candles):
        # Finite & positive
        for val, name in [(c.open, "open"), (c.high, "high"), (c.low, "low"), (c.close, "close")]:
            if not math.isfinite(val):
                raise ValueError(f"Candle {i} has non-finite price {name}={val}")
            if val <= 0:
                raise ValueError(f"Candle {i} has non-positive price {name}={val}")

        if c.high < c.low:
            raise ValueError(f"Candle {i} has high ({c.high}) < low ({c.low})")
        if c.high < c.upper_body_edge:
            raise ValueError(f"Candle {i} has high ({c.high}) < upper body ({c.upper_body_edge})")
        if c.low > c.lower_body_edge:
            raise ValueError(f"Candle {i} has low ({c.low}) > lower body ({c.lower_body_edge})")

        # Monotonic time check
        if prev_time is not None:
            if c.open_time <= prev_time:
                raise ValueError(
                    f"Non-chronological or duplicate candle timestamp at index {i}: "
                    f"{c.open_time} <= {prev_time}"
                )
        prev_time = c.open_time


def validate_start_candle(config: MSMConfig, candles: List[StrategyCandle]) -> int:
    """Validates starting candle selection per OPEN-08.

    Returns the candle index of the starting candle.
    Raises ValueError with standard message if start candle is absent, forming, or unconfirmed.
    """
    target_time = config.start_candle_time
    if isinstance(target_time, str):
        target_time = datetime.fromisoformat(target_time)

    # Normalize tz
    if target_time.tzinfo is None:
        target_time = target_time.replace(tzinfo=timezone.utc)

    matched_idx: int | None = None
    matched_candle: StrategyCandle | None = None

    for i, c in enumerate(candles):
        c_time = c.open_time
        if c_time.tzinfo is None:
            c_time = c_time.replace(tzinfo=timezone.utc)
        if c_time == target_time:
            matched_idx = i
            matched_candle = c
            break

    if matched_idx is None or matched_candle is None:
        raise ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")

    if matched_candle.is_forming or matched_candle.bar_status != "CONFIRMED_COMPLETED":
        raise ValueError("Invalid starting candle: start candle must be a verified completed historical candle.")

    return matched_idx
