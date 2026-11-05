"""Domain models, enums, and immutable value objects for Internal Structure Shift (ISS).

Scope & Design Boundary:
-------------------------
- Independent of MT5, Dash, Plotly, network, and persistent storage.
- All result structures, zones, snapshots, and event records are strictly immutable (frozen dataclasses).
- Adjacency and scan boundaries are tracked via chronological candle positions (0, 1, 2, ...),
  while preserving source candle IDs.
- Strictly read-only calculation logic. Zero order execution, zero network access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .types import Direction, StrategyCandle, SwingPoint, validate_and_normalize_timestamp

if TYPE_CHECKING:
    from .coordinator import CoordinatorSnapshot


class ISSLifecycleStatus(str, Enum):
    """Lifecycle progression states for an ISS candidate."""
    PENDING_PREREQUISITES = "PENDING_PREREQUISITES"
    ELIGIBLE_SEARCH = "ELIGIBLE_SEARCH"
    CONFIRMED = "CONFIRMED"
    OUT_OF_BOUNDS_REJECTED = "OUT_OF_BOUNDS_REJECTED"
    OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY = "OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY"
    MAIN_CONTINUATION_CANCELLED = "MAIN_CONTINUATION_CANCELLED"
    MAIN_CHOCH_CANCELLED = "MAIN_CHOCH_CANCELLED"


class ISSZoneType(str, Enum):
    """Specific structural zone roles formed upon ISS confirmation."""
    RBS = "RBS"                         # Resistance-Become-Support (from internal point 3 in bearish main)
    BUYING_A_PLUS = "BUYING_A_PLUS"     # Buying A+ (from internal point 4 in bearish main)
    SBR = "SBR"                         # Support-Become-Resistance (from internal point 3 in bullish main)
    SELLING_A_PLUS = "SELLING_A_PLUS"   # Selling A+ (from internal point 4 in bullish main)


class ISSDiagnosticType(str, Enum):
    """Diagnostic categorization for ISS state transitions, rejections, and cancellations."""
    WAITING_FOR_MAIN_PREREQUISITES = "WAITING_FOR_MAIN_PREREQUISITES"
    ELIGIBLE_SEARCH_ACTIVE = "ELIGIBLE_SEARCH_ACTIVE"
    CONFIRMED_COMPLETION_INSIDE = "CONFIRMED_COMPLETION_INSIDE"
    MARKED_POINT_OUT_OF_BOUNDS = "MARKED_POINT_OUT_OF_BOUNDS"
    COMPLETION_CLOSE_OUTSIDE_RANGE = "COMPLETION_CLOSE_OUTSIDE_RANGE"
    CANCELLED_BY_MAIN_CONTINUATION = "CANCELLED_BY_MAIN_CONTINUATION"
    CANCELLED_BY_MAIN_CHOCH = "CANCELLED_BY_MAIN_CHOCH"
    PAUSED_BY_UNRESOLVED_MAIN = "PAUSED_BY_UNRESOLVED_MAIN"
    NO_REVIVAL_UNDER_SAME_MAIN_L3 = "NO_REVIVAL_UNDER_SAME_MAIN_L3"
    FRESH_SEARCH_ON_NEW_MAIN_L3 = "FRESH_SEARCH_ON_NEW_MAIN_L3"


@dataclass(frozen=True)
class FrozenBoundary:
    """Captured inclusive price range [min_price, max_price] frozen at Main Level 3 identification."""
    min_price: float
    max_price: float
    main_level_2_price: float
    main_level_3_price: float
    frozen_at_candle_index: int
    frozen_at_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not (math.isfinite(self.min_price) and math.isfinite(self.max_price)):
            raise ValueError(f"Boundary prices must be finite: [{self.min_price}, {self.max_price}]")
        if self.min_price > self.max_price:
            raise ValueError(f"min_price ({self.min_price}) cannot exceed max_price ({self.max_price})")
        if self.frozen_at_time is not None:
            norm_time = validate_and_normalize_timestamp(self.frozen_at_time, "FrozenBoundary frozen_at_time")
            object.__setattr__(self, "frozen_at_time", norm_time)

    def contains_price(self, price: float) -> bool:
        """Evaluates inclusive range boundary: min_price <= price <= max_price.

        Exact equality is valid and satisfies the boundary condition.
        No rounding or tolerance is permitted.
        """
        if not math.isfinite(price):
            return False
        return self.min_price <= price <= self.max_price


@dataclass(frozen=True)
class CandidateIdentity:
    """Immutable identity and provenance of an ISS search candidate.

    Distinguishes a new Main Level-3 identification event even if a later
    search selects the same original source candle.
    """
    candidate_id: str
    sequence_number: int
    main_direction: Direction
    main_level_2_index: int
    main_level_2_price: float
    main_level_3_index: int
    main_level_3_price: float
    main_level_3_identified_bar_index: int
    frozen_at_candle_index: int
    frozen_at_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.frozen_at_time is not None:
            norm_time = validate_and_normalize_timestamp(self.frozen_at_time, "CandidateIdentity frozen_at_time")
            object.__setattr__(self, "frozen_at_time", norm_time)


@dataclass(frozen=True)
class InternalPoint:
    """An internal marked structural swing point within an ISS candidate."""
    point_number: int                   # 1, 2, 3, 4, or 5
    role: str                           # e.g. "CH1", "CL1", "CH2", "CL2", "TENTATIVE_HIGH", "TENTATIVE_LOW"
    source_candle_index: int            # Source ID of the extreme body edge candle
    candle_open_time: datetime          # Open time of the extreme body edge candle
    body_edge_price: float              # UB or LB
    is_confirmed: bool                  # True if confirmed by break; False if tentative (e.g. Point 5)
    identified_bar_index: int           # Bar index of the pullback candle 2 identifying this level
    confirmed_bar_index: Optional[int] = None  # Bar index of the break candle confirming this level
    is_inside_boundary: bool = True     # Evaluated against candidate's frozen boundary

    def __post_init__(self) -> None:
        if self.point_number not in (1, 2, 3, 4, 5):
            raise ValueError(f"point_number must be 1..5, got {self.point_number}")
        if not math.isfinite(self.body_edge_price):
            raise ValueError(f"body_edge_price must be finite, got {self.body_edge_price}")
        norm_time = validate_and_normalize_timestamp(self.candle_open_time, "InternalPoint candle_open_time")
        object.__setattr__(self, "candle_open_time", norm_time)


@dataclass(frozen=True)
class InternalFivePointStructure:
    """Collection of up to five marked internal points formed within a candidate."""
    points: Tuple[InternalPoint, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.points) > 5:
            raise ValueError(f"Internal structure cannot exceed 5 points, got {len(self.points)}")

    @property
    def count(self) -> int:
        return len(self.points)

    @property
    def is_complete(self) -> bool:
        return len(self.points) == 5

    def get_point(self, num: int) -> Optional[InternalPoint]:
        for pt in self.points:
            if pt.point_number == num:
                return pt
        return None


@dataclass(frozen=True)
class ISSZone:
    """An immutable structural zone derived strictly from internal point 3 or point 4."""
    zone_type: ISSZoneType
    lower_price: float
    upper_price: float
    is_line: bool
    source_candle_index: int
    source_candle_open_time: datetime
    source_point_number: int            # 3 or 4
    source_point_role: str              # e.g. "CH2" or "CL2"
    confirmation_availability_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not (math.isfinite(self.lower_price) and math.isfinite(self.upper_price)):
            raise ValueError(f"Zone prices must be finite: [{self.lower_price}, {self.upper_price}]")
        if self.lower_price > self.upper_price:
            raise ValueError(
                f"Zone {self.zone_type} lower_price ({self.lower_price}) cannot exceed upper_price ({self.upper_price})"
            )
        if self.is_line and self.lower_price != self.upper_price:
            raise ValueError(
                f"Zone {self.zone_type} marked is_line=True but prices differ: {self.lower_price} != {self.upper_price}"
            )
        if not self.is_line and self.lower_price == self.upper_price:
            raise ValueError(
                f"Zone {self.zone_type} marked is_line=False but prices are identical: {self.lower_price}"
            )
        if self.source_point_number not in (3, 4):
            raise ValueError(f"Zone source_point_number must be 3 or 4, got {self.source_point_number}")

        norm_time = validate_and_normalize_timestamp(self.source_candle_open_time, "ISSZone source_candle_open_time")
        object.__setattr__(self, "source_candle_open_time", norm_time)

        if self.confirmation_availability_time is not None:
            norm_avail = validate_and_normalize_timestamp(
                self.confirmation_availability_time, "ISSZone confirmation_availability_time"
            )
            object.__setattr__(self, "confirmation_availability_time", norm_avail)

    @classmethod
    def from_candle(
        cls,
        zone_type: ISSZoneType,
        candle: StrategyCandle,
        is_high_side: bool,
        source_point_number: int,
        source_point_role: str,
        confirmation_availability_time: Optional[datetime] = None,
    ) -> ISSZone:
        """Constructs an exact zone from the original internal swing candle.

        High-Side Geometry (RBS in Bearish Main, selling A+ in Bullish Main):
            lower_price = upper_body_edge
            upper_price = high
            if high == upper_body_edge -> is_line = True (zero width)

        Low-Side Geometry (buying A+ in Bearish Main, SBR in Bullish Main):
            lower_price = low
            upper_price = lower_body_edge
            if low == lower_body_edge -> is_line = True (zero width)
        """
        if is_high_side:
            low_p = float(candle.upper_body_edge)
            high_p = float(candle.high)
        else:
            low_p = float(candle.low)
            high_p = float(candle.lower_body_edge)

        is_line = (low_p == high_p)
        return cls(
            zone_type=zone_type,
            lower_price=low_p,
            upper_price=high_p,
            is_line=is_line,
            source_candle_index=candle.index,
            source_candle_open_time=candle.open_time,
            source_point_number=source_point_number,
            source_point_role=source_point_role,
            confirmation_availability_time=confirmation_availability_time,
        )


@dataclass(frozen=True)
class ConfirmedISSEvent:
    """Immutable record of a confirmed Internal Structure Shift (ISS)."""
    candidate_id: str
    main_direction: Direction
    confirmation_candle_index: int
    confirmation_time: Optional[datetime]
    completion_close_price: float
    captured_boundary: FrozenBoundary
    internal_points: Tuple[InternalPoint, ...]
    level_3_zone: ISSZone
    level_4_zone: ISSZone

    def __post_init__(self) -> None:
        if self.confirmation_time is not None:
            norm_time = validate_and_normalize_timestamp(
                self.confirmation_time, "ConfirmedISSEvent confirmation_time"
            )
            object.__setattr__(self, "confirmation_time", norm_time)
        if len(self.internal_points) != 5:
            raise ValueError(f"Confirmed ISS must contain exactly 5 internal points, got {len(self.internal_points)}")


@dataclass(frozen=True)
class ISSSnapshot:
    """Immutable snapshot of the ISS detection engine state at a given candle."""
    lifecycle_status: ISSLifecycleStatus
    candidate_identity: Optional[CandidateIdentity] = None
    captured_boundary: Optional[FrozenBoundary] = None
    internal_points: Tuple[InternalPoint, ...] = field(default_factory=tuple)
    attempted_points: Optional[Tuple[InternalPoint, ...]] = None
    tracking_points: Tuple[InternalPoint, ...] = field(default_factory=tuple)
    active_zones: Tuple[ISSZone, ...] = field(default_factory=tuple)
    confirmed_events: Tuple[ConfirmedISSEvent, ...] = field(default_factory=tuple)
    is_tracking_only: bool = False
    last_processed_index: int = -1
    last_received_index: int = -1
    diagnostic_type: Optional[ISSDiagnosticType] = None
    diagnostic_message: Optional[str] = None
    is_unresolved: bool = False
    unresolved_dependency: Optional[str] = None


@dataclass(frozen=True)
class ISSConfig:
    """Configuration for ISS engine initialization."""
    main_direction: Direction
    start_candle_time: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.main_direction, Direction):
            raise TypeError(f"main_direction must be Direction, got {type(self.main_direction).__name__}")
        norm_time = validate_and_normalize_timestamp(self.start_candle_time, "ISSConfig start_candle_time")
        object.__setattr__(self, "start_candle_time", norm_time)


@dataclass(frozen=True)
class ISSCombinedResult:
    """Immutable combined result providing authoritative public access to main coordinator and ISS state."""
    iss_snapshot: ISSSnapshot
    main_coordinator_snapshot: CoordinatorSnapshot
    confirmed_iss_events: Tuple[ConfirmedISSEvent, ...]
