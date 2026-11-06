"""AuthorityContextBuilder — Pure in-memory offline authority preprocessor.

Scope & Design Boundary:
-------------------------
- Pure in-memory validation of usage evidence records and feed coverage records.
- Enforces strict 6-step preprocessing pipeline compliant with Milestone 34 specification.
- Zero database writes, zero filesystem IO, zero live broker calls.
- Deeply immutable results with MappingProxyType and defensive tuple freezing.
- Maps resolved authority into existing accepted MatchingContext and SourceMemberReference.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
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
        self._trust_config = trust_config if trust_config is not None else TrustConfiguration()

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

        # =========================================================================
        # PART A: FEED COVERAGE VALIDATION
        # =========================================================================

        # Step 1: Availability filter
        visible_coverage: List[ProposedFeedCoverageRecord] = []
        for cov in coverage_records:
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

        # Step 2: Schema, Issuer, Scope & Duplicate-ID Validation (Order-Insensitive Grouping)
        coverage_by_id: Dict[str, List[ProposedFeedCoverageRecord]] = {}
        for cov in visible_coverage:
            coverage_by_id.setdefault(cov.record_id, []).append(cov)

        coalesced_coverage: Dict[str, ProposedFeedCoverageRecord] = {}

        for rid in sorted(coverage_by_id.keys()):
            group = coverage_by_id[rid]
            # Check for conflicting payloads under identical record_id
            if any(c != group[0] for c in group[1:]):
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.CONFLICTING_IDENTITY,
                        message=f"Coverage record {rid} has conflicting payloads across duplicates",
                    )
                )
                continue

            # Identical duplicates coalesce into single representative
            cov = group[0]

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

        # Step 3: Complete Predecessor Chain Validation & Supersession
        # Detect forks across all coalesced coverage records
        claimed_predecessors: Dict[str, List[ProposedFeedCoverageRecord]] = {}
        for rid, cov in coalesced_coverage.items():
            if cov.supersedes_record_id:
                claimed_predecessors.setdefault(cov.supersedes_record_id, []).append(cov)

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

        # Validate complete ancestor chains for all records
        valid_coverage_ids: Set[str] = set()
        invalid_coverage_ids: Set[str] = set()
        superseded_coverage_ids: Set[str] = set()
        has_scope_wide_anomaly = bool(forked_predecessors)

        def validate_coverage_chain(
            rec: ProposedFeedCoverageRecord,
        ) -> Tuple[bool, Optional[AuthorityDiagnosticReason], Optional[str]]:
            """Recursively validates entire ancestor chain back to root."""
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
                invalid_coverage_ids.add(rid)
                if reason == AuthorityDiagnosticReason.CYCLIC_PREDECESSOR_LINK:
                    has_scope_wide_anomaly = True
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=reason or AuthorityDiagnosticReason.INVALID_ANCESTOR,
                        message=msg or f"Invalid ancestor chain for {rid}",
                    )
                )

        # Valid successors retire their validated predecessors
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
            # Check if an UNCERTAIN certificate intersects the required interval
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
                        # Conflict intersects required interval?
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

        if has_intersecting_conflict or has_relevant_uncertainty:
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

        # =========================================================================
        # PART B: PHYSICAL LEVEL USAGE VALIDATION
        # =========================================================================

        # Step 1: Temporal invariants (both available_time and established_time <= eval_time)
        visible_usage: List[ProposedUsageEvidenceRecord] = []
        for usg in usage_records:
            if usg.available_time > eval_time:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=usg.record_id,
                        diagnostic_reason=AuthorityDiagnosticReason.RECORD_NOT_YET_AVAILABLE,
                        message=f"Usage record {usg.record_id} available at {usg.available_time.isoformat()} > eval_time {eval_time.isoformat()}",
                    )
                )
            elif usg.established_time > eval_time:
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=usg.record_id,
                        diagnostic_reason=AuthorityDiagnosticReason.RECORD_NOT_YET_ESTABLISHED,
                        message=f"Usage record {usg.record_id} established at {usg.established_time.isoformat()} > eval_time {eval_time.isoformat()}",
                    )
                )
            else:
                visible_usage.append(usg)

        # Step 2: Schema, Issuer & Duplicate-ID Validation (Order-Insensitive Grouping)
        usage_by_id: Dict[str, List[ProposedUsageEvidenceRecord]] = {}
        for usg in visible_usage:
            usage_by_id.setdefault(usg.record_id, []).append(usg)

        coalesced_usage: Dict[str, ProposedUsageEvidenceRecord] = {}

        for rid in sorted(usage_by_id.keys()):
            group = usage_by_id[rid]
            if any(u != group[0] for u in group[1:]):
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=AuthorityDiagnosticReason.CONFLICTING_IDENTITY,
                        message=f"Usage record {rid} has conflicting payloads across duplicates",
                    )
                )
                continue

            usg = group[0]

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

        # Step 3: Complete Usage Ancestor Chain Resolution & Terminal Usage Preservation
        claimed_usage_predecessors: Dict[str, List[ProposedUsageEvidenceRecord]] = {}
        for rid, u in coalesced_usage.items():
            if u.predecessor_record_id:
                claimed_usage_predecessors.setdefault(u.predecessor_record_id, []).append(u)

        forked_usage_predecessors: Set[str] = set()
        for pred_id, claimants in claimed_usage_predecessors.items():
            if len(claimants) > 1:
                first_st = claimants[0].status
                if any(c.status != first_st for c in claimants[1:]):
                    forked_usage_predecessors.add(pred_id)
                    for c in claimants:
                        diagnostics.append(
                            AuthorityDiagnosticEntry(
                                entity_key=c.record_id,
                                diagnostic_reason=AuthorityDiagnosticReason.AMBIGUOUS_FORK,
                                message=f"Ambiguous usage fork claiming predecessor {pred_id}",
                            )
                        )

        def validate_usage_chain(
            rec: ProposedUsageEvidenceRecord,
        ) -> Tuple[bool, Optional[AuthorityDiagnosticReason], Optional[str], bool]:
            """Recursively validates usage chain and tracks if any ancestor is USED."""
            visited: Set[str] = {rec.record_id}
            curr = rec
            has_used_ancestor = (rec.status == UsageEvidenceStatus.USED)

            while curr.predecessor_record_id is not None:
                p_id = curr.predecessor_record_id
                if p_id in visited:
                    return False, AuthorityDiagnosticReason.CYCLIC_PREDECESSOR_LINK, f"Cyclic usage chain involving {p_id}", False
                visited.add(p_id)

                if p_id in forked_usage_predecessors:
                    return False, AuthorityDiagnosticReason.AMBIGUOUS_FORK, f"Usage ancestor {p_id} has ambiguous forks", False

                pred = coalesced_usage.get(p_id)
                if pred is None:
                    return False, AuthorityDiagnosticReason.UNKNOWN_PREDECESSOR, f"Usage predecessor {p_id} unknown or unavailable at {eval_time.isoformat()}", False

                if pred.level_id != curr.level_id:
                    return False, AuthorityDiagnosticReason.WRONG_SCOPE_SUPERSEDED, f"Usage level {curr.level_id} mismatches predecessor {pred.level_id}", False

                if curr.established_time < pred.established_time:
                    return False, AuthorityDiagnosticReason.INVALID_USAGE_TRANSITION, f"Usage established {curr.established_time.isoformat()} < predecessor {pred.established_time.isoformat()}", False

                if pred.status == UsageEvidenceStatus.USED:
                    has_used_ancestor = True

                curr = pred

            # Multi-hop terminal preservation: If any ancestor in chain was USED, descendant cannot reset to UNUSED
            if has_used_ancestor and rec.status == UsageEvidenceStatus.UNUSED:
                return False, AuthorityDiagnosticReason.USAGE_USED_TERMINAL, f"Level {rec.level_id} has USED in ancestry; cannot reset to UNUSED in {rec.record_id}", True

            return True, None, None, has_used_ancestor

        valid_usage_ids: Set[str] = set()
        invalid_usage_ids: Set[str] = set()
        superseded_usage_ids: Set[str] = set()
        levels_with_terminal_used: Set[StableLevelId] = set()
        authoritative_used_by_level: Dict[StableLevelId, ProposedUsageEvidenceRecord] = {}

        for rid in sorted(coalesced_usage.keys()):
            u = coalesced_usage[rid]
            is_valid, reason, msg, has_used = validate_usage_chain(u)
            if has_used:
                levels_with_terminal_used.add(u.level_id)
                if u.status == UsageEvidenceStatus.USED:
                    authoritative_used_by_level[u.level_id] = u

            if is_valid:
                valid_usage_ids.add(rid)
            else:
                invalid_usage_ids.add(rid)
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=rid,
                        diagnostic_reason=reason or AuthorityDiagnosticReason.INVALID_ANCESTOR,
                        message=msg or f"Invalid ancestor chain for usage {rid}",
                    )
                )

        # Valid successors supersede their predecessors
        for rid in sorted(valid_usage_ids):
            u = coalesced_usage[rid]
            curr_pred_id = u.predecessor_record_id
            while curr_pred_id and curr_pred_id in valid_usage_ids:
                superseded_usage_ids.add(curr_pred_id)
                diagnostics.append(
                    AuthorityDiagnosticEntry(
                        entity_key=curr_pred_id,
                        diagnostic_reason=AuthorityDiagnosticReason.SUPERSEDED_BY_VALID_REVISION,
                        message=f"Usage predecessor {curr_pred_id} superseded by validated successor {rid}",
                    )
                )
                curr_pred_id = coalesced_usage[curr_pred_id].predecessor_record_id

        # Group remaining active records by level
        active_usage_by_level: Dict[StableLevelId, List[ProposedUsageEvidenceRecord]] = {}
        for rid in sorted(valid_usage_ids):
            if rid not in superseded_usage_ids:
                u = coalesced_usage[rid]
                active_usage_by_level.setdefault(u.level_id, []).append(u)

        resolved_usage: Dict[StableLevelId, UsageEvidenceStatus] = {}
        authoritative_usage_map: Dict[StableLevelId, ProposedUsageEvidenceRecord] = {}

        all_target_levels = sorted(
            list(set(physical_levels) | set(active_usage_by_level.keys()) | levels_with_terminal_used),
            key=lambda l: (
                l.symbol_feed_id,
                l.source_timeframe,
                l.source_open_time.isoformat(),
                str(l.side),
            ),
        )

        for lvl in all_target_levels:
            active_for_lvl = active_usage_by_level.get(lvl, [])

            # Check for unlinked contradictory assertions among active records first
            if active_for_lvl:
                statuses = {r.status for r in active_for_lvl}
                if len(statuses) > 1:
                    # Contradictory unlinked assertions -> UNKNOWN
                    resolved_usage[lvl] = UsageEvidenceStatus.UNKNOWN
                    diagnostics.append(
                        AuthorityDiagnosticEntry(
                            entity_key=str(lvl),
                            diagnostic_reason=AuthorityDiagnosticReason.CONTRADICTORY_ASSERTION,
                            message=f"Contradictory unlinked usage assertions for level {lvl}: {statuses}",
                        )
                    )
                    continue

            # 1. Multi-hop terminal USED fact: If level was ever USED without unresolved contradiction, status is permanently USED
            if lvl in levels_with_terminal_used:
                resolved_usage[lvl] = UsageEvidenceStatus.USED
                if lvl in authoritative_used_by_level:
                    authoritative_usage_map[lvl] = authoritative_used_by_level[lvl]
                continue

            if not active_for_lvl:
                # No valid record exists -> UNKNOWN (strictly no negative proof)
                resolved_usage[lvl] = UsageEvidenceStatus.UNKNOWN
                continue

            final_st = list(statuses)[0]
            resolved_usage[lvl] = final_st
            active_for_lvl.sort(
                key=lambda r: (r.established_time.isoformat(), r.available_time.isoformat(), r.record_id),
                reverse=True,
            )
            authoritative_usage_map[lvl] = active_for_lvl[0]

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
        """Map resolved authority into accepted MatchingContext and updated member references.

        Preserves existing accepted MatchingContext and SourceMemberReference structures.
        Does not rewrite historical activation records or manufacture synthetic True mappings.
        """
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

        # Source resolution mapping: do not manufacture a True mapping
        src_res: Dict[str, bool] = {}
        if source_resolution_status is not None:
            src_res = dict(source_resolution_status)

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
