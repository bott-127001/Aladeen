"""Pure offline Tap and Zone Activation Lifecycle Engine.

Scope & Design Boundary:
-------------------------
- Pure calculation and state transition reducer independent of MT5, UI, or IO.
- Consumes discrete price prints, candle evidence, coverage evidence, and authoritative lifecycle cancellations.
- Strictly immutable snapshots and event records.
- Sequence domain scoping: compares event sequence references only within declared (feed_id, run_id).
- Strict monotonic sequence ordering: distinct events with equal sequence_ref are rejected.
- Unambiguous canonical activation ID encoding.
- Raw price observations are immutable facts; association with activations is tracked separately without mutating shared prints.
- Atomic multi-member registration and atomic batch processing with full state rollback on failure.
- Bit-for-bit idempotent replay determinism executed on isolated engine instances.
- Strictly zero order placement, zero execution ledger, zero live account modification.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .activation_types import (
    ActivationError,
    ActivationRecord,
    ActivationSnapshot,
    ActivationState,
    CancellationReason,
    ConflictingEventError,
    CoverageEvidence,
    CoverageStatus,
    DomainMismatchError,
    ExactPricePrint,
    ExternalCommitEvent,
    IntervalBoundedCandleEvidence,
    InvalidEvidenceError,
    PriceBasis,
    RearmController,
    RegisterMembersEvent,
    SequenceDomain,
    SequenceOrderError,
    SourceCancellationEvent,
    SourceMemberReference,
    TIMEFRAME_CONFIRMATION_MAP,
    UsageEvidenceStatus,
    format_activation_id,
)
from .types import Direction, validate_and_normalize_timestamp


@dataclass(frozen=True)
class ActivationEngineConfig:
    """Immutable configuration for an Activation Engine instance."""
    engine_id: str
    symbol: str
    source_timeframe: str
    sequence_domain: SequenceDomain
    price_basis: PriceBasis = PriceBasis.BID

    def __post_init__(self) -> None:
        if not isinstance(self.engine_id, str) or not self.engine_id.strip():
            raise ValueError("engine_id must be non-empty string")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be non-empty string")
        if self.source_timeframe not in TIMEFRAME_CONFIRMATION_MAP:
            raise ValueError(
                f"Unsupported source_timeframe {self.source_timeframe!r}. "
                f"Must be one of {list(TIMEFRAME_CONFIRMATION_MAP.keys())}"
            )
        if not isinstance(self.sequence_domain, SequenceDomain):
            raise TypeError("sequence_domain must be an instance of SequenceDomain")
        if not isinstance(self.price_basis, PriceBasis):
            raise TypeError("price_basis must be an instance of PriceBasis")


class ActivationEngine:
    """Pure lifecycle state machine managing Tap observation and Zone Activation."""

    def __init__(self, config: ActivationEngineConfig) -> None:
        self._config = config
        self._confirmation_timeframe = TIMEFRAME_CONFIRMATION_MAP[config.source_timeframe]

        # Mutable reducer state
        self._current_members: Dict[str, SourceMemberReference] = {}
        self._active_activations: Dict[str, ActivationRecord] = {}
        self._terminal_activations: List[ActivationRecord] = []
        self._rearm_controllers: Dict[str, RearmController] = {}

        # Association and consumption tracking (does NOT mutate raw print objects)
        self._processed_events: Dict[str, Any] = {}
        self._observation_associations: Dict[str, Set[str]] = {}
        self._member_consumed_observations: Dict[str, Set[str]] = {}
        self._generation_counts: Dict[str, int] = {}

        self._last_processed_sequence: Optional[int] = None
        self._last_processed_timestamp: Optional[datetime] = None
        self._coverage_status: CoverageStatus = CoverageStatus.COMPLETE

    @property
    def config(self) -> ActivationEngineConfig:
        return self._config

    @property
    def engine_id(self) -> str:
        return self._config.engine_id

    @property
    def symbol(self) -> str:
        return self._config.symbol

    @property
    def source_timeframe(self) -> str:
        return self._config.source_timeframe

    @property
    def confirmation_timeframe(self) -> str:
        return self._confirmation_timeframe

    @property
    def sequence_domain(self) -> SequenceDomain:
        return self._config.sequence_domain

    @property
    def price_basis(self) -> PriceBasis:
        return self._config.price_basis

    def register_source_member(self, member: SourceMemberReference) -> ActivationSnapshot:
        """Registers a single eligible source level member with the engine."""
        return self.register_source_members([member])

    def register_source_members(self, members: Sequence[SourceMemberReference]) -> ActivationSnapshot:
        """Registers a sequence of eligible source level members atomically."""
        # 1. Validate all members before mutating state
        staged_candidates: Dict[str, SourceMemberReference] = {}
        for m in members:
            if m.engine_id != self.engine_id:
                raise InvalidEvidenceError(
                    f"Member engine_id {m.engine_id!r} does not match activation engine {self.engine_id!r}"
                )
            if m.symbol != self.symbol:
                raise InvalidEvidenceError(
                    f"Member symbol {m.symbol!r} does not match activation engine {self.symbol!r}"
                )
            if m.source_timeframe != self.source_timeframe:
                raise InvalidEvidenceError(
                    f"Member source_timeframe {m.source_timeframe!r} does not match activation engine {self.source_timeframe!r}"
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
            existing_m = self._current_members.get(m.member_key)
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
            existing_rec = self._active_activations.get(m.member_key)
            existing_member = self._current_members.get(m.member_key)

            if existing_member == m and existing_rec is not None:
                # Idempotent re-registration of identical member: preserve existing activation state!
                continue

            self._current_members[m.member_key] = m

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
                # Member existed: if usage or timing changed, update state without resetting ongoing activations if valid
                if existing_rec.state in (
                    ActivationState.PENDING_ACTIVATION,
                    ActivationState.REARMED_PENDING,
                ):
                    if init_state == ActivationState.INACTIVE_INELIGIBLE:
                        # Gating revoked! Transition to INACTIVE_INELIGIBLE
                        self._active_activations[m.member_key] = replace(
                            existing_rec,
                            state=ActivationState.INACTIVE_INELIGIBLE,
                            blocked_reason=blocked,
                            usage_evidence_status=m.usage_evidence_status,
                        )
                    else:
                        # Gating still valid: keep current active state
                        self._active_activations[m.member_key] = replace(
                            existing_rec,
                            usage_evidence_status=m.usage_evidence_status,
                        )
                    continue

            # First time registering member or re-registering an inactive slot
            self._active_activations[m.member_key] = ActivationRecord(
                activation_id=format_activation_id(
                    self.engine_id, self.source_timeframe, self.symbol, m.set_id, m.role, 0
                ),
                engine_id=self.engine_id,
                symbol=self.symbol,
                source_timeframe=self.source_timeframe,
                confirmation_timeframe=self.confirmation_timeframe,
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

        return self.get_snapshot()

    def process_event(self, event: Any) -> ActivationSnapshot:
        """Dispatches and processes a single event through the activation reducer transactionally."""
        checkpoint = self.create_checkpoint()
        try:
            if isinstance(event, ExactPricePrint):
                return self._process_exact_price_print(event)
            elif isinstance(event, SourceCancellationEvent):
                return self._process_cancellation_event(event)
            elif isinstance(event, ExternalCommitEvent):
                return self._process_external_commit_event(event)
            elif isinstance(event, IntervalBoundedCandleEvidence):
                return self._process_candle_evidence(event)
            elif isinstance(event, CoverageEvidence):
                return self._process_coverage_evidence(event)
            elif isinstance(event, RegisterMembersEvent):
                return self._process_register_members_event(event)
            else:
                raise TypeError(f"Unsupported event type: {type(event)!r}")
        except Exception:
            self.restore_checkpoint(checkpoint)
            raise

    def process_batch(self, events: Sequence[Any]) -> ActivationSnapshot:
        """Processes a sequence of events atomically. Rolls back state if any event fails."""
        checkpoint = self.create_checkpoint()
        try:
            for ev in events:
                self.process_event(ev)
            return self.get_snapshot()
        except Exception:
            self.restore_checkpoint(checkpoint)
            raise

    def replay(
        self,
        events: Sequence[Any],
        initial_members: Optional[Sequence[SourceMemberReference]] = None,
    ) -> List[ActivationSnapshot]:
        """Performs fresh, deterministic replay from baseline on an isolated engine, returning prefix snapshots."""
        isolated_engine = ActivationEngine(self._config)
        if initial_members:
            isolated_engine.register_source_members(initial_members)

        snapshots = []
        for ev in events:
            snap = isolated_engine.process_event(ev)
            snapshots.append(snap)
        return snapshots

    def reset(self) -> None:
        """Completely resets engine state to fresh baseline while preserving immutable config."""
        self._current_members.clear()
        self._active_activations.clear()
        self._terminal_activations.clear()
        self._rearm_controllers.clear()
        self._processed_events.clear()
        self._observation_associations.clear()
        self._member_consumed_observations.clear()
        self._generation_counts.clear()
        self._last_processed_sequence = None
        self._last_processed_timestamp = None
        self._coverage_status = CoverageStatus.COMPLETE

    def get_snapshot(self) -> ActivationSnapshot:
        """Returns an immutable snapshot of current engine state."""
        return ActivationSnapshot(
            engine_id=self.engine_id,
            symbol=self.symbol,
            source_timeframe=self.source_timeframe,
            confirmation_timeframe=self.confirmation_timeframe,
            sequence_domain=self.sequence_domain,
            active_activations=MappingProxyType(dict(self._active_activations)),
            terminal_activations=tuple(self._terminal_activations),
            coverage_status=self._coverage_status,
            last_processed_sequence=self._last_processed_sequence,
            last_processed_timestamp=self._last_processed_timestamp,
            current_members=MappingProxyType(dict(self._current_members)),
            rearm_controllers=MappingProxyType(dict(self._rearm_controllers)),
        )

    # -------------------------------------------------------------------------
    # Internal Event Reducer Methods
    # -------------------------------------------------------------------------

    def _validate_sequence_and_domain(
        self,
        event_id: str,
        sequence_domain: SequenceDomain,
        sequence_ref: int,
        timestamp: Optional[datetime],
        event_payload: Any,
    ) -> bool:
        """Validates domain, monotonicity, and idempotence. Returns True if event is a duplicate no-op."""
        if sequence_domain != self.sequence_domain:
            raise DomainMismatchError(
                f"Event sequence domain {sequence_domain} does not match engine domain {self.sequence_domain}"
            )

        # Idempotence & conflict check
        if event_id in self._processed_events:
            prev_event = self._processed_events[event_id]
            if prev_event == event_payload:
                return True  # Idempotent duplicate: skip processing
            raise ConflictingEventError(
                f"Event ID {event_id!r} already processed with conflicting payload: {event_payload!r} vs {prev_event!r}"
            )

        # Strict monotonic sequence ref for distinct events:
        # Rejects sequence_ref <= last_processed_sequence
        if self._last_processed_sequence is not None:
            if sequence_ref <= self._last_processed_sequence:
                raise SequenceOrderError(
                    f"Sequence ref {sequence_ref} <= last processed sequence {self._last_processed_sequence}. "
                    "Distinct events must have strictly increasing sequence references."
                )

        # Monotonic timestamp check (if timestamps are known)
        if timestamp is not None and self._last_processed_timestamp is not None:
            if timestamp < self._last_processed_timestamp:
                raise SequenceOrderError(
                    f"Timestamp {timestamp} is strictly earlier than last processed timestamp {self._last_processed_timestamp}"
                )

        self._processed_events[event_id] = event_payload
        self._last_processed_sequence = sequence_ref
        if timestamp is not None:
            self._last_processed_timestamp = timestamp
        return False

    def _process_register_members_event(self, event: RegisterMembersEvent) -> ActivationSnapshot:
        is_duplicate = self._validate_sequence_and_domain(
            event_id=event.event_id,
            sequence_domain=event.sequence_domain,
            sequence_ref=event.sequence_ref,
            timestamp=event.timestamp,
            event_payload=event,
        )
        if is_duplicate:
            return self.get_snapshot()

        return self.register_source_members(event.members)

    def _process_exact_price_print(self, event: ExactPricePrint) -> ActivationSnapshot:
        # Validate configured price basis
        if event.price_basis != self.price_basis:
            raise InvalidEvidenceError(
                f"Event price basis {event.price_basis} does not match engine configured basis {self.price_basis}"
            )

        is_duplicate = self._validate_sequence_and_domain(
            event_id=event.observation_id,
            sequence_domain=event.sequence_domain,
            sequence_ref=event.sequence_ref,
            timestamp=event.timestamp,
            event_payload=event,
        )
        if is_duplicate:
            return self.get_snapshot()

        # Evaluate against all currently registered members
        for member_key, member in list(self._current_members.items()):
            if member_key in self._rearm_controllers:
                # Under active rearm controller supervision: handled below
                continue

            # Fail closed on coverage
            if self._coverage_status != CoverageStatus.COMPLETE:
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

            rec = self._active_activations.get(member_key)
            if rec is None or rec.state in (ActivationState.INACTIVE_ELIGIBLE, ActivationState.BLOCKED_UNKNOWN_ORDER):
                if is_inside:
                    # Check evidence recycling across generations for this level
                    consumed = self._member_consumed_observations.get(member_key, set())
                    if event.observation_id in consumed:
                        # Recycled evidence rejected!
                        continue

                    # First valid touch transitions to PENDING_ACTIVATION
                    gen_seq = self._generation_counts.get(member_key, 0) + 1
                    self._generation_counts[member_key] = gen_seq
                    act_id = format_activation_id(
                        self.engine_id, self.source_timeframe, self.symbol, member.set_id, member.role, gen_seq
                    )
                    new_rec = ActivationRecord(
                        activation_id=act_id,
                        engine_id=self.engine_id,
                        symbol=self.symbol,
                        source_timeframe=self.source_timeframe,
                        confirmation_timeframe=self.confirmation_timeframe,
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
                    self._active_activations[member_key] = new_rec
                    self._observation_associations.setdefault(event.observation_id, set()).add(act_id)
                    self._member_consumed_observations.setdefault(member_key, set()).add(event.observation_id)
                elif is_outside:
                    if rec is not None:
                        self._active_activations[member_key] = replace(rec, last_observed_position="OUTSIDE")

            elif rec.state in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
                if is_inside:
                    # Repeated touch does NOT reset first_touch_time
                    self._active_activations[member_key] = replace(rec, last_observed_position="INSIDE")
                elif is_outside:
                    # Note outside departure while pending
                    self._active_activations[member_key] = replace(rec, last_observed_position="OUTSIDE")

        # Evaluate rearm controllers decoupled from activation records
        for member_key, ctrl in list(self._rearm_controllers.items()):
            member = self._current_members.get(member_key)
            if member is None:
                continue

            # Fail closed on coverage
            if self._coverage_status != CoverageStatus.COMPLETE:
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
                    self._rearm_controllers[member_key] = replace(
                        ctrl,
                        state=ActivationState.OUT_OF_ZONE_ARMED,
                        rearm_armed=True,
                        last_observed_position="OUTSIDE",
                    )
                elif is_inside:
                    # Lingering inside without departure: blocks rearming
                    self._rearm_controllers[member_key] = replace(
                        ctrl,
                        last_observed_position="INSIDE",
                    )

            elif ctrl.state == ActivationState.OUT_OF_ZONE_ARMED:
                if is_inside:
                    consumed = self._member_consumed_observations.get(member_key, set())
                    if event.observation_id in consumed:
                        continue

                    # Fresh touch rearms to REARMED_PENDING with a brand-new activation ID!
                    gen_seq = ctrl.generation_seq
                    self._generation_counts[member_key] = gen_seq
                    act_id = format_activation_id(
                        self.engine_id, self.source_timeframe, self.symbol, member.set_id, member.role, gen_seq
                    )
                    new_rec = ActivationRecord(
                        activation_id=act_id,
                        engine_id=self.engine_id,
                        symbol=self.symbol,
                        source_timeframe=self.source_timeframe,
                        confirmation_timeframe=self.confirmation_timeframe,
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
                    self._active_activations[member_key] = new_rec
                    self._rearm_controllers.pop(member_key, None)
                    self._observation_associations.setdefault(event.observation_id, set()).add(act_id)
                    self._member_consumed_observations.setdefault(member_key, set()).add(event.observation_id)
                elif is_outside:
                    self._rearm_controllers[member_key] = replace(
                        ctrl,
                        last_observed_position="OUTSIDE",
                    )

        return self.get_snapshot()

    def _process_cancellation_event(self, event: SourceCancellationEvent) -> ActivationSnapshot:
        is_duplicate = self._validate_sequence_and_domain(
            event_id=event.event_id,
            sequence_domain=event.sequence_domain,
            sequence_ref=event.sequence_ref,
            timestamp=event.timestamp,
            event_payload=event,
        )
        if is_duplicate:
            return self.get_snapshot()

        # Identify all members affected by this source cancellation
        members_to_cancel: List[str] = []
        for member_key, member in list(self._current_members.items()):
            if event.cancellation_reason == CancellationReason.SOURCE_CHOCH:
                # Source CHOCH invalidates all levels in old direction (or all if not specified)
                if event.affected_direction is None or member.direction == event.affected_direction:
                    members_to_cancel.append(member_key)
            elif event.cancellation_reason == CancellationReason.SOURCE_REPLACEMENT:
                # Pullback t2 replacement invalidates outgoing set members
                if event.target_set_id is None or member.set_id == event.target_set_id:
                    members_to_cancel.append(member_key)

        for member_key in members_to_cancel:
            # 1. Remove membership eligibility permanently from current members
            member = self._current_members.pop(member_key, None)

            # 2. Transition active activation to terminal if it was pending or rearmed pending
            rec = self._active_activations.pop(member_key, None)
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
                self._terminal_activations.append(term_rec)

            # 3. Disable rearm controller if present (zero second terminal outcome for prior activation ID!)
            self._rearm_controllers.pop(member_key, None)

        return self.get_snapshot()

    def _process_external_commit_event(self, event: ExternalCommitEvent) -> ActivationSnapshot:
        is_duplicate = self._validate_sequence_and_domain(
            event_id=event.event_id,
            sequence_domain=event.sequence_domain,
            sequence_ref=event.sequence_ref,
            timestamp=event.timestamp,
            event_payload=event,
        )
        if is_duplicate:
            return self.get_snapshot()

        # External commit cancels competing pending activations, excluding the winner
        for member_key, rec in list(self._active_activations.items()):
            # Exclude winner from cancellation
            is_winner = (
                event.winning_engine_id == self.engine_id
                and event.winning_set_id == rec.set_id
                and event.winning_role == rec.role
            )
            if is_winner:
                continue

            if rec.state in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
                # 1. Terminalize active activation (single, unique terminal outcome per activation ID)
                self._active_activations.pop(member_key, None)
                term_rec = replace(
                    rec,
                    state=ActivationState.CANCELLED_EXTERNAL_ENTRY,
                    cancellation_reason=CancellationReason.EXTERNAL_ENTRY,
                    cancellation_time=event.timestamp,
                    cancellation_sequence_ref=event.sequence_ref,
                    terminal=True,
                )
                self._terminal_activations.append(term_rec)

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
                self._rearm_controllers[member_key] = controller

        return self.get_snapshot()

    def _process_candle_evidence(self, event: IntervalBoundedCandleEvidence) -> ActivationSnapshot:
        is_duplicate = self._validate_sequence_and_domain(
            event_id=event.event_id,
            sequence_domain=event.sequence_domain,
            sequence_ref=event.sequence_ref,
            timestamp=event.timestamp or event.interval_close,
            event_payload=event,
        )
        if is_duplicate:
            return self.get_snapshot()

        # Check intra-candle availability or unknown sequence
        for member_key, member in list(self._current_members.items()):
            rec = self._active_activations.get(member_key)
            # Uncertain candle evidence must NOT erase an already-authoritative pending or rearmed activation
            if rec is not None and rec.state in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
                continue

            avail = member.eligibility_available_time
            if avail is not None and event.interval_open < avail < event.interval_close:
                # Intra-candle availability
                if not event.sub_bar_sequence_available:
                    # Cannot prove sequence relative to availability: fail closed for unactivated level
                    if rec is not None:
                        self._active_activations[member_key] = replace(
                            rec,
                            state=ActivationState.BLOCKED_UNKNOWN_ORDER,
                            blocked_reason="UNKNOWN_ORDER_INTRA_CANDLE_AVAILABILITY",
                        )

        return self.get_snapshot()

    def _process_coverage_evidence(self, event: CoverageEvidence) -> ActivationSnapshot:
        is_duplicate = self._validate_sequence_and_domain(
            event_id=event.event_id,
            sequence_domain=event.sequence_domain,
            sequence_ref=event.sequence_ref,
            timestamp=event.timestamp,
            event_payload=event,
        )
        if is_duplicate:
            return self.get_snapshot()

        # Scope validation: only update coverage if scope matches this engine's context
        valid_scopes = {
            self.symbol,
            f"{self.symbol}_{self.source_timeframe}",
            self.engine_id,
            "ALL",
            "GLOBAL",
        }
        if event.scope in valid_scopes:
            self._coverage_status = event.coverage_status
        return self.get_snapshot()

    def create_checkpoint(self) -> Dict[str, Any]:
        """Creates an internal state checkpoint for atomic rollback."""
        return {
            "current_members": dict(self._current_members),
            "active_activations": dict(self._active_activations),
            "terminal_activations": list(self._terminal_activations),
            "rearm_controllers": dict(self._rearm_controllers),
            "processed_events": dict(self._processed_events),
            "observation_associations": {k: set(v) for k, v in self._observation_associations.items()},
            "member_consumed_observations": {k: set(v) for k, v in self._member_consumed_observations.items()},
            "generation_counts": dict(self._generation_counts),
            "last_processed_sequence": self._last_processed_sequence,
            "last_processed_timestamp": self._last_processed_timestamp,
            "coverage_status": self._coverage_status,
        }

    def restore_checkpoint(self, cp: Dict[str, Any]) -> None:
        """Restores internal state from a checkpoint on atomic rollback."""
        self._current_members = dict(cp["current_members"])
        self._active_activations = dict(cp["active_activations"])
        self._terminal_activations = list(cp["terminal_activations"])
        self._rearm_controllers = dict(cp["rearm_controllers"])
        self._processed_events = dict(cp["processed_events"])
        self._observation_associations = {k: set(v) for k, v in cp["observation_associations"].items()}
        self._member_consumed_observations = {k: set(v) for k, v in cp["member_consumed_observations"].items()}
        self._generation_counts = dict(cp["generation_counts"])
        self._last_processed_sequence = cp["last_processed_sequence"]
        self._last_processed_timestamp = cp["last_processed_timestamp"]
        self._coverage_status = cp["coverage_status"]

    _create_checkpoint = create_checkpoint
    _restore_checkpoint = restore_checkpoint
