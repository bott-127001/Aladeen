"""Deterministic price print and member registration logic for ActivationEngine.

Contains authoritative implementations for:
- Sequence and domain validation with idempotence and conflict detection
- Source member registration with intra-batch conflict prevention and immutable geometry
- Exact price print evaluation, touch observation, and rearm controller reactivation
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set

from aladeen.strategy.activation_state import ActivationEngineState
from aladeen.strategy.activation_types import (
    ActivationLifecycleSnapshot,
    ActivationRecord,
    ActivationState,
    ConflictingEventError,
    CoverageStatus,
    DomainMismatchError,
    ExactPricePrint,
    InvalidEvidenceError,
    PriceBasis,
    RearmController,
    RegisterMembersEvent,
    SequenceDomain,
    SequenceOrderError,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_activation_id,
)


def validate_sequence_and_domain(
    state: ActivationEngineState,
    event_id: str,
    sequence_domain: SequenceDomain,
    sequence_ref: int,
    timestamp: Optional[datetime],
    event_payload: Any,
) -> bool:
    """Validates domain, monotonicity, and idempotence. Returns True if event is a duplicate no-op."""
    if sequence_domain != state.sequence_domain:
        raise DomainMismatchError(
            f"Event sequence domain {sequence_domain} does not match engine domain {state.sequence_domain}"
        )

    # Idempotence & conflict check
    if event_id in state.processed_events:
        prev_event = state.processed_events[event_id]
        if prev_event == event_payload:
            return True  # Idempotent duplicate: skip processing
        raise ConflictingEventError(
            f"Event ID {event_id!r} already processed with conflicting payload: {event_payload!r} vs {prev_event!r}"
        )

    # Strict monotonic sequence ref for distinct events
    if state.last_processed_sequence is not None:
        if sequence_ref <= state.last_processed_sequence:
            raise SequenceOrderError(
                f"Sequence ref {sequence_ref} <= last processed sequence {state.last_processed_sequence}. "
                "Distinct events must have strictly increasing sequence references."
            )

    # Monotonic timestamp check (if timestamps are known)
    if timestamp is not None and state.last_processed_timestamp is not None:
        if timestamp < state.last_processed_timestamp:
            raise SequenceOrderError(
                f"Timestamp {timestamp} is strictly earlier than last processed timestamp {state.last_processed_timestamp}"
            )

    # Record event envelope in transaction
    state.processed_events[event_id] = event_payload
    state.last_processed_sequence = sequence_ref
    if timestamp is not None:
        state.last_processed_timestamp = timestamp
    return False


def register_source_members(
    state: ActivationEngineState,
    members: Sequence[SourceMemberReference],
) -> ActivationLifecycleSnapshot:
    """Registers a sequence of eligible source level members atomically into engine state."""
    # 1. Validate all members before mutating state
    staged_candidates: Dict[str, SourceMemberReference] = {}
    for m in members:
        if m.engine_id != state.engine_id:
            raise InvalidEvidenceError(
                f"Member engine_id {m.engine_id!r} does not match activation engine {state.engine_id!r}"
            )
        if m.symbol != state.symbol:
            raise InvalidEvidenceError(
                f"Member symbol {m.symbol!r} does not match activation engine {state.symbol!r}"
            )
        if m.source_timeframe != state.source_timeframe:
            raise InvalidEvidenceError(
                f"Member source_timeframe {m.source_timeframe!r} does not match activation engine {state.source_timeframe!r}"
            )

        # Check against permanently invalidated outgoing memberships/sets
        if m.member_key in state.invalidated_member_keys or m.set_id in state.invalidated_set_ids:
            raise InvalidEvidenceError(
                f"Cannot register source-invalidated outgoing member or set {m.member_key!r}. "
                "Source cancellations permanently retire outgoing set identities within the run; "
                "persistent physical levels must return under a new successor set identity."
            )

        # Check intra-batch conflicts
        if m.member_key in staged_candidates:
            prev_cand = staged_candidates[m.member_key]
            if prev_cand == m:
                # Coalesce identical duplicates within same submitted batch
                continue
            raise InvalidEvidenceError(
                f"Conflicting member registration within submitted batch for {m.member_key}: "
                f"candidate {prev_cand} != candidate {m}. "
                "Conflicting duplicate keys within one registration call are rejected before mutation."
            )
        staged_candidates[m.member_key] = m

        # Check conflicting registration against existing membership
        existing_m = state.current_members.get(m.member_key)
        if existing_m is not None:
            if existing_m == m:
                continue
            # Validate explicit usage-evidence update only:
            is_usage_update = (
                existing_m.engine_id == m.engine_id
                and existing_m.symbol == m.symbol
                and existing_m.source_timeframe == m.source_timeframe
                and existing_m.set_id == m.set_id
                and existing_m.role == m.role
                and existing_m.level_id == m.level_id
                and existing_m.lower_edge == m.lower_edge
                and existing_m.upper_edge == m.upper_edge
                and existing_m.is_line == m.is_line
                and existing_m.side == m.side
                and existing_m.direction == m.direction
                and existing_m.eligibility_available_time == m.eligibility_available_time
            )
            if not is_usage_update:
                raise InvalidEvidenceError(
                    f"Conflicting member registration for {m.member_key}: existing {existing_m} != new {m}. "
                    "Geometry, role, identity, and availability are immutable; cannot silently replace bounds beneath existing member."
                )

    # 2. Mutate state atomically
    for m in members:
        existing_rec = state.active_activations.get(m.member_key)
        existing_member = state.current_members.get(m.member_key)

        if existing_member == m and existing_rec is not None:
            # Idempotent re-registration of identical member: preserve existing activation state!
            continue

        state.current_members[m.member_key] = m

        # Determine initial state and effective gating
        if m.eligibility_available_time is None:
            init_state = ActivationState.INACTIVE_INELIGIBLE
            blocked = "UNKNOWN_AVAILABILITY_TIMING"
        elif m.usage_evidence_status != UsageEvidenceStatus.UNUSED:
            init_state = ActivationState.INACTIVE_INELIGIBLE
            blocked = "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"
        else:
            init_state = ActivationState.INACTIVE_ELIGIBLE
            blocked = None

        if existing_rec is not None:
            # Check if this activation record has already established touch provenance
            has_touch_provenance = existing_rec.first_touch_time is not None or existing_rec.state in (
                ActivationState.PENDING_ACTIVATION,
                ActivationState.REARMED_PENDING,
            )
            if has_touch_provenance:
                # Active activation provenance must NEVER be erased by temporary evidence fluctuations
                state.active_activations[m.member_key] = replace(
                    existing_rec,
                    usage_evidence_status=m.usage_evidence_status,
                    blocked_reason=blocked,
                )
                continue
            else:
                # Untouched member slot: update state and blocked gating cleanly
                state.active_activations[m.member_key] = replace(
                    existing_rec,
                    state=init_state,
                    blocked_reason=blocked,
                    usage_evidence_status=m.usage_evidence_status,
                )
                continue

        # First time registering member or re-registering an inactive slot
        state.active_activations[m.member_key] = ActivationRecord(
            activation_id=format_activation_id(
                state.engine_id, state.source_timeframe, state.symbol, m.set_id, m.role, 0
            ),
            engine_id=state.engine_id,
            symbol=state.symbol,
            source_timeframe=state.source_timeframe,
            confirmation_timeframe=state.confirmation_timeframe,
            set_id=m.set_id,
            role=m.role,
            level_id=m.level_id,
            lower_edge=m.lower_edge,
            upper_edge=m.upper_edge,
            state=init_state,
            first_touch_time=None,
            first_touch_price=None,
            trigger_observation_id=None,
            prior_activation_id=None,
            rearm_armed=False,
            last_observed_position=None,
            usage_evidence_status=m.usage_evidence_status,
            generation_seq=0,
            terminal=False,
            blocked_reason=blocked,
        )

    return state.get_snapshot()


def process_register_members_event(
    state: ActivationEngineState,
    event: RegisterMembersEvent,
) -> ActivationLifecycleSnapshot:
    """Processes an external RegisterMembersEvent through sequence validation."""
    is_duplicate = validate_sequence_and_domain(
        state=state,
        event_id=event.event_id,
        sequence_domain=event.sequence_domain,
        sequence_ref=event.sequence_ref,
        timestamp=event.timestamp,
        event_payload=event,
    )
    if is_duplicate:
        return state.get_snapshot()

    return register_source_members(state, event.members)


def process_exact_price_print(
    state: ActivationEngineState,
    event: ExactPricePrint,
    expected_price_basis: Optional[PriceBasis] = None,
) -> ActivationLifecycleSnapshot:
    """Evaluates an exact price observation against current members and rearm controllers."""
    if expected_price_basis is not None and event.price_basis != expected_price_basis:
        raise InvalidEvidenceError(
            f"Exact price print price basis {event.price_basis} does not match engine {expected_price_basis}"
        )

    is_dup = validate_sequence_and_domain(
        state=state,
        event_id=event.observation_id,
        sequence_domain=event.sequence_domain,
        sequence_ref=event.sequence_ref,
        timestamp=event.timestamp,
        event_payload=event,
    )
    if is_dup:
        return state.get_snapshot()

    # 1. Evaluate against all currently registered members
    for member_key, member in list(state.current_members.items()):
        if member_key in state.rearm_controllers:
            # Under active rearm controller supervision: handled below
            continue

        # Fail closed on coverage
        if state.coverage_status != CoverageStatus.COMPLETE:
            continue

        # Fail closed on usage
        if member.usage_evidence_status != UsageEvidenceStatus.UNUSED:
            continue

        # Fail closed on availability
        if member.eligibility_available_time is None:
            continue

        # Cannot claim touch strictly prior to availability
        if event.timestamp < member.eligibility_available_time:
            continue

        # Price position relative to zone
        is_inside = (event.price == member.lower_edge) if member.is_line else (member.lower_edge <= event.price <= member.upper_edge)
        is_outside = (event.price < member.lower_edge or event.price > member.upper_edge)

        rec = state.active_activations.get(member_key)
        # Allow first touch or recovery from BLOCKED_UNKNOWN_ORDER upon valid discrete print
        if rec is None or rec.state in (ActivationState.INACTIVE_ELIGIBLE, ActivationState.BLOCKED_UNKNOWN_ORDER):
            if is_inside:
                # Check evidence recycling across generations for this level
                consumed = state.member_consumed_observations.get(member_key, set())
                if event.observation_id in consumed:
                    continue

                # Valid touch transitions to PENDING_ACTIVATION
                gen_seq = state.generation_counts.get(member_key, 0) + 1
                state.generation_counts[member_key] = gen_seq
                act_id = format_activation_id(
                    state.engine_id, state.source_timeframe, state.symbol, member.set_id, member.role, gen_seq
                )
                new_rec = ActivationRecord(
                    activation_id=act_id,
                    engine_id=state.engine_id,
                    symbol=state.symbol,
                    source_timeframe=state.source_timeframe,
                    confirmation_timeframe=state.confirmation_timeframe,
                    set_id=member.set_id,
                    role=member.role,
                    level_id=member.level_id,
                    lower_edge=member.lower_edge,
                    upper_edge=member.upper_edge,
                    state=ActivationState.PENDING_ACTIVATION,
                    first_touch_time=event.timestamp,
                    first_touch_price=event.price,
                    trigger_observation_id=event.observation_id,
                    prior_activation_id=None,
                    rearm_armed=False,
                    last_observed_position="INSIDE",
                    usage_evidence_status=member.usage_evidence_status,
                    generation_seq=gen_seq,
                    terminal=False,
                )
                state.active_activations[member_key] = new_rec
                state.observation_associations.setdefault(event.observation_id, set()).add(act_id)
                state.member_consumed_observations.setdefault(member_key, set()).add(event.observation_id)
            elif is_outside:
                if rec is not None:
                    state.active_activations[member_key] = replace(rec, last_observed_position="OUTSIDE")

        elif rec.state in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
            if is_inside:
                state.active_activations[member_key] = replace(rec, last_observed_position="INSIDE")
            elif is_outside:
                state.active_activations[member_key] = replace(rec, last_observed_position="OUTSIDE")

    # 2. Evaluate rearm controllers decoupled from activation records
    for member_key, ctrl in list(state.rearm_controllers.items()):
        member = state.current_members.get(member_key)
        if member is None:
            continue

        # Fail closed on coverage
        if state.coverage_status != CoverageStatus.COMPLETE:
            continue

        # Fail closed on usage
        if member.usage_evidence_status != UsageEvidenceStatus.UNUSED:
            continue

        # Fail closed on availability
        if member.eligibility_available_time is None:
            continue
        if event.timestamp < member.eligibility_available_time:
            continue

        is_inside = (event.price == member.lower_edge) if member.is_line else (member.lower_edge <= event.price <= member.upper_edge)
        is_outside = (event.price < member.lower_edge or event.price > member.upper_edge)

        if ctrl.state == ActivationState.CANCELLED_EXTERNAL_ENTRY:
            # Path A: inside at cancellation, awaiting confirmed outside departure
            if is_outside:
                state.rearm_controllers[member_key] = replace(
                    ctrl,
                    state=ActivationState.OUT_OF_ZONE_ARMED,
                    rearm_armed=True,
                    last_observed_position="OUTSIDE",
                )
            elif is_inside:
                state.rearm_controllers[member_key] = replace(
                    ctrl,
                    last_observed_position="INSIDE",
                )

        elif ctrl.state == ActivationState.OUT_OF_ZONE_ARMED:
            if is_inside:
                consumed = state.member_consumed_observations.get(member_key, set())
                if event.observation_id in consumed:
                    continue

                # Fresh touch rearms to REARMED_PENDING with a brand-new activation ID
                gen_seq = ctrl.generation_seq
                state.generation_counts[member_key] = gen_seq
                act_id = format_activation_id(
                    state.engine_id, state.source_timeframe, state.symbol, member.set_id, member.role, gen_seq
                )
                new_rec = ActivationRecord(
                    activation_id=act_id,
                    engine_id=state.engine_id,
                    symbol=state.symbol,
                    source_timeframe=state.source_timeframe,
                    confirmation_timeframe=state.confirmation_timeframe,
                    set_id=member.set_id,
                    role=member.role,
                    level_id=member.level_id,
                    lower_edge=member.lower_edge,
                    upper_edge=member.upper_edge,
                    state=ActivationState.REARMED_PENDING,
                    first_touch_time=event.timestamp,
                    first_touch_price=event.price,
                    trigger_observation_id=event.observation_id,
                    prior_activation_id=ctrl.prior_activation_id,
                    rearm_armed=False,
                    last_observed_position="INSIDE",
                    usage_evidence_status=member.usage_evidence_status,
                    generation_seq=gen_seq,
                    terminal=False,
                )
                state.active_activations[member_key] = new_rec
                state.rearm_controllers.pop(member_key, None)
                state.observation_associations.setdefault(event.observation_id, set()).add(act_id)
                state.member_consumed_observations.setdefault(member_key, set()).add(event.observation_id)
            elif is_outside:
                state.rearm_controllers[member_key] = replace(
                    ctrl,
                    last_observed_position="OUTSIDE",
                )

    return state.get_snapshot()



