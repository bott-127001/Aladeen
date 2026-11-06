"""Domain models, enums, and immutable value objects for Offline Authority Propagation.

Scope & Design Boundary:
-------------------------
- Pure mathematical, typing, and domain modeling for offline authority inputs (usage, coverage, trust).
- Zero database writes, zero filesystem ledger operations, zero network/broker interaction.
- Strictly immutable frozen dataclasses and deterministic diagnostic classifications.
- Compliant with Milestone 34 specification (docs/requirements/offline-authority-propagation.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
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
    CONFLICTING_IDENTITY = "CONFLICTING_IDENTITY"
    SCOPE_MISMATCH_FEED = "SCOPE_MISMATCH_FEED"
    SCOPE_MISMATCH_RUN = "SCOPE_MISMATCH_RUN"
    SCOPE_MISMATCH_TIMEFRAME = "SCOPE_MISMATCH_TIMEFRAME"
    SCOPE_MISMATCH_CONFIG = "SCOPE_MISMATCH_CONFIG"
    UNKNOWN_PREDECESSOR = "UNKNOWN_PREDECESSOR"
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
    """Explicitly declared trust boundaries for offline authority sources."""
    trusted_usage_issuers: Tuple[str, ...] = ("UPSTREAM_TRADE_LEDGER_OFFLINE", "FIXTURE_HARNESS_USAGE")
    trusted_coverage_issuers: Tuple[str, ...] = ("OFFLINE_FEED_AUDITOR_v1", "FIXTURE_HARNESS_COVERAGE")


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


@dataclass(frozen=True)
class AuthorityDiagnosticEntry:
    """Immutable audit entry capturing a specific validation diagnostic."""
    entity_key: str
    diagnostic_reason: AuthorityDiagnosticReason
    message: str


@dataclass(frozen=True)
class AuthorityBuildResult:
    """Immutable outcome of offline authority preprocessing."""
    resolved_coverage_status: CoverageStatus
    resolved_usage_statuses: Mapping[StableLevelId, UsageEvidenceStatus]
    diagnostics: Tuple[AuthorityDiagnosticEntry, ...]
    authoritative_coverage_record: Optional[ProposedFeedCoverageRecord] = None
    authoritative_usage_records: Mapping[StableLevelId, ProposedUsageEvidenceRecord] = field(default_factory=dict)
