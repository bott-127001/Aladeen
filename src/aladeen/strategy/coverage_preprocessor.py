"""CoveragePreprocessor — Pure in-memory feed coverage validation preprocessor.

Scope & Design Boundary:
-------------------------
- Pure in-memory validation of feed coverage certification records.
- Implements Steps 1-5 of the Milestone 34 preprocessing pipeline for coverage.
- Admissibility check precedes duplicate grouping to prevent poisoning from untrusted/out-of-scope records.
- Conflicting admissible identities fail closed as UNCERTAIN on the target scope.
- Link validity check precedes fork detection to prevent invalid links from creating false forks.
- Recursive ancestor chain validation back to root.
- Restricts interval uncertainty to intersection with the required interval.
- Canonical future diagnostics and idempotent diagnostic deduplication.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .activation_types import CoverageStatus, SequenceDomain
from .authority_types import (
    AuthorityDiagnosticEntry,
    AuthorityDiagnosticReason,
    ProposedFeedCoverageRecord,
    TrustConfiguration,
)
from .types import validate_and_normalize_timestamp


class CoveragePreprocessor:
    """Preprocesses and resolves authoritative feed coverage certifications."""

    def __init__(self, trust_config: TrustConfiguration) -> None:
        self._trust_config = trust_config

    def process(
        self,
        coverage_records: Sequence[ProposedFeedCoverageRecord],
        evaluation_time: datetime,
        target_feed_id: str,
        target_sequence_domain: SequenceDomain,
        target_timeframe: str,
        target_confirmation_config_id: str,
        required_interval_start: datetime,
        required_interval_end: datetime,
    ) -> Tuple[CoverageStatus, Optional[ProposedFeedCoverageRecord], Tuple[AuthorityDiagnosticEntry, ...]]:
        """Execute Steps 1-5 of coverage preprocessing."""
        eval_time = validate_and_normalize_timestamp(evaluation_time, "evaluation_time")
        req_start = validate_and_normalize_timestamp(required_interval_start, "required_interval_start")
        req_end = validate_and_normalize_timestamp(required_interval_end, "required_interval_end")

        if req_start > req_end:
            raise ValueError(
                f"required_interval_start ({req_start.isoformat()}) "
                f"cannot be after required_interval_end ({req_end.isoformat()})"
            )
        if req_end > eval_time:
            raise ValueError(
                f"required_interval_end ({req_end.isoformat()}) "
                f"cannot exceed evaluation_time ({eval_time.isoformat()})"
            )

        diagnostics: List[AuthorityDiagnosticEntry] = []

        # Step 1: Availability filter with order-invariant grouped future diagnostics
        future_by_id: Dict[str, List[ProposedFeedCoverageRecord]] = {}
        visible_coverage: List[ProposedFeedCoverageRecord] = []

        for cov in coverage_records:
            if cov.available_time > eval_time:
                future_by_id.setdefault(cov.record_id, []).append(cov)
            else:
                visible_coverage.append(cov)

        for rid in sorted(future_by_id.keys()):
            group = future_by_id[rid]
            min_avail = min(c.available_time for c in group)
            diagnostics.append(
                AuthorityDiagnosticEntry(
                    entity_key=rid,
                    diagnostic_reason=AuthorityDiagnosticReason.RECORD_NOT_YET_AVAILABLE,
                    message=f"Coverage record {rid} available at {min_avail.isoformat()} > eval_time {eval_time.isoformat()}",
                )
            )

        # Step 2: Admissibility validation precedes duplicate grouping
        admissible_records: List[ProposedFeedCoverageRecord] = []
        for cov in visible_coverage:
            rid = cov.record_id
            if cov.schema_version != "v1":
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.INVALID_SCHEMA_VERSION,
                        message=f"Unsupported schema version: {cov.schema_version}",
                    )
                )
                continue

            if cov.issuer_id not in self._trust_config.trusted_coverage_issuers:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.ISSUER_NOT_TRUSTED,
                        message=f"Coverage issuer {cov.issuer_id} not in trusted coverage issuers",
                    )
                )
                continue

            if cov.feed_id != target_feed_id:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.SCOPE_MISMATCH_FEED,
                        message=f"Feed mismatch: {cov.feed_id} != {target_feed_id}",
                    )
                )
                continue

            if cov.sequence_domain != target_sequence_domain:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.SCOPE_MISMATCH_RUN,
                        message=f"Sequence domain mismatch: {cov.sequence_domain} != {target_sequence_domain}",
                    )
                )
                continue

            if cov.timeframe != target_timeframe:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.SCOPE_MISMATCH_TIMEFRAME,
                        message=f"Timeframe mismatch: {cov.timeframe} != {target_timeframe}",
                    )
                )
                continue

            if cov.confirmation_config_id != target_confirmation_config_id:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.SCOPE_MISMATCH_CONFIG,
                        message=f"Config mismatch: {cov.confirmation_config_id} != {target_confirmation_config_id}",
                    )
                )
                continue

            admissible_records.append(cov)

        # Duplicate grouping on admissible trusted in-scope records
        coverage_by_id: Dict[str, List[ProposedFeedCoverageRecord]] = {}
        for cov in admissible_records:
            coverage_by_id.setdefault(cov.record_id, []).append(cov)

        has_scope_conflicting_identity = False
        coalesced_coverage: Dict[str, ProposedFeedCoverageRecord] = {}

        for rid in sorted(coverage_by_id.keys()):
            group = coverage_by_id[rid]
            if any(c != group[0] for c in group[1:]):
                has_scope_conflicting_identity = True
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.CONFLICTING_IDENTITY,
                        message=f"Coverage record {rid} has conflicting payloads across duplicates",
                    )
                )
                continue
            coalesced_coverage[rid] = group[0]

        # Step 3: Complete Predecessor Chain Validation & Fork Rejection
        # Finding 3: Validate link validity before adding to claimed_predecessors
        claimed_predecessors: Dict[str, List[ProposedFeedCoverageRecord]] = {}
        for rid, cov in coalesced_coverage.items():
            pred_id = cov.supersedes_record_id
            if pred_id:
                pred = coalesced_coverage.get(pred_id)
                if pred is None:
                    continue
                if (
                    cov.feed_id != pred.feed_id
                    or cov.sequence_domain != pred.sequence_domain
                    or cov.timeframe != pred.timeframe
                    or cov.confirmation_config_id != pred.confirmation_config_id
                    or cov.issuer_id != pred.issuer_id
                ):
                    continue
                if cov.revision_seq <= pred.revision_seq:
                    continue
                claimed_predecessors.setdefault(pred_id, []).append(cov)

        forked_predecessors: Set[str] = set()
        for pred_id, claimants in claimed_predecessors.items():
            if len(claimants) > 1:
                first_payload = (
                    claimants[0].status,
                    claimants[0].covered_interval_start,
                    claimants[0].covered_interval_end,
                )
                if any(
                    (c.status, c.covered_interval_start, c.covered_interval_end) != first_payload
                    for c in claimants[1:]
                ):
                    forked_predecessors.add(pred_id)
                    for c in claimants:
                        diagnostics.append(
                            AuthorityDiagnosticEntry(
                                entity_key=c.record_id,
                                diagnostic_reason=AuthorityDiagnosticReason.AMBIGUOUS_FORK,
                                message=f"Ambiguous fork claiming predecessor {pred_id}",
                            )
                        )

        valid_coverage_ids: Set[str] = set()
        superseded_coverage_ids: Set[str] = set()
        has_scope_wide_anomaly = bool(forked_predecessors) or has_scope_conflicting_identity

        def validate_coverage_chain(
            rec: ProposedFeedCoverageRecord,
        ) -> Tuple[bool, Optional[AuthorityDiagnosticReason], Optional[str]]:
            visited: Set[str] = {rec.record_id}
            curr = rec
            while curr.supersedes_record_id is not None:
                p_id = curr.supersedes_record_id
                if p_id in visited:
                    return False, AuthorityDiagnosticReason.CYCLIC_PREDECESSOR_LINK, f"Cyclic predecessor chain detected involving {p_id}"
                visited.add(p_id)

                if p_id in forked_predecessors:
                    return False, AuthorityDiagnosticReason.AMBIGUOUS_FORK, f"Ancestor {p_id} has ambiguous forks"

                pred = coalesced_coverage.get(p_id)
                if pred is None:
                    return False, AuthorityDiagnosticReason.UNKNOWN_PREDECESSOR, f"Predecessor {p_id} unknown or unavailable at {eval_time.isoformat()}"

                if (
                    curr.feed_id != pred.feed_id
                    or curr.sequence_domain != pred.sequence_domain
                    or curr.timeframe != pred.timeframe
                    or curr.confirmation_config_id != pred.confirmation_config_id
                    or curr.issuer_id != pred.issuer_id
                ):
                    return False, AuthorityDiagnosticReason.WRONG_SCOPE_SUPERSEDED, f"Successor {curr.record_id} scope mismatches predecessor {p_id}"

                if curr.revision_seq <= pred.revision_seq:
                    return False, AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION, f"Successor revision {curr.revision_seq} <= predecessor {pred.revision_seq}"

                curr = pred
            return True, None, None

        for rid in sorted(coalesced_coverage.keys()):
            cov = coalesced_coverage[rid]
            is_valid, reason, msg = validate_coverage_chain(cov)
            if is_valid:
                valid_coverage_ids.add(rid)
            else:
                if reason == AuthorityDiagnosticReason.CYCLIC_PREDECESSOR_LINK:
                    has_scope_wide_anomaly = True
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=reason or AuthorityDiagnosticReason.INVALID_ANCESTOR,
                        message=msg or f"Invalid ancestor chain for {rid}",
                    )
                )

        for rid in sorted(valid_coverage_ids):
            cov = coalesced_coverage[rid]
            curr_pred_id = cov.supersedes_record_id
            while curr_pred_id and curr_pred_id in valid_coverage_ids:
                superseded_coverage_ids.add(curr_pred_id)
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=curr_pred_id,
                        diagnostic_reason=AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION,
                        message=f"Predecessor {curr_pred_id} superseded by validated revision {rid}",
                    )
                )
                curr_pred_id = coalesced_coverage[curr_pred_id].supersedes_record_id

        active_coverage = [
            coalesced_coverage[rid]
            for rid in sorted(valid_coverage_ids)
            if rid not in superseded_coverage_ids
        ]

        # Step 4: Conflict Resolution & Relevant Interval Uncertainty
        has_intersecting_conflict = False
        has_relevant_uncertainty = has_scope_wide_anomaly

        for i, c1 in enumerate(active_coverage):
            if c1.status == CoverageStatus.UNCERTAIN:
                overlap_req_start = max(c1.covered_interval_start, req_start)
                overlap_req_end = min(c1.covered_interval_end, req_end)
                if overlap_req_start <= overlap_req_end:
                    has_relevant_uncertainty = True

            for j in range(i + 1, len(active_coverage)):
                c2 = active_coverage[j]
                overlap_start = max(c1.covered_interval_start, c2.covered_interval_start)
                overlap_end = min(c1.covered_interval_end, c2.covered_interval_end)
                if overlap_start <= overlap_end:
                    if c1.status != c2.status:
                        req_overlap_start = max(overlap_start, req_start)
                        req_overlap_end = min(overlap_end, req_end)
                        if req_overlap_start <= req_overlap_end:
                            has_intersecting_conflict = True
                            diagnostics.append(
                                AuthorityDiagnosticEntry(
                                    entity_key=f"{c1.record_id}:{c2.record_id}",
                                    diagnostic_reason=AuthorityDiagnosticReason.INTERSECTING_CONFLICT,
                                    message=f"Conflicting statuses ({c1.status} vs {c2.status}) intersect required interval",
                                )
                            )

        # Step 5: Independent Interval Coverage Evaluation
        resolved_cov_status = CoverageStatus.INCOMPLETE
        authoritative_cov_rec: Optional[ProposedFeedCoverageRecord] = None

        if has_intersecting_conflict or has_relevant_uncertainty or has_scope_conflicting_identity:
            resolved_cov_status = CoverageStatus.UNCERTAIN
        else:
            covering_candidates = [
                cov
                for cov in active_coverage
                if cov.status == CoverageStatus.COMPLETE
                and cov.covered_interval_start <= req_start
                and cov.covered_interval_end >= req_end
            ]

            if covering_candidates:
                covering_candidates.sort(
                    key=lambda c: (c.revision_seq, c.available_time.isoformat(), c.record_id),
                    reverse=True,
                )
                authoritative_cov_rec = covering_candidates[0]
                resolved_cov_status = CoverageStatus.COMPLETE
            else:
                resolved_cov_status = CoverageStatus.INCOMPLETE

        # Idempotent diagnostic deduplication and canonical sorting
        unique_diags: Dict[Tuple[str, str, str], AuthorityDiagnosticEntry] = {}
        for d in diagnostics:
            key = (d.entity_key, d.diagnostic_reason.value, d.message)
            if key not in unique_diags:
                unique_diags[key] = d
        sorted_diags = sorted(unique_diags.values(), key=lambda d: (d.entity_key, d.diagnostic_reason.value, d.message))

        return resolved_cov_status, authoritative_cov_rec, tuple(sorted_diags)
