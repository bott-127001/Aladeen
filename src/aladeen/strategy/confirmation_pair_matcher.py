"""Pair-level evaluation for associating confirmation evidence with eligible activation records.

Scope & Design Boundary:
-------------------------
- Pure mathematical and domain matching between a single ActivationRecord and ConfirmationEvidenceRecord.
- Strictly read-only calculation logic.
- Evaluates strict gating stages:
  1. Authoritative matching context & explicit source resolution authority.
  2. Member eligibility timing and physical level metadata consistency.
  3. Association target gating (explicit activation_id / member_key).
  4. Context gating (feed, symbol, basis, config, sequence domain).
  5. Provenance & structural dependency validation (synthetic provenance explicitly labeled).
  6. Activation state gating (permits PENDING_ACTIVATION and REARMED_PENDING).
  7. Direction mapping gating (UPWARD -> BUY, DOWNWARD -> SELL).
  8. Timeframe mapping gating (D1 -> H1, H4 -> M5, H1 -> M1).
  9. Causal ordering & evaluation boundary gating (never compares None touch times).
  10. Coverage gating (COMPLETE).
  11. Usage gating (UNUSED).
- Zero wall-clock dependence: evaluation derives strictly from MatchingContext.evaluation_time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

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
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchResult,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
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

    Requires explicit authoritative bounds, domain binding, member mapping, evaluation time,
    and explicit source resolution status for every evaluated member.
    """
    domain_session_id: str
    revision_id: str
    expected_price_basis: PriceBasis
    expected_confirmation_config_id: str
    matching_sequence_domain: SequenceDomain
    evaluation_time: datetime
    current_members: Mapping[str, SourceMemberReference]
    source_resolution_status: Mapping[str, bool]
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
        norm_time = validate_and_normalize_timestamp(self.evaluation_time, "evaluation_time")
        object.__setattr__(self, "evaluation_time", norm_time)
        if not isinstance(self.current_members, Mapping):
            raise TypeError("current_members must be a Mapping of member_key -> SourceMemberReference")
        if not isinstance(self.source_resolution_status, Mapping):
            raise TypeError("source_resolution_status must be a Mapping of member_key -> bool")
        if not isinstance(self.coverage_status, CoverageStatus):
            raise TypeError("coverage_status must be CoverageStatus enum")


class ConfirmationPairMatcher:
    """Evaluates association between an ActivationRecord and a ConfirmationEvidenceRecord."""

    def match(
        self,
        activation: ActivationRecord,
        evidence: ConfirmationEvidenceRecord,
        context: MatchingContext,
    ) -> ConfirmationMatchResult:
        """Evaluates whether a single confirmation evidence record associates with an activation."""
        if not isinstance(activation, ActivationRecord):
            raise TypeError("activation must be an ActivationRecord instance")
        if not isinstance(evidence, ConfirmationEvidenceRecord):
            raise TypeError("evidence must be a ConfirmationEvidenceRecord instance")
        if not isinstance(context, MatchingContext):
            raise TypeError("context must be a MatchingContext instance")

        match_id = f"MATCH[{len(activation.activation_id)}:{activation.activation_id}][{len(evidence.event_id)}:{evidence.event_id}]"
        rejection_reasons: List[ConfirmationRejectionReason] = []
        diagnostic_messages: List[str] = []

        # 0. Activation Touch Provenance Validation (never compare None touch times)
        has_valid_touch = True
        if activation.first_touch_time is None:
            has_valid_touch = False
            rejection_reasons.append(ConfirmationRejectionReason.MISSING_TOUCH_EVIDENCE)
            diagnostic_messages.append("Activation lacks valid first_touch_time")

        if not activation.trigger_observation_id or not activation.trigger_observation_id.strip():
            has_valid_touch = False
            rejection_reasons.append(ConfirmationRejectionReason.MISSING_TOUCH_EVIDENCE)
            diagnostic_messages.append("Activation lacks valid trigger_observation_id")

        # 1. Authoritative Membership, Explicit Source Resolution & Physical Identity
        current_member: Optional[SourceMemberReference] = None
        if context.current_members is None:
            rejection_reasons.append(ConfirmationRejectionReason.MISSING_MATCHING_AUTHORITY)
            diagnostic_messages.append("Context missing authoritative current_members map")
        else:
            current_member = context.current_members.get(activation.member_key)
            if current_member is None:
                rejection_reasons.append(ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED)
                diagnostic_messages.append(
                    f"Member {activation.member_key} is not registered in current eligible members"
                )
            else:
                # Explicit source resolution authority check (fail closed if unknown or unresolved)
                if activation.member_key not in context.source_resolution_status:
                    rejection_reasons.append(ConfirmationRejectionReason.UNKNOWN_SOURCE_RESOLUTION_AUTHORITY)
                    diagnostic_messages.append(
                        f"Member {activation.member_key} lacks explicit source_resolution_status in context"
                    )
                elif not context.source_resolution_status[activation.member_key]:
                    rejection_reasons.append(ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY)
                    diagnostic_messages.append(
                        f"Source calculation for member {activation.member_key} is marked unresolved"
                    )

                # Source availability check (guarded by touch existence)
                if current_member.eligibility_available_time is None:
                    rejection_reasons.append(ConfirmationRejectionReason.UNKNOWN_ELIGIBILITY_AVAILABLE_TIME)
                    diagnostic_messages.append(
                        f"Member {activation.member_key} has unknown eligibility_available_time"
                    )
                elif has_valid_touch and activation.first_touch_time is not None:
                    if activation.first_touch_time < current_member.eligibility_available_time:
                        rejection_reasons.append(ConfirmationRejectionReason.TOUCH_BEFORE_ELIGIBILITY)
                        diagnostic_messages.append(
                            f"Activation touch {activation.first_touch_time.isoformat()} occurred before member eligibility {current_member.eligibility_available_time.isoformat()}"
                        )

                # Consistency check between activation and member
                if (
                    current_member.engine_id != activation.engine_id
                    or current_member.symbol != activation.symbol
                    or current_member.source_timeframe != activation.source_timeframe
                    or current_member.set_id != activation.set_id
                    or current_member.role != activation.role
                    or current_member.lower_edge != activation.lower_edge
                    or current_member.upper_edge != activation.upper_edge
                    or current_member.usage_evidence_status != activation.usage_evidence_status
                ):
                    rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
                    diagnostic_messages.append(
                        f"Activation {activation.activation_id} contradicts registered member {activation.member_key}"
                    )

                # Physical level identity must be present and identical
                if current_member.level_id is None or activation.level_id is None or current_member.level_id != activation.level_id:
                    rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
                    diagnostic_messages.append(
                        "Physical level mismatch or missing level identity between activation and registered member"
                    )
                else:
                    # Validate physical identity metadata against member context: source timeframe, feed, side, and line geometry
                    if (
                        activation.level_id.source_timeframe != current_member.source_timeframe
                        or activation.level_id.side != current_member.side
                        or current_member.level_id.source_timeframe != current_member.source_timeframe
                        or current_member.level_id.side != current_member.side
                        or activation.level_id.symbol_feed_id != context.matching_sequence_domain.feed_id
                        or (current_member.is_line and current_member.lower_edge != current_member.upper_edge)
                    ):
                        rejection_reasons.append(ConfirmationRejectionReason.PHYSICAL_LEVEL_METADATA_MISMATCH)
                        diagnostic_messages.append(
                            "Physical level metadata contradicts member/context: feed/timeframe/side/geometry mismatch"
                        )

        # 2. Contradictory Explicit Association Fields Gating
        if evidence.activation_id is not None and evidence.activation_id != activation.activation_id:
            rejection_reasons.append(ConfirmationRejectionReason.ASSOCIATION_TARGET_MISMATCH)
            diagnostic_messages.append(
                f"Evidence target activation {evidence.activation_id} contradicts candidate {activation.activation_id}"
            )
        if evidence.source_member_key is not None and evidence.source_member_key != activation.member_key:
            rejection_reasons.append(ConfirmationRejectionReason.ASSOCIATION_TARGET_MISMATCH)
            diagnostic_messages.append(
                f"Evidence target member {evidence.source_member_key} contradicts candidate {activation.member_key}"
            )

        # 3. Context Gating (Configuration, Symbol, Feed, Price Basis, Sequence Domain)
        if evidence.confirmation_config_id != context.expected_confirmation_config_id:
            rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
            diagnostic_messages.append(
                f"Config mismatch: expected {context.expected_confirmation_config_id}, got {evidence.confirmation_config_id}"
            )

        if evidence.symbol != activation.symbol:
            rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
            diagnostic_messages.append(
                f"Symbol mismatch: activation has {activation.symbol}, evidence has {evidence.symbol}"
            )

        if activation.level_id is not None and evidence.feed_id != activation.level_id.symbol_feed_id:
            rejection_reasons.append(ConfirmationRejectionReason.CONTEXT_MISMATCH)
            diagnostic_messages.append(
                f"Feed mismatch: activation has {activation.level_id.symbol_feed_id}, evidence has {evidence.feed_id}"
            )

        if evidence.price_basis != context.expected_price_basis:
            rejection_reasons.append(ConfirmationRejectionReason.PRICE_BASIS_MISMATCH)
            diagnostic_messages.append(
                f"Price basis mismatch: expected {context.expected_price_basis.value}, got {evidence.price_basis.value}"
            )

        if evidence.sequence_domain != context.matching_sequence_domain:
            rejection_reasons.append(ConfirmationRejectionReason.CROSS_DOMAIN_ORDERING_REJECTED)
            diagnostic_messages.append(
                f"Sequence domain mismatch: expected {context.matching_sequence_domain}, got {evidence.sequence_domain}"
            )

        # 4. Provenance & Structural Dependencies Gating
        if evidence.provenance_type == EvidenceProvenanceType.BLOCKED_INCOMPLETE:
            rejection_reasons.append(ConfirmationRejectionReason.INCOMPLETE_EVIDENCE)
            diagnostic_messages.append("Evidence marked with BLOCKED_INCOMPLETE provenance")

        if not evidence.structural_dependency_references:
            rejection_reasons.append(ConfirmationRejectionReason.MISSING_STRUCTURAL_PROVENANCE)
            diagnostic_messages.append("Evidence missing structural dependency references")

        # 5. Activation State Gating (permits PENDING_ACTIVATION and REARMED_PENDING)
        if activation.state not in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
            rejection_reasons.append(ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE)
            diagnostic_messages.append(
                f"Activation state is {activation.state.value}, expected PENDING_ACTIVATION or REARMED_PENDING"
            )

        # 6. Direction Mapping Gating (Milestone 30 §6.1)
        expected_signal_side: Optional[str] = None
        if current_member is not None:
            if current_member.direction == Direction.UPWARD:
                expected_signal_side = "BUY"
                if evidence.direction != Direction.UPWARD:
                    rejection_reasons.append(ConfirmationRejectionReason.DIRECTION_MISMATCH)
                    diagnostic_messages.append("Expected UPWARD confirmation for BUY setup")
            elif current_member.direction == Direction.DOWNWARD:
                expected_signal_side = "SELL"
                if evidence.direction != Direction.DOWNWARD:
                    rejection_reasons.append(ConfirmationRejectionReason.DIRECTION_MISMATCH)
                    diagnostic_messages.append("Expected DOWNWARD confirmation for SELL setup")
            else:
                rejection_reasons.append(ConfirmationRejectionReason.DIRECTION_MISMATCH)
                diagnostic_messages.append(f"Unrecognized member direction: {current_member.direction}")

        # 7. Timeframe Mapping Gating (Milestone 30 §6.1)
        expected_conf_tf = TIMEFRAME_CONFIRMATION_MAP.get(activation.source_timeframe)
        if expected_conf_tf is None or evidence.confirmation_timeframe != expected_conf_tf:
            rejection_reasons.append(ConfirmationRejectionReason.TIMEFRAME_MISMATCH)
            diagnostic_messages.append(
                f"Timeframe mismatch: source {activation.source_timeframe} requires {expected_conf_tf}, got {evidence.confirmation_timeframe}"
            )

        # 8. Causal Ordering Gating (Milestone 30 §6.1)
        if evidence.close_timestamp is not None and evidence.close_timestamp > context.evaluation_time:
            rejection_reasons.append(ConfirmationRejectionReason.EVIDENCE_NOT_YET_AVAILABLE)
            diagnostic_messages.append(
                f"Confirmation close {evidence.close_timestamp.isoformat()} > evaluation boundary {context.evaluation_time.isoformat()}"
            )

        if evidence.close_timestamp is None:
            rejection_reasons.append(ConfirmationRejectionReason.INCOMPLETE_EVIDENCE)
            diagnostic_messages.append("Confirmation evidence lacks close_timestamp (incomplete)")
        elif has_valid_touch and activation.first_touch_time is not None:
            if evidence.close_timestamp < activation.first_touch_time:
                rejection_reasons.append(ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION)
                diagnostic_messages.append(
                    f"Confirmation close {evidence.close_timestamp.isoformat()} strictly before activation touch {activation.first_touch_time.isoformat()}"
                )
            elif evidence.close_timestamp == activation.first_touch_time:
                # Timestamp tie: resolve via sequence ordering if available
                touch_seq: Optional[TouchSequenceEvidence] = None
                if context.touch_sequence_evidence is not None:
                    touch_seq = context.touch_sequence_evidence.get(activation.activation_id)

                if touch_seq is None or evidence.sequence_ref is None:
                    rejection_reasons.append(ConfirmationRejectionReason.UNKNOWN_ORDER)
                    diagnostic_messages.append(
                        "Timestamp tie at touch time without complete sequence reference ordering"
                    )
                else:
                    if (
                        touch_seq.sequence_domain != context.matching_sequence_domain
                        or evidence.sequence_domain != context.matching_sequence_domain
                    ):
                        rejection_reasons.append(ConfirmationRejectionReason.CROSS_DOMAIN_ORDERING_REJECTED)
                        diagnostic_messages.append("Sequence comparison rejected: sequence domains do not match context")
                    elif evidence.sequence_ref <= touch_seq.sequence_ref:
                        rejection_reasons.append(ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION)
                        diagnostic_messages.append(
                            f"Confirmation sequence {evidence.sequence_ref} <= touch sequence {touch_seq.sequence_ref}"
                        )

        # 9. Coverage Gating (Milestone 30 §6.1)
        if context.coverage_status != CoverageStatus.COMPLETE:
            rejection_reasons.append(ConfirmationRejectionReason.INCOMPLETE_COVERAGE)
            diagnostic_messages.append(f"Coverage status is {context.coverage_status.value}, expected COMPLETE")

        # 10. Usage Evidence Gating (Milestone 30 §6.1)
        if activation.usage_evidence_status == UsageEvidenceStatus.UNKNOWN:
            rejection_reasons.append(ConfirmationRejectionReason.UNKNOWN_USAGE)
            diagnostic_messages.append("Activation usage status is UNKNOWN")
        elif activation.usage_evidence_status == UsageEvidenceStatus.USED:
            rejection_reasons.append(ConfirmationRejectionReason.STALE_EVIDENCE_FOR_GENERATION)
            diagnostic_messages.append(
                f"Confirmation close is stale for generation {activation.generation_seq}"
            )

        # 11. Evaluate Match Status
        status = ConfirmationMatchStatus.MATCHED
        if (
            ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP in rejection_reasons
            or ConfirmationRejectionReason.BLOCKED_UNRESOLVED_SOURCE_DEPENDENCY in rejection_reasons
            or ConfirmationRejectionReason.UNKNOWN_SOURCE_RESOLUTION_AUTHORITY in rejection_reasons
        ):
            status = ConfirmationMatchStatus.BLOCKED
        elif (
            evidence.has_unresolved_dependencies
            or ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY in rejection_reasons
        ):
            if ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY not in rejection_reasons:
                rejection_reasons.append(ConfirmationRejectionReason.UNRESOLVED_DEPENDENCY)
            if ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP not in rejection_reasons:
                rejection_reasons.append(ConfirmationRejectionReason.BLOCKED_UNRESOLVED_CONFIRMATION_GAP)
            status = ConfirmationMatchStatus.BLOCKED
        elif evidence.is_isolated_tracking:
            rejection_reasons.append(ConfirmationRejectionReason.ISOLATED_TRACKING_ONLY)
            status = ConfirmationMatchStatus.UNCERTAIN
        elif not evidence.is_completed:
            if ConfirmationRejectionReason.INCOMPLETE_EVIDENCE not in rejection_reasons:
                rejection_reasons.append(ConfirmationRejectionReason.INCOMPLETE_EVIDENCE)
            status = ConfirmationMatchStatus.REJECTED
        elif rejection_reasons:
            status = ConfirmationMatchStatus.REJECTED

        candidate: Optional[CandidateSetupRecord] = None
        if status == ConfirmationMatchStatus.MATCHED and expected_signal_side is not None:
            assert evidence.close_timestamp is not None
            setup_key = format_candidate_setup_key(
                domain_session_id=context.domain_session_id,
                revision_id=context.revision_id,
                activation_id=activation.activation_id,
                source_member_key=activation.member_key,
                confirmation_config_id=evidence.confirmation_config_id,
                confirmation_candle_id=evidence.confirmation_candle_id,
                confirmation_close_iso=evidence.close_timestamp.isoformat(),
            )
            # Setup-stable candidate identifier independent of pattern arrival order
            candidate_id = f"CAND[{len(setup_key)}:{setup_key}]"
            timeframe_rank = TIMEFRAME_RANK_MAP.get(evidence.confirmation_timeframe, 3)
            role_rank = ROLE_RANK_MAP.get(activation.role, 2)

            candidate = CandidateSetupRecord(
                candidate_id=candidate_id,
                setup_key=setup_key,
                domain_session_id=context.domain_session_id,
                revision_id=context.revision_id,
                activation_id=activation.activation_id,
                source_level_id=activation.level_id,
                source_timeframe=activation.source_timeframe,
                source_set_id=activation.set_id,
                source_role=activation.role,
                signal_side=expected_signal_side,
                confirmation_timeframe=evidence.confirmation_timeframe,
                confirmation_close_timestamp=evidence.close_timestamp,
                entry_reference_price=evidence.close_price,
                price_basis=evidence.price_basis,
                price_provenance=evidence.price_provenance,
                confirmation_event_ids=(evidence.event_id,),
                confirmation_patterns=(evidence.pattern_type,),
                is_consolidated=False,
                timeframe_rank=timeframe_rank,
                role_rank=role_rank,
                provenance_type=evidence.provenance_type,
            )

        diag = "; ".join(diagnostic_messages) if diagnostic_messages else None
        return ConfirmationMatchResult(
            match_id=match_id,
            status=status,
            activation_id=activation.activation_id,
            evidence_event_id=evidence.event_id,
            evaluated_at=context.evaluation_time,
            candidate_record=candidate,
            rejection_reasons=tuple(rejection_reasons),
            diagnostic_message=diag,
        )
