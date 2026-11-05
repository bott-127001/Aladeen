"""Type definitions, domain models, and value objects for strategy engines.

Scope & Design Boundary:
-------------------------
Independent of MT5, Dash, Plotly, network, or persistent storage.
All result structures and snapshots are strictly immutable (frozen dataclasses or namedtuples).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Set, Tuple


VALID_BAR_STATUSES: Set[str] = {"CONFIRMED_COMPLETED", "UNCONFIRMED_LATEST", "FORMING"}


def validate_and_normalize_timestamp(dt: Any, field_name: str) -> datetime:
    """Strictly validates and normalizes a timestamp to timezone-aware UTC datetime.

    Rejects:
    - None / missing
    - NaT (pd.NaT, numpy nat)
    - Naive datetimes (dt.tzinfo is None)
    - Datetimes with invalid timezone offsets (tzinfo.utcoffset is None)
    - Non-datetime types

    Normalizes:
    - Timezone-aware datetimes with valid offsets to UTC (+00:00).
    """
    if dt is None:
        raise ValueError(f"{field_name} must not be None.")

    try:
        import pandas as pd
        if pd.isna(dt):
            raise ValueError(f"{field_name} cannot be NaT or NaN.")
    except ImportError:
        pass

    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()

    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception as e:
            raise ValueError(f"{field_name} invalid ISO timestamp string: {dt}") from e

    if not isinstance(dt, datetime):
        raise TypeError(f"{field_name} must be datetime, got {type(dt).__name__}")

    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field_name} must be timezone-aware (UTC), got naive datetime: {dt}")

    return dt.astimezone(timezone.utc)


class Direction(str, Enum):
    """Initial strategy marking direction."""
    UPWARD = "UPWARD"
    DOWNWARD = "DOWNWARD"


class EngineState(str, Enum):
    """MSM core sequential state machine states."""
    SEARCHING_PULLBACK = "SEARCHING_PULLBACK"
    WAITING_FOR_BREAK = "WAITING_FOR_BREAK"


class CandleColor(str, Enum):
    """Strict candle color definitions."""
    GREEN = "GREEN"  # close > open
    RED = "RED"      # close < open
    FLAT = "FLAT"    # close == open


class TrendStatus(str, Enum):
    """Display-only diagnostic trend status values."""
    MARKING_UPWARD = "Marking upward structure"
    MARKING_DOWNWARD = "Marking downward structure"
    UPWARD_TREND = "Upward trend"
    DOWNWARD_TREND = "Downward trend"
    NOT_CONFIRMED = "Trend not confirmed"


@dataclass(frozen=True)
class StrategyCandle:
    """Immutable representation of a market candle for strategy processing."""
    index: int
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    is_forming: bool
    bar_status: str
    close_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        # Index validation: integer only, strictly reject bool and float
        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise TypeError(f"Candle index must be int, got {type(self.index).__name__}")

        # Timestamp validation and UTC normalization
        norm_open = validate_and_normalize_timestamp(self.open_time, "Candle open_time")
        object.__setattr__(self, "open_time", norm_open)

        if self.close_time is not None:
            norm_close = validate_and_normalize_timestamp(self.close_time, "Candle close_time")
            object.__setattr__(self, "close_time", norm_close)
            if self.close_time <= self.open_time:
                raise ValueError(
                    f"Candle close_time ({self.close_time}) must be strictly later than open_time ({self.open_time})"
                )

        # Numeric price validations: strictly reject bool, non-numeric, non-finite, and <= 0
        prices = {"open": self.open, "high": self.high, "low": self.low, "close": self.close}
        for name, val in prices.items():
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise TypeError(f"Candle {name} price must be finite float, got {type(val).__name__} ({val})")
            if not math.isfinite(val):
                raise ValueError(f"Candle {name} price must be finite, got {val}")
            if val <= 0:
                raise ValueError(f"Candle {name} price must be positive, got {val}")

        # OHLC geometry
        if self.high < self.low:
            raise ValueError(f"Candle high ({self.high}) cannot be less than low ({self.low})")
        if self.high < self.upper_body_edge:
            raise ValueError(f"Candle high ({self.high}) cannot be less than upper body edge ({self.upper_body_edge})")
        if self.low > self.lower_body_edge:
            raise ValueError(f"Candle low ({self.low}) cannot be greater than lower body edge ({self.lower_body_edge})")

        # Completion evidence validation
        if not isinstance(self.is_forming, bool):
            raise TypeError(f"Candle is_forming must be bool, got {type(self.is_forming).__name__}")
        if not isinstance(self.bar_status, str):
            raise TypeError(f"Candle bar_status must be str, got {type(self.bar_status).__name__}")

        if self.bar_status not in VALID_BAR_STATUSES:
            raise ValueError(
                f"Unknown bar_status '{self.bar_status}'. Must be one of {sorted(VALID_BAR_STATUSES)}"
            )

        if self.is_forming and self.bar_status == "CONFIRMED_COMPLETED":
            raise ValueError("Contradictory completion evidence: is_forming=True cannot have bar_status='CONFIRMED_COMPLETED'")
        if not self.is_forming and self.bar_status in {"UNCONFIRMED_LATEST", "FORMING"}:
            raise ValueError(f"Contradictory completion evidence: is_forming=False cannot have bar_status='{self.bar_status}'")

    @property
    def upper_body_edge(self) -> float:
        """Whichever is higher, opening price or closing price."""
        return max(self.open, self.close)

    @property
    def lower_body_edge(self) -> float:
        """Whichever is lower, opening price or closing price."""
        return min(self.open, self.close)

    @property
    def color(self) -> CandleColor:
        """Red if close < open, Green if close > open, Flat if close == open."""
        if self.close > self.open:
            return CandleColor.GREEN
        elif self.close < self.open:
            return CandleColor.RED
        return CandleColor.FLAT


@dataclass(frozen=True)
class SwingPoint:
    """An immutable swing level retaining explicit identification and confirmation provenance."""
    price: float
    candle_index: int                       # Source index of the candle containing the body edge
    candle_open_time: datetime               # Open timestamp of the candle
    identified_bar_index: int                # Source index of the bar that established the point
    identified_time: Optional[datetime] = None  # Knowledge/availability time of identification
    confirmed_bar_index: Optional[int] = None   # Source index of the break bar that confirmed it
    confirmed_time: Optional[datetime] = None   # Knowledge/availability time of confirmation

    @property
    def is_confirmed(self) -> bool:
        """Returns True if the swing point has been confirmed by a closing break."""
        return self.confirmed_bar_index is not None

    @property
    def event_bar_index(self) -> int:
        """Returns confirmation bar index if confirmed, else identification bar index."""
        return self.confirmed_bar_index if self.confirmed_bar_index is not None else self.identified_bar_index

    @property
    def event_time(self) -> Optional[datetime]:
        """Returns confirmation time if confirmed, else identification time.

        If confirmed, returns confirmed_time (remains None if confirmation time is unknown).
        """
        if self.confirmed_bar_index is not None:
            return self.confirmed_time
        return self.identified_time


@dataclass(frozen=True)
class ConfirmedPair:
    """A confirmed pair of swing levels (High and Low)."""
    pair_index: int
    high: SwingPoint
    low: SwingPoint
    confirmation_bar_index: int
    confirmation_time: Optional[datetime] = None


@dataclass(frozen=True)
class MSMConfig:
    """Configuration for a Market Structure Marking run."""
    start_candle_time: datetime
    direction: Direction
    earliest_pullback_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        norm_start = validate_and_normalize_timestamp(self.start_candle_time, "start_candle_time")
        object.__setattr__(self, "start_candle_time", norm_start)

        if isinstance(self.direction, str):
            try:
                object.__setattr__(self, "direction", Direction(self.direction))
            except ValueError:
                raise ValueError(f"Invalid direction '{self.direction}': must be Direction.UPWARD or Direction.DOWNWARD")
        elif not isinstance(self.direction, Direction):
            raise TypeError(f"direction must be Direction enum, got {type(self.direction).__name__}")

        if self.earliest_pullback_time is not None:
            norm_earliest = validate_and_normalize_timestamp(self.earliest_pullback_time, "earliest_pullback_time")
            object.__setattr__(self, "earliest_pullback_time", norm_earliest)


@dataclass(frozen=True)
class MSMSnapshot:
    """Immutable snapshot of the MSM engine state at a specific evaluation point."""
    state: EngineState
    direction: Direction
    search_start_index: int
    tentative_point: Optional[SwingPoint]
    confirmed_pairs: Tuple[ConfirmedPair, ...] = field(default_factory=tuple)
    trend_status: str = TrendStatus.MARKING_UPWARD.value
    last_processed_index: int = -1
    last_support: Optional[SwingPoint] = None
    last_resistance: Optional[SwingPoint] = None
    next_eligible_pullback_index: Optional[int] = None
    next_eligible_pullback_position: int = 0
