"""Domain models, enums, and immutable value objects for Confirmation Evidence and Setup Matching.

Scope & Design Boundary:
-------------------------
- Pure mathematical, typing, and domain modeling for entry confirmation evidence and candidate setups.
- Independent of MT5, Dash, Plotly, network, broker connection, and persistent storage.
- All evidence records, setup records, and matching results are strictly immutable (frozen dataclasses).
- Explicit observational fields: direction and structural dependency references are captured
  directly from detector/provenance data and never inferred from producer names or arbitrary IDs.
- Strictly read-only passive matching logic.
- Zero winner selection, zero level usage consumption, zero signal publication, and zero order execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .activation_types import (
    PriceBasis,
    SequenceDomain,
    UsageEvidenceStatus,
    CoverageStatus,
    ActivationState,
    format_activation_id,
    format_member_key,
)
from .tjl_types import StableLevelId
from .types import Direction, validate_and_normalize_timestamp


class ConfirmationMatchStatus(str, Enum):
    """Lifecycle status of an activation-to-confirmation matching evaluation."""
    MATCHED = "MATCHED"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    UNCERTAIN = "UNCERTAIN"


class EvidenceProvenanceType(str, Enum):
    """Explicit provenance classification of confirmation evidence."""
    DETECTOR_CONFIRMED = "DETECTOR_CONFIRMED"
    SYNTHETIC_TYPED = "SYNTHETIC_TYPED"
    BLOCKED_INCOMPLETE = "BLOCKED_INCOMPLETE"


class ConfirmationRejectionReason(str, Enum):
    """Explicit diagnostic reasons for rejection or blocking of confirmation associations."""
    DIRECTION_MISMATCH = "DIRECTION_MISMATCH"
    TIMEFRAME_MISMATCH = "TIMEFRAME_MISMATCH"
    CONTEXT_MISMATCH = "CONTEXT_MISMATCH"
    PRICE_BASIS_MISMATCH = "PRICE_BASIS_MISMATCH"
    INELIGIBLE_ACTIVATION_STATE = "INELIGIBLE_ACTIVATION_STATE"
    PRE_ACTIVATION_CONFIRMATION = "PRE_ACTIVATION_CONFIRMATION"
    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    INCOMPLETE_COVERAGE = "INCOMPLETE_COVERAGE"
    UNKNOWN_USAGE = "UNKNOWN_USAGE"
    UNRESOLVED_DEPENDENCY = "UNRESOLVED_DEPENDENCY"
    BLOCKED_UNRESOLVED_CONFIRMATION_GAP = "BLOCKED_UNRESOLVED_CONFIRMATION_GAP"
    MEMBERSHIP_CANCELLED_OR_REPLACED = "MEMBERSHIP_CANCELLED_OR_REPLACED"
    STALE_EVIDENCE_FOR_GENERATION = "STALE_EVIDENCE_FOR_GENERATION"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"
    ISOLATED_TRACKING_ONLY = "ISOLATED_TRACKING_ONLY"
    CONFLICTING_IDENTITY = "CONFLICTING_IDENTITY"
    MISSING_MATCHING_AUTHORITY = "MISSING_MATCHING_AUTHORITY"
    EVIDENCE_NOT_YET_AVAILABLE = "EVIDENCE_NOT_YET_AVAILABLE"
    CROSS_DOMAIN_ORDERING_REJECTED = "CROSS_DOMAIN_ORDERING_REJECTED"
    ASSOCIATION_TARGET_MISMATCH = "ASSOCIATION_TARGET_MISMATCH"
    TOUCH_BEFORE_ELIGIBILITY = "TOUCH_BEFORE_ELIGIBILITY"
    UNKNOWN_ELIGIBILITY_AVAILABLE_TIME = "UNKNOWN_ELIGIBILITY_AVAILABLE_TIME"
    BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY = "BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY"
    PHYSICAL_LEVEL_METADATA_MISMATCH = "PHYSICAL_LEVEL_METADATA_MISMATCH"
    MISSING_CONFIRMING_CANDLE_AUTHORITY = "MISSING_CONFIRMING_CANDLE_AUTHORITY"
    CANDLE_EVENT_DISAGREEMENT = "CANDLE_EVENT_DISAGREEMENT"
    MISSING_STRUCTURAL_PROVENANCE = "MISSING_STRUCTURAL_PROVENANCE"
    MISSING_TOUCH_EVIDENCE = "MISSING_TOUCH_EVIDENCE"
    UNKNOWN_SOURCE_RESOLUTION_AUTHORITY = "UNKNOWN_SOURCE_RESOLUTION_AUTHORITY"


def format_length_prefixed(val: str) -> str:
    """Format string with canonical length prefix [len:val]."""
    return f"[{len(val)}:{val}]"


def format_candidate_setup_key(
    domain_session_id: str,
    revision_id: str,
    activation_id: str,
    source_member_key: str,
    confirmation_config_id: str,
    confirmation_candle_id: str,
    confirmation_close_iso: str,
) -> str:
    """Canonical length-prefixed encoding for CandidateSetupKey.

    Canonical format:
    CSK[{len:session}][{len:rev}][{len:act}][{len:member}][{len:conf_cfg}][{len:candle}][{len:close}]
    """
    return (
        "CSK"
        f"{format_length_prefixed(domain_session_id)}"
        f"{format_length_prefixed(revision_id)}"
        f"{format_length_prefixed(activation_id)}"
        f"{format_length_prefixed(source_member_key)}"
        f"{format_length_prefixed(confirmation_config_id)}"
        f"{format_length_prefixed(confirmation_candle_id)}"
        f"{format_length_prefixed(confirmation_close_iso)}"
    )


_SETUP_KEY_SEGMENT_RE = re.compile(r"\[(\d+):(.*?)\]")


def parse_candidate_setup_key(key: str) -> Dict[str, str]:
    """Parse and validate canonical CandidateSetupKey, enforcing exact length prefixes."""
    if not key.startswith("CSK"):
        raise ValueError(f"CandidateSetupKey must start with 'CSK', got {key!r}")

    rest = key[3:]
    fields = [
        "domain_session_id",
        "revision_id",
        "activation_id",
        "source_member_key",
        "confirmation_config_id",
        "confirmation_candle_id",
        "confirmation_close_iso",
    ]
    parsed: Dict[str, str] = {}
    curr = rest
    for field_name in fields:
        if not curr.startswith("["):
            raise ValueError(f"Malformed key at field {field_name}: expected '[', got {curr[:10]!r}")
        match = _SETUP_KEY_SEGMENT_RE.match(curr)
        if not match:
            raise ValueError(f"Malformed length prefix segment at {curr[:20]!r}")
        expected_len = int(match.group(1))
        content = match.group(2)
        if len(content) != expected_len:
            raise ValueError(
                f"Length prefix mismatch for {field_name}: declared {expected_len}, found {len(content)}"
            )
        parsed[field_name] = content
        curr = curr[match.end():]

    if curr:
        raise ValueError(f"Unexpected trailing content in key: {curr!r}")
    return parsed


SUPPORTED_CONFIRMATION_PATTERNS = frozenset({"CHOCH", "ISS", "AUTHORITATIVE_CONFIRMED_ISS"})
SUPPORTED_CONFIRMATION_TIMEFRAMES = frozenset({"H1", "M5", "M1"})


@dataclass(frozen=True)
class ConfirmationEvidenceRecord:
    """Authoritative, immutable evidence record emitted by a confirmation detector.

    Required context binding:
    - symbol: Explicit market symbol (e.g. 'EURUSD').
    - feed_id: Explicit market data feed identifier.
    - sequence_domain: Explicit SequenceDomain ensuring causal comparability.
    - close_timestamp: Explicit UTC close timestamp, or None if unknown (which enforces is_completed=False).
    - direction: Explicit observational direction (UPWARD/DOWNWARD) captured directly from
      the detector's structural output. Direction is never inferred from producer names or IDs.
    - structural_dependency_references: Explicit structural provenance identifiers establishing verifiable origin.
    """
    event_id: str
    producer_id: str
    pattern_type: str  # "CHOCH" or "ISS"
    confirmation_config_id: str
    confirmation_timeframe: str
    confirmation_candle_id: str
    symbol: str
    feed_id: str
    sequence_domain: SequenceDomain
    close_price: float
    price_basis: PriceBasis
    direction: Direction
    close_timestamp: Optional[datetime] = None
    price_provenance: str = "CONFIRMATION_CANDLE_CLOSE"
    provenance_type: EvidenceProvenanceType = EvidenceProvenanceType.DETECTOR_CONFIRMED
    is_completed: bool = True
    has_unresolved_dependencies: bool = False
    structural_dependency_references: Tuple[str, ...] = field(default_factory=tuple)
    sequence_ref: Optional[int] = None
    is_isolated_tracking: bool = False
    activation_id: Optional[str] = None
    source_member_key: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError(f"event_id must be non-empty string, got {self.event_id!r}")
        if not isinstance(self.producer_id, str) or not self.producer_id.strip():
            raise ValueError(f"producer_id must be non-empty string, got {self.producer_id!r}")
        if self.pattern_type not in ("CHOCH", "ISS", "AUTHORITATIVE_CONFIRMED_ISS"):
            raise ValueError(f"Unsupported pattern_type {self.pattern_type!r}")
        if not isinstance(self.confirmation_config_id, str) or not self.confirmation_config_id.strip():
            raise ValueError("confirmation_config_id must be non-empty string")
        if self.confirmation_timeframe not in SUPPORTED_CONFIRMATION_TIMEFRAMES:
            raise ValueError(f"Unsupported confirmation_timeframe {self.confirmation_timeframe!r}")
        if not isinstance(self.confirmation_candle_id, str) or not self.confirmation_candle_id.strip():
            raise ValueError("confirmation_candle_id must be non-empty string")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be non-empty string")
        if not isinstance(self.feed_id, str) or not self.feed_id.strip():
            raise ValueError("feed_id must be non-empty string")
        if not isinstance(self.sequence_domain, SequenceDomain):
            raise TypeError("sequence_domain must be SequenceDomain instance")
        if not isinstance(self.provenance_type, EvidenceProvenanceType):
            raise TypeError(f"provenance_type must be EvidenceProvenanceType enum, got {type(self.provenance_type).__name__}")

        if self.provenance_type == EvidenceProvenanceType.BLOCKED_INCOMPLETE:
            object.__setattr__(self, "is_completed", False)

        if self.close_timestamp is not None:
            norm_time = validate_and_normalize_timestamp(self.close_timestamp, "close_timestamp")
            object.__setattr__(self, "close_timestamp", norm_time)
        else:
            # Unknown completion time: cannot be an authoritative completed confirmation
            object.__setattr__(self, "is_completed", False)

        if not math.isfinite(self.close_price) or self.close_price <= 0:
            raise ValueError(f"close_price must be finite positive float, got {self.close_price}")
        if not isinstance(self.price_basis, PriceBasis):
            raise TypeError(f"price_basis must be PriceBasis enum, got {type(self.price_basis).__name__}")
        if not isinstance(self.direction, Direction):
            raise TypeError(f"direction must be Direction enum, got {type(self.direction).__name__}")
        if not isinstance(self.structural_dependency_references, tuple):
            object.__setattr__(self, "structural_dependency_references", tuple(self.structural_dependency_references))

        # Validate that structural dependency references contain genuine values, not placeholders
        for ref in self.structural_dependency_references:
            if not isinstance(ref, str) or not ref.strip():
                raise ValueError("structural dependency reference must be non-empty string")
            if ":None" in ref or ":null" in ref or ":undefined" in ref or ref.endswith(":-1"):
                raise ValueError(f"Invalid structural dependency reference with missing/placeholder value: {ref!r}")

        if self.sequence_ref is not None and (not isinstance(self.sequence_ref, int) or self.sequence_ref < 0):
            raise ValueError(f"sequence_ref must be non-negative integer, got {self.sequence_ref}")


@dataclass(frozen=True)
class CandidateSetupRecord:
    """Immutable candidate setup record evaluated in confirmation matching.

    Matches all 20 required fields from Milestone 30 Specification §6.4.
    """
    candidate_id: str
    setup_key: str
    domain_session_id: str
    revision_id: str
    activation_id: str
    source_level_id: Optional[StableLevelId]
    source_timeframe: str
    source_set_id: str
    source_role: str
    signal_side: str  # "BUY" or "SELL"
    confirmation_timeframe: str
    confirmation_close_timestamp: datetime
    entry_reference_price: float
    price_basis: PriceBasis
    price_provenance: str
    confirmation_event_ids: Tuple[str, ...]
    confirmation_patterns: Tuple[str, ...]
    is_consolidated: bool
    timeframe_rank: int  # M1=1, M5=2, H1=3
    role_rank: int       # TJL2_A_PLUS=1, TJL1=2
    provenance_type: EvidenceProvenanceType = EvidenceProvenanceType.DETECTOR_CONFIRMED

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.strip():
            raise ValueError("candidate_id must be non-empty string")
        if not isinstance(self.setup_key, str) or not self.setup_key.strip():
            raise ValueError("setup_key must be non-empty string")
        if self.signal_side not in ("BUY", "SELL"):
            raise ValueError(f"signal_side must be 'BUY' or 'SELL', got {self.signal_side!r}")
        norm_time = validate_and_normalize_timestamp(
            self.confirmation_close_timestamp, "confirmation_close_timestamp"
        )
        object.__setattr__(self, "confirmation_close_timestamp", norm_time)
        if not math.isfinite(self.entry_reference_price) or self.entry_reference_price <= 0:
            raise ValueError(f"entry_reference_price must be finite positive float, got {self.entry_reference_price}")
        if self.timeframe_rank not in (1, 2, 3):
            raise ValueError(f"timeframe_rank must be 1, 2, or 3, got {self.timeframe_rank}")
        if self.role_rank not in (1, 2):
            raise ValueError(f"role_rank must be 1 or 2, got {self.role_rank}")
        if not isinstance(self.provenance_type, EvidenceProvenanceType):
            raise TypeError(f"provenance_type must be EvidenceProvenanceType enum, got {type(self.provenance_type).__name__}")
        if not isinstance(self.confirmation_event_ids, tuple):
            object.__setattr__(self, "confirmation_event_ids", tuple(self.confirmation_event_ids))
        if not isinstance(self.confirmation_patterns, tuple):
            object.__setattr__(self, "confirmation_patterns", tuple(self.confirmation_patterns))


@dataclass(frozen=True)
class ConfirmationMatchResult:
    """Immutable result of associating a confirmation evidence record with an activation.

    Evaluated timestamp is strictly deterministic from MatchingContext.evaluation_time.
    """
    match_id: str
    status: ConfirmationMatchStatus
    activation_id: str
    evidence_event_id: str
    evaluated_at: datetime
    candidate_record: Optional[CandidateSetupRecord] = None
    rejection_reasons: Tuple[ConfirmationRejectionReason, ...] = field(default_factory=tuple)
    diagnostic_message: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.match_id, str) or not self.match_id.strip():
            raise ValueError("match_id must be non-empty string")
        if not isinstance(self.status, ConfirmationMatchStatus):
            raise TypeError("status must be ConfirmationMatchStatus enum")
        if not isinstance(self.rejection_reasons, tuple):
            object.__setattr__(self, "rejection_reasons", tuple(self.rejection_reasons))
        norm_time = validate_and_normalize_timestamp(self.evaluated_at, "evaluated_at")
        object.__setattr__(self, "evaluated_at", norm_time)


@dataclass(frozen=True)
class TouchSequenceEvidence:
    """Authoritative sequence domain and monotonic sequence index of a price touch observation."""
    sequence_domain: SequenceDomain
    sequence_ref: int

    def __post_init__(self) -> None:
        if not isinstance(self.sequence_domain, SequenceDomain):
            raise TypeError("sequence_domain must be SequenceDomain instance")
        if not isinstance(self.sequence_ref, int) or self.sequence_ref < 0:
            raise ValueError("sequence_ref must be non-negative integer")


@dataclass(frozen=True)
class BatchMatchResult:
    """Immutable result of batch confirmation matching.

    Provides unique, deduplicated candidate setup records separately
    from pair-level association diagnostics.
    """
    unique_candidates: Tuple[CandidateSetupRecord, ...]
    pair_results: Tuple[ConfirmationMatchResult, ...]
    diagnostic_messages: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.unique_candidates, tuple):
            object.__setattr__(self, "unique_candidates", tuple(self.unique_candidates))
        if not isinstance(self.pair_results, tuple):
            object.__setattr__(self, "pair_results", tuple(self.pair_results))
        if not isinstance(self.diagnostic_messages, tuple):
            object.__setattr__(self, "diagnostic_messages", tuple(self.diagnostic_messages))
