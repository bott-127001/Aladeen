"""Adapter connecting accepted TJL Engine outputs to the Activation Engine.

Scope & Design Boundary:
-------------------------
- Pure conversion and mapping layer.
- Consumes accepted CurrentEligibleSet, TJLTransitionRecord, and TJLSnapshot.
- Does NOT duplicate TJL detection or MSM calculations.
- Frozen unresolved snapshots (is_unresolved == True) strictly DO NOT create fresh eligibility.
- Preserves StableLevelId, exact body edge bounds, and eligibility_available_time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .activation_engine import ActivationEngine
from .activation_types import (
    ActivationSnapshot,
    CancellationReason,
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
    """Converts an accepted TJL CurrentEligibleSet into exactly two SourceMemberReferences."""
    if not isinstance(current_set, CurrentEligibleSet):
        raise TypeError(f"Expected CurrentEligibleSet, got {type(current_set).__name__}")

    usage_map = usage_evidence or {}

    def _convert_zone(zone: TJLZone, role_str: str) -> SourceMemberReference:
        status = usage_map.get(zone.level_id, UsageEvidenceStatus.UNUSED)
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
    """Converts a TJL cancellation transition into an authoritative SourceCancellationEvent."""
    if not isinstance(transition, TJLTransitionRecord):
        raise TypeError(f"Expected TJLTransitionRecord, got {type(transition).__name__}")

    if transition.transition_type == TJLTransitionType.CHOCH_INVALIDATION:
        timestamp = transition.transition_time or datetime.now(timezone.utc)
        return SourceCancellationEvent(
            event_id=event_id,
            cancellation_reason=CancellationReason.SOURCE_CHOCH,
            timestamp=timestamp,
            sequence_domain=sequence_domain,
            sequence_ref=sequence_ref,
            target_set_id=transition.outgoing_cancelled_set_id,
            note=transition.diagnostic or "Source CHOCH invalidation transition",
        )
    elif transition.transition_type == TJLTransitionType.SET_REPLACEMENT:
        timestamp = transition.transition_time or datetime.now(timezone.utc)
        return SourceCancellationEvent(
            event_id=event_id,
            cancellation_reason=CancellationReason.SOURCE_REPLACEMENT,
            timestamp=timestamp,
            sequence_domain=sequence_domain,
            sequence_ref=sequence_ref,
            target_set_id=transition.outgoing_cancelled_set_id,
            note=transition.diagnostic or "Source set replacement transition",
        )

    return None


def sync_tjl_snapshot_to_activation_engine(
    engine: ActivationEngine,
    snapshot: TJLSnapshot,
    sequence_ref: int,
    usage_evidence: Optional[Mapping[StableLevelId, UsageEvidenceStatus]] = None,
) -> ActivationSnapshot:
    """Synchronizes an accepted TJLSnapshot to the ActivationEngine.

    Invariants:
    - If snapshot.is_unresolved is True, frozen state creates ZERO fresh eligibility.
    - If snapshot has a cancellation transition, dispatches cancellation event.
    - If snapshot has an active current_eligible_set, registers the two members.
    """
    if not isinstance(snapshot, TJLSnapshot):
        raise TypeError(f"Expected TJLSnapshot, got {type(snapshot).__name__}")

    # Frozen unresolved snapshots strictly DO NOT create fresh eligibility
    if snapshot.is_unresolved:
        return engine.get_snapshot()

    # Process cancellation transition if present
    if snapshot.last_transition is not None and snapshot.last_transition.outgoing_cancellation_intent:
        cancel_evt = adapt_tjl_cancellation_record(
            transition=snapshot.last_transition,
            sequence_domain=engine.sequence_domain,
            sequence_ref=sequence_ref,
            event_id=f"EVT_TJL_CANCEL_{snapshot.last_transition.transition_candle_index}_{sequence_ref}",
        )
        if cancel_evt is not None:
            engine.process_event(cancel_evt)

    # Register current eligible set members if available
    if snapshot.current_eligible_set is not None:
        tjl1_ref, tjl2_ref = adapt_tjl_current_set(
            snapshot.current_eligible_set, usage_evidence=usage_evidence
        )
        engine.register_source_members([tjl1_ref, tjl2_ref])

    return engine.get_snapshot()
