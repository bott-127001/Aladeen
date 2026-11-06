"""Internal state container and checkpoint management for ActivationEngine.

Provides:
- ActivationEngineState: encapsulated mutable state for the activation state machine.
- Complete checkpoint creation and restoration for transactional atomicity.
- Immutable snapshot projection.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from aladeen.strategy.activation_types import (
    ActivationLifecycleSnapshot,
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    RearmController,
    SequenceDomain,
    SourceMemberReference,
)


class ActivationEngineState:
    """Encapsulates all mutable state for an ActivationEngine instance.

    Guarantees bit-for-bit checkpoint restoration across all tracking dictionaries,
    consumed observation sets, and generation counters.
    """

    def __init__(self, engine_id: str, symbol: str, source_timeframe: str, confirmation_timeframe: str, sequence_domain: SequenceDomain) -> None:
        self.engine_id = engine_id
        self.symbol = symbol
        self.source_timeframe = source_timeframe
        self.confirmation_timeframe = confirmation_timeframe
        self.sequence_domain = sequence_domain

        # Core state collections
        self.current_members: Dict[str, SourceMemberReference] = {}
        self.active_activations: Dict[str, ActivationRecord] = {}
        self.terminal_activations: List[ActivationRecord] = []
        self.rearm_controllers: Dict[str, RearmController] = {}

        # Observation associations and consumption tracking
        self.processed_events: Dict[str, Any] = {}
        self.observation_associations: Dict[str, Set[str]] = {}
        self.member_consumed_observations: Dict[str, Set[str]] = {}
        self.generation_counts: Dict[str, int] = {}

        # Sequence and coverage tracking
        self.last_processed_sequence: Optional[int] = None
        self.last_processed_timestamp: Optional[datetime] = None
        self.coverage_status: CoverageStatus = CoverageStatus.COMPLETE

        # Authoritative invalidation tracking (prevents re-registration of cancelled outgoing sets)
        self.invalidated_member_keys: Set[str] = set()
        self.invalidated_set_ids: Set[str] = set()

    def create_checkpoint(self) -> Dict[str, Any]:
        """Creates an internal state checkpoint for atomic rollback."""
        return {
            "current_members": dict(self.current_members),
            "active_activations": dict(self.active_activations),
            "terminal_activations": list(self.terminal_activations),
            "rearm_controllers": dict(self.rearm_controllers),
            "processed_events": dict(self.processed_events),
            "observation_associations": {k: set(v) for k, v in self.observation_associations.items()},
            "member_consumed_observations": {k: set(v) for k, v in self.member_consumed_observations.items()},
            "generation_counts": dict(self.generation_counts),
            "last_processed_sequence": self.last_processed_sequence,
            "last_processed_timestamp": self.last_processed_timestamp,
            "coverage_status": self.coverage_status,
            "invalidated_member_keys": set(self.invalidated_member_keys),
            "invalidated_set_ids": set(self.invalidated_set_ids),
        }

    def restore_checkpoint(self, cp: Dict[str, Any]) -> None:
        """Restores internal state from a checkpoint on atomic rollback."""
        self.current_members = dict(cp["current_members"])
        self.active_activations = dict(cp["active_activations"])
        self.terminal_activations = list(cp["terminal_activations"])
        self.rearm_controllers = dict(cp["rearm_controllers"])
        self.processed_events = dict(cp["processed_events"])
        self.observation_associations = {k: set(v) for k, v in cp["observation_associations"].items()}
        self.member_consumed_observations = {k: set(v) for k, v in cp["member_consumed_observations"].items()}
        self.generation_counts = dict(cp["generation_counts"])
        self.last_processed_sequence = cp["last_processed_sequence"]
        self.last_processed_timestamp = cp["last_processed_timestamp"]
        self.coverage_status = cp["coverage_status"]
        self.invalidated_member_keys = set(cp["invalidated_member_keys"])
        self.invalidated_set_ids = set(cp["invalidated_set_ids"])

    def reset(self) -> None:
        """Resets all mutable state collections to fresh baseline."""
        self.current_members.clear()
        self.active_activations.clear()
        self.terminal_activations.clear()
        self.rearm_controllers.clear()
        self.processed_events.clear()
        self.observation_associations.clear()
        self.member_consumed_observations.clear()
        self.generation_counts.clear()
        self.last_processed_sequence = None
        self.last_processed_timestamp = None
        self.coverage_status = CoverageStatus.COMPLETE
        self.invalidated_member_keys.clear()
        self.invalidated_set_ids.clear()

    def get_snapshot(self) -> ActivationLifecycleSnapshot:
        """Returns an immutable snapshot projection of the engine's current state."""
        return ActivationLifecycleSnapshot(
            engine_id=self.engine_id,
            symbol=self.symbol,
            source_timeframe=self.source_timeframe,
            confirmation_timeframe=self.confirmation_timeframe,
            sequence_domain=self.sequence_domain,
            active_activations=MappingProxyType(dict(self.active_activations)),
            terminal_activations=tuple(self.terminal_activations),
            coverage_status=self.coverage_status,
            last_processed_sequence=self.last_processed_sequence,
            last_processed_timestamp=self.last_processed_timestamp,
            current_members=MappingProxyType(dict(self.current_members)),
            rearm_controllers=MappingProxyType(dict(self.rearm_controllers)),
        )
