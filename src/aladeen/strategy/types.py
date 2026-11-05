"""Type definitions, domain models, and value objects for strategy engines.

Scope & Design Boundary:
-------------------------
Independent of MT5, Dash, Plotly, network, or persistent storage.
All result structures and snapshots are strictly immutable (frozen dataclasses or namedtuples).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple


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
    close_time: Optional[datetime] = None
    is_forming: bool = False
    bar_status: str = "CONFIRMED_COMPLETED"

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
    """An immutable swing level (tentative or confirmed)."""
    price: float
    candle_index: int
    candle_open_time: datetime
    event_bar_index: int
    event_time: Optional[datetime] = None


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
    next_eligible_pullback_index: int = 0
