"""Domain models, enums, and immutable value objects for Trend Joining Level (TJL).

Scope & Design Boundary:
-------------------------
- Independent of MT5, Dash, Plotly, network, and persistent storage.
- All result structures, zones, snapshots, sets, and event records are strictly immutable (frozen dataclasses).
- Level identity is stable and engineering-defined:
    (symbol_feed_id, source_timeframe, source_open_time, HIGH|LOW)
  Strictly independent of role name, set ID, calendar week, or activation ID.
- Adjacency is tracked via chronological candle positions, NOT arithmetic on source candle IDs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .types import Direction, StrategyCandle, SwingPoint, validate_and_normalize_timestamp


class TJLLabel(str, Enum):
    """Directional role designation for Trend Joining Levels."""
    TJL1 = "TJL1"
    TJL2_A_PLUS = "TJL2_A_PLUS"


class TJLSide(str, Enum):
    """Structural side of the originating swing candle."""
    HIGH = "HIGH"
    LOW = "LOW"


class TJLTransitionType(str, Enum):
    """Lifecycle transition classifications for TJL state machine."""
    LABELS_ONLY = "LABELS_ONLY"
    FIRST_CREATION = "FIRST_CREATION"
    CONTINUATION_RETAINED = "CONTINUATION_RETAINED"
    SET_REPLACEMENT = "SET_REPLACEMENT"
    IDEMPOTENT_NO_OP = "IDEMPOTENT_NO_OP"
    CHOCH_INVALIDATION = "CHOCH_INVALIDATION"
    BLOCKED_UNRESOLVED = "BLOCKED_UNRESOLVED"


@dataclass(frozen=True)
class StableLevelId:
    """Immutable, unique engineering identifier for a physical price level.

    Formula: (symbol_feed_id, source_timeframe, source_open_time, HIGH|LOW)
    Invariance:
    - Independent of strategy role (TJL1 vs TJL2).
    - Independent of current-set identity (Set 1 vs Set 2).
    - Independent of week / calendar resets (retained across Monday 00:00).
    - Independent of future activation state or execution ledger.
    """
    symbol_feed_id: str
    source_timeframe: str
    source_open_time: datetime
    side: TJLSide

    def __post_init__(self) -> None:
        if not isinstance(self.symbol_feed_id, str) or not self.symbol_feed_id.strip():
            raise ValueError(f"symbol_feed_id must be a non-empty string, got {self.symbol_feed_id!r}")
        if not isinstance(self.source_timeframe, str) or not self.source_timeframe.strip():
            raise ValueError(f"source_timeframe must be a non-empty string, got {self.source_timeframe!r}")

        norm_time = validate_and_normalize_timestamp(self.source_open_time, "source_open_time")
        object.__setattr__(self, "source_open_time", norm_time)

        if isinstance(self.side, str):
            try:
                object.__setattr__(self, "side", TJLSide(self.side.upper()))
            except ValueError:
                raise ValueError(f"Invalid side '{self.side}': must be 'HIGH' or 'LOW'")
        elif not isinstance(self.side, TJLSide):
            raise TypeError(f"side must be TJLSide enum, got {type(self.side).__name__}")

    def to_tuple(self) -> Tuple[str, str, str, str]:
        """Returns standard 4-element string tuple representation."""
        return (
            self.symbol_feed_id,
            self.source_timeframe,
            self.source_open_time.isoformat(),
            self.side.value,
        )

    def to_list(self) -> List[str]:
        """Returns standard 4-element list representation."""
        return list(self.to_tuple())

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, StableLevelId):
            return (
                self.symbol_feed_id == other.symbol_feed_id
                and self.source_timeframe == other.source_timeframe
                and self.source_open_time == other.source_open_time
                and self.side == other.side
            )
        if isinstance(other, (list, tuple)) and len(other) == 4:
            feed_id, tf, dt_raw, side_raw = other
            if self.symbol_feed_id != feed_id or self.source_timeframe != tf:
                return False
            try:
                other_dt = validate_and_normalize_timestamp(dt_raw, "comparison timestamp")
                if self.source_open_time != other_dt:
                    return False
            except Exception:
                return False
            other_side = side_raw.value if isinstance(side_raw, TJLSide) else str(side_raw).upper()
            return self.side.value == other_side
        return False

    def __hash__(self) -> int:
        return hash((self.symbol_feed_id, self.source_timeframe, self.source_open_time, self.side))

    def __repr__(self) -> str:
        return (
            f"StableLevelId(symbol_feed_id={self.symbol_feed_id!r}, "
            f"source_timeframe={self.source_timeframe!r}, "
            f"source_open_time={self.source_open_time.isoformat()!r}, "
            f"side={self.side.value!r})"
        )


@dataclass(frozen=True)
class PhysicalLevel:
    """Immutable physical level geometry and source provenance.

    Independent of contextual directional role (TJL1 vs TJL2).
    """
    level_id: StableLevelId
    lower_price: float
    upper_price: float
    is_line: bool
    source_candle_index: int
    source_candle_open_time: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.level_id, StableLevelId):
            raise TypeError(f"level_id must be StableLevelId, got {type(self.level_id).__name__}")
        for p_name, p_val in (("lower_price", self.lower_price), ("upper_price", self.upper_price)):
            if isinstance(p_val, bool) or not isinstance(p_val, (int, float)):
                raise TypeError(f"{p_name} must be numeric, got {type(p_val).__name__}")
            if not math.isfinite(p_val) or p_val <= 0:
                raise ValueError(f"{p_name} must be finite positive, got {p_val}")

        if self.lower_price > self.upper_price:
            raise ValueError(
                f"PhysicalLevel lower_price ({self.lower_price}) cannot exceed upper_price ({self.upper_price})"
            )

        # Exact zero-width line classification: strict equality, zero tolerance
        expected_is_line = (self.lower_price == self.upper_price)
        if self.is_line != expected_is_line:
            raise ValueError(
                f"PhysicalLevel is_line={self.is_line} inconsistent with exact prices: lower={self.lower_price}, upper={self.upper_price}"
            )

        norm_open = validate_and_normalize_timestamp(self.source_candle_open_time, "source_candle_open_time")
        object.__setattr__(self, "source_candle_open_time", norm_open)


@dataclass(frozen=True)
class TJLZone:
    """An immutable contextual structural zone referencing a physical level and directional role."""
    level_id: StableLevelId
    label: TJLLabel
    lower_price: float
    upper_price: float
    is_line: bool
    source_candle_index: int
    source_candle_open_time: datetime
    confirmed_candle_index: int
    confirmed_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not isinstance(self.level_id, StableLevelId):
            raise TypeError(f"level_id must be StableLevelId instance, got {type(self.level_id).__name__}")
        if not isinstance(self.label, TJLLabel):
            if isinstance(self.label, str):
                object.__setattr__(self, "label", TJLLabel(self.label))
            else:
                raise TypeError(f"label must be TJLLabel enum, got {type(self.label).__name__}")

        for p_name, p_val in (("lower_price", self.lower_price), ("upper_price", self.upper_price)):
            if isinstance(p_val, bool) or not isinstance(p_val, (int, float)):
                raise TypeError(f"{p_name} must be numeric, got {type(p_val).__name__}")
            if not math.isfinite(p_val) or p_val <= 0:
                raise ValueError(f"{p_name} must be finite positive, got {p_val}")

        if self.lower_price > self.upper_price:
            raise ValueError(
                f"TJLZone lower_price ({self.lower_price}) cannot exceed upper_price ({self.upper_price})"
            )

        # Exact zero-width classification: strict equality, no rounding or tolerance
        expected_is_line = (self.lower_price == self.upper_price)
        if self.is_line != expected_is_line:
            raise ValueError(
                f"TJLZone is_line={self.is_line} inconsistent with exact prices: lower={self.lower_price}, upper={self.upper_price}"
            )

        norm_open = validate_and_normalize_timestamp(self.source_candle_open_time, "source_candle_open_time")
        object.__setattr__(self, "source_candle_open_time", norm_open)

        if self.confirmed_time is not None:
            norm_conf = validate_and_normalize_timestamp(self.confirmed_time, "confirmed_time")
            object.__setattr__(self, "confirmed_time", norm_conf)

        if isinstance(self.confirmed_candle_index, bool) or not isinstance(self.confirmed_candle_index, int):
            raise TypeError(f"confirmed_candle_index must be int, got {type(self.confirmed_candle_index).__name__}")

    @classmethod
    def from_candle(
        cls,
        candle: StrategyCandle,
        label: TJLLabel,
        is_high_side: bool,
        feed_id: str,
        timeframe: str,
        confirmed_candle_index: int,
        confirmed_time: Optional[datetime] = None,
    ) -> TJLZone:
        """Constructs an exact TJLZone directly from a raw source candle."""
        if not isinstance(candle, StrategyCandle):
            raise TypeError(f"candle must be StrategyCandle, got {type(candle).__name__}")

        side = TJLSide.HIGH if is_high_side else TJLSide.LOW
        level_id = StableLevelId(
            symbol_feed_id=feed_id,
            source_timeframe=timeframe,
            source_open_time=candle.open_time,
            side=side,
        )

        if is_high_side:
            lower_price = candle.upper_body_edge
            upper_price = candle.high
        else:
            lower_price = candle.low
            upper_price = candle.lower_body_edge

        # Exact zero-width line classification: equality on preserved price representation
        is_line = (lower_price == upper_price)

        return cls(
            level_id=level_id,
            label=label,
            lower_price=lower_price,
            upper_price=upper_price,
            is_line=is_line,
            source_candle_index=candle.index,
            source_candle_open_time=candle.open_time,
            confirmed_candle_index=confirmed_candle_index,
            confirmed_time=confirmed_time,
        )


@dataclass(frozen=True)
class TJLFingerprint:
    """Unique structural fingerprint characterizing a complete current eligible set.

    Formula: (source_engine_id, direction, ch_point_id, cl_point_id, p3_point_id)
    """
    source_engine_id: str
    direction: Direction
    ch_point_id: int
    cl_point_id: int
    p3_point_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.source_engine_id, str) or not self.source_engine_id.strip():
            raise ValueError(f"source_engine_id must be non-empty string, got {self.source_engine_id!r}")
        if isinstance(self.direction, str):
            object.__setattr__(self, "direction", Direction(self.direction))
        elif not isinstance(self.direction, Direction):
            raise TypeError(f"direction must be Direction enum, got {type(self.direction).__name__}")

        for name, val in (("ch_point_id", self.ch_point_id), ("cl_point_id", self.cl_point_id), ("p3_point_id", self.p3_point_id)):
            if isinstance(val, bool) or not isinstance(val, int):
                raise TypeError(f"{name} must be int, got {type(val).__name__}")

    def to_tuple(self) -> Tuple[str, str, int, int, int]:
        return (
            self.source_engine_id,
            self.direction.value,
            self.ch_point_id,
            self.cl_point_id,
            self.p3_point_id,
        )

    def to_list(self) -> List[Any]:
        return list(self.to_tuple())

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, TJLFingerprint):
            return self.to_tuple() == other.to_tuple()
        if isinstance(other, (list, tuple)) and len(other) == 5:
            eng_id, dir_raw, ch_id, cl_id, p3_id = other
            dir_str = dir_raw.value if isinstance(dir_raw, Direction) else str(dir_raw)
            return (
                self.source_engine_id == eng_id
                and self.direction.value == dir_str
                and self.ch_point_id == ch_id
                and self.cl_point_id == cl_id
                and self.p3_point_id == p3_id
            )
        return False

    def __hash__(self) -> int:
        return hash(self.to_tuple())


@dataclass(frozen=True)
class CurrentEligibleSet:
    """An immutable current eligible TJL set containing exactly two confirmed zones and tentative Point 3 anchor."""
    set_id: str
    fingerprint: TJLFingerprint
    direction: Direction
    source_engine_id: str
    symbol_feed_id: str
    source_timeframe: str
    tjl1_zone: TJLZone
    tjl2_zone: TJLZone
    p3_source_index: int
    p3_open_time: datetime
    p3_price: float
    eligibility_available_time: Optional[datetime]
    created_at_candle_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.fingerprint, TJLFingerprint):
            raise TypeError(f"fingerprint must be TJLFingerprint, got {type(self.fingerprint).__name__}")
        if not isinstance(self.tjl1_zone, TJLZone) or not isinstance(self.tjl2_zone, TJLZone):
            raise TypeError("tjl1_zone and tjl2_zone must be TJLZone instances")

        norm_p3_time = validate_and_normalize_timestamp(self.p3_open_time, "p3_open_time")
        object.__setattr__(self, "p3_open_time", norm_p3_time)

        if self.eligibility_available_time is not None:
            norm_avail = validate_and_normalize_timestamp(self.eligibility_available_time, "eligibility_available_time")
            object.__setattr__(self, "eligibility_available_time", norm_avail)

        # Cross-field consistency validations
        if self.fingerprint.source_engine_id != self.source_engine_id:
            raise ValueError(
                f"Fingerprint source_engine_id ({self.fingerprint.source_engine_id}) differs from set source_engine_id ({self.source_engine_id})"
            )
        if self.fingerprint.direction != self.direction:
            raise ValueError(
                f"Fingerprint direction ({self.fingerprint.direction}) differs from set direction ({self.direction})"
            )
        if self.fingerprint.p3_point_id != self.p3_source_index:
            raise ValueError(
                f"Fingerprint p3_point_id ({self.fingerprint.p3_point_id}) differs from set p3_source_index ({self.p3_source_index})"
            )

        if self.direction == Direction.UPWARD:
            if self.tjl1_zone.label != TJLLabel.TJL1 or self.tjl1_zone.level_id.side != TJLSide.HIGH:
                raise ValueError("In UPWARD set, tjl1_zone must have label=TJL1 and side=HIGH")
            if self.tjl2_zone.label != TJLLabel.TJL2_A_PLUS or self.tjl2_zone.level_id.side != TJLSide.LOW:
                raise ValueError("In UPWARD set, tjl2_zone must have label=TJL2_A_PLUS and side=LOW")
            if self.fingerprint.ch_point_id != self.tjl1_zone.source_candle_index:
                raise ValueError("In UPWARD set, fingerprint ch_point_id must match tjl1_zone source candle index")
            if self.fingerprint.cl_point_id != self.tjl2_zone.source_candle_index:
                raise ValueError("In UPWARD set, fingerprint cl_point_id must match tjl2_zone source candle index")
        else:
            if self.tjl1_zone.label != TJLLabel.TJL1 or self.tjl1_zone.level_id.side != TJLSide.LOW:
                raise ValueError("In DOWNWARD set, tjl1_zone must have label=TJL1 and side=LOW")
            if self.tjl2_zone.label != TJLLabel.TJL2_A_PLUS or self.tjl2_zone.level_id.side != TJLSide.HIGH:
                raise ValueError("In DOWNWARD set, tjl2_zone must have label=TJL2_A_PLUS and side=HIGH")
            if self.fingerprint.cl_point_id != self.tjl1_zone.source_candle_index:
                raise ValueError("In DOWNWARD set, fingerprint cl_point_id must match tjl1_zone source candle index")
            if self.fingerprint.ch_point_id != self.tjl2_zone.source_candle_index:
                raise ValueError("In DOWNWARD set, fingerprint ch_point_id must match tjl2_zone source candle index")

        for z_name, z in (("tjl1_zone", self.tjl1_zone), ("tjl2_zone", self.tjl2_zone)):
            if z.level_id.symbol_feed_id != self.symbol_feed_id:
                raise ValueError(f"{z_name} symbol_feed_id ({z.level_id.symbol_feed_id}) does not match set ({self.symbol_feed_id})")
            if z.level_id.source_timeframe != self.source_timeframe:
                raise ValueError(f"{z_name} source_timeframe ({z.level_id.source_timeframe}) does not match set ({self.source_timeframe})")


@dataclass(frozen=True)
class TJLTransitionRecord:
    """Immutable diagnostic record describing an atomic lifecycle transition.

    Explicitly identifies outgoing cancelled set ID and fingerprint when cancellation is emitted.
    """
    transition_type: TJLTransitionType
    outgoing_cancellation_intent: bool
    current_set: Optional[CurrentEligibleSet]
    newly_labeled_zones: Tuple[TJLZone, ...]
    transition_candle_index: int
    transition_time: Optional[datetime]
    outgoing_cancelled_set_id: Optional[str] = None
    outgoing_cancelled_fingerprint: Optional[TJLFingerprint] = None
    diagnostic: Optional[str] = None

    def __post_init__(self) -> None:
        if isinstance(self.transition_type, str):
            object.__setattr__(self, "transition_type", TJLTransitionType(self.transition_type))
        if self.transition_time is not None:
            norm_time = validate_and_normalize_timestamp(self.transition_time, "transition_time")
            object.__setattr__(self, "transition_time", norm_time)

        if self.outgoing_cancellation_intent:
            if self.outgoing_cancelled_set_id is None or self.outgoing_cancelled_fingerprint is None:
                raise ValueError(
                    "outgoing_cancellation_intent=True requires explicit outgoing_cancelled_set_id and outgoing_cancelled_fingerprint"
                )
        else:
            if self.outgoing_cancelled_set_id is not None or self.outgoing_cancelled_fingerprint is not None:
                raise ValueError(
                    "outgoing_cancellation_intent=False cannot have outgoing_cancelled_set_id or outgoing_cancelled_fingerprint"
                )


@dataclass(frozen=True)
class TJLStructuralObservation:
    """Input payload delivered to the pure TJL lifecycle reducer at each observation point.

    Decouples reducer state logic from candle iteration.
    Maintains separate candle_open_time for chronology and availability_time for event availability.
    """
    source_engine_id: str
    symbol_feed_id: str
    source_timeframe: str
    direction: Direction
    candle_index: int
    candle_open_time: datetime
    availability_time: Optional[datetime] = None
    ch_point: Optional[SwingPoint] = None
    cl_point: Optional[SwingPoint] = None
    tentative_p3: Optional[SwingPoint] = None
    is_choch_event: bool = False
    new_choch_direction: Optional[Direction] = None
    is_unresolved: bool = False
    unresolved_diagnostic: Optional[str] = None
    source_candle_lookup: Mapping[int, StrategyCandle] = field(default_factory=dict)
    structural_epoch: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.source_engine_id, str) or not self.source_engine_id.strip():
            raise ValueError("source_engine_id must be non-empty string")
        if not isinstance(self.symbol_feed_id, str) or not self.symbol_feed_id.strip():
            raise ValueError("symbol_feed_id must be non-empty string")
        if not isinstance(self.source_timeframe, str) or not self.source_timeframe.strip():
            raise ValueError("source_timeframe must be non-empty string")
        if not isinstance(self.structural_epoch, int) or self.structural_epoch < 0:
            raise ValueError(f"structural_epoch must be non-negative integer, got {self.structural_epoch}")
        if isinstance(self.direction, str):
            object.__setattr__(self, "direction", Direction(self.direction))
        elif not isinstance(self.direction, Direction):
            raise TypeError(f"direction must be Direction, got {type(self.direction).__name__}")

        norm_open = validate_and_normalize_timestamp(self.candle_open_time, "candle_open_time")
        object.__setattr__(self, "candle_open_time", norm_open)

        if self.availability_time is not None:
            norm_avail = validate_and_normalize_timestamp(self.availability_time, "availability_time")
            object.__setattr__(self, "availability_time", norm_avail)

        # Defensive copy: copy contents even if input is MappingProxyType
        copied_lookup = dict(self.source_candle_lookup)
        object.__setattr__(self, "source_candle_lookup", MappingProxyType(copied_lookup))

        # Validate CHOCH flags and directions together
        if self.is_choch_event:
            if self.new_choch_direction is None:
                raise ValueError("is_choch_event=True requires explicit new_choch_direction")
            if self.new_choch_direction == self.direction:
                raise ValueError(
                    f"is_choch_event=True must transition to opposite direction, got {self.direction} -> {self.new_choch_direction}"
                )
        else:
            if self.new_choch_direction is not None:
                raise ValueError("is_choch_event=False cannot have new_choch_direction")

        observation_horizon = self.availability_time if self.availability_time is not None else self.candle_open_time

        # Validate swing point kinds, confirmation status, exact marking prices, and lookup consistency
        if self.ch_point is not None:
            if not isinstance(self.ch_point, SwingPoint):
                raise TypeError(f"ch_point must be SwingPoint, got {type(self.ch_point).__name__}")
            if not self.ch_point.is_confirmed:
                raise ValueError("ch_point in observation must be confirmed (is_confirmed=True)")
            if self.ch_point.candle_index not in self.source_candle_lookup:
                raise ValueError(f"ch_point candle index {self.ch_point.candle_index} missing from source lookup")
            c_high = self.source_candle_lookup[self.ch_point.candle_index]
            if c_high.index != self.ch_point.candle_index:
                raise ValueError(f"Lookup key {self.ch_point.candle_index} does not match candle index {c_high.index}")
            if self.ch_point.candle_open_time != c_high.open_time:
                raise ValueError("ch_point open_time does not match source candle open_time")
            if self.ch_point.candle_open_time > self.candle_open_time:
                raise ValueError(f"ch_point candle_open_time {self.ch_point.candle_open_time} lies in future relative to observation {self.candle_open_time}")
            if self.ch_point.identified_time is not None and self.ch_point.identified_time > observation_horizon:
                raise ValueError(f"ch_point identified_time {self.ch_point.identified_time} lies in future relative to observation horizon {observation_horizon}")
            if self.ch_point.confirmed_time is not None and self.ch_point.confirmed_time > observation_horizon:
                raise ValueError(f"ch_point confirmed_time {self.ch_point.confirmed_time} lies in future relative to observation horizon {observation_horizon}")
            # Strict exact equality (no tolerance, no math.isclose)
            if self.ch_point.price != c_high.upper_body_edge:
                raise ValueError(
                    f"ch_point price ({self.ch_point.price}) does not exactly match source candle upper body edge ({c_high.upper_body_edge})"
                )

        if self.cl_point is not None:
            if not isinstance(self.cl_point, SwingPoint):
                raise TypeError(f"cl_point must be SwingPoint, got {type(self.cl_point).__name__}")
            if not self.cl_point.is_confirmed:
                raise ValueError("cl_point in observation must be confirmed (is_confirmed=True)")
            if self.cl_point.candle_index not in self.source_candle_lookup:
                raise ValueError(f"cl_point candle index {self.cl_point.candle_index} missing from source lookup")
            c_low = self.source_candle_lookup[self.cl_point.candle_index]
            if c_low.index != self.cl_point.candle_index:
                raise ValueError(f"Lookup key {self.cl_point.candle_index} does not match candle index {c_low.index}")
            if self.cl_point.candle_open_time != c_low.open_time:
                raise ValueError("cl_point open_time does not match source candle open_time")
            if self.cl_point.candle_open_time > self.candle_open_time:
                raise ValueError(f"cl_point candle_open_time {self.cl_point.candle_open_time} lies in future relative to observation {self.candle_open_time}")
            if self.cl_point.identified_time is not None and self.cl_point.identified_time > observation_horizon:
                raise ValueError(f"cl_point identified_time {self.cl_point.identified_time} lies in future relative to observation horizon {observation_horizon}")
            if self.cl_point.confirmed_time is not None and self.cl_point.confirmed_time > observation_horizon:
                raise ValueError(f"cl_point confirmed_time {self.cl_point.confirmed_time} lies in future relative to observation horizon {observation_horizon}")
            # Strict exact equality (no tolerance, no math.isclose)
            if self.cl_point.price != c_low.lower_body_edge:
                raise ValueError(
                    f"cl_point price ({self.cl_point.price}) does not exactly match source candle lower body edge ({c_low.lower_body_edge})"
                )

        if self.ch_point is not None and self.cl_point is not None:
            if self.ch_point.price <= self.cl_point.price:
                raise ValueError(
                    f"ch_point price ({self.ch_point.price}) must be strictly greater than cl_point price ({self.cl_point.price})"
                )

        if self.tentative_p3 is not None:
            if not isinstance(self.tentative_p3, SwingPoint):
                raise TypeError(f"tentative_p3 must be SwingPoint, got {type(self.tentative_p3).__name__}")
            if self.tentative_p3.is_confirmed:
                raise ValueError("tentative_p3 in observation cannot be already confirmed")
            if self.tentative_p3.candle_index not in self.source_candle_lookup:
                raise ValueError(f"tentative_p3 candle index {self.tentative_p3.candle_index} missing from source lookup")
            c_p3 = self.source_candle_lookup[self.tentative_p3.candle_index]
            if c_p3.index != self.tentative_p3.candle_index:
                raise ValueError(f"Lookup key {self.tentative_p3.candle_index} does not match candle index {c_p3.index}")
            if self.tentative_p3.candle_open_time != c_p3.open_time:
                raise ValueError("tentative_p3 open_time does not match source candle open_time")
            if self.tentative_p3.candle_open_time > self.candle_open_time:
                raise ValueError(f"tentative_p3 candle_open_time {self.tentative_p3.candle_open_time} lies in future relative to observation {self.candle_open_time}")
            if self.tentative_p3.identified_time is not None and self.tentative_p3.identified_time > observation_horizon:
                raise ValueError(f"tentative_p3 identified_time {self.tentative_p3.identified_time} lies in future relative to observation horizon {observation_horizon}")
            expected_p3_price = c_p3.upper_body_edge if self.direction == Direction.UPWARD else c_p3.lower_body_edge
            # Strict exact equality (no tolerance, no math.isclose)
            if self.tentative_p3.price != expected_p3_price:
                raise ValueError(
                    f"tentative_p3 price ({self.tentative_p3.price}) does not exactly match expected body edge ({expected_p3_price})"
                )


@dataclass(frozen=True)
class TJLSnapshot:
    """Immutable snapshot of the pure TJL engine state."""
    source_engine_id: str
    symbol_feed_id: str
    source_timeframe: str
    direction: Optional[Direction]
    current_eligible_set: Optional[CurrentEligibleSet]
    all_labeled_zones: Tuple[TJLZone, ...]
    historical_sets: Tuple[CurrentEligibleSet, ...]
    outgoing_cancellation_intent: bool
    last_transition: Optional[TJLTransitionRecord]
    transition_history: Tuple[TJLTransitionRecord, ...]
    is_unresolved: bool
    unresolved_diagnostic: Optional[str]
    last_processed_index: int
    last_received_index: int
    structural_epoch: int = 0
