"""Deterministic evidence and lifecycle event processing for ActivationEngine.

Provides retrievable, isolated handlers for:
- Source cancellation (CHOCH and Replacement)
- External commit processing and winner exclusion
- Interval-bounded candle evidence and fail-closed intra-candle availability
- Scoped coverage evidence updates
"""

from __future__ import annotations

from dataclasses import replace
from typing import List

from aladeen.strategy.activation_handlers import validate_sequence_and_domain
from aladeen.strategy.activation_state import ActivationEngineState
from aladeen.strategy.activation_types import (
    ActivationLifecycleSnapshot,
    ActivationState,
    CancellationReason,
    CoverageEvidence,
    ExternalCommitEvent,
    IntervalBoundedCandleEvidence,
    RearmController,
    SourceCancellationEvent,
)


def process_cancellation_event(
    state: ActivationEngineState,
    event: SourceCancellationEvent,
) -> ActivationLifecycleSnapshot:
    """Processes source CHOCH and replacement cancellations."""
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

    members_to_cancel: List[str] = []
    for member_key, member in list(state.current_members.items()):
        if event.cancellation_reason == CancellationReason.SOURCE_CHOCH:
            if event.affected_direction is None or member.direction == event.affected_direction:
                members_to_cancel.append(member_key)
        elif event.cancellation_reason == CancellationReason.SOURCE_REPLACEMENT:
            if event.target_set_id is None or member.set_id == event.target_set_id:
                members_to_cancel.append(member_key)

    for member_key in members_to_cancel:
        # 1. Remove membership eligibility permanently from current members
        state.current_members.pop(member_key, None)

        # 2. Transition active activation to terminal if it was pending or rearmed pending
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

        # 3. Disable rearm controller if present
        state.rearm_controllers.pop(member_key, None)

    return state.get_snapshot()


def process_external_commit_event(
    state: ActivationEngineState,
    event: ExternalCommitEvent,
) -> ActivationLifecycleSnapshot:
    """Processes external commit notifications, terminalizing competitors and instantiating rearm controllers."""
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

    # External commit cancels competing pending activations, excluding the winner
    for member_key, rec in list(state.active_activations.items()):
        is_winner = (
            event.winning_engine_id == state.engine_id
            and event.winning_set_id == rec.set_id
            and event.winning_role == rec.role
        )
        if is_winner:
            continue

        if rec.state in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
            # 1. Terminalize active activation
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

            # 2. Initialize separate RearmController for next generation
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
