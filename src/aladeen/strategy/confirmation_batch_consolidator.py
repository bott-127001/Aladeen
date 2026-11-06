"""Batch consolidation and conflict validation for confirmation-to-activation associations.

Scope & Design Boundary:
-------------------------
- Pure calculation logic evaluating multiple activations against multiple confirmation evidences.
- Validates complete activation and evidence identities using exact immutable equality.
- Detects and rejects conflicting duplicate activation IDs and event IDs fail-closed with CONFLICTING_IDENTITY.
- Coalesces identical duplicate activations and evidences cleanly.
- Validates shared-setup consistency across candidates sharing setup_key using exact equality.
- Setup-stable candidate identities independent of confirmation pattern or arrival order.
- Consolidates CHOCH + ISS confirmation evidence sharing identical CandidateSetupKey under OPEN-07.
- Returns unique candidate setups separately from pair diagnostics.
- Guarantees deterministic output sorting strictly invariant to input order permutations across both activations and evidences.
- Zero wall-clock dependence.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set, Tuple

from .activation_types import ActivationRecord
from .confirmation_pair_matcher import ConfirmationPairMatcher, MatchingContext
from .confirmation_types import (
    BatchMatchResult,
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchResult,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
)


class ConfirmationBatchConsolidator:
    """Consolidates and validates batch confirmation matching results."""

    def __init__(self, pair_matcher: Optional[ConfirmationPairMatcher] = None) -> None:
        self._pair_matcher = pair_matcher or ConfirmationPairMatcher()

    def match_batch(
        self,
        activations: Sequence[ActivationRecord],
        evidences: Sequence[ConfirmationEvidenceRecord],
        context: MatchingContext,
    ) -> BatchMatchResult:
        """Evaluates associations across activations and confirmation evidences.

        1. Validates input activation identities: deduplicates identical activations and
           rejects conflicting activation IDs fail-closed with CONFLICTING_IDENTITY.
        2. Validates input evidence identities: deduplicates identical events and
           rejects conflicting event IDs fail-closed with CONFLICTING_IDENTITY.
        3. Evaluates all valid (activation, evidence) pairs.
        4. Validates shared-setup consistency using exact equality before consolidation.
        5. Consolidates CHOCH + ISS evidence sharing identical CandidateSetupKey under OPEN-07.
        6. Returns unique candidate setups with setup-stable candidate IDs,
           sorted deterministically by setup_key (strictly permutation invariant).
        """
        if not isinstance(context, MatchingContext):
            raise TypeError("context must be a valid MatchingContext instance")

        # 1. Complete Activation Identity Validation & Deduplication
        activations_by_id: Dict[str, List[ActivationRecord]] = {}
        for act in activations:
            activations_by_id.setdefault(act.activation_id, []).append(act)

        deduped_activations: List[ActivationRecord] = []
        conflicted_activation_ids: Set[str] = set()

        for act_id, act_list in sorted(activations_by_id.items(), key=lambda x: x[0]):
            first_act = act_list[0]
            has_act_conflict = any(other != first_act for other in act_list[1:])
            if has_act_conflict:
                conflicted_activation_ids.add(act_id)
            else:
                deduped_activations.append(first_act)

        # 2. Complete Evidence Identity Validation & Deduplication
        evidences_by_id: Dict[str, List[ConfirmationEvidenceRecord]] = {}
        for ev in evidences:
            evidences_by_id.setdefault(ev.event_id, []).append(ev)

        deduped_evidences: List[ConfirmationEvidenceRecord] = []
        conflicted_event_ids: Set[str] = set()

        for evt_id, ev_list in sorted(evidences_by_id.items(), key=lambda x: x[0]):
            first_ev = ev_list[0]
            has_ev_conflict = any(other != first_ev for other in ev_list[1:])
            if has_ev_conflict:
                conflicted_event_ids.add(evt_id)
            else:
                deduped_evidences.append(first_ev)

        # 3. Pair Evaluation
        raw_results: List[ConfirmationMatchResult] = []

        # Handle conflicted activations
        for act_id in sorted(conflicted_activation_ids):
            for ev in deduped_evidences:
                match_id = f"MATCH[{len(act_id)}:{act_id}][{len(ev.event_id)}:{ev.event_id}]"
                raw_results.append(
                    ConfirmationMatchResult(
                        match_id=match_id,
                        status=ConfirmationMatchStatus.REJECTED,
                        activation_id=act_id,
                        evidence_event_id=ev.event_id,
                        evaluated_at=context.evaluation_time,
                        rejection_reasons=(ConfirmationRejectionReason.CONFLICTING_IDENTITY,),
                        diagnostic_message=f"Duplicate activation with conflicting payload fields for activation {act_id}",
                    )
                )

        # Handle valid activations
        for act in deduped_activations:
            # First emit explicit failure for conflicted duplicate events
            for evt_id in sorted(conflicted_event_ids):
                match_id = f"MATCH[{len(act.activation_id)}:{act.activation_id}][{len(evt_id)}:{evt_id}]"
                raw_results.append(
                    ConfirmationMatchResult(
                        match_id=match_id,
                        status=ConfirmationMatchStatus.REJECTED,
                        activation_id=act.activation_id,
                        evidence_event_id=evt_id,
                        evaluated_at=context.evaluation_time,
                        rejection_reasons=(ConfirmationRejectionReason.CONFLICTING_IDENTITY,),
                        diagnostic_message=f"Duplicate evidence with conflicting identity fields for event {evt_id}",
                    )
                )

            for ev in deduped_evidences:
                raw_results.append(self._pair_matcher.match(act, ev, context))

        # 4. Candidate Consolidation & Shared-Setup Conflict Validation (OPEN-07)
        candidates_by_key: Dict[str, List[CandidateSetupRecord]] = {}
        for res in raw_results:
            if res.status == ConfirmationMatchStatus.MATCHED and res.candidate_record is not None:
                candidates_by_key.setdefault(res.candidate_record.setup_key, []).append(res.candidate_record)

        conflicted_setup_keys: Set[str] = set()

        for k, cand_list in sorted(candidates_by_key.items(), key=lambda x: x[0]):
            first = cand_list[0]
            # Validate exact consistency across all candidates sharing this setup key
            has_setup_conflict = any(
                (
                    other.signal_side != first.signal_side
                    or other.price_basis != first.price_basis
                    or other.entry_reference_price != first.entry_reference_price
                    or other.confirmation_close_timestamp != first.confirmation_close_timestamp
                )
                for other in cand_list[1:]
            )

            if has_setup_conflict:
                conflicted_setup_keys.add(k)

        # Consolidate non-conflicted candidates
        unique_candidates: List[CandidateSetupRecord] = []
        for k, cand_list in sorted(candidates_by_key.items(), key=lambda x: x[0]):
            if k in conflicted_setup_keys:
                continue

            all_event_ids: Set[str] = set()
            all_patterns: Set[str] = set()
            any_synthetic = False
            for cand in cand_list:
                all_event_ids.update(cand.confirmation_event_ids)
                all_patterns.update(cand.confirmation_patterns)
                if cand.provenance_type == EvidenceProvenanceType.SYNTHETIC_TYPED:
                    any_synthetic = True

            first = cand_list[0]
            is_consolidated = len(all_patterns) > 1 or len(all_event_ids) > 1
            prov_type = EvidenceProvenanceType.SYNTHETIC_TYPED if any_synthetic else EvidenceProvenanceType.DETECTOR_CONFIRMED

            # Setup-stable candidate ID derived strictly from setup_key
            setup_candidate_id = f"CAND[{len(first.setup_key)}:{first.setup_key}]"

            consolidated = CandidateSetupRecord(
                candidate_id=setup_candidate_id,
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
                confirmation_event_ids=tuple(sorted(all_event_ids)),
                confirmation_patterns=tuple(sorted(all_patterns)),
                is_consolidated=is_consolidated,
                timeframe_rank=first.timeframe_rank,
                role_rank=first.role_rank,
                provenance_type=prov_type,
            )
            unique_candidates.append(consolidated)

        # Build pair results, marking setup conflicts
        final_pair_results: List[ConfirmationMatchResult] = []
        batch_diagnostics: List[str] = []

        if conflicted_activation_ids:
            batch_diagnostics.append(f"Rejected conflicted duplicate activations: {sorted(conflicted_activation_ids)}")
        if conflicted_event_ids:
            batch_diagnostics.append(f"Rejected conflicted duplicate events: {sorted(conflicted_event_ids)}")
        if conflicted_setup_keys:
            batch_diagnostics.append(f"Rejected conflicted setup keys: {sorted(conflicted_setup_keys)}")

        for res in raw_results:
            if (
                res.status == ConfirmationMatchStatus.MATCHED
                and res.candidate_record is not None
                and res.candidate_record.setup_key in conflicted_setup_keys
            ):
                final_pair_results.append(
                    ConfirmationMatchResult(
                        match_id=res.match_id,
                        status=ConfirmationMatchStatus.REJECTED,
                        activation_id=res.activation_id,
                        evidence_event_id=res.evidence_event_id,
                        evaluated_at=context.evaluation_time,
                        rejection_reasons=(ConfirmationRejectionReason.CONFLICTING_IDENTITY,),
                        diagnostic_message=f"Setup {res.candidate_record.setup_key} has contradictory candidate attributes",
                    )
                )
            else:
                final_pair_results.append(res)

        # Sort results deterministically by primary keys for strict permutation invariance
        unique_candidates.sort(key=lambda c: c.setup_key)
        final_pair_results.sort(key=lambda r: r.match_id)

        return BatchMatchResult(
            unique_candidates=tuple(unique_candidates),
            pair_results=tuple(final_pair_results),
            diagnostic_messages=tuple(batch_diagnostics),
        )
