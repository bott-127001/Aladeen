"""Passive Offline Confirmation-to-Activation Matcher.

Scope & Design Boundary:
-------------------------
- Pure read-only offline matching layer.
- Associates completed confirmation evidence with eligible activation generations.
- Strictly passive: emits CandidateSetupRecord candidates.
- Zero winner selection, zero level usage consumption, zero signal publication,
  and zero state modification of activation engine or strategy checkpoints.
- Does not perform hidden arbitration; same source event may be associated with
  multiple eligible activations where the contract permits it.
- Explicit diagnostic results for all rejected, blocked, or uncertain associations.
- Strict authoritative gating: missing authority fails closed.
- Strict causal ordering: cross-domain bare integers are rejected; evaluation availability enforced.
- Batch consolidation validates conflicts, deduplicates identical evidence, and produces
  unique candidates with deterministic output sorting invariant to input permutations.
- Zero wall-clock dependence: evaluation time is an explicit required parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .activation_types import (
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    TIMEFRAME_CONFIRMATION_MAP,
    UsageEvidenceStatus,
    format_member_key,
)
from .confirmation_types import (
    BatchMatchResult,
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchResult,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    TouchSequenceEvidence,
    format_candidate_setup_key,
)
from .tjl_types import StableLevelId
from .types import Direction, validate_and_normalize_timestamp

TIMEFRAME_RANK_MAP: Mapping[str, int] = {
    "M1": 1,
    "M5": 2,
    "H1": 3,
}

ROLE_RANK_MAP: Mapping[str, int] = {
    "TJL2_A_PLUS": 1,
    "TJL2": 1,
    "TJL1": 2,
}


@dataclass(frozen=True)
class MatchingContext:
    """Authoritative evaluation context for confirmation matching operations.

    Requires explicit authoritative bounds, domain binding, member mapping, and evaluation time.
    """
    domain_session_id: str
    revision_id: str
    expected_price_basis: PriceBasis
    expected_confirmation_config_id: str
    matching_sequence_domain: SequenceDomain
    evaluation_time: datetime
    current_members: Mapping[str, SourceMemberReference]
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE
    touch_sequence_evidence: Optional[Mapping[str, TouchSequenceEvidence]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.domain_session_id, str) or not self.domain_session_id.strip():
            raise ValueError("domain_session_id must be non-empty string")
        if not isinstance(self.revision_id, str) or not self.revision_id.strip():
            raise ValueError("revision_id must be non-empty string")
        if not isinstance(self.expected_price_basis, PriceBasis):
            raise TypeError("expected_price_basis must be PriceBasis enum")
        if not isinstance(self.expected_confirmation_config_id, str) or not self.expected_confirmation_config_id.strip():
            raise ValueError("expected_confirmation_config_id must be non-empty string")
        if not isinstance(self.matching_sequence_domain, SequenceDomain):
            raise TypeError("matching_sequence_domain must be SequenceDomain instance")
        norm_eval = validate_and_normalize_timestamp(self.evaluation_time, "evaluation_time")
        object.__setattr__(self, "evaluation_time", norm_eval)
        if not isinstance(self.current_members, Mapping):
            raise TypeError("current_members must be a Mapping of member_key to SourceMemberReference")
        if not isinstance(self.coverage_status, CoverageStatus):
            raise TypeError("coverage_status must be CoverageStatus enum")


class ConfirmationMatcher:
    """Passive, stateless offline matcher evaluating confirmation evidence against activations."""

    def match(
        self,
        activation: ActivationRecord,
        evidence: ConfirmationEvidenceRecord,
        context: MatchingContext,
    ) -> ConfirmationMatchResult:
        """Evaluates association between an activation record and a confirmation evidence record."""
        if not isinstance(context, MatchingContext):
            raise TypeError("context must be a valid MatchingContext instance")

        rejection_reasons: List[ConfirmationRejectionReason] = []
        diagnostic_messages: List[str] = []
        is_blocked = False
        is_uncertain = False

        # 1. Authoritative Membership & Consistency Gating
        if not context.current_members:
            rejection_reasons.append(ConfirmationRejectionReason.MISSING_MATCHING_AUTHORITY)
            diagnostic_messages.append("MatchingContext contains no registered current_members")
            is_blocked = True
            current_member = None
        else:
            current_member = context.current_members.get(activation.member_key)
            if current_member is None:
                rejection_reasons.append(ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED)
                diagnostic_messages.append(
                    f"Member {activation.member_key} is not registered in current eligible members"
                )
            else:
                # Full member-to-activation consistency verification
                if (
                    current_member.engine_id != activation.engine_id
                    or current_member.symbol != activation.symbol
                    or current_member.source_timeframe != activation.source_timeframe
                    or current_member.set_id != activation.set_id
                    or current_member.role != activation.role
                    or abs(current_member.lower_edge - activation.lower_edge) > 1e-6
                    or abs(current_member.upper_edge - activation.upper_edge) > 1e-6
                    or current_member.usage_evidence_status != activation.usage_evidence_status
                ):
                    rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
                    diagnostic_messages.append(
                        f"Activation {activation.activation_id} contradicts registered member {activation.member_key}"
                    )
                if (
                    current_member.level_id is not None
                    and activation.level_id is not None
                    and current_member.level_id != activation.level_id
                ):
                    rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
                    diagnostic_messages.append(
                        f"Physical level mismatch between activation and registered member"
                    )

        # 2. Contradictory Explicit Association Fields Gating
        if evidence.activation_id is not None and evidence.activation_id != activation.activation_id:
            rejection_reasons.append(ConfirmationRejectionReason.ASSOCIATION_TARGET_MISMATCH)
            diagnostic_messages.append(
                f"Evidence explicit activation_id {evidence.activation_id} != activation {activation.activation_id}"
            )

        if evidence.source_member_key is not None and evidence.source_member_key != activation.member_key:
            rejection_reasons.append(ConfirmationRejectionReason.ASSOCIATION_TARGET_MISMATCH)
            diagnostic_messages.append(
                f"Evidence explicit source_member_key {evidence.source_member_key} != member {activation.member_key}"
            )

        # 3. Context, Feed & Configuration Binding Gating
        if evidence.confirmation_config_id != context.expected_confirmation_config_id:
            rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
            diagnostic_messages.append(
                f"Config mismatch: expected {context.expected_confirmation_config_id}, got {evidence.confirmation_config_id}"
            )

        if evidence.symbol is not None and evidence.symbol != activation.symbol:
            rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
            diagnostic_messages.append(
                f"Symbol mismatch: activation has {activation.symbol}, evidence has {evidence.symbol}"
            )

        if (
            activation.level_id is not None
            and evidence.feed_id is not None
            and activation.level_id.symbol_feed_id != evidence.feed_id
        ):
            rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
            diagnostic_messages.append(
                f"Feed mismatch: activation has {activation.level_id.symbol_feed_id}, evidence has {evidence.feed_id}"
            )

        if evidence.price_basis != context.expected_price_basis:
            rejection_reasons.append(ConfirmationRejectionReason.PRICE_BASIS_MISMATCH)
            diagnostic_messages.append(
                f"Price basis mismatch: expected {context.expected_price_basis.value}, got {evidence.price_basis.value}"
            )

        if (
            evidence.sequence_domain is not None
            and evidence.sequence_domain != context.matching_sequence_domain
        ):
            rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
            diagnostic_messages.append(
                f"Sequence domain mismatch: expected {context.matching_sequence_domain}, got {evidence.sequence_domain}"
            )

        # 4. Intended Direction Concordance (§3, §6)
        if current_member is not None:
            intended_direction = current_member.direction
            if evidence.direction != intended_direction:
                rejection_reasons.append(ConfirmationRejectionReason.DIRECTION_MISMATCH)
                diagnostic_messages.append(
                    f"Direction mismatch: activation requires {intended_direction.value}, evidence is {evidence.direction.value}"
                )

        # 5. Evaluation Availability Boundary Gating
        if evidence.close_timestamp > context.evaluation_time:
            rejection_reasons.append(ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE)
            diagnostic_messages.append(
                f"Evidence close {evidence.close_timestamp.isoformat()} is in future relative to evaluation boundary {context.evaluation_time.isoformat()}"
            )

        # 6. Assigned Confirmation Timeframe Gating (§6)
        expected_conf_tf = TIMEFRAME_CONFIRMATION_MAP.get(activation.source_timeframe)
        if evidence.confirmation_timeframe != expected_conf_tf or evidence.confirmation_timeframe != activation.confirmation_timeframe:
            rejection_reasons.append(ConfirmationRejectionReason.TIMEFRAME_MISMATCH)
            diagnostic_messages.append(
                f"Timeframe mismatch: source {activation.source_timeframe} requires {expected_conf_tf}, "
                f"evidence has {evidence.confirmation_timeframe}"
            )

        # 7. Activation Lifecycle State & Evidence Gating
        if activation.state not in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
            rejection_reasons.append(ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE)
            diagnostic_messages.append(f"Activation {activation.activation_id} is in state {activation.state.value}")

        if activation.usage_evidence_status == UsageEvidenceStatus.UNKNOWN:
            rejection_reasons.append(ConfirmationRejectionReason.UNKNOWN_USAGE)
            diagnostic_messages.append(f"Activation {activation.activation_id} has UNKNOWN usage evidence status")
            is_blocked = True
        elif activation.usage_evidence_status == UsageEvidenceStatus.USED:
            rejection_reasons.append(ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE)
            diagnostic_messages.append(f"Activation {activation.activation_id} is already USED")

        if context.coverage_status != CoverageStatus.COMPLETE:
            rejection_reasons.append(ConfirmationRejectionReason.INCOMPLETE_COVERAGE)
            diagnostic_messages.append(f"Context coverage status is {context.coverage_status.value}")
            is_blocked = True

        # 8. Confirmation Completion, Provenance & Dependency Gating
        if not evidence.is_completed:
            rejection_reasons.append(ConfirmationRejectionReason.INCOMPLETE_EVIDENCE)
            diagnostic_messages.append(f"Confirmation evidence {evidence.event_id} is not completed")

        if evidence.is_isolated_tracking:
            rejection_reasons.append(ConfirmationRejectionReason.ISOLATED_TRACKING_ONLY)
            diagnostic_messages.append(f"Confirmation evidence {evidence.event_id} is isolated tracking only")

        if evidence.has_unresolved_dependencies:
            if evidence.pattern_type in ("ISS", "AUTHORITATIVE_CONFIRMED_ISS"):
                rejection_reasons.append(ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP)
            else:
                rejection_reasons.append(ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY)
            diagnostic_messages.append(
                f"Confirmation evidence {evidence.event_id} has unresolved dependencies"
            )
            is_blocked = True

        if not evidence.structural_dependency_references:
            rejection_reasons.append(ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY)
            diagnostic_messages.append(
                f"Confirmation evidence {evidence.event_id} lacks structural dependency references"
            )
            is_blocked = True

        # 9. Authoritative Touch-Before-Completion Ordering & Causality (§7, OPEN-04)
        if activation.first_touch_time is None:
            rejection_reasons.append(ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE)
            diagnostic_messages.append(f"Activation {activation.activation_id} has no first_touch_time")
        else:
            if evidence.close_timestamp < activation.first_touch_time:
                # Completed strictly before tap cannot be reused (§7, sig_05)
                rejection_reasons.append(ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION)
                diagnostic_messages.append(
                    f"Confirmation close {evidence.close_timestamp.isoformat()} occurred strictly before "
                    f"first tap {activation.first_touch_time.isoformat()}"
                )
            elif evidence.close_timestamp == activation.first_touch_time:
                # Shared coarse interval / same timestamp: validate domain-scoped sequence ordering
                touch_ev: Optional[TouchSequenceEvidence] = None
                if context.touch_sequence_evidence:
                    touch_ev = context.touch_sequence_evidence.get(activation.activation_id)
                    if touch_ev is None and activation.trigger_observation_id:
                        touch_ev = context.touch_sequence_evidence.get(activation.trigger_observation_id)

                if touch_ev is not None and evidence.sequence_ref is not None:
                    # Validate domain comparability: cross-domain integers cannot establish order
                    if (
                        touch_ev.sequence_domain != context.matching_sequence_domain
                        or (evidence.sequence_domain is not None and evidence.sequence_domain != context.matching_sequence_domain)
                    ):
                        rejection_reasons.append(ConfirmationRejectionReason.CROSS_DOMAIN_ORDERING_REJECTED)
                        diagnostic_messages.append(
                            f"Touch domain {touch_ev.sequence_domain} or evidence domain {evidence.sequence_domain} "
                            f"does not match context domain {context.matching_sequence_domain}"
                        )
                        is_blocked = True
                    elif evidence.sequence_ref <= touch_ev.sequence_ref:
                        rejection_reasons.append(ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION)
                        diagnostic_messages.append(
                            f"Same timestamp sequence violation: evidence seq {evidence.sequence_ref} <= tap seq {touch_ev.sequence_ref}"
                        )
                else:
                    # Case C: OHLC overlap without sequence evidence -> fail closed as UNKNOWN_ORDER (sig_22)
                    rejection_reasons.append(ConfirmationRejectionReason.UNKNOWN_ORDER)
                    diagnostic_messages.append(
                        f"Tap and confirmation share timestamp {evidence.close_timestamp.isoformat()} "
                        f"without domain-scoped sequence evidence: fails closed as UNKNOWN_ORDER"
                    )
                    is_uncertain = True

        # 10. Fresh Evidence for Rearmed Generation (§9)
        if activation.state == ActivationState.REARMED_PENDING and activation.generation_seq > 1:
            if activation.first_touch_time is not None and evidence.close_timestamp < activation.first_touch_time:
                rejection_reasons.append(ConfirmationRejectionReason.STALE_EVIDENCE_FOR_GENERATION)
                diagnostic_messages.append(
                    f"Confirmation close {evidence.close_timestamp.isoformat()} is stale for generation {activation.generation_seq}"
                )

        # Build Match Result
        match_id = f"MATCH[{len(activation.activation_id)}:{activation.activation_id}][{len(evidence.event_id)}:{evidence.event_id}]"

        if rejection_reasons:
            status = (
                ConfirmationMatchStatus.BLOCKED
                if is_blocked
                else (ConfirmationMatchStatus.UNCERTAIN if is_uncertain else ConfirmationMatchStatus.REJECTED)
            )
            return ConfirmationMatchResult(
                match_id=match_id,
                status=status,
                activation_id=activation.activation_id,
                evidence_event_id=evidence.event_id,
                candidate_record=None,
                rejection_reasons=tuple(rejection_reasons),
                diagnostic_message="; ".join(diagnostic_messages),
                evaluated_at=context.evaluation_time,
            )

        # 11. Candidate Setup Construction (Milestone 30 §6.1, §6.4)
        setup_key = format_candidate_setup_key(
            domain_session_id=context.domain_session_id,
            revision_id=context.revision_id,
            activation_id=activation.activation_id,
            source_member_key=activation.member_key,
            confirmation_config_id=evidence.confirmation_config_id,
            confirmation_candle_id=evidence.confirmation_candle_id,
            confirmation_close_iso=evidence.close_timestamp.isoformat(),
        )

        cand_id = f"CAND[{len(setup_key)}:{setup_key}]"
        sig_side = "BUY" if evidence.direction == Direction.UPWARD else "SELL"
        tf_rank = TIMEFRAME_RANK_MAP.get(evidence.confirmation_timeframe, 3)
        role_rank = ROLE_RANK_MAP.get(activation.role, 2)

        candidate = CandidateSetupRecord(
            candidate_id=cand_id,
            setup_key=setup_key,
            domain_session_id=context.domain_session_id,
            revision_id=context.revision_id,
            activation_id=activation.activation_id,
            source_level_id=activation.level_id,
            source_timeframe=activation.source_timeframe,
            source_set_id=activation.set_id,
            source_role=activation.role,
            signal_side=sig_side,
            confirmation_timeframe=evidence.confirmation_timeframe,
            confirmation_close_timestamp=evidence.close_timestamp,
            entry_reference_price=evidence.close_price,
            price_basis=evidence.price_basis,
            price_provenance=evidence.price_provenance,
            confirmation_event_ids=(evidence.event_id,),
            confirmation_patterns=(evidence.pattern_type,),
            is_consolidated=False,
            timeframe_rank=tf_rank,
            role_rank=role_rank,
        )

        return ConfirmationMatchResult(
            match_id=match_id,
            status=ConfirmationMatchStatus.MATCHED,
            activation_id=activation.activation_id,
            evidence_event_id=evidence.event_id,
            candidate_record=candidate,
            rejection_reasons=(),
            diagnostic_message="Association validated successfully",
            evaluated_at=context.evaluation_time,
        )

    def match_batch(
        self,
        activations: Sequence[ActivationRecord],
        evidences: Sequence[ConfirmationEvidenceRecord],
        context: MatchingContext,
    ) -> BatchMatchResult:
        """Evaluates associations across activations and confirmation evidences.

        1. Validates input evidence identities: deduplicates identical events and
           rejects conflicting identities fail-closed.
        2. Evaluates all valid (activation, evidence) pairs.
        3. Validates shared-setup consistency: checks for conflicting prices, sides, or
           bases before consolidation.
        4. Consolidates CHOCH + ISS evidence sharing identical CandidateSetupKey under OPEN-07.
        5. Returns unique candidate setups separately from pair-level diagnostics,
           sorted deterministically by setup_key (permutation invariant).
        """
        if not isinstance(context, MatchingContext):
            raise TypeError("context must be a valid MatchingContext instance")

        # 1. Evidence Identity Validation & Deduplication
        evidences_by_id: Dict[str, List[ConfirmationEvidenceRecord]] = {}
        for ev in evidences:
            evidences_by_id.setdefault(ev.event_id, []).append(ev)

        deduped_evidences: List[ConfirmationEvidenceRecord] = []
        conflicted_event_ids: Set[str] = set()

        for evt_id, ev_list in sorted(evidences_by_id.items(), key=lambda x: x[0]):
            first = ev_list[0]
            has_conflict = False
            for other in ev_list[1:]:
                if (
                    other.pattern_type != first.pattern_type
                    or other.confirmation_config_id != first.confirmation_config_id
                    or other.confirmation_timeframe != first.confirmation_timeframe
                    or other.confirmation_candle_id != first.confirmation_candle_id
                    or other.close_timestamp != first.close_timestamp
                    or abs(other.close_price - first.close_price) > 1e-6
                    or other.price_basis != first.price_basis
                    or other.direction != first.direction
                ):
                    has_conflict = True
                    break
            if has_conflict:
                conflicted_event_ids.add(evt_id)
            else:
                deduped_evidences.append(first)

        # 2. Pair Evaluation
        raw_results: List[ConfirmationMatchResult] = []
        for act in activations:
            # First handle conflicted evidence events
            for evt_id in sorted(conflicted_event_ids):
                match_id = f"MATCH[{len(act.activation_id)}:{act.activation_id}][{len(evt_id)}:{evt_id}]"
                raw_results.append(
                    ConfirmationMatchResult(
                        match_id=match_id,
                        status=ConfirmationMatchStatus.BLOCKED,
                        activation_id=act.activation_id,
                        evidence_event_id=evt_id,
                        candidate_record=None,
                        rejection_reasons=(ConfirmationRejectionReason.CONFLICTING_IDENTITY,),
                        diagnostic_message=f"Evidence {evt_id} has conflicting duplicate payloads",
                        evaluated_at=context.evaluation_time,
                    )
                )

            # Evaluate against valid deduped evidences
            for ev in deduped_evidences:
                res = self.match(act, ev, context)
                raw_results.append(res)

        # 3. Setup Consistency Validation & Consolidation (OPEN-07)
        candidates_by_key: Dict[str, List[CandidateSetupRecord]] = {}
        for r in raw_results:
            if r.status == ConfirmationMatchStatus.MATCHED and r.candidate_record is not None:
                k = r.candidate_record.setup_key
                candidates_by_key.setdefault(k, []).append(r.candidate_record)

        conflicted_setup_keys: Set[str] = set()
        consolidated_candidates: Dict[str, CandidateSetupRecord] = {}

        for k, cand_list in sorted(candidates_by_key.items(), key=lambda x: x[0]):
            first = cand_list[0]
            # Validate consistency across all candidates sharing this setup key
            has_setup_conflict = False
            for other in cand_list[1:]:
                if (
                    other.signal_side != first.signal_side
                    or other.price_basis != first.price_basis
                    or abs(other.entry_reference_price - first.entry_reference_price) > 1e-6
                    or other.confirmation_close_timestamp != first.confirmation_close_timestamp
                ):
                    has_setup_conflict = True
                    break

            if has_setup_conflict:
                conflicted_setup_keys.add(k)
            else:
                all_evt_ids: List[str] = []
                all_patterns: List[str] = []
                for c in cand_list:
                    all_evt_ids.extend(c.confirmation_event_ids)
                    all_patterns.extend(c.confirmation_patterns)

                dedup_evt_ids = tuple(sorted(set(all_evt_ids)))
                dedup_patterns = tuple(sorted(set(all_patterns)))
                is_cons = len(dedup_patterns) > 1

                consolidated = CandidateSetupRecord(
                    candidate_id=first.candidate_id,
                    setup_key=first.setup_key,
                    domain_session_id=first.domain_session_id,
                    revision_id=first.revision_id,
                    activation_id=first.activation_id,
                    source_level_id=first.source_level_id,
                    source_timeframe=first.source_timeframe,
                    source_set_id=first.source_set_id,
                    source_role=first.source_role,
                    signal_side=first.signal_side,
                    confirmation_timeframe=first.confirmation_timeframe,
                    confirmation_close_timestamp=first.confirmation_close_timestamp,
                    entry_reference_price=first.entry_reference_price,
                    price_basis=first.price_basis,
                    price_provenance=first.price_provenance,
                    confirmation_event_ids=dedup_evt_ids,
                    confirmation_patterns=dedup_patterns,
                    is_consolidated=is_cons,
                    timeframe_rank=first.timeframe_rank,
                    role_rank=first.role_rank,
                )
                consolidated_candidates[k] = consolidated

        # 4. Finalize Pair Results (mark conflicted setup keys fail-closed)
        final_pair_results: List[ConfirmationMatchResult] = []
        for r in raw_results:
            if r.status == ConfirmationMatchStatus.MATCHED and r.candidate_record is not None:
                k = r.candidate_record.setup_key
                if k in conflicted_setup_keys:
                    final_pair_results.append(
                        ConfirmationMatchResult(
                            match_id=r.match_id,
                            status=ConfirmationMatchStatus.BLOCKED,
                            activation_id=r.activation_id,
                            evidence_event_id=r.evidence_event_id,
                            candidate_record=None,
                            rejection_reasons=(ConfirmationRejectionReason.CONFLICTING_IDENTITY,),
                            diagnostic_message=f"Setup {k} contains conflicting candidate evidence",
                            evaluated_at=context.evaluation_time,
                        )
                    )
                else:
                    cons_cand = consolidated_candidates[k]
                    final_pair_results.append(
                        ConfirmationMatchResult(
                            match_id=r.match_id,
                            status=r.status,
                            activation_id=r.activation_id,
                            evidence_event_id=r.evidence_event_id,
                            candidate_record=cons_cand,
                            rejection_reasons=r.rejection_reasons,
                            diagnostic_message=r.diagnostic_message,
                            evaluated_at=context.evaluation_time,
                        )
                    )
            else:
                final_pair_results.append(r)

        # 5. Extract Unique Candidates Sorted Deterministically by Setup Key
        unique_cands_list: List[CandidateSetupRecord] = [
            cand for k, cand in sorted(consolidated_candidates.items(), key=lambda x: x[0])
            if k not in conflicted_setup_keys
        ]

        # Deterministic sorting of pair results
        final_pair_results.sort(key=lambda r: (r.activation_id, r.evidence_event_id, r.match_id))

        return BatchMatchResult(
            unique_candidates=tuple(unique_cands_list),
            pair_results=tuple(final_pair_results),
            diagnostic_messages=(),
        )
