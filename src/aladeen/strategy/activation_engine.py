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

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set

from .activation_evidence import (
    process_candle_evidence,
    process_cancellation_event,
    process_coverage_evidence,
    process_external_commit_event,
)
from .activation_handlers import (
    process_exact_price_print,
    process_register_members_event,
    register_source_members,
)
from .activation_state import ActivationEngineState
from .activation_types import (
    ActivationRecord,
    ActivationSnapshot,
    CoverageEvidence,
    CoverageStatus,
    ExactPricePrint,
    ExternalCommitEvent,
    IntervalBoundedCandleEvidence,
    PriceBasis,
    RearmController,
    RegisterMembersEvent,
    SequenceDomain,
    SourceCancellationEvent,
    SourceMemberReference,
    TIMEFRAME_CONFIRMATION_MAP,
)


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
        self._state = ActivationEngineState(
            engine_id=config.engine_id,
            symbol=config.symbol,
            source_timeframe=config.source_timeframe,
            confirmation_timeframe=self._confirmation_timeframe,
            sequence_domain=config.sequence_domain,
        )

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

    @property
    def _current_members(self) -> Dict[str, SourceMemberReference]:
        return self._state.current_members

    @property
    def _active_activations(self) -> Dict[str, ActivationRecord]:
        return self._state.active_activations

    @property
    def _terminal_activations(self) -> List[ActivationRecord]:
        return self._state.terminal_activations

    @property
    def _rearm_controllers(self) -> Dict[str, RearmController]:
        return self._state.rearm_controllers

    @property
    def _processed_events(self) -> Dict[str, Any]:
        return self._state.processed_events

    @property
    def _observation_associations(self) -> Dict[str, Set[str]]:
        return self._state.observation_associations

    @property
    def _member_consumed_observations(self) -> Dict[str, Set[str]]:
        return self._state.member_consumed_observations

    @property
    def _generation_counts(self) -> Dict[str, int]:
        return self._state.generation_counts

    @property
    def _last_processed_sequence(self) -> Optional[int]:
        return self._state.last_processed_sequence

    @property
    def _last_processed_timestamp(self) -> Optional[datetime]:
        return self._state.last_processed_timestamp

    @property
    def _coverage_status(self) -> CoverageStatus:
        return self._state.coverage_status

    def register_source_member(self, member: SourceMemberReference) -> ActivationSnapshot:
        """Registers a single eligible source level member with the engine."""
        return self.register_source_members([member])

    def register_source_members(self, members: Sequence[SourceMemberReference]) -> ActivationSnapshot:
        """Registers a sequence of eligible source level members atomically."""
        return register_source_members(self._state, members)

    def process_event(self, event: Any) -> ActivationSnapshot:
        """Dispatches and processes a single event through the activation reducer transactionally."""
        checkpoint = self.create_checkpoint()
        try:
            if isinstance(event, ExactPricePrint):
                return process_exact_price_print(self._state, event, self.price_basis)
            elif isinstance(event, SourceCancellationEvent):
                return process_cancellation_event(self._state, event)
            elif isinstance(event, ExternalCommitEvent):
                return process_external_commit_event(self._state, event)
            elif isinstance(event, IntervalBoundedCandleEvidence):
                return process_candle_evidence(self._state, event)
            elif isinstance(event, CoverageEvidence):
                return process_coverage_evidence(self._state, event)
            elif isinstance(event, RegisterMembersEvent):
                return process_register_members_event(self._state, event)
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
        self._state.reset()

    def get_snapshot(self) -> ActivationSnapshot:
        """Returns an immutable snapshot of current engine state."""
        return self._state.get_snapshot()

    def create_checkpoint(self) -> Dict[str, Any]:
        """Creates an internal state checkpoint for atomic rollback."""
        return self._state.create_checkpoint()

    def restore_checkpoint(self, cp: Dict[str, Any]) -> None:
        """Restores internal state from a checkpoint on atomic rollback."""
        self._state.restore_checkpoint(cp)

    _create_checkpoint = create_checkpoint
    _restore_checkpoint = restore_checkpoint
