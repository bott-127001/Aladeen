"""Domain models, enums, and immutable value objects for Offline Authority Propagation.

Scope & Design Boundary:
-------------------------
- Pure mathematical, typing, and domain modeling for offline authority inputs (usage, coverage, trust).
- Zero database writes, zero filesystem ledger operations, zero network/broker interaction.
- Strictly immutable frozen value objects, defensive freezing, and deterministic diagnostics.
- Compliant with Milestone 34 specification (docs/requirements/offline-authority-propagation.md)
  and Milestone 35 directives (HANDOFF-114 review).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .activation_types import (
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
)
from .confirmation_pair_matcher import MatchingContext
from .tjl_types import StableLevelId
from .types import validate_and_normalize_timestamp


class AuthorityDiagnosticReason(str, Enum):
    """Detailed diagnostic reasons emitted during offline authority preprocessing."""
    AUTHORITY_VALID = "AUTHORITY_VALID"
    ISSUER_NOT_TRUSTED = "ISSUER_NOT_TRUSTED"
    INVALID_SCHEMA_VERSION = "INVALID_SCHEMA_VERSION"
    RECORD_NOT_YET_AVAILABLE = "RECORD_NOT_YET_AVAILABLE"
    RECORD_NOT_YET_ESTABLISHED = "RECORD_NOT_YET_ESTABLISHED"
    CONFLICTING_IDENTITY = "CONFLICTING_IDENTITY"
    SCOPE_MISMATCH_FEED = "SCOPE_MISMATCH_FEED"
    SCOPE_MISMATCH_RUN = "SCOPE_MISMATCH_RUN"
    SCOPE_MISMATCH_TIMEFRAME = "SCOPE_MISMATCH_TIMEFRAME"
    SCOPE_MISMATCH_CONFIG = "SCOPE_MISMATCH_CONFIG"
    UNKNOWN_PREDECESSOR = "UNKNOWN_PREDECESSOR"
    INVALID_ANCESTOR = "INVALID_ANCESTOR"
    WRONG_SCOPE_SUPERSEDED = "WRONG_SCOPE_SUPERSEDED"
    CYCLIC_PREDECESSOR_LINK = "CYCLIC_PREDECESSOR_LINK"
    AMBIGUOUS_FORK = "AMBIGUOUS_FORK"
    CONTRADICTORY_ASSERTION = "CONTRADICTORY_ASSERTION"
    SUPERSEDED_BY_VALID_REVISION = "SUPERSEDED_BY_VALID_REVISION"
    INCOMPLETE_STATUS = "INCOMPLETE_STATUS"
    UNCERTAIN_STATUS = "UNCERTAIN_STATUS"
    INTERVAL_NOT_COVERED = "INTERVAL_NOT_COVERED"
    INTERSECTING_CONFLICT = "INTERSECTING_CONFLICT"
    USAGE_USED_TERMINAL = "USAGE_USED_TERMINAL"
    INVALID_USAGE_TRANSITION = "INVALID_USAGE_TRANSITION"


@dataclass(frozen=True)
class TrustConfiguration:
    """Explicitly declared trust boundaries for offline authority sources.

    Defaults to empty collections: trusted issuers must be explicitly supplied.
    Defensively converts caller inputs to immutable tuples.
    """
    trusted_usage_issuers: Tuple[str, ...] = ()
    trusted_coverage_issuers: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "trusted_usage_issuers", tuple(self.trusted_usage_issuers))
        object.__setattr__(self, "trusted_coverage_issuers", tuple(self.trusted_coverage_issuers))


@dataclass(frozen=True)
class ProposedUsageEvidenceRecord:
    """Authoritative physical-level usage evidence record."""
    record_id: str
    schema_version: str
    issuer_id: str
    level_id: StableLevelId
    status: UsageEvidenceStatus
    established_time: datetime
    available_time: datetime
    provenance_ref: str
    predecessor_record_id: Optional[str] = None
    optional_integrity_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id.strip():
            raise ValueError(f"record_id must be non-empty string, got {self.record_id!r}")
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise ValueError(f"schema_version must be non-empty string, got {self.schema_version!r}")
        if not isinstance(self.issuer_id, str) or not self.issuer_id.strip():
            raise ValueError(f"issuer_id must be non-empty string, got {self.issuer_id!r}")
        if not isinstance(self.level_id, StableLevelId):
            raise TypeError(f"level_id must be StableLevelId instance, got {type(self.level_id).__name__}")
        if not isinstance(self.status, UsageEvidenceStatus):
            raise TypeError(f"status must be UsageEvidenceStatus enum, got {type(self.status).__name__}")
        if not isinstance(self.provenance_ref, str) or not self.provenance_ref.strip():
            raise ValueError(f"provenance_ref must be non-empty string, got {self.provenance_ref!r}")
        if self.predecessor_record_id is not None:
            if not isinstance(self.predecessor_record_id, str) or not self.predecessor_record_id.strip():
                raise ValueError("predecessor_record_id must be non-empty string when provided")

        object.__setattr__(
            self,
            "established_time",
            validate_and_normalize_timestamp(self.established_time, "established_time"),
        )
        object.__setattr__(
            self,
            "available_time",
            validate_and_normalize_timestamp(self.available_time, "available_time"),
        )


@dataclass(frozen=True)
class ProposedFeedCoverageRecord:
    """Authoritative market-data feed completeness certification record."""
    record_id: str
    schema_version: str
    issuer_id: str
    feed_id: str
    sequence_domain: SequenceDomain
    timeframe: str
    confirmation_config_id: str
    covered_interval_start: datetime
    covered_interval_end: datetime
    status: CoverageStatus
    issued_time: datetime
    available_time: datetime
    revision_seq: int = 1
    supersedes_record_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id.strip():
            raise ValueError(f"record_id must be non-empty string, got {self.record_id!r}")
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise ValueError(f"schema_version must be non-empty string, got {self.schema_version!r}")
        if not isinstance(self.issuer_id, str) or not self.issuer_id.strip():
            raise ValueError(f"issuer_id must be non-empty string, got {self.issuer_id!r}")
        if not isinstance(self.feed_id, str) or not self.feed_id.strip():
            raise ValueError(f"feed_id must be non-empty string, got {self.feed_id!r}")
        if not isinstance(self.sequence_domain, SequenceDomain):
            raise TypeError(f"sequence_domain must be SequenceDomain instance, got {type(self.sequence_domain).__name__}")
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise ValueError(f"timeframe must be non-empty string, got {self.timeframe!r}")
        if not isinstance(self.confirmation_config_id, str) or not self.confirmation_config_id.strip():
            raise ValueError(f"confirmation_config_id must be non-empty string, got {self.confirmation_config_id!r}")
        if not isinstance(self.status, CoverageStatus):
            raise TypeError(f"status must be CoverageStatus enum, got {type(self.status).__name__}")
        if not isinstance(self.revision_seq, int) or self.revision_seq < 1:
            raise ValueError(f"revision_seq must be positive integer >= 1, got {self.revision_seq!r}")
        if self.supersedes_record_id is not None:
            if not isinstance(self.supersedes_record_id, str) or not self.supersedes_record_id.strip():
                raise ValueError("supersedes_record_id must be non-empty string when provided")

        object.__setattr__(
            self,
            "covered_interval_start",
            validate_and_normalize_timestamp(self.covered_interval_start, "covered_interval_start"),
        )
        object.__setattr__(
            self,
            "covered_interval_end",
            validate_and_normalize_timestamp(self.covered_interval_end, "covered_interval_end"),
        )
        object.__setattr__(
            self,
            "issued_time",
            validate_and_normalize_timestamp(self.issued_time, "issued_time"),
        )
        object.__setattr__(
            self,
            "available_time",
            validate_and_normalize_timestamp(self.available_time, "available_time"),
        )

        if self.covered_interval_start > self.covered_interval_end:
            raise ValueError(
                f"covered_interval_start ({self.covered_interval_start.isoformat()}) "
                f"cannot be after covered_interval_end ({self.covered_interval_end.isoformat()})"
            )
        if self.issued_time > self.available_time:
            raise ValueError(
                f"issued_time ({self.issued_time.isoformat()}) "
                f"cannot be after available_time ({self.available_time.isoformat()})"
            )


@dataclass(frozen=True)
class AuthorityDiagnosticEntry:
    """Immutable audit entry capturing a specific validation diagnostic."""
    entity_key: str
    diagnostic_reason: AuthorityDiagnosticReason
    message: str


@dataclass(frozen=True)
class AuthorityBuildResult:
    """Immutable outcome of offline authority preprocessing.

    Enforces deep immutability by wrapping mapping fields in MappingProxyType.
    """
    resolved_coverage_status: CoverageStatus
    resolved_usage_statuses: Mapping[StableLevelId, UsageEvidenceStatus]
    diagnostics: Tuple[AuthorityDiagnosticEntry, ...]
    authoritative_coverage_record: Optional[ProposedFeedCoverageRecord] = None
    authoritative_usage_records: Mapping[StableLevelId, ProposedUsageEvidenceRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resolved_usage_statuses",
            MappingProxyType(dict(self.resolved_usage_statuses)),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(self.diagnostics),
        )
        object.__setattr__(
            self,
            "authoritative_usage_records",
            MappingProxyType(dict(self.authoritative_usage_records)),
        )
