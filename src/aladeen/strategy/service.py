"""Application service layer for Market Structure Marking (MSM).

Bridges UI / data adapters and pure domain logic:
- Adapts chart DataFrames (Demo / MT5) to validated immutable StrategyCandles.
- Validates context compatibility across symbol / timeframe / data source changes.
- Derives stable integer IDs from UTC timestamps when explicit integer index is absent.
- Executes fresh batch MSM runs via MSMEngine.
- Returns immutable MSMServiceResult structures containing snapshot and diagnostic provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd

from .engine import MSMEngine
from .types import (
    Direction,
    EngineState,
    MSMConfig,
    MSMSnapshot,
    StrategyCandle,
    SwingPoint,
    ConfirmedPair,
    TrendStatus,
    validate_and_normalize_timestamp,
)
from .validator import adapt_candles, validate_start_candle


@dataclass(frozen=True)
class MSMContext:
    """Configuration context for an applied MSM calculation."""
    data_source: str
    symbol: str
    timeframe: str
    start_candle_time: datetime
    direction: Direction
    rule_version: str = "1.0"
    enabled: bool = True

    def __post_init__(self) -> None:
        norm_start = validate_and_normalize_timestamp(self.start_candle_time, "start_candle_time")
        object.__setattr__(self, "start_candle_time", norm_start)

        if isinstance(self.direction, str):
            try:
                object.__setattr__(self, "direction", Direction(self.direction))
            except ValueError:
                raise ValueError(
                    f"Invalid direction '{self.direction}': must be Direction.UPWARD or Direction.DOWNWARD"
                )
        elif not isinstance(self.direction, Direction):
            raise TypeError(f"direction must be Direction enum, got {type(self.direction).__name__}")

        if not isinstance(self.data_source, str) or not self.data_source:
            raise ValueError("data_source must be a non-empty string.")
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("symbol must be a non-empty string.")
        if not isinstance(self.timeframe, str) or not self.timeframe:
            raise ValueError("timeframe must be a non-empty string.")
        if not isinstance(self.enabled, bool):
            raise TypeError(f"enabled must be bool, got {type(self.enabled).__name__}")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize context to a JSON-compatible dictionary."""
        return {
            "data_source": self.data_source,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_candle_time": self.start_candle_time.isoformat(),
            "direction": self.direction.value,
            "rule_version": self.rule_version,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MSMContext:
        """Construct MSMContext from a dictionary."""
        if not isinstance(data, dict):
            raise TypeError(f"data must be dict, got {type(data).__name__}")
        start_time = validate_and_normalize_timestamp(
            data["start_candle_time"], "start_candle_time"
        )
        return cls(
            data_source=str(data["data_source"]),
            symbol=str(data["symbol"]),
            timeframe=str(data["timeframe"]),
            start_candle_time=start_time,
            direction=Direction(data["direction"]),
            rule_version=str(data.get("rule_version", "1.0")),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(frozen=True)
class MSMServiceResult:
    """Immutable result structure of an MSM service calculation."""
    context: MSMContext
    snapshot: Optional[MSMSnapshot]
    candles: Tuple[StrategyCandle, ...]
    status_message: str
    candle_count: int
    start_candle_found: bool
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        """True if calculation completed successfully and produced a valid snapshot."""
        return self.snapshot is not None and self.error is None


def adapt_chart_dataframe(df: pd.DataFrame) -> List[StrategyCandle]:
    """Adapts a chart OHLC DataFrame into a sequence of validated StrategyCandle objects.

    Rules & Invariants:
    -------------------
    1. df must have a UTC-aware DatetimeIndex without nulls / NaT.
    2. Required columns: open, high, low, close.
    3. Scalar handling: Supports int, float, np.integer, np.floating.
       Strictly rejects bool, np.bool_, strings, NaN, +/-inf.
    4. Stable Identity: If df contains an integer 'index' column, it is used.
       If absent, derives a stable integer ID from the UTC open timestamp
       (int(open_time.timestamp())), preserving identity across window shifts.
    5. Completion evidence: If 'is_forming' is present, reflects its value.
       Historical rows without 'is_forming' default to CONFIRMED_COMPLETED (is_forming=False).
    """
    if df is None:
        raise ValueError("DataFrame cannot be None.")
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Expected pandas DataFrame, got {type(df).__name__}")
    if df.empty:
        raise ValueError("DataFrame is empty.")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("DataFrame must have a DatetimeIndex.")
    if df.index.tz is None:
        raise ValueError("DataFrame index must be timezone-aware (UTC).")
    if df.index.hasnans:
        raise ValueError("DataFrame index contains NaT.")

    required_cols = {"open", "high", "low", "close"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required candle columns: {sorted(missing)}")

    candles: List[StrategyCandle] = []

    for row_pos, (ts, row) in enumerate(df.iterrows()):
        open_time = validate_and_normalize_timestamp(ts, f"Row {row_pos} open timestamp")

        # Validate numeric prices strictly
        for col in ["open", "high", "low", "close"]:
            val = row[col]
            if isinstance(val, (bool, np.bool_)):
                raise TypeError(f"Row {row_pos} '{col}' cannot be boolean ({val}).")
            if not isinstance(val, (int, float, np.integer, np.floating)):
                raise TypeError(f"Row {row_pos} '{col}' must be numeric, got {type(val).__name__} ({val}).")
            f_val = float(val)
            if not math.isfinite(f_val):
                raise ValueError(f"Row {row_pos} '{col}' must be finite, got {f_val}.")
            if f_val <= 0:
                raise ValueError(f"Row {row_pos} '{col}' must be positive, got {f_val}.")

        # Completion status
        if "is_forming" in row and pd.notna(row["is_forming"]):
            raw_forming = row["is_forming"]
            if isinstance(raw_forming, (bool, np.bool_)):
                is_forming = bool(raw_forming)
            else:
                raise TypeError(f"Row {row_pos} 'is_forming' must be bool, got {type(raw_forming).__name__}")
        else:
            is_forming = False

        if "bar_status" in row and pd.notna(row["bar_status"]):
            bar_status = str(row["bar_status"])
        else:
            bar_status = "FORMING" if is_forming else "CONFIRMED_COMPLETED"

        close_time: Optional[datetime] = None
        if "close_time" in row and pd.notna(row["close_time"]):
            close_time = validate_and_normalize_timestamp(row["close_time"], f"Row {row_pos} close timestamp")

        # Stable integer index derivation
        if "index" in row and pd.notna(row["index"]):
            raw_idx = row["index"]
            if isinstance(raw_idx, (bool, np.bool_)) or not isinstance(raw_idx, (int, np.integer)):
                raise TypeError(f"Row {row_pos} 'index' must be int, got {type(raw_idx).__name__} ({raw_idx})")
            candle_index = int(raw_idx)
        else:
            # Stable integer ID derived from UTC epoch seconds
            candle_index = int(open_time.timestamp())

        candle = StrategyCandle(
            index=candle_index,
            open_time=open_time,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            is_forming=is_forming,
            bar_status=bar_status,
            close_time=close_time,
        )
        candles.append(candle)

    # Monotonic order check
    for i in range(1, len(candles)):
        if candles[i].open_time <= candles[i - 1].open_time:
            raise ValueError(
                f"Candle sequence not strictly monotonically increasing: "
                f"Candle {i} ({candles[i].open_time}) <= Candle {i-1} ({candles[i-1].open_time})"
            )

    return candles


def calculate_msm(df: pd.DataFrame, context: MSMContext) -> MSMServiceResult:
    """Performs a deterministic, fresh batch MSM calculation on *df* using *context*.

    Returns an MSMServiceResult. Fails closed with descriptive error messages
    if the starting candle is missing or forming.
    """
    try:
        candles = adapt_chart_dataframe(df)
    except Exception as e:
        return MSMServiceResult(
            context=context,
            snapshot=None,
            candles=tuple(),
            status_message=f"Failed to adapt candle data: {e}",
            candle_count=0,
            start_candle_found=False,
            error=str(e),
        )

    # Locate starting candle by open timestamp
    target_time = context.start_candle_time
    start_candle: Optional[StrategyCandle] = None
    for c in candles:
        if c.open_time == target_time:
            start_candle = c
            break

    if start_candle is None:
        return MSMServiceResult(
            context=context,
            snapshot=None,
            candles=tuple(candles),
            status_message=(
                f"Selected starting candle ({target_time.strftime('%Y-%m-%d %H:%M UTC')}) "
                f"not found in loaded chart data ({len(candles)} candles). "
                f"It may have fallen outside the history window."
            ),
            candle_count=len(candles),
            start_candle_found=False,
            error=(
                f"Starting candle {target_time.strftime('%Y-%m-%d %H:%M UTC')} "
                f"not found in loaded history window."
            ),
        )

    if start_candle.is_forming:
        return MSMServiceResult(
            context=context,
            snapshot=None,
            candles=tuple(candles),
            status_message="Selected starting candle is still forming / unconfirmed.",
            candle_count=len(candles),
            start_candle_found=True,
            error="Selected starting candle is still forming / unconfirmed and cannot be used as start candle.",
        )

    try:
        config = MSMConfig(
            start_candle_time=context.start_candle_time,
            direction=context.direction,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)
        pair_count = len(snapshot.confirmed_pairs)
        status_msg = (
            f"MSM Applied: {context.direction.value} from "
            f"{context.start_candle_time.strftime('%Y-%m-%d %H:%M UTC')} | "
            f"Pairs: {pair_count} | Trend: {snapshot.trend_status}"
        )
        return MSMServiceResult(
            context=context,
            snapshot=snapshot,
            candles=tuple(candles),
            status_message=status_msg,
            candle_count=len(candles),
            start_candle_found=True,
            error=None,
        )
    except Exception as e:
        return MSMServiceResult(
            context=context,
            snapshot=None,
            candles=tuple(candles),
            status_message=f"MSM calculation error: {e}",
            candle_count=len(candles),
            start_candle_found=True,
            error=str(e),
        )


def is_context_compatible(
    saved_context: Union[MSMContext, Dict[str, Any], None],
    current_source: str,
    current_symbol: Optional[str],
    current_timeframe: str,
) -> bool:
    """Verifies whether a saved MSM configuration matches the current chart context.

    Prevents markings from one instrument / timeframe / data source being drawn
    on another.
    """
    if saved_context is None:
        return False

    if isinstance(saved_context, dict):
        try:
            ctx = MSMContext.from_dict(saved_context)
        except Exception:
            return False
    elif isinstance(saved_context, MSMContext):
        ctx = saved_context
    else:
        return False

    if not ctx.enabled:
        return False

    if ctx.data_source.lower() != current_source.lower():
        return False

    if current_symbol is None or ctx.symbol != current_symbol:
        return False

    if ctx.timeframe.upper() != current_timeframe.upper():
        return False

    return True
