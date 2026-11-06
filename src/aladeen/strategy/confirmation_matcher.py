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
- Explicit diagnostic results for all rejected or uncertain associations.
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
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchResult,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
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
    """Evaluation context for confirmation matching operations."""
    domain_session_id: str = "SESSION_DEFAULT"
    revision_id: str = "REV_001"
    default_price_basis: Optional[PriceBasis] = PriceBasis.BID
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE
    current_members: Optional[Mapping[str, SourceMemberReference]] = None
    member_directions: Optional[Mapping[str, Direction]] = None
    touch_sequence_refs: Optional[Mapping[str, int]] = None  # keyed by activation_id or observation_id
    evaluation_time: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not isinstance(self.domain_session_id, str) or not self.domain_session_id.strip():
            raise ValueError("domain_session_id must be non-empty string")
        if not isinstance(self.revision_id, str) or not self.revision_id.strip():
            raise ValueError("revision_id must be non-empty string")
        if self.evaluation_time is not None:
            norm_eval = validate_and_normalize_timestamp(self.evaluation_time, "evaluation_time")
            object.__setattr__(self, "evaluation_time", norm_eval)


class ConfirmationMatcher:
    """Passive, stateless offline matcher evaluating confirmation evidence against activations."""

    def __init__(self, default_context: Optional[MatchingContext] = None) -> None:
        self._default_context = default_context or MatchingContext()

    def match(
        self,
        activation: ActivationRecord,
        evidence: ConfirmationEvidenceRecord,
        context: Optional[MatchingContext] = None,
    ) -> ConfirmationMatchResult:
        """Evaluates association between an activation record and a confirmation evidence record."""
        ctx = context or self._default_context
        eval_time = ctx.evaluation_time or datetime.now(timezone.utc)
        rejection_reasons: List[ConfirmationRejectionReason] = []
        diagnostic_messages: List[str] = []
        is_blocked = False
        is_uncertain = False

        # 1. Activation Lifecycle State & Membership Gating
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

        if ctx.coverage_status != CoverageStatus.COMPLETE:
            rejection_reasons.append(ConfirmationRejectionReason.INCOMPLETE_COVERAGE)
            diagnostic_messages.append(f"Context coverage status is {ctx.coverage_status.value}")
            is_blocked = True

        # Check current member registration if provided
        if ctx.current_members is not None:
            if activation.member_key not in ctx.current_members:
                rejection_reasons.append(ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED)
                diagnostic_messages.append(
                    f"Member {activation.member_key} is not registered in current eligible members"
                )

        # 2. Context & Feed Compatibility Gating
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

        if ctx.default_price_basis is not None and evidence.price_basis != ctx.default_price_basis:
            rejection_reasons.append(ConfirmationRejectionReason.PRICE_BASIS_MISMATCH)
            diagnostic_messages.append(
                f"Price basis mismatch: expected {ctx.default_price_basis.value}, evidence has {evidence.price_basis.value}"
            )

        # 3. Assigned Confirmation Timeframe Gating (§6)
        expected_conf_tf = TIMEFRAME_CONFIRMATION_MAP.get(activation.source_timeframe)
        if evidence.confirmation_timeframe != expected_conf_tf or evidence.confirmation_timeframe != activation.confirmation_timeframe:
            rejection_reasons.append(ConfirmationRejectionReason.TIMEFRAME_MISMATCH)
            diagnostic_messages.append(
                f"Timeframe mismatch: source {activation.source_timeframe} requires {expected_conf_tf}, "
                f"evidence has {evidence.confirmation_timeframe}"
            )

        # 4. Confirmation Completion, Provenance & Dependency Gating
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

        # 5. Directional Concordance Gating (§3, §6)
        # Determine intended direction from member reference or context
        intended_direction: Optional[Direction] = None
        if ctx.member_directions and activation.member_key in ctx.member_directions:
            intended_direction = ctx.member_directions[activation.member_key]
        elif ctx.current_members and activation.member_key in ctx.current_members:
            intended_direction = ctx.current_members[activation.member_key].direction

        if intended_direction is not None:
            if evidence.direction != intended_direction:
                rejection_reasons.append(ConfirmationRejectionReason.DIRECTION_MISMATCH)
                diagnostic_messages.append(
                    f"Direction mismatch: activation requires {intended_direction.value}, evidence is {evidence.direction.value}"
                )

        # 6. Authoritative Touch-Before-Completion Ordering & Causality (§7, OPEN-04)
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
                # Shared coarse interval / same timestamp: check sequence ordering
                tap_seq: Optional[int] = None
                if ctx.touch_sequence_refs:
                    tap_seq = ctx.touch_sequence_refs.get(activation.activation_id)
                    if tap_seq is None and activation.trigger_observation_id:
                        tap_seq = ctx.touch_sequence_refs.get(activation.trigger_observation_id)

                if tap_seq is not None and evidence.sequence_ref is not None:
                    if evidence.sequence_ref <= tap_seq:
                        rejection_reasons.append(ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION)
                        diagnostic_messages.append(
                            f"Same timestamp sequence order violation: evidence seq {evidence.sequence_ref} <= tap seq {tap_seq}"
                        )
                else:
                    # Case C: OHLC overlap without sequence evidence -> fail closed as UNKNOWN_ORDER (sig_22)
                    rejection_reasons.append(ConfirmationRejectionReason.UNKNOWN_ORDER)
                    diagnostic_messages.append(
                        f"Tap and confirmation share timestamp {evidence.close_timestamp.isoformat()} "
                        f"without sequence evidence: fails closed as UNKNOWN_ORDER"
                    )
                    is_uncertain = True

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
                evaluated_at=eval_time,
            )

        # 7. Candidate Setup Construction (Milestone 30 §6.1, §6.4)
        setup_key = format_candidate_setup_key(
            domain_session_id=ctx.domain_session_id,
            revision_id=ctx.revision_id,
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
            domain_session_id=ctx.domain_session_id,
            revision_id=ctx.revision_id,
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
            evaluated_at=eval_time,
        )

    def match_batch(
        self,
        activations: Sequence[ActivationRecord],
        evidences: Sequence[ConfirmationEvidenceRecord],
        context: Optional[MatchingContext] = None,
    ) -> Sequence[ConfirmationMatchResult]:
        """Evaluates associations across activations and confirmation evidences.

        Consolidates CHOCH + ISS evidence sharing identical CandidateSetupKey (OPEN-07).
        Does NOT perform hidden arbitration or level consumption.
        """
        ctx = context or self._default_context
        raw_results: List[ConfirmationMatchResult] = []

        # Evaluate each pairing
        for act in activations:
            for ev in evidences:
                res = self.match(act, ev, ctx)
                raw_results.append(res)

        # Consolidate candidate setups sharing identical setup_key under OPEN-07
        # Map setup_key -> list of matched CandidateSetupRecord
        candidates_by_key: Dict[str, List[CandidateSetupRecord]] = {}
        for r in raw_results:
            if r.status == ConfirmationMatchStatus.MATCHED and r.candidate_record is not None:
                k = r.candidate_record.setup_key
                candidates_by_key.setdefault(k, []).append(r.candidate_record)

        # Consolidate where multiple patterns exist
        consolidated_candidates: Dict[str, CandidateSetupRecord] = {}
        for k, cand_list in candidates_by_key.items():
            if len(cand_list) == 1:
                consolidated_candidates[k] = cand_list[0]
            else:
                first = cand_list[0]
                all_evt_ids: List[str] = []
                all_patterns: List[str] = []
                for c in cand_list:
                    all_evt_ids.extend(c.confirmation_event_ids)
                    all_patterns.extend(c.confirmation_patterns)

                # Ensure deterministic ordering
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

        # Re-attach consolidated candidates
        final_results: List[ConfirmationMatchResult] = []
        for r in raw_results:
            if r.status == ConfirmationMatchStatus.MATCHED and r.candidate_record is not None:
                k = r.candidate_record.setup_key
                cons_cand = consolidated_candidates.get(k, r.candidate_record)
                final_results.append(
                    ConfirmationMatchResult(
                        match_id=r.match_id,
                        status=r.status,
                        activation_id=r.activation_id,
                        evidence_event_id=r.evidence_event_id,
                        candidate_record=cons_cand,
                        rejection_reasons=r.rejection_reasons,
                        diagnostic_message=r.diagnostic_message,
                        evaluated_at=r.evaluated_at,
                    )
                )
            else:
                final_results.append(r)

        return tuple(final_results)
