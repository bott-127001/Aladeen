"""Deterministic evidence and lifecycle event processing for ActivationEngine.

Provides retrievable, isolated handlers for:
- Source cancellation (CHOCH and Replacement) with explicit targeting and contradiction rejection
- External commit processing with scope contract enforcement and winner exclusion
- Interval-bounded candle evidence and fail-closed intra-candle availability
- Scoped coverage evidence updates
"""

from __future__ import annotations

from dataclasses import replace
from typing import List

from aladeen.strategy.activation_handlers import validate_sequence_and_domain
from aladeen.strategy.activation_state import ActivationEngineState
from aladeen.strategy.activation_types import (
    SUPPORTED_COMMIT_SCOPES,
    ActivationLifecycleSnapshot,
    ActivationState,
    CancellationReason,
    CoverageEvidence,
    ExternalCommitEvent,
    IntervalBoundedCandleEvidence,
    InvalidEvidenceError,
    RearmController,
    SourceCancellationEvent,
)


def process_cancellation_event(
    state: ActivationEngineState,
    event: SourceCancellationEvent,
) -> ActivationLifecycleSnapshot:
    """Processes source CHOCH and replacement cancellations with explicit targeting validation."""
    # 1. Reject unsupported partial-role targeting (source cancellations operate at set/direction level)
    if event.target_role is not None:
        raise InvalidEvidenceError(
            f"Partial-role targeting is not supported for {event.cancellation_reason.value}; "
            "source cancellations operate at full set or directional level."
        )

    # 2. Validate targeting contracts per cancellation reason
    if event.cancellation_reason == CancellationReason.SOURCE_REPLACEMENT:
        if event.target_set_id is None or not event.target_set_id.strip():
            raise InvalidEvidenceError("SOURCE_REPLACEMENT cancellation requires non-empty target_set_id")
    elif event.cancellation_reason == CancellationReason.SOURCE_CHOCH:
        if event.target_set_id is None and event.affected_direction is None:
            raise InvalidEvidenceError("SOURCE_CHOCH cancellation requires target_set_id and/or affected_direction")

    # 3. Check for contradictory targeting against known members in current state
    if event.target_set_id is not None and event.affected_direction is not None:
        for m in state.current_members.values():
            if m.set_id == event.target_set_id and m.direction != event.affected_direction:
                raise InvalidEvidenceError(
                    f"Contradictory cancellation targets: target_set_id {event.target_set_id!r} "
                    f"has direction {m.direction.value!r} but event declared affected_direction {event.affected_direction.value!r}"
                )

    # 4. Domain and sequence validation
    is_dup = validate_sequence_and_domain(
        state=state,
        event_id=event.event_id,
        sequence_domain=event.sequence_domain,
        sequence_ref=event.sequence_ref,
        timestamp=event.timestamp,
        event_payload=event,
    )
    if is_dup:
        return state.get_snapshot()

    # 5. Identify matching members strictly by declared targets
    members_to_cancel: List[str] = []
    for member_key, member in list(state.current_members.items()):
        # If target_set_id is specified, member must match that set
        if event.target_set_id is not None and member.set_id != event.target_set_id:
            continue

        # If affected_direction is specified, member must match that direction
        if event.affected_direction is not None and member.direction != event.affected_direction:
            continue

        members_to_cancel.append(member_key)

    # 6. Apply cancellations to matching members
    for member_key in members_to_cancel:
        # Remove membership eligibility permanently from current members
        state.current_members.pop(member_key, None)

        # Transition active activation to terminal
        rec = state.active_activations.pop(member_key, None)
        if rec is not None and rec.state in (
            ActivationState.PENDING_ACTIVATION,
            ActivationState.REARMED_PENDING,
        ):
            cancel_state = (
                ActivationState.CANCELLED_SOURCE_CHOCH
                if event.cancellation_reason == CancellationReason.SOURCE_CHOCH
                else ActivationState.CANCELLED_SOURCE_REPLACEMENT
            )
            term_rec = replace(
                rec,
                state=cancel_state,
                cancellation_reason=event.cancellation_reason,
                cancellation_time=event.timestamp,
                cancellation_sequence_ref=event.sequence_ref,
                terminal=True,
                rearm_armed=False,
            )
            state.terminal_activations.append(term_rec)

        # Disable rearm controller if present
        state.rearm_controllers.pop(member_key, None)

    return state.get_snapshot()


def process_external_commit_event(
    state: ActivationEngineState,
    event: ExternalCommitEvent,
) -> ActivationLifecycleSnapshot:
    """Processes external commit notifications, enforcing scope contract and excluding the winner."""
    # 1. Enforce supported external-commit scope contract before consuming sequence/domain
    if event.cancelled_competing_scope not in SUPPORTED_COMMIT_SCOPES:
        raise InvalidEvidenceError(
            f"Unsupported external commit scope {event.cancelled_competing_scope!r}. "
            f"Supported scopes are: {sorted(SUPPORTED_COMMIT_SCOPES)}"
        )

    # 2. Context routing: if target symbol or timeframe is specified, verify match
    if event.target_symbol is not None and event.target_symbol != state.symbol:
        return state.get_snapshot()
    if event.target_source_timeframe is not None and event.target_source_timeframe != state.source_timeframe:
        return state.get_snapshot()

    # 3. Domain and monotonic sequence validation (consumes sequence only after scope is validated)
    is_dup = validate_sequence_and_domain(
        state=state,
        event_id=event.event_id,
        sequence_domain=event.sequence_domain,
        sequence_ref=event.sequence_ref,
        timestamp=event.timestamp,
        event_payload=event,
    )
    if is_dup:
        return state.get_snapshot()

    # 4. External commit cancels competing pending activations in scope, excluding the external winner
    for member_key, rec in list(state.active_activations.items()):
        is_winner = (
            event.winning_engine_id == state.engine_id
            and event.winning_set_id == rec.set_id
            and event.winning_role == rec.role
        )
        if is_winner:
            continue

        if rec.state in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
            # Terminalize active activation
            state.active_activations.pop(member_key, None)
            term_rec = replace(
                rec,
                state=ActivationState.CANCELLED_EXTERNAL_ENTRY,
                cancellation_reason=CancellationReason.EXTERNAL_ENTRY,
                cancellation_time=event.timestamp,
                cancellation_sequence_ref=event.sequence_ref,
                terminal=True,
            )
            state.terminal_activations.append(term_rec)

            # Initialize separate RearmController for next generation
            is_outside = (rec.last_observed_position == "OUTSIDE")
            init_state = ActivationState.OUT_OF_ZONE_ARMED if is_outside else ActivationState.CANCELLED_EXTERNAL_ENTRY
            controller = RearmController(
                member_key=member_key,
                prior_activation_id=rec.activation_id,
                generation_seq=rec.generation_seq + 1,
                state=init_state,
                rearm_armed=is_outside,
                last_observed_position=rec.last_observed_position,
                cancellation_time=event.timestamp,
                cancellation_sequence_ref=event.sequence_ref,
            )
            state.rearm_controllers[member_key] = controller

    return state.get_snapshot()


def process_candle_evidence(
    state: ActivationEngineState,
    event: IntervalBoundedCandleEvidence,
) -> ActivationLifecycleSnapshot:
    """Evaluates interval-bounded candle evidence; fails closed on unknown sequence without corrupting pending activations."""
    is_dup = validate_sequence_and_domain(
        state=state,
        event_id=event.event_id,
        sequence_domain=event.sequence_domain,
        sequence_ref=event.sequence_ref,
        timestamp=event.timestamp or event.interval_close,
        event_payload=event,
    )
    if is_dup:
        return state.get_snapshot()

    for member_key, member in list(state.current_members.items()):
        rec = state.active_activations.get(member_key)
        # Uncertain candle evidence must NOT erase an already-authoritative pending or rearmed activation
        if rec is not None and rec.state in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
            continue

        avail = member.eligibility_available_time
        if avail is not None and event.interval_open < avail < event.interval_close:
            # Intra-candle availability
            if not event.sub_bar_sequence_available:
                # Cannot prove sequence relative to availability: fail closed for unactivated level
                if rec is not None:
                    state.active_activations[member_key] = replace(
                        rec,
                        state=ActivationState.BLOCKED_UNKNOWN_ORDER,
                        blocked_reason="UNKNOWN_ORDER_INTRA_CANDLE_AVAILABILITY",
                    )

    return state.get_snapshot()


def process_coverage_evidence(
    state: ActivationEngineState,
    event: CoverageEvidence,
) -> ActivationLifecycleSnapshot:
    """Processes coverage evidence with scope validation."""
    is_dup = validate_sequence_and_domain(
        state=state,
        event_id=event.event_id,
        sequence_domain=event.sequence_domain,
        sequence_ref=event.sequence_ref,
        timestamp=event.timestamp,
        event_payload=event,
    )
    if is_dup:
        return state.get_snapshot()

    # Scope validation: only update coverage if scope matches this engine's context
    valid_scopes = {
        state.symbol,
        f"{state.symbol}_{state.source_timeframe}",
        state.engine_id,
        "ALL",
        "GLOBAL",
    }
    if event.scope in valid_scopes:
        state.coverage_status = event.coverage_status
    return state.get_snapshot()
