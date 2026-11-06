"""AuthorityContextBuilder — Pure in-memory offline authority preprocessor.

Scope & Design Boundary:
-------------------------
- Pure in-memory validation of usage evidence records and feed coverage records.
- Enforces strict 6-step preprocessing pipeline compliant with Milestone 34 specification.
- Zero database writes, zero filesystem IO, zero live broker calls.
- Maps resolved authority into existing accepted MatchingContext and SourceMemberReference.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .activation_types import (
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
)
from .authority_types import (
    AuthorityBuildResult,
    AuthorityDiagnosticEntry,
    AuthorityDiagnosticReason,
    ProposedFeedCoverageRecord,
    ProposedUsageEvidenceRecord,
    TrustConfiguration,
)
from .confirmation_pair_matcher import MatchingContext
from .tjl_types import StableLevelId
from .types import validate_and_normalize_timestamp


class AuthorityContextBuilder:
    """Preprocesses offline authority records and builds validated MatchingContext."""

    def __init__(self, trust_config: Optional[TrustConfiguration] = None) -> None:
        self._trust_config = trust_config or TrustConfiguration()

    @property
    def trust_config(self) -> TrustConfiguration:
        return self._trust_config

    def validate_and_build(
        self,
        usage_records: Sequence[ProposedUsageEvidenceRecord],
        coverage_records: Sequence[ProposedFeedCoverageRecord],
        evaluation_time: datetime,
        target_feed_id: str,
        target_sequence_domain: SequenceDomain,
        target_timeframe: str,
        target_confirmation_config_id: str,
        required_interval_start: datetime,
        required_interval_end: datetime,
        physical_levels: Sequence[StableLevelId] = (),
    ) -> AuthorityBuildResult:
        """Execute the 6-step authority preprocessing pipeline."""
        eval_time = validate_and_normalize_timestamp(evaluation_time, "evaluation_time")
        req_start = validate_and_normalize_timestamp(required_interval_start, "required_interval_start")
        req_end = validate_and_normalize_timestamp(required_interval_end, "required_interval_end")

        diagnostics: List[AuthorityDiagnosticEntry] = []

        # =========================================================================
        # PART A: FEED COVERAGE VALIDATION
        # =========================================================================
        # Deterministic stable ordering of input records (guarantees permutation invariance)
        sorted_coverage_inputs = sorted(
            coverage_records,
            key=lambda c: (c.record_id, c.revision_seq, c.available_time.isoformat()),
        )

        # Step 1: Availability filter
        visible_coverage: List[ProposedFeedCoverageRecord] = []
        for cov in sorted_coverage_inputs:
            if cov.available_time > eval_time:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=cov.record_id,
                        diagnostic_reason=AuthorityDiagnosticReason.RECORD_NOT_YET_AVAILABLE,
                        message=f"Coverage record {cov.record_id} available at {cov.available_time.isoformat()} > eval_time {eval_time.isoformat()}",
                    )
                )
            else:
                visible_coverage.append(cov)

        # Step 2: Schema, Issuer, Scope & Identical-Duplicate Coalescence
        coalesced_coverage: Dict[str, ProposedFeedCoverageRecord] = {}
        conflicted_coverage_ids: Set[str] = set()

        for cov in visible_coverage:
            rid = cov.record_id
            if rid in conflicted_coverage_ids:
                continue

            if rid in coalesced_coverage:
                existing = coalesced_coverage[rid]
                if existing == cov:
                    # Identical duplicate: coalesce idempotently
                    continue
                else:
                    # Conflicting payload under identical ID
                    conflicted_coverage_ids.add(rid)
                    del coalesced_coverage[rid]
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=rid,
                            diagnostic_reason=AuthorityDiagnosticReason.CONFLICTING_IDENTITY,
                            message=f"Coverage record {rid} has conflicting payloads across duplicates",
                        )
                    )
                    continue

            # Schema validation
            if cov.schema_version != "v1":
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.INVALID_SCHEMA_VERSION,
                        message=f"Unsupported schema version: {cov.schema_version}",
                    )
                )
                continue

            # Issuer trust validation
            if cov.issuer_id not in self._trust_config.trusted_coverage_issuers:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.ISSUER_NOT_TRUSTED,
                        message=f"Coverage issuer {cov.issuer_id} not in trusted coverage issuers",
                    )
                )
                continue

            # Scope validation
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

            coalesced_coverage[rid] = cov

        # Step 3: Predecessor Validation & Supersession Resolution
        valid_coverage_records = dict(coalesced_coverage)
        superseded_coverage_ids: Set[str] = set()
        invalid_successor_ids: Set[str] = set()
        has_ambiguous_fork = False
        has_cyclic_chain = False

        # Detect forks: predecessors claimed by multiple successors
        claimed_predecessors: Dict[str, List[ProposedFeedCoverageRecord]] = {}
        for rid, cov in valid_coverage_records.items():
            if cov.supersedes_record_id:
                claimed_predecessors.setdefault(cov.supersedes_record_id, []).append(cov)

        for pred_id, claimants in claimed_predecessors.items():
            if len(claimants) > 1:
                # Multiple successors claim the same predecessor
                first_payload = (
                    claimants[0].status,
                    claimants[0].covered_interval_start,
                    claimants[0].covered_interval_end,
                )
                if any(
                    (c.status, c.covered_interval_start, c.covered_interval_end) != first_payload
                    for c in claimants[1:]
                ):
                    has_ambiguous_fork = True
                    for c in claimants:
                        invalid_successor_ids.add(c.record_id)
                        diagnostics.append(
                            AuthorityDiagnosticEntry(
                                entity_key=c.record_id,
                                diagnostic_reason=AuthorityDiagnosticReason.AMBIGUOUS_FORK,
                                message=f"Ambiguous fork claiming predecessor {pred_id}",
                            )
                        )

        # Validate replacement chains
        for rid, cov in list(valid_coverage_records.items()):
            if rid in invalid_successor_ids:
                continue

            if cov.supersedes_record_id:
                pred_id = cov.supersedes_record_id
                # a) Predecessor exists and is visible at evaluation boundary
                pred = coalesced_coverage.get(pred_id)
                if not pred or pred.available_time > eval_time:
                    invalid_successor_ids.add(rid)
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=rid,
                            diagnostic_reason=AuthorityDiagnosticReason.UNKNOWN_PREDECESSOR,
                            message=f"Predecessor {pred_id} unknown or unavailable at {eval_time.isoformat()}",
                        )
                    )
                    continue

                # b) Strict scope match between successor and predecessor
                if (
                    cov.feed_id != pred.feed_id
                    or cov.sequence_domain != pred.sequence_domain
                    or cov.timeframe != pred.timeframe
                    or cov.confirmation_config_id != pred.confirmation_config_id
                    or cov.issuer_id != pred.issuer_id
                ):
                    invalid_successor_ids.add(rid)
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=rid,
                            diagnostic_reason=AuthorityDiagnosticReason.WRONG_SCOPE_SUPERSEDED,
                            message=f"Successor scope mismatches predecessor {pred_id}",
                        )
                    )
                    continue

                # c) Strictly higher revision
                if cov.revision_seq <= pred.revision_seq:
                    invalid_successor_ids.add(rid)
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=rid,
                            diagnostic_reason=AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION,
                            message=f"Successor revision {cov.revision_seq} <= predecessor {pred.revision_seq}",
                        )
                    )
                    continue

                # d) Acyclic chain check
                visited = {rid}
                curr: Optional[ProposedFeedCoverageRecord] = pred
                is_cyclic = False
                while curr and curr.supersedes_record_id:
                    if curr.supersedes_record_id in visited:
                        is_cyclic = True
                        break
                    visited.add(curr.supersedes_record_id)
                    curr = coalesced_coverage.get(curr.supersedes_record_id)

                if is_cyclic:
                    has_cyclic_chain = True
                    invalid_successor_ids.add(rid)
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=rid,
                            diagnostic_reason=AuthorityDiagnosticReason.CYCLIC_PREDECESSOR_LINK,
                            message=f"Cyclic predecessor chain detected involving {rid}",
                        )
                    )
                    continue

                # All validation checks pass: successor replaces predecessor
                superseded_coverage_ids.add(pred_id)
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=pred_id,
                        diagnostic_reason=AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION,
                        message=f"Predecessor {pred_id} superseded by validated revision {rid}",
                    )
                )

        # Remove invalid successors and superseded predecessors
        active_coverage = [
            cov
            for rid, cov in valid_coverage_records.items()
            if rid not in invalid_successor_ids and rid not in superseded_coverage_ids
        ]

        # Step 4: Conflict Resolution among remaining active coverage
        has_intersecting_conflict = False
        has_uncertain_coverage = has_ambiguous_fork or has_cyclic_chain

        for i, c1 in enumerate(active_coverage):
            if c1.status == CoverageStatus.UNCERTAIN:
                has_uncertain_coverage = True
            for j in range(i + 1, len(active_coverage)):
                c2 = active_coverage[j]
                # Check if intervals overlap
                overlap_start = max(c1.covered_interval_start, c2.covered_interval_start)
                overlap_end = min(c1.covered_interval_end, c2.covered_interval_end)
                if overlap_start <= overlap_end:
                    # Overlap exists!
                    if c1.status != c2.status:
                        # Conflicting statuses on overlap!
                        # Does conflict intersect required interval [req_start, req_end]?
                        req_overlap_start = max(overlap_start, req_start)
                        req_overlap_end = min(overlap_end, req_end)
                        if req_overlap_start <= req_overlap_end:
                            # Intersecting conflict!
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

        if has_intersecting_conflict or has_uncertain_coverage:
            resolved_cov_status = CoverageStatus.UNCERTAIN
        else:
            # Test each active certificate independently
            covering_candidates = [
                cov
                for cov in active_coverage
                if cov.status == CoverageStatus.COMPLETE
                and cov.covered_interval_start <= req_start
                and cov.covered_interval_end >= req_end
            ]

            if covering_candidates:
                # Extent satisfied independently by at least one valid certificate!
                # If multiple candidates, select highest revision_seq then latest available_time
                covering_candidates.sort(
                    key=lambda c: (c.revision_seq, c.available_time.isoformat()),
                    reverse=True,
                )
                authoritative_cov_rec = covering_candidates[0]
                resolved_cov_status = CoverageStatus.COMPLETE
            else:
                resolved_cov_status = CoverageStatus.INCOMPLETE

        # =========================================================================
        # PART B: PHYSICAL LEVEL USAGE VALIDATION
        # =========================================================================
        sorted_usage_inputs = sorted(
            usage_records,
            key=lambda u: (u.record_id, u.established_time.isoformat(), u.available_time.isoformat()),
        )

        # Step 1: Availability filter
        visible_usage: List[ProposedUsageEvidenceRecord] = []
        for usg in sorted_usage_inputs:
            if usg.available_time > eval_time:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=usg.record_id,
                        diagnostic_reason=AuthorityDiagnosticReason.RECORD_NOT_YET_AVAILABLE,
                        message=f"Usage record {usg.record_id} available at {usg.available_time.isoformat()} > eval_time {eval_time.isoformat()}",
                    )
                )
            else:
                visible_usage.append(usg)

        # Step 2: Schema, Issuer & Identical-Duplicate Coalescence
        coalesced_usage: Dict[str, ProposedUsageEvidenceRecord] = {}
        conflicted_usage_ids: Set[str] = set()

        for usg in visible_usage:
            rid = usg.record_id
            if rid in conflicted_usage_ids:
                continue

            if rid in coalesced_usage:
                existing = coalesced_usage[rid]
                if existing == usg:
                    continue
                else:
                    conflicted_usage_ids.add(rid)
                    del coalesced_usage[rid]
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=rid,
                            diagnostic_reason=AuthorityDiagnosticReason.CONFLICTING_IDENTITY,
                            message=f"Usage record {rid} has conflicting payloads across duplicates",
                        )
                    )
                    continue

            if usg.schema_version != "v1":
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.INVALID_SCHEMA_VERSION,
                        message=f"Unsupported schema version: {usg.schema_version}",
                    )
                )
                continue

            if usg.issuer_id not in self._trust_config.trusted_usage_issuers:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.ISSUER_NOT_TRUSTED,
                        message=f"Usage issuer {usg.issuer_id} not in trusted usage issuers",
                    )
                )
                continue

            coalesced_usage[rid] = usg

        # Step 3: Group by StableLevelId and evaluate deterministic predecessor & causal transitions
        usage_by_level: Dict[StableLevelId, List[ProposedUsageEvidenceRecord]] = {}
        for usg in coalesced_usage.values():
            usage_by_level.setdefault(usg.level_id, []).append(usg)

        resolved_usage: Dict[StableLevelId, UsageEvidenceStatus] = {}
        authoritative_usage_map: Dict[StableLevelId, ProposedUsageEvidenceRecord] = {}

        # Evaluate target physical levels
        all_levels = sorted(
            list(set(physical_levels) | set(usage_by_level.keys())),
            key=lambda l: (
                l.symbol_feed_id,
                l.source_timeframe,
                l.source_open_time.isoformat(),
                str(l.side),
            ),
        )

        for lvl in all_levels:
            lvl_records = usage_by_level.get(lvl, [])
            if not lvl_records:
                # No record exists -> UNKNOWN (strictly no negative proof)
                resolved_usage[lvl] = UsageEvidenceStatus.UNKNOWN
                continue

            # Validate predecessor chains for usage records of this level
            valid_lvl_records: Dict[str, ProposedUsageEvidenceRecord] = {r.record_id: r for r in lvl_records}
            invalid_lvl_successors: Set[str] = set()
            superseded_lvl_records: Set[str] = set()

            # Detect forks claiming same predecessor
            claimed_usage_predecessors: Dict[str, List[ProposedUsageEvidenceRecord]] = {}
            for r in lvl_records:
                if r.predecessor_record_id:
                    claimed_usage_predecessors.setdefault(r.predecessor_record_id, []).append(r)

            for pred_id, claimants in claimed_usage_predecessors.items():
                if len(claimants) > 1:
                    first_st = claimants[0].status
                    if any(c.status != first_st for c in claimants[1:]):
                        for c in claimants:
                            invalid_lvl_successors.add(c.record_id)
                            diagnostics.append(
                                AuthorityDiagnosticEntry(
                                    entity_key=c.record_id,
                                    diagnostic_reason=AuthorityDiagnosticReason.AMBIGUOUS_FORK,
                                    message=f"Ambiguous usage fork claiming predecessor {pred_id}",
                                )
                            )

            for r in lvl_records:
                if r.record_id in invalid_lvl_successors:
                    continue

                if r.predecessor_record_id:
                    pred_id = r.predecessor_record_id
                    pred = coalesced_usage.get(pred_id)
                    if not pred or pred.available_time > eval_time:
                        invalid_lvl_successors.add(r.record_id)
                        diagnostics.append(
                            AuthorityDiagnosticEntry(
                                entity_key=r.record_id,
                                diagnostic_reason=AuthorityDiagnosticReason.UNKNOWN_PREDECESSOR,
                                message=f"Usage predecessor {pred_id} unknown or unavailable at {eval_time.isoformat()}",
                            )
                        )
                        continue

                    if pred.level_id != r.level_id:
                        invalid_lvl_successors.add(r.record_id)
                        diagnostics.append(
                            AuthorityDiagnosticEntry(
                                entity_key=r.record_id,
                                diagnostic_reason=AuthorityDiagnosticReason.WRONG_SCOPE_SUPERSEDED,
                                message=f"Usage successor level {r.level_id} mismatches predecessor level {pred.level_id}",
                            )
                        )
                        continue

                    if r.established_time < pred.established_time:
                        invalid_lvl_successors.add(r.record_id)
                        diagnostics.append(
                            AuthorityDiagnosticEntry(
                                entity_key=r.record_id,
                                diagnostic_reason=AuthorityDiagnosticReason.INVALID_USAGE_TRANSITION,
                                message=f"Usage successor established {r.established_time.isoformat()} < predecessor {pred.established_time.isoformat()}",
                            )
                        )
                        continue

                    # Acyclic check
                    vis = {r.record_id}
                    curr_u: Optional[ProposedUsageEvidenceRecord] = pred
                    is_cyclic = False
                    while curr_u and curr_u.predecessor_record_id:
                        if curr_u.predecessor_record_id in vis:
                            is_cyclic = True
                            break
                        vis.add(curr_u.predecessor_record_id)
                        curr_u = coalesced_usage.get(curr_u.predecessor_record_id)

                    if is_cyclic:
                        invalid_lvl_successors.add(r.record_id)
                        diagnostics.append(
                            AuthorityDiagnosticEntry(
                                entity_key=r.record_id,
                                diagnostic_reason=AuthorityDiagnosticReason.CYCLIC_PREDECESSOR_LINK,
                                message=f"Cyclic usage predecessor link detected involving {r.record_id}",
                            )
                        )
                        continue

                    # Terminal USED check: cannot transition USED -> UNUSED
                    if pred.status == UsageEvidenceStatus.USED and r.status == UsageEvidenceStatus.UNUSED:
                        invalid_lvl_successors.add(r.record_id)
                        diagnostics.append(
                            AuthorityDiagnosticEntry(
                                entity_key=r.record_id,
                                diagnostic_reason=AuthorityDiagnosticReason.USAGE_USED_TERMINAL,
                                message=f"Level {lvl} is USED; cannot reset to UNUSED in {r.record_id}",
                            )
                        )
                        continue

                    # Valid transition: predecessor superseded
                    superseded_lvl_records.add(pred_id)
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=pred_id,
                            diagnostic_reason=AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION,
                            message=f"Usage predecessor {pred_id} superseded by validated successor {r.record_id}",
                        )
                    )

            active_lvl_records = [
                r for r in lvl_records
                if r.record_id not in invalid_lvl_successors and r.record_id not in superseded_lvl_records
            ]

            if not active_lvl_records:
                # No valid active record -> UNKNOWN
                resolved_usage[lvl] = UsageEvidenceStatus.UNKNOWN
                continue

            # Check for contradictory simultaneous assertions among active records
            active_statuses = {r.status for r in active_lvl_records}
            if len(active_statuses) > 1:
                # Contradictory without valid causal sequence -> UNKNOWN
                resolved_usage[lvl] = UsageEvidenceStatus.UNKNOWN
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=str(lvl),
                        diagnostic_reason=AuthorityDiagnosticReason.CONTRADICTORY_ASSERTION,
                        message=f"Contradictory unlinked usage assertions for level {lvl}: {active_statuses}",
                    )
                )
            else:
                final_st = list(active_statuses)[0]
                resolved_usage[lvl] = final_st
                # Authoritative record is latest established/available
                active_lvl_records.sort(
                    key=lambda r: (r.established_time.isoformat(), r.available_time.isoformat()),
                    reverse=True,
                )
                authoritative_usage_map[lvl] = active_lvl_records[0]

        return AuthorityBuildResult(
            resolved_coverage_status=resolved_cov_status,
            resolved_usage_statuses=resolved_usage,
            diagnostics=tuple(diagnostics),
            authoritative_coverage_record=authoritative_cov_rec,
            authoritative_usage_records=authoritative_usage_map,
        )

    def build_matching_context(
        self,
        authority_result: AuthorityBuildResult,
        base_members: Mapping[str, SourceMemberReference],
        domain_session_id: str,
        revision_id: str,
        expected_price_basis: PriceBasis,
        expected_confirmation_config_id: str,
        matching_sequence_domain: SequenceDomain,
        evaluation_time: datetime,
        source_resolution_status: Optional[Mapping[str, bool]] = None,
    ) -> Tuple[MatchingContext, Dict[str, SourceMemberReference]]:
        """Map resolved authority into accepted MatchingContext and updated member references."""
        eval_time = validate_and_normalize_timestamp(evaluation_time, "evaluation_time")

        # Update member usage evidence status based on resolved physical level usage
        updated_members: Dict[str, SourceMemberReference] = {}
        for m_k, mem in base_members.items():
            lvl = mem.level_id
            resolved_st = authority_result.resolved_usage_statuses.get(lvl, UsageEvidenceStatus.UNKNOWN)
            updated_mem = SourceMemberReference(
                engine_id=mem.engine_id,
                symbol=mem.symbol,
                source_timeframe=mem.source_timeframe,
                set_id=mem.set_id,
                role=mem.role,
                side=mem.side,
                lower_edge=mem.lower_edge,
                upper_edge=mem.upper_edge,
                is_line=mem.is_line,
                direction=mem.direction,
                level_id=mem.level_id,
                eligibility_available_time=mem.eligibility_available_time,
                usage_evidence_status=resolved_st,
            )
            updated_members[m_k] = updated_mem

        # Source resolution mapping
        src_res: Dict[str, bool] = {}
        if source_resolution_status is not None:
            src_res = dict(source_resolution_status)
        else:
            # If not provided, omit to preserve UNKNOWN_SOURCE_RESOLUTION_AUTHORITY fail-closed
            pass

        ctx = MatchingContext(
            domain_session_id=domain_session_id,
            revision_id=revision_id,
            expected_price_basis=expected_price_basis,
            expected_confirmation_config_id=expected_confirmation_config_id,
            matching_sequence_domain=matching_sequence_domain,
            evaluation_time=eval_time,
            current_members=updated_members,
            source_resolution_status=src_res,
            coverage_status=authority_result.resolved_coverage_status,
        )

        return ctx, updated_members
