"""Pure offline Tap and Zone Activation Lifecycle Engine.

Scope & Design Boundary:
-------------------------
- Pure calculation and state transition reducer independent of MT5, UI, or IO.
- Consumes discrete price prints, candle evidence, coverage evidence, and authoritative lifecycle cancellations.
- Strictly immutable snapshots and event records.
- Sequence domain scoping: compares event sequence references only within declared (feed_id, run_id).
- Unambiguous canonical activation ID encoding.
- Raw price observations are immutable facts; association with activations is tracked separately without mutating shared prints.
- Atomic batch processing with full state rollback on failure.
- Bit-for-bit idempotent replay determinism.
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
        """Registers a sequence of eligible source level members with the engine."""
        for m in members:
            if m.engine_id != self.engine_id and m.engine_id != "":
                # Scoped to engine
                pass
            self._current_members[m.member_key] = m

            # If member not yet in active activations, initialize its baseline status
            if m.member_key not in self._active_activations:
                if m.eligibility_available_time is None:
                    init_state = ActivationState.INACTIVE_INELIGIBLE
                    blocked = "UNKNOWN_AVAILABILITY_TIMING"
                elif m.usage_evidence_status != UsageEvidenceStatus.UNUSED:
                    init_state = ActivationState.INACTIVE_INELIGIBLE
                    blocked = "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"
                else:
                    init_state = ActivationState.INACTIVE_ELIGIBLE
                    blocked = None

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
        """Dispatches and processes a single event through the activation reducer."""
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
        else:
            raise TypeError(f"Unsupported event type: {type(event)!r}")

    def process_batch(self, events: Sequence[Any]) -> ActivationSnapshot:
        """Processes a sequence of events atomically. Rolls back state if any event fails."""
        checkpoint = self._create_checkpoint()
        try:
            for ev in events:
                self.process_event(ev)
            return self.get_snapshot()
        except Exception:
            self._restore_checkpoint(checkpoint)
            raise

    def replay(self, events: Sequence[Any]) -> List[ActivationSnapshot]:
        """Performs fresh, deterministic replay from baseline, returning prefix snapshots."""
        saved_members = list(self._current_members.values())
        self.reset()
        if saved_members:
            self.register_source_members(saved_members)
        snapshots = []
        for ev in events:
            snap = self.process_event(ev)
            snapshots.append(snap)
        return snapshots

    def reset(self) -> None:
        """Completely resets engine state to fresh baseline while preserving immutable config."""
        self._current_members.clear()
        self._active_activations.clear()
        self._terminal_activations.clear()
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
        )

    # -------------------------------------------------------------------------
    # Internal Event Reducer Methods
    # -------------------------------------------------------------------------

    def _validate_sequence_and_domain(
        self,
        event_id: str,
        sequence_domain: SequenceDomain,
        sequence_ref: int,
        timestamp: datetime,
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

        # Monotonicity check
        if self._last_processed_sequence is not None and sequence_ref < self._last_processed_sequence:
            raise SequenceOrderError(
                f"Sequence ref {sequence_ref} is strictly less than last processed sequence {self._last_processed_sequence}"
            )
        if self._last_processed_timestamp is not None and timestamp < self._last_processed_timestamp:
            raise SequenceOrderError(
                f"Timestamp {timestamp} is strictly earlier than last processed timestamp {self._last_processed_timestamp}"
            )

        self._processed_events[event_id] = event_payload
        self._last_processed_sequence = sequence_ref
        self._last_processed_timestamp = timestamp
        return False

    def _process_exact_price_print(self, event: ExactPricePrint) -> ActivationSnapshot:
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
            if rec is None or rec.state == ActivationState.INACTIVE_ELIGIBLE:
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

            elif rec.state == ActivationState.OUT_OF_ZONE_ARMED:
                # Level was armed for rearm!
                if is_inside:
                    consumed = self._member_consumed_observations.get(member_key, set())
                    if event.observation_id in consumed:
                        continue

                    # Fresh touch rearms to REARMED_PENDING!
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
                        state=ActivationState.REARMED_PENDING,
                        first_touch_time=event.timestamp,
                        first_touch_price=event.price,
                        trigger_observation_id=event.observation_id,
                        prior_activation_id=rec.activation_id,
                        rearm_armed=False,
                        last_observed_position="INSIDE",
                        usage_evidence_status=member.usage_evidence_status,
                        generation_seq=gen_seq,
                        terminal=False,
                    )
                    self._active_activations[member_key] = new_rec
                    self._observation_associations.setdefault(event.observation_id, set()).add(act_id)
                    self._member_consumed_observations.setdefault(member_key, set()).add(event.observation_id)

            elif rec.state == ActivationState.CANCELLED_EXTERNAL_ENTRY:
                # Path A: Cancelled while inside; awaiting confirmed outside departure
                if is_outside:
                    # Confirmed departure! Armed for next touch
                    self._active_activations[member_key] = replace(
                        rec,
                        state=ActivationState.OUT_OF_ZONE_ARMED,
                        rearm_armed=True,
                        last_observed_position="OUTSIDE",
                    )
                elif is_inside:
                    # Lingering inside without departure: blocks rearming
                    pass

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

        for member_key, rec in list(self._active_activations.items()):
            if rec.state in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
                should_cancel = False
                cancel_state = rec.state

                if event.cancellation_reason == CancellationReason.SOURCE_CHOCH:
                    # CHOCH cancels old direction
                    should_cancel = True
                    cancel_state = ActivationState.CANCELLED_SOURCE_CHOCH
                elif event.cancellation_reason == CancellationReason.SOURCE_REPLACEMENT:
                    # Replacement cancels outgoing set
                    if event.target_set_id is None or rec.set_id == event.target_set_id:
                        should_cancel = True
                        cancel_state = ActivationState.CANCELLED_SOURCE_REPLACEMENT

                if should_cancel:
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
                    # Reset active slot for this member
                    self._active_activations[member_key] = replace(
                        term_rec,
                        state=ActivationState.INACTIVE_ELIGIBLE,
                        first_touch_time=None,
                        first_touch_price=None,
                        trigger_observation_id=None,
                        terminal=False,
                    )

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

        # External commit cancels competing pending activations
        for member_key, rec in list(self._active_activations.items()):
            if rec.state in (ActivationState.PENDING_ACTIVATION, ActivationState.REARMED_PENDING):
                # Save outgoing record to terminal history
                term_rec = replace(
                    rec,
                    state=ActivationState.CANCELLED_EXTERNAL_ENTRY,
                    cancellation_reason=CancellationReason.EXTERNAL_ENTRY,
                    cancellation_time=event.timestamp,
                    cancellation_sequence_ref=event.sequence_ref,
                    terminal=True,
                )
                self._terminal_activations.append(term_rec)

                # Rearming evaluation: Path B (already outside) vs Path A (inside)
                if rec.last_observed_position == "OUTSIDE":
                    # Path B: Already outside at cancellation -> Armed immediately!
                    self._active_activations[member_key] = replace(
                        term_rec,
                        state=ActivationState.OUT_OF_ZONE_ARMED,
                        rearm_armed=True,
                        terminal=False,
                    )
                else:
                    # Path A: Inside or unknown -> un-armed; requires departure
                    self._active_activations[member_key] = replace(
                        term_rec,
                        state=ActivationState.CANCELLED_EXTERNAL_ENTRY,
                        rearm_armed=False,
                        terminal=False,
                    )

        return self.get_snapshot()

    def _process_candle_evidence(self, event: IntervalBoundedCandleEvidence) -> ActivationSnapshot:
        # Check intra-candle availability or unknown sequence
        for member_key, member in list(self._current_members.items()):
            avail = member.eligibility_available_time
            if avail is not None and event.interval_open < avail < event.interval_close:
                # Intra-candle availability
                if not event.sub_bar_sequence_available:
                    # Cannot prove sequence relative to availability: fail closed
                    rec = self._active_activations.get(member_key)
                    if rec is not None:
                        self._active_activations[member_key] = replace(
                            rec,
                            state=ActivationState.BLOCKED_UNKNOWN_ORDER,
                            blocked_reason="UNKNOWN_ORDER_INTRA_CANDLE_AVAILABILITY",
                        )

        return self.get_snapshot()

    def _process_coverage_evidence(self, event: CoverageEvidence) -> ActivationSnapshot:
        self._coverage_status = event.coverage_status
        return self.get_snapshot()

    def _create_checkpoint(self) -> Dict[str, Any]:
        """Creates an internal state checkpoint for atomic rollback."""
        return {
            "current_members": dict(self._current_members),
            "active_activations": dict(self._active_activations),
            "terminal_activations": list(self._terminal_activations),
            "processed_events": dict(self._processed_events),
            "observation_associations": {k: set(v) for k, v in self._observation_associations.items()},
            "member_consumed_observations": {k: set(v) for k, v in self._member_consumed_observations.items()},
            "generation_counts": dict(self._generation_counts),
            "last_processed_sequence": self._last_processed_sequence,
            "last_processed_timestamp": self._last_processed_timestamp,
            "coverage_status": self._coverage_status,
        }

    def _restore_checkpoint(self, cp: Dict[str, Any]) -> None:
        """Restores internal state from a checkpoint on atomic rollback."""
        self._current_members = dict(cp["current_members"])
        self._active_activations = dict(cp["active_activations"])
        self._terminal_activations = list(cp["terminal_activations"])
        self._processed_events = dict(cp["processed_events"])
        self._observation_associations = {k: set(v) for k, v in cp["observation_associations"].items()}
        self._member_consumed_observations = {k: set(v) for k, v in cp["member_consumed_observations"].items()}
        self._generation_counts = dict(cp["generation_counts"])
        self._last_processed_sequence = cp["last_processed_sequence"]
        self._last_processed_timestamp = cp["last_processed_timestamp"]
        self._coverage_status = cp["coverage_status"]
