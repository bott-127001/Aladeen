"""Application service layer for Market Structure Marking (MSM).

Bridges UI / data adapters and pure domain logic:
- Adapts chart DataFrames (Demo / MT5) to validated immutable StrategyCandles.
- Validates context compatibility across symbol / timeframe / data source changes.
- Derives stable integer IDs from UTC timestamps when explicit integer index is absent.
- Enforces strict explicit completion evidence (no silent defaulting).
- Executes fresh batch MSM runs via MSMEngine.
- Returns immutable MSMServiceResult structures containing snapshot and diagnostic provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Set, Tuple, Union
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
    VALID_BAR_STATUSES,
    validate_and_normalize_timestamp,
)
from .validator import adapt_candles, validate_start_candle

SUPPORTED_RULE_VERSIONS: Set[str] = {"1.0"}


def validate_candle_completion(row_pos: int, row: Any) -> Tuple[bool, str]:
    """Strictly validates candle completion evidence fields.

    Rules & Invariants (R10.1):
    ---------------------------
    - Requires explicit 'is_forming' and 'bar_status' fields.
    - Rejects missing, null, or NaN completion fields with ValueError.
    - Accepts legitimate bool or np.bool_ for is_forming; rejects strings, numbers, etc. with TypeError.
    - Validates bar_status is an exact string belonging to VALID_BAR_STATUSES without loose coercions.
    - Rejects contradictory completion evidence:
      - is_forming=True with bar_status='CONFIRMED_COMPLETED' (ValueError)
      - is_forming=False with bar_status in {'UNCONFIRMED_LATEST', 'FORMING'} (ValueError)
    """
    if "is_forming" not in row:
        raise ValueError(f"Row {row_pos} missing required completion field 'is_forming'.")

    raw_forming = row["is_forming"]
    if pd.isna(raw_forming) if hasattr(pd, "isna") else raw_forming is None:
        raise ValueError(f"Row {row_pos} 'is_forming' cannot be null/NaN.")

    if isinstance(raw_forming, (bool, np.bool_)):
        is_forming = bool(raw_forming)
    else:
        raise TypeError(
            f"Row {row_pos} 'is_forming' must be bool, got {type(raw_forming).__name__} ({raw_forming})"
        )

    if "bar_status" not in row:
        raise ValueError(f"Row {row_pos} missing required completion field 'bar_status'.")

    raw_status = row["bar_status"]
    if pd.isna(raw_status) if hasattr(pd, "isna") else raw_status is None:
        raise ValueError(f"Row {row_pos} 'bar_status' cannot be null/NaN.")

    if not isinstance(raw_status, str):
        raise TypeError(
            f"Row {row_pos} 'bar_status' must be str, got {type(raw_status).__name__} ({raw_status})"
        )

    if raw_status not in VALID_BAR_STATUSES:
        raise ValueError(
            f"Row {row_pos} unknown bar_status '{raw_status}'. Must be one of {sorted(VALID_BAR_STATUSES)}"
        )

    if is_forming and raw_status == "CONFIRMED_COMPLETED":
        raise ValueError(
            f"Row {row_pos} contradictory completion evidence: is_forming=True cannot have bar_status='CONFIRMED_COMPLETED'"
        )

    if not is_forming and raw_status in {"UNCONFIRMED_LATEST", "FORMING"}:
        raise ValueError(
            f"Row {row_pos} contradictory completion evidence: is_forming=False cannot have bar_status='{raw_status}'"
        )

    return is_forming, raw_status


def is_candle_completed(row_pos: int, row: Any) -> bool:
    """Predicate evaluating whether a candle row is verified completed.

    Fails closed with errors if completion evidence is malformed or contradictory.
    """
    is_forming, bar_status = validate_candle_completion(row_pos, row)
    return (not is_forming) and (bar_status == "CONFIRMED_COMPLETED")


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
        if not isinstance(self.data_source, str) or not self.data_source.strip():
            raise TypeError(f"data_source must be a non-empty string, got {type(self.data_source).__name__}")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise TypeError(f"symbol must be a non-empty string, got {type(self.symbol).__name__}")
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise TypeError(f"timeframe must be a non-empty string, got {type(self.timeframe).__name__}")

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

        if not isinstance(self.rule_version, str) or self.rule_version not in SUPPORTED_RULE_VERSIONS:
            raise ValueError(
                f"Unsupported rule_version '{self.rule_version}'. Supported: {sorted(SUPPORTED_RULE_VERSIONS)}"
            )

        if isinstance(self.enabled, (bool, np.bool_)):
            object.__setattr__(self, "enabled", bool(self.enabled))
        else:
            raise TypeError(f"enabled must be bool, got {type(self.enabled).__name__} ({self.enabled})")

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
        """Construct MSMContext from a dictionary with strict type validation (R10.5)."""
        if not isinstance(data, dict):
            raise TypeError(f"data must be dict, got {type(data).__name__}")

        for field_name in ["data_source", "symbol", "timeframe", "start_candle_time", "direction"]:
            if field_name not in data or data[field_name] is None:
                raise ValueError(f"Missing required context field: '{field_name}'")

        if not isinstance(data["data_source"], str):
            raise TypeError(f"data_source must be str, got {type(data['data_source']).__name__}")
        if not isinstance(data["symbol"], str):
            raise TypeError(f"symbol must be str, got {type(data['symbol']).__name__}")
        if not isinstance(data["timeframe"], str):
            raise TypeError(f"timeframe must be str, got {type(data['timeframe']).__name__}")

        raw_enabled = data.get("enabled", True)
        if not isinstance(raw_enabled, (bool, np.bool_)):
            raise TypeError(f"enabled must be bool, got {type(raw_enabled).__name__} ({raw_enabled})")

        rule_ver = data.get("rule_version", "1.0")
        if not isinstance(rule_ver, str) or rule_ver not in SUPPORTED_RULE_VERSIONS:
            raise ValueError(f"Unsupported rule_version '{rule_ver}'. Supported: {sorted(SUPPORTED_RULE_VERSIONS)}")

        raw_dir = data["direction"]
        if not isinstance(raw_dir, (str, Direction)):
            raise TypeError(f"direction must be str or Direction, got {type(raw_dir).__name__}")

        start_time = validate_and_normalize_timestamp(data["start_candle_time"], "start_candle_time")

        return cls(
            data_source=data["data_source"],
            symbol=data["symbol"],
            timeframe=data["timeframe"],
            start_candle_time=start_time,
            direction=Direction(raw_dir) if isinstance(raw_dir, str) else raw_dir,
            rule_version=rule_ver,
            enabled=bool(raw_enabled),
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

    Rules & Invariants (R10.1):
    ---------------------------
    1. df must have a UTC-aware DatetimeIndex without nulls / NaT.
    2. Required columns: open, high, low, close, is_forming, bar_status.
    3. Scalar handling: Supports int, float, np.integer, np.floating.
       Strictly rejects bool, np.bool_, strings, NaN, +/-inf.
    4. Stable Identity: If df contains an integer 'index' column, it is used.
       If absent, derives a stable integer ID from the UTC open timestamp
       (int(open_time.timestamp())), preserving identity across window shifts.
    5. Explicit Completion: Strictly validates completion fields via
       `validate_candle_completion`. Reject missing or null completion evidence.
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

    required_cols = {"open", "high", "low", "close", "is_forming", "bar_status"}
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

        # Explicit completion validation (R10.1)
        is_forming, bar_status = validate_candle_completion(row_pos, row)

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
    """Verifies whether a saved MSM configuration matches the current chart context (R10.5).

    Prevents markings from one instrument / timeframe / data source being drawn
    on another.
    """
    if saved_context is None:
        return False

    try:
        if isinstance(saved_context, dict):
            ctx = MSMContext.from_dict(saved_context)
        elif isinstance(saved_context, MSMContext):
            ctx = saved_context
        else:
            return False
    except Exception:
        return False

    if not ctx.enabled:
        return False

    if ctx.rule_version not in SUPPORTED_RULE_VERSIONS:
        return False

    if ctx.data_source.lower() != current_source.lower():
        return False

    if current_symbol is None or ctx.symbol != current_symbol:
        return False

    if ctx.timeframe.upper() != current_timeframe.upper():
        return False

    return True
