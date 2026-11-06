"""Adapter connecting accepted TJL Engine outputs to the Activation Engine.

Scope & Design Boundary:
-------------------------
- Pure conversion and mapping layer.
- Consumes accepted CurrentEligibleSet, TJLTransitionRecord, and TJLSnapshot.
- Does NOT duplicate TJL detection or MSM calculations.
- Missing usage evidence strictly defaults to UNKNOWN (fail-closed).
- Preserves unknown cancellation timestamps; zero wall-clock invention.
- State-preserving, idempotent synchronization cursor over transition history.
- Frozen unresolved snapshots (is_unresolved == True) strictly DO NOT create fresh eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .activation_engine import ActivationEngine
from .activation_types import (
    ActivationSnapshot,
    CancellationReason,
    InvalidEvidenceError,
    SequenceDomain,
    SourceCancellationEvent,
    SourceMemberReference,
    UsageEvidenceStatus,
)
from .tjl_types import (
    CurrentEligibleSet,
    StableLevelId,
    TJLLabel,
    TJLSnapshot,
    TJLTransitionRecord,
    TJLTransitionType,
    TJLZone,
)
from .types import Direction


def adapt_tjl_current_set(
    current_set: CurrentEligibleSet,
    usage_evidence: Optional[Mapping[StableLevelId, UsageEvidenceStatus]] = None,
) -> Tuple[SourceMemberReference, SourceMemberReference]:
    """Converts an accepted TJL CurrentEligibleSet into exactly two SourceMemberReferences.

    Missing usage evidence strictly defaults to UNKNOWN.
    """
    if not isinstance(current_set, CurrentEligibleSet):
        raise TypeError(f"Expected CurrentEligibleSet, got {type(current_set).__name__}")

    usage_map = usage_evidence or {}

    def _convert_zone(zone: TJLZone, role_str: str) -> SourceMemberReference:
        # Default to UNKNOWN (fail-closed)
        status = usage_map.get(zone.level_id, UsageEvidenceStatus.UNKNOWN)
        return SourceMemberReference(
            engine_id=current_set.source_engine_id,
            symbol=current_set.symbol_feed_id,
            source_timeframe=current_set.source_timeframe,
            set_id=current_set.set_id,
            role=role_str,
            side=zone.level_id.side.value if hasattr(zone.level_id.side, "value") else str(zone.level_id.side),
            lower_edge=zone.lower_price,
            upper_edge=zone.upper_price,
            is_line=zone.is_line,
            direction=current_set.direction,
            level_id=zone.level_id,
            eligibility_available_time=current_set.eligibility_available_time,
            usage_evidence_status=status,
        )

    tjl1_ref = _convert_zone(current_set.tjl1_zone, "TJL1")
    tjl2_ref = _convert_zone(current_set.tjl2_zone, "TJL2_A_PLUS")
    return tjl1_ref, tjl2_ref


def adapt_tjl_cancellation_record(
    transition: TJLTransitionRecord,
    sequence_domain: SequenceDomain,
    sequence_ref: int,
    event_id: str,
) -> Optional[SourceCancellationEvent]:
    """Converts a TJL cancellation transition into an authoritative SourceCancellationEvent.

    Preserves unknown timestamps (None); zero wall-clock generation.
    """
    if not isinstance(transition, TJLTransitionRecord):
        raise TypeError(f"Expected TJLTransitionRecord, got {type(transition).__name__}")

    if transition.transition_type == TJLTransitionType.CHOCH_INVALIDATION:
        return SourceCancellationEvent(
            event_id=event_id,
            cancellation_reason=CancellationReason.SOURCE_CHOCH,
            timestamp=transition.transition_time,  # Optional[datetime] preserved as-is!
            sequence_domain=sequence_domain,
            sequence_ref=sequence_ref,
            target_set_id=transition.outgoing_cancelled_set_id,
            note=transition.diagnostic or "Source CHOCH invalidation transition",
        )
    elif transition.transition_type == TJLTransitionType.SET_REPLACEMENT:
        return SourceCancellationEvent(
            event_id=event_id,
            cancellation_reason=CancellationReason.SOURCE_REPLACEMENT,
            timestamp=transition.transition_time,  # Optional[datetime] preserved as-is!
            sequence_domain=sequence_domain,
            sequence_ref=sequence_ref,
            target_set_id=transition.outgoing_cancelled_set_id,
            note=transition.diagnostic or "Source set replacement transition",
        )

    return None


@dataclass
class TJLSynchronizer:
    """Stateful adapter maintaining an explicit processed-transition cursor over TJLSnapshot."""
    engine: ActivationEngine
    last_synced_transition_index: int = -1
    _usage_cache: Dict[StableLevelId, UsageEvidenceStatus] = field(default_factory=dict)

    def sync(
        self,
        snapshot: TJLSnapshot,
        sequence_ref_start: int,
        usage_evidence: Optional[Mapping[StableLevelId, UsageEvidenceStatus]] = None,
    ) -> ActivationSnapshot:
        """Synchronizes an accepted TJLSnapshot atomically and idempotently."""
        if not isinstance(snapshot, TJLSnapshot):
            raise TypeError(f"Expected TJLSnapshot, got {type(snapshot).__name__}")

        if usage_evidence is not None:
            self._usage_cache.update(usage_evidence)

        # Frozen unresolved snapshots strictly create ZERO fresh eligibility
        if snapshot.is_unresolved:
            return self.engine.get_snapshot()

        curr_seq = sequence_ref_start

        # Validate synchronization input completeness
        history = snapshot.transition_history
        if snapshot.last_transition is not None:
            if not history or snapshot.last_transition != history[-1]:
                raise InvalidEvidenceError(
                    "Incomplete synchronization input: last_transition is not the tail of transition_history"
                )

        if len(history) < self.last_synced_transition_index + 1:
            raise InvalidEvidenceError(
                f"Transition history truncated: expected at least {self.last_synced_transition_index + 1} records, got {len(history)}"
            )

        # Process transition history sequentially via explicit cursor
        for idx in range(self.last_synced_transition_index + 1, len(history)):
            trans = history[idx]
            if trans.outgoing_cancellation_intent:
                stable_event_id = f"EVT_TJL_TRANS_{trans.transition_type.value}_{trans.transition_candle_index}_{idx}"
                cancel_evt = adapt_tjl_cancellation_record(
                    transition=trans,
                    sequence_domain=self.engine.sequence_domain,
                    sequence_ref=curr_seq,
                    event_id=stable_event_id,
                )
                if cancel_evt is not None:
                    self.engine.process_event(cancel_evt)
                    curr_seq += 1

            self.last_synced_transition_index = idx

        # Atomically register current eligible set members if present
        if snapshot.current_eligible_set is not None:
            tjl1_ref, tjl2_ref = adapt_tjl_current_set(
                snapshot.current_eligible_set, usage_evidence=self._usage_cache
            )
            self.engine.register_source_members([tjl1_ref, tjl2_ref])

        return self.engine.get_snapshot()


def sync_tjl_snapshot_to_activation_engine(
    engine: ActivationEngine,
    snapshot: TJLSnapshot,
    sequence_ref: int,
    usage_evidence: Optional[Mapping[StableLevelId, UsageEvidenceStatus]] = None,
) -> ActivationSnapshot:
    """One-shot synchronization helper using a transient TJLSynchronizer."""
    synchronizer = TJLSynchronizer(engine=engine)
    return synchronizer.sync(snapshot, sequence_ref_start=sequence_ref, usage_evidence=usage_evidence)
