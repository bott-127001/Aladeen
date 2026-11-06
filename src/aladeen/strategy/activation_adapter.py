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
    """Stateful, transactional adapter maintaining an explicit processed-transition cursor over TJLSnapshot."""
    engine: ActivationEngine
    last_synced_transition_index: int = -1
    _usage_cache: Dict[StableLevelId, UsageEvidenceStatus] = field(default_factory=dict)
    _consumed_transitions: List[TJLTransitionRecord] = field(default_factory=list)
    _bound_engine_id: Optional[str] = None
    _bound_symbol_feed_id: Optional[str] = None
    _bound_source_timeframe: Optional[str] = None

    def sync(
        self,
        snapshot: TJLSnapshot,
        sequence_ref_start: int,
        usage_evidence: Optional[Mapping[StableLevelId, UsageEvidenceStatus]] = None,
    ) -> ActivationSnapshot:
        """Synchronizes an accepted TJLSnapshot atomically and idempotently across all components."""
        if not isinstance(snapshot, TJLSnapshot):
            raise TypeError(f"Expected TJLSnapshot, got {type(snapshot).__name__}")

        # 1. Validate source context before ANY state mutation
        if snapshot.source_engine_id != self.engine.engine_id:
            raise InvalidEvidenceError(
                f"Cross-engine snapshot rejected: snapshot source_engine_id {snapshot.source_engine_id!r} "
                f"!= activation engine {self.engine.engine_id!r}"
            )
        if snapshot.symbol_feed_id != self.engine.symbol:
            raise InvalidEvidenceError(
                f"Cross-symbol snapshot rejected: snapshot symbol_feed_id {snapshot.symbol_feed_id!r} "
                f"!= activation engine {self.engine.symbol!r}"
            )
        if snapshot.source_timeframe != self.engine.source_timeframe:
            raise InvalidEvidenceError(
                f"Cross-timeframe snapshot rejected: snapshot source_timeframe {snapshot.source_timeframe!r} "
                f"!= activation engine {self.engine.source_timeframe!r}"
            )

        if self._bound_engine_id is not None:
            if (
                snapshot.source_engine_id != self._bound_engine_id
                or snapshot.symbol_feed_id != self._bound_symbol_feed_id
                or snapshot.source_timeframe != self._bound_source_timeframe
            ):
                raise InvalidEvidenceError("Cross-context snapshot rejected against previously bound synchronizer context")

        # 2. Validate transition input completeness and authoritative history continuity
        history = snapshot.transition_history
        if snapshot.is_unresolved:
            # Unresolved snapshot contract:
            if snapshot.last_transition is not None:
                if snapshot.last_transition.transition_type != TJLTransitionType.BLOCKED_UNRESOLVED:
                    raise InvalidEvidenceError(
                        f"Inconsistent snapshot: unresolved snapshot carries non-diagnostic last_transition "
                        f"{snapshot.last_transition.transition_type}"
                    )
                # Valid receipt diagnostic BLOCKED_UNRESOLVED is not required to be in transition_history
        else:
            # Resolved snapshot contract:
            if snapshot.last_transition is not None:
                if snapshot.last_transition.transition_type == TJLTransitionType.BLOCKED_UNRESOLVED:
                    raise InvalidEvidenceError(
                        "Inconsistent snapshot: resolved snapshot carries BLOCKED_UNRESOLVED receipt diagnostic"
                    )
                if not history:
                    raise InvalidEvidenceError("Incomplete synchronization input: last_transition provided without transition_history")
                if snapshot.last_transition != history[-1]:
                    raise InvalidEvidenceError(
                        "Incomplete synchronization input: last_transition does not match the tail of authoritative transition_history"
                    )

        if len(history) < len(self._consumed_transitions):
            raise InvalidEvidenceError(
                f"Transition history truncated: expected at least {len(self._consumed_transitions)} records, got {len(history)}"
            )

        # Complete semantic equality comparison covering timestamps, resulting sets, geometry, and fingerprints
        for idx, expected_trans in enumerate(self._consumed_transitions):
            actual_trans = history[idx]
            if actual_trans != expected_trans:
                raise InvalidEvidenceError(
                    f"Consumed transition history mismatch at index {idx}: expected {expected_trans}, got {actual_trans}. "
                    "Rewritten history, altered transition timestamps, altered resulting sets, or cross-run snapshots are strictly rejected."
                )

        # Check if repeating identical sync without new transitions or sets
        if (
            len(history) == len(self._consumed_transitions)
            and (snapshot.is_unresolved or snapshot.current_eligible_set is None)
        ):
            return self.engine.get_snapshot()

        # 3. Staged Transactional Commit across engine, cursor, usage cache, transitions, and context binding
        engine_checkpoint = self.engine.create_checkpoint()
        prev_cursor = self.last_synced_transition_index
        prev_usage_cache = dict(self._usage_cache)
        prev_consumed_transitions = list(self._consumed_transitions)
        prev_bound_engine_id = self._bound_engine_id
        prev_bound_symbol_feed_id = self._bound_symbol_feed_id
        prev_bound_source_timeframe = self._bound_source_timeframe

        staged_bound_engine_id = self._bound_engine_id or snapshot.source_engine_id
        staged_bound_symbol_feed_id = self._bound_symbol_feed_id or snapshot.symbol_feed_id
        staged_bound_source_timeframe = self._bound_source_timeframe or snapshot.source_timeframe

        try:
            staged_usage_cache = dict(self._usage_cache)
            if usage_evidence is not None:
                staged_usage_cache.update(usage_evidence)

            staged_transitions = list(self._consumed_transitions)
            curr_seq = sequence_ref_start

            # Process newly observed finalized transitions sequentially (even if snapshot is currently unresolved!)
            for idx in range(len(self._consumed_transitions), len(history)):
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

                staged_transitions.append(trans)

            # Suppress fresh eligibility registration from unresolved snapshots
            if not snapshot.is_unresolved and snapshot.current_eligible_set is not None:
                tjl1_ref, tjl2_ref = adapt_tjl_current_set(
                    snapshot.current_eligible_set, usage_evidence=staged_usage_cache
                )
                self.engine.register_source_members([tjl1_ref, tjl2_ref])

            # Commit staged transaction
            if history:
                self.last_synced_transition_index = len(history) - 1
            self._usage_cache = staged_usage_cache
            self._consumed_transitions = staged_transitions
            self._bound_engine_id = staged_bound_engine_id
            self._bound_symbol_feed_id = staged_bound_symbol_feed_id
            self._bound_source_timeframe = staged_bound_source_timeframe
            return self.engine.get_snapshot()

        except Exception:
            # Atomic rollback across all components
            self.engine.restore_checkpoint(engine_checkpoint)
            self.last_synced_transition_index = prev_cursor
            self._usage_cache = prev_usage_cache
            self._consumed_transitions = prev_consumed_transitions
            self._bound_engine_id = prev_bound_engine_id
            self._bound_symbol_feed_id = prev_bound_symbol_feed_id
            self._bound_source_timeframe = prev_bound_source_timeframe
            raise


def sync_tjl_snapshot_to_activation_engine(
    synchronizer: TJLSynchronizer,
    snapshot: TJLSnapshot,
    sequence_ref: int,
    usage_evidence: Optional[Mapping[StableLevelId, UsageEvidenceStatus]] = None,
) -> ActivationSnapshot:
    """Supported public synchronization wrapper around a caller-retained TJLSynchronizer.

    A persistent TJLSynchronizer instance must be retained by the caller across synchronization
    invocations to maintain continuous transition cursors and prefix verification state.
    Transient/one-shot synchronization without a retained synchronizer is prohibited to prevent
    silent cursor discards.
    """
    if not isinstance(synchronizer, TJLSynchronizer):
        raise TypeError(
            "sync_tjl_snapshot_to_activation_engine requires a persistent, retained "
            f"TJLSynchronizer instance, got {type(synchronizer).__name__}. "
            "Transient synchronization with a bare ActivationEngine is deprecated and prohibited."
        )
    return synchronizer.sync(snapshot, sequence_ref_start=sequence_ref, usage_evidence=usage_evidence)
