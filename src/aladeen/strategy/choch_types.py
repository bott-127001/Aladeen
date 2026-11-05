"""Domain models, enums, and immutable value objects for Change of Character (CHOCH).

Scope & Design Boundary:
-------------------------
- Independent of MT5, Dash, Plotly, network, and persistent storage.
- All result structures, zones, snapshots, and event records are strictly immutable (frozen dataclasses).
- Adjacency is tracked via chronological candle positions (0, 1, 2, ...), NOT arithmetic on source candle IDs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .types import Direction, StrategyCandle, SwingPoint, validate_and_normalize_timestamp


class ChochType(str, Enum):
    """Directional classification of a confirmed Change of Character."""
    BEARISH_CHOCH = "BEARISH_CHOCH"
    BULLISH_CHOCH = "BULLISH_CHOCH"


class ChochZoneType(str, Enum):
    """Specific structural zone roles formed upon CHOCH confirmation."""
    SBR = "SBR"                       # Support-Become-Resistance (from broken support)
    RBS = "RBS"                       # Resistance-Become-Support (from broken resistance)
    QML_A_PLUS = "QML_A_PLUS"         # Quasimodo Level / A+ (from preceding major swing extreme)
    DOUBLE_TOP = "DOUBLE_TOP"         # Double Top (from Point 3 peak in upward trend)
    DOUBLE_BOTTOM = "DOUBLE_BOTTOM"   # Double Bottom (from Point 3 trough in downward trend)


class ChochDiagnosticType(str, Enum):
    """Diagnostic categorization for rejection, timing, and unresolved conditions."""
    UNRESOLVED_SAME_CLOSE = "UNRESOLVED_SAME_CLOSE"
    ACTIVE_POINT_3_ABSENT = "ACTIVE_POINT_3_ABSENT"
    CLOSES_BEFORE_POINT_3_IDENTIFICATION = "CLOSES_BEFORE_POINT_3_IDENTIFICATION"
    EQUALITY_REJECTED = "EQUALITY_REJECTED"
    WICK_CROSSING_ONLY_REJECTED = "WICK_CROSSING_ONLY_REJECTED"
    NON_CONSECUTIVE_REJECTED = "NON_CONSECUTIVE_REJECTED"
    SECOND_CLOSE_FAILED = "SECOND_CLOSE_FAILED"
    CONTINUATION_RESET = "CONTINUATION_RESET"
    PREREQUISITE_CHANGED = "PREREQUISITE_CHANGED"
    FORMING_CANDLE_REJECTED = "FORMING_CANDLE_REJECTED"
    OUT_OF_ORDER_OR_DUPLICATE = "OUT_OF_ORDER_OR_DUPLICATE"
    BLOCKED_BY_UNRESOLVED_STATE = "BLOCKED_BY_UNRESOLVED_STATE"
    REQUIRED_ZONE_PROVENANCE_MISSING = "REQUIRED_ZONE_PROVENANCE_MISSING"


@dataclass(frozen=True)
class ChochZone:
    """An immutable structural zone derived from an original swing candle upon CHOCH confirmation."""
    zone_type: ChochZoneType
    lower_price: float
    upper_price: float
    is_line: bool
    source_candle_index: int
    source_candle_open_time: datetime

    def __post_init__(self) -> None:
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
        norm_time = validate_and_normalize_timestamp(self.source_candle_open_time, "source_candle_open_time")
        object.__setattr__(self, "source_candle_open_time", norm_time)

    @classmethod
    def from_candle(
        cls,
        zone_type: ChochZoneType,
        candle: StrategyCandle,
        is_high_side: bool
    ) -> ChochZone:
        """Constructs an exact zone from an original swing candle using high-side or low-side geometry.

        High-Side Geometry:
            lower_price = upper_body_edge
            upper_price = high
            if high == upper_body_edge -> is_line = True (thickness 0)

        Low-Side Geometry:
            lower_price = low
            upper_price = lower_body_edge
            if low == lower_body_edge -> is_line = True (thickness 0)
        """
        if is_high_side:
            low_p = candle.upper_body_edge
            high_p = candle.high
        else:
            low_p = candle.low
            high_p = candle.lower_body_edge

        is_line = (low_p == high_p)
        return cls(
            zone_type=zone_type,
            lower_price=low_p,
            upper_price=high_p,
            is_line=is_line,
            source_candle_index=candle.index,
            source_candle_open_time=candle.open_time,
        )


@dataclass(frozen=True)
class ChochCandidate:
    """Pending evidence of an in-progress CHOCH break sequence."""
    direction: Direction
    broken_level_price: float
    broken_level_source_index: int
    point_3_source_index: int
    point_3_identified_bar_index: int
    point_3_identified_at: Optional[datetime]
    c1_candle_index: int
    c1_chronological_pos: int
    c1_open_time: datetime
    c1_close: float
    close_count: int = 1

    def __post_init__(self) -> None:
        if self.point_3_identified_at is not None:
            norm_p3 = validate_and_normalize_timestamp(self.point_3_identified_at, "point_3_identified_at")
            object.__setattr__(self, "point_3_identified_at", norm_p3)
        norm_c1 = validate_and_normalize_timestamp(self.c1_open_time, "c1_open_time")
        object.__setattr__(self, "c1_open_time", norm_c1)


@dataclass(frozen=True)
class ConfirmedChoch:
    """Immutable event record representing a confirmed Change of Character."""
    choch_type: ChochType
    broken_level_type: str                   # "LAST_SUPPORT" or "LAST_RESISTANCE"
    broken_level_price: float
    broken_level_source_index: int
    c1_candle_index: int
    c2_candle_index: int
    c1_chronological_pos: int
    c2_chronological_pos: int
    c1_open_time: datetime
    c2_open_time: datetime
    confirmation_time: Optional[datetime]    # Knowledge/availability time (c2.close_time)
    point_3_source_index: int
    point_3_open_time: datetime
    point_3_identified_bar_index: int
    point_3_identified_at: Optional[datetime]
    zones: Tuple[ChochZone, ...]
    new_direction: Direction
    restart_reference_candle_index: int
    restart_reference_open_time: datetime
    first_eligible_pullback_pos: int         # c2_chronological_pos + 1
    event_id: str = ""

    def __post_init__(self) -> None:
        if self.c2_chronological_pos != self.c1_chronological_pos + 1:
            raise ValueError(
                f"CHOCH qualifying closes must be strictly consecutive in chronological positions: "
                f"c1_pos={self.c1_chronological_pos}, c2_pos={self.c2_chronological_pos}"
            )
        if len(self.zones) != 3:
            raise ValueError(
                f"ConfirmedChoch must contain exactly 3 zones (SBR/RBS, QML/A+, Double Top/Bottom), got {len(self.zones)}"
            )
        norm_c1 = validate_and_normalize_timestamp(self.c1_open_time, "c1_open_time")
        object.__setattr__(self, "c1_open_time", norm_c1)
        norm_c2 = validate_and_normalize_timestamp(self.c2_open_time, "c2_open_time")
        object.__setattr__(self, "c2_open_time", norm_c2)
        if self.confirmation_time is not None:
            norm_conf = validate_and_normalize_timestamp(self.confirmation_time, "confirmation_time")
            object.__setattr__(self, "confirmation_time", norm_conf)
        norm_p3_open = validate_and_normalize_timestamp(self.point_3_open_time, "point_3_open_time")
        object.__setattr__(self, "point_3_open_time", norm_p3_open)
        if self.point_3_identified_at is not None:
            norm_p3_id = validate_and_normalize_timestamp(self.point_3_identified_at, "point_3_identified_at")
            object.__setattr__(self, "point_3_identified_at", norm_p3_id)
        norm_restart = validate_and_normalize_timestamp(self.restart_reference_open_time, "restart_reference_open_time")
        object.__setattr__(self, "restart_reference_open_time", norm_restart)
        if not self.event_id:
            eid = f"CHOCH-{self.choch_type.value}-{self.c1_candle_index}-{self.c2_candle_index}"
            object.__setattr__(self, "event_id", eid)


@dataclass(frozen=True)
class ChochDiagnostic:
    """An immutable diagnostic entry recording rejected or unresolved evaluation conditions."""
    diagnostic_type: ChochDiagnosticType
    candle_index: int
    chronological_pos: int
    candle_open_time: datetime
    message: str
    is_unresolved: bool = False

    def __post_init__(self) -> None:
        norm_time = validate_and_normalize_timestamp(self.candle_open_time, "candle_open_time")
        object.__setattr__(self, "candle_open_time", norm_time)


@dataclass(frozen=True)
class ChochSnapshot:
    """Immutable snapshot of the CHOCH detector state."""
    active_direction: Direction
    last_processed_pos: int
    last_processed_index: int
    candidate: Optional[ChochCandidate]
    confirmed_choch: Optional[ConfirmedChoch]
    diagnostics: Tuple[ChochDiagnostic, ...] = field(default_factory=tuple)
    is_unresolved: bool = False
