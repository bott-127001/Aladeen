"""Domain models, enums, and immutable value objects for Tap and Zone Activation.

Scope & Design Boundary:
-------------------------
- Independent of MT5, UI, Dash, Plotly, network, broker connection, and storage.
- All domain events, snapshots, records, and evidence representations are strictly immutable.
- Explicit sequence domain scoping: bare integer sequences are compared only within declared (feed_id, run_id).
- Unambiguous canonical activation ID encoding.
- Raw price observations are immutable facts; association with activations is tracked separately without mutating shared prints.
- No trade execution, no order management, no balance inspection, no live account modification.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from .tjl_types import StableLevelId
from .types import Direction, validate_and_normalize_timestamp


class PriceBasis(str, Enum):
    """Configured pricing basis for discrete print evaluation."""
    BID = "BID"
    ASK = "ASK"
    MID = "MID"


class UsageEvidenceStatus(str, Enum):
    """Physical level lifetime usage status from authoritative evidence."""
    UNUSED = "UNUSED"
    USED = "USED"
    UNKNOWN = "UNKNOWN"


class CoverageStatus(str, Enum):
    """Market data batch completeness and coverage classification."""
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNCERTAIN = "UNCERTAIN"


class ActivationState(str, Enum):
    """Lifecycle states of a transient activation state machine."""
    INACTIVE_ELIGIBLE = "INACTIVE_ELIGIBLE"
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    REARMED_PENDING = "REARMED_PENDING"
    CANCELLED_SOURCE_CHOCH = "CANCELLED_SOURCE_CHOCH"
    CANCELLED_SOURCE_REPLACEMENT = "CANCELLED_SOURCE_REPLACEMENT"
    CANCELLED_EXTERNAL_ENTRY = "CANCELLED_EXTERNAL_ENTRY"
    OUT_OF_ZONE_ARMED = "OUT_OF_ZONE_ARMED"
    INACTIVE_INELIGIBLE = "INACTIVE_INELIGIBLE"
    BLOCKED_UNKNOWN_ORDER = "BLOCKED_UNKNOWN_ORDER"


class CancellationReason(str, Enum):
    """Authoritative triggers for activation cancellation."""
    SOURCE_CHOCH = "SOURCE_CHOCH"
    SOURCE_REPLACEMENT = "SOURCE_REPLACEMENT"
    EXTERNAL_ENTRY = "EXTERNAL_ENTRY"


@dataclass(frozen=True)
class SequenceDomain:
    """Declares the feed and engine run context for causal sequence ordering.

    A bare integer sequence reference is not comparable across independent feeds or runs.
    """
    feed_id: str
    run_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.feed_id, str) or not self.feed_id.strip():
            raise ValueError(f"feed_id must be non-empty string, got {self.feed_id!r}")
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError(f"run_id must be non-empty string, got {self.run_id!r}")


SUPPORTED_SOURCE_ROLES = frozenset({"TJL1", "TJL2_A_PLUS"})
SUPPORTED_COMMIT_SCOPES = frozenset({"SAME_SOURCE_TIMEFRAME", "ENGINE_LOCAL"})


def format_member_key(set_id: str, role: str) -> str:
    """Canonical, unambiguous length-prefixed member key encoding.

    Length-prefixing prevents collision even if set_id or role contains delimiters.
    """
    return f"MK[{len(set_id)}:{set_id}][{len(role)}:{role}]"


@dataclass(frozen=True)
class SourceMemberReference:
    """Current eligible source level member registered with the activation engine."""
    engine_id: str
    symbol: str
    source_timeframe: str
    set_id: str
    role: str  # "TJL1" or "TJL2_A_PLUS"
    side: str  # "HIGH" or "LOW"
    lower_edge: float
    upper_edge: float
    is_line: bool
    direction: Direction
    level_id: Optional[StableLevelId] = None
    eligibility_available_time: Optional[datetime] = None
    usage_evidence_status: UsageEvidenceStatus = UsageEvidenceStatus.UNKNOWN

    def __post_init__(self) -> None:
        if self.role not in SUPPORTED_SOURCE_ROLES:
            raise ValueError(
                f"Unsupported role {self.role!r}. Supported roles are: {sorted(SUPPORTED_SOURCE_ROLES)}"
            )
        if not math.isfinite(self.lower_edge) or self.lower_edge <= 0:
            raise ValueError(f"lower_edge must be finite positive float, got {self.lower_edge}")
        if not math.isfinite(self.upper_edge) or self.upper_edge <= 0:
            raise ValueError(f"upper_edge must be finite positive float, got {self.upper_edge}")
        if self.upper_edge < self.lower_edge:
            raise ValueError(f"upper_edge ({self.upper_edge}) cannot be strictly less than lower_edge ({self.lower_edge})")
        if self.is_line and self.lower_edge != self.upper_edge:
            raise ValueError(f"is_line is True but lower_edge ({self.lower_edge}) != upper_edge ({self.upper_edge})")
        if not isinstance(self.usage_evidence_status, UsageEvidenceStatus):
            raise TypeError("usage_evidence_status must be UsageEvidenceStatus enum")

    @property
    def member_key(self) -> str:
        """Deterministic, unambiguous member lookup key scoped by set_id and role."""
        return format_member_key(self.set_id, self.role)


@dataclass(frozen=True)
class ExactPricePrint:
    """Discrete, immutable market price observation."""
    observation_id: str
    price: float
    price_basis: PriceBasis
    timestamp: datetime
    sequence_domain: SequenceDomain
    sequence_ref: int
    provenance: Optional[str] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, str) or not self.observation_id.strip():
            raise ValueError(f"observation_id must be non-empty string, got {self.observation_id!r}")
        if not math.isfinite(self.price) or self.price <= 0:
            raise ValueError(f"price must be finite positive float, got {self.price}")
        if not isinstance(self.price_basis, PriceBasis):
            raise TypeError(f"price_basis must be PriceBasis enum, got {self.price_basis!r}")
        if self.timestamp.tzinfo != timezone.utc:
            raise ValueError(f"timestamp must be UTC timezone-aware, got {self.timestamp}")
        if not isinstance(self.sequence_ref, int) or self.sequence_ref < 0:
            raise ValueError(f"sequence_ref must be non-negative integer, got {self.sequence_ref}")


@dataclass(frozen=True)
class IntervalBoundedCandleEvidence:
    """Interval-bounded candle evidence with unknown intra-bar exact occurrence time."""
    event_id: str
    sequence_domain: SequenceDomain
    sequence_ref: int
    candle_id: str
    interval_open: datetime
    interval_close: datetime
    observed_field: str  # "HIGH", "LOW", "CLOSE", "OPEN"
    observed_value: float
    sub_bar_sequence_available: bool = False
    timestamp: Optional[datetime] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id must be non-empty string")
        if not isinstance(self.sequence_ref, int) or self.sequence_ref < 0:
            raise ValueError("sequence_ref must be non-negative integer")
        if self.interval_open.tzinfo != timezone.utc:
            raise ValueError("interval_open must be UTC timezone-aware")
        if self.interval_close.tzinfo != timezone.utc:
            raise ValueError("interval_close must be UTC timezone-aware")
        if self.interval_close <= self.interval_open:
            raise ValueError("interval_close must be strictly greater than interval_open")
        if not math.isfinite(self.observed_value) or self.observed_value <= 0:
            raise ValueError(f"observed_value must be finite positive float, got {self.observed_value}")
        if self.timestamp is not None and self.timestamp.tzinfo != timezone.utc:
            raise ValueError("timestamp must be UTC timezone-aware if provided")


@dataclass(frozen=True)
class SourceCancellationEvent:
    """Authoritative event triggering cancellation of source level activations."""
    event_id: str
    cancellation_reason: CancellationReason
    sequence_domain: SequenceDomain
    sequence_ref: int
    timestamp: Optional[datetime] = None
    target_set_id: Optional[str] = None
    target_role: Optional[str] = None
    affected_direction: Optional[Direction] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id must be non-empty string")
        if self.timestamp is not None and self.timestamp.tzinfo != timezone.utc:
            raise ValueError("timestamp must be UTC timezone-aware if provided")
        if not isinstance(self.sequence_ref, int) or self.sequence_ref < 0:
            raise ValueError("sequence_ref must be non-negative integer")


@dataclass(frozen=True)
class ExternalCommitEvent:
    """Notification of an external winning entry commit.

    External commit notifications are inputs only; do not select a winner or write usage.
    """
    event_id: str
    timestamp: datetime
    sequence_domain: SequenceDomain
    sequence_ref: int
    winning_engine_id: str
    winning_set_id: str
    winning_role: str
    cancelled_competing_scope: str = "SAME_SOURCE_TIMEFRAME"
    target_symbol: Optional[str] = None
    target_source_timeframe: Optional[str] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id must be non-empty string")
        if self.timestamp.tzinfo != timezone.utc:
            raise ValueError("timestamp must be UTC timezone-aware")
        if not isinstance(self.sequence_ref, int) or self.sequence_ref < 0:
            raise ValueError("sequence_ref must be non-negative integer")
        if not isinstance(self.cancelled_competing_scope, str) or not self.cancelled_competing_scope.strip():
            raise ValueError("cancelled_competing_scope must be non-empty string")


@dataclass(frozen=True)
class CoverageEvidence:
    """Authoritative declaration of market data coverage completeness."""
    event_id: str
    sequence_domain: SequenceDomain
    sequence_ref: int
    coverage_status: CoverageStatus
    scope: str
    missing_gap_count: int = 0
    timestamp: Optional[datetime] = None
    details: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id must be non-empty string")
        if not isinstance(self.sequence_ref, int) or self.sequence_ref < 0:
            raise ValueError("sequence_ref must be non-negative integer")
        if self.timestamp is not None and self.timestamp.tzinfo != timezone.utc:
            raise ValueError("timestamp must be UTC timezone-aware if provided")


@dataclass(frozen=True)
class RegisterMembersEvent:
    """Explicit member registration event for deterministic historical replay."""
    event_id: str
    sequence_domain: SequenceDomain
    sequence_ref: int
    timestamp: Optional[datetime]
    members: Tuple[SourceMemberReference, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id must be non-empty string")
        if not isinstance(self.sequence_ref, int) or self.sequence_ref < 0:
            raise ValueError("sequence_ref must be non-negative integer")
        if self.timestamp is not None and self.timestamp.tzinfo != timezone.utc:
            raise ValueError("timestamp must be UTC timezone-aware if provided")


def format_activation_id(
    engine_id: str,
    source_timeframe: str,
    symbol: str,
    set_id: str,
    role: str,
    generation_seq: int,
) -> str:
    """Canonical, unambiguous length-prefixed activation-ID encoding.

    Length-prefixing mathematically guarantees collision resistance even if
    arbitrary identifier components contain delimiter strings.
    """
    return (
        f"ACT_G{generation_seq:02d}"
        f"[{len(engine_id)}:{engine_id}]"
        f"[{len(source_timeframe)}:{source_timeframe}]"
        f"[{len(symbol)}:{symbol}]"
        f"[{len(set_id)}:{set_id}]"
        f"[{len(role)}:{role}]"
    )


@dataclass(frozen=True)
class ActivationRecord:
    """Immutable record of an activation lifecycle state machine."""
    activation_id: str
    engine_id: str
    symbol: str
    source_timeframe: str
    confirmation_timeframe: str
    set_id: str
    role: str
    level_id: Optional[StableLevelId]
    lower_edge: float
    upper_edge: float
    state: ActivationState
    first_touch_time: Optional[datetime] = None
    first_touch_price: Optional[float] = None
    trigger_observation_id: Optional[str] = None
    prior_activation_id: Optional[str] = None
    rearm_armed: bool = False
    last_observed_position: Optional[str] = None  # "INSIDE", "OUTSIDE"
    usage_evidence_status: UsageEvidenceStatus = UsageEvidenceStatus.UNKNOWN
    cancellation_reason: Optional[CancellationReason] = None
    cancellation_time: Optional[datetime] = None
    cancellation_sequence_ref: Optional[int] = None
    generation_seq: int = 1
    terminal: bool = False
    blocked_reason: Optional[str] = None

    @property
    def member_key(self) -> str:
        """Deterministic, unambiguous member lookup key scoped by set_id and role."""
        return format_member_key(self.set_id, self.role)


@dataclass(frozen=True)
class RearmController:
    """Stateful rearm controller managing outside departure and arming after external cancellation.

    Strictly decoupled from immutable terminal activation records. References prior_activation_id.
    """
    member_key: str
    prior_activation_id: str
    generation_seq: int
    state: ActivationState  # CANCELLED_EXTERNAL_ENTRY or OUT_OF_ZONE_ARMED
    rearm_armed: bool
    last_observed_position: Optional[str] = None  # "INSIDE", "OUTSIDE"
    cancellation_time: Optional[datetime] = None
    cancellation_sequence_ref: Optional[int] = None


@dataclass(frozen=True)
class ActivationSnapshot:
    """Immutable point-in-time state of the Activation Engine."""
    engine_id: str
    symbol: str
    source_timeframe: str
    confirmation_timeframe: str
    sequence_domain: SequenceDomain
    active_activations: Mapping[str, ActivationRecord]  # keyed by member_key (e.g. "SET_1::TJL1")
    terminal_activations: Sequence[ActivationRecord]
    coverage_status: CoverageStatus
    last_processed_sequence: Optional[int]
    last_processed_timestamp: Optional[datetime]
    current_members: Mapping[str, SourceMemberReference]
    rearm_controllers: Mapping[str, RearmController] = field(default_factory=dict)


# Semantic alias
ActivationLifecycleSnapshot = ActivationSnapshot


# Standard MTF timeframe mapping dictionary (§6)
TIMEFRAME_CONFIRMATION_MAP: Mapping[str, str] = MappingProxyType({
    "D1": "H1",
    "H4": "M5",
    "H1": "M1",
})


class ActivationError(Exception):
    """Base exception for activation lifecycle engine."""
    pass


class DomainMismatchError(ActivationError):
    """Raised when an event's sequence domain does not match the engine's configured domain."""
    pass


class SequenceOrderError(ActivationError):
    """Raised when an event arrives with an inverted sequence ref or non-monotonic ordering."""
    pass


class ConflictingEventError(ActivationError):
    """Raised when a duplicate event ID carries conflicting payload content."""
    pass


class InvalidEvidenceError(ActivationError):
    """Raised when invalid or incomplete evidence blocks transition."""
    pass
