"""Pure Trend Joining Level (TJL) lifecycle reducer and state machine.

Scope & Design Boundary:
-------------------------
- Pure calculation and state transition logic independent of MT5, UI, or IO.
- Consumes validated structural observations (TJLStructuralObservation).
- Strictly immutable snapshots and event records.
- Enforces stable level identity formula, exact zero-width geometry,
  idempotent re-observation, and atomic set replacement with explicit outgoing set identification.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .types import Direction, StrategyCandle, SwingPoint
from .tjl_types import (
    CurrentEligibleSet,
    PhysicalLevel,
    StableLevelId,
    TJLFingerprint,
    TJLLabel,
    TJLSide,
    TJLSnapshot,
    TJLStructuralObservation,
    TJLTransitionRecord,
    TJLTransitionType,
    TJLZone,
)


class TJLReducer:
    """Pure lifecycle state machine managing TJL labels, geometry, and current-set eligibility.

    PROVENANCE TRUST BOUNDARY:
    Explicit event positions passed in TJLStructuralObservation represent validated input
    contract parameters, not independently authenticated cryptographic proofs.
    - Coordinator Context: In integrated execution, TJLCoordinator derives these positions directly
      from authoritative MSMChochCoordinator completed candle history and confirmed event positions.
    - Reducer Context: When synthetic or external callers invoke the standalone TJLReducer directly,
      the reducer strictly enforces internal consistency rules (structural epochs, strictly increasing
      observation event positions, dependent event horizon limits, and exact source candle body edges).
      The reducer does not claim to detect fabricated-yet-internally-consistent event metadata without
      receiving the underlying event history.
    """

    def __init__(
        self,
        source_engine_id: str,
        symbol_feed_id: str,
        source_timeframe: str,
    ) -> None:
        if not isinstance(source_engine_id, str) or not source_engine_id.strip():
            raise ValueError(f"source_engine_id must be non-empty string, got {source_engine_id!r}")
        if not isinstance(symbol_feed_id, str) or not symbol_feed_id.strip():
            raise ValueError(f"symbol_feed_id must be non-empty string, got {symbol_feed_id!r}")
        if not isinstance(source_timeframe, str) or not source_timeframe.strip():
            raise ValueError(f"source_timeframe must be non-empty string, got {source_timeframe!r}")

        self._source_engine_id: str = source_engine_id
        self._symbol_feed_id: str = symbol_feed_id
        self._source_timeframe: str = source_timeframe

        self._current_direction: Optional[Direction] = None
        self._current_eligible_set: Optional[CurrentEligibleSet] = None
        self._historical_sets: List[CurrentEligibleSet] = []
        self._physical_levels: Dict[StableLevelId, PhysicalLevel] = {}
        self._role_zones: Dict[Tuple[StableLevelId, TJLLabel], TJLZone] = {}
        self._all_labeled_zones: List[TJLZone] = []
        self._outgoing_cancellation_intent: bool = False
        self._last_transition: Optional[TJLTransitionRecord] = None
        self._transition_history: List[TJLTransitionRecord] = []
        self._is_unresolved: bool = False
        self._unresolved_diagnostic: Optional[str] = None
        self._last_processed_index: int = -1
        self._last_received_index: int = -1
        self._last_received_open_time: Optional[datetime] = None
        self._received_indices: Set[int] = set()
        self._set_counter: int = 0
        self._structural_epoch: int = 0
        self._epoch_choch_event_pos: Optional[int] = None
        self._last_received_event_pos: Optional[int] = None
        self._last_choch_time: Optional[datetime] = None
        self._last_choch_c2_index: Optional[int] = None
        self._last_choch_event_time: Optional[datetime] = None

    @property
    def source_engine_id(self) -> str:
        return self._source_engine_id

    @property
    def symbol_feed_id(self) -> str:
        return self._symbol_feed_id

    @property
    def source_timeframe(self) -> str:
        return self._source_timeframe

    @property
    def current_eligible_set(self) -> Optional[CurrentEligibleSet]:
        return self._current_eligible_set

    @property
    def is_unresolved(self) -> bool:
        return self._is_unresolved

    @property
    def last_processed_index(self) -> int:
        return self._last_processed_index

    @property
    def last_received_index(self) -> int:
        return self._last_received_index if self._last_received_index >= 0 else self._last_processed_index

    @property
    def structural_epoch(self) -> int:
        return self._structural_epoch

    @property
    def last_received_event_pos(self) -> Optional[int]:
        return self._last_received_event_pos

    def reset(self) -> None:
        """Resets the reducer to initial clean state."""
        self._current_direction = None
        self._current_eligible_set = None
        self._historical_sets.clear()
        self._physical_levels.clear()
        self._role_zones.clear()
        self._all_labeled_zones.clear()
        self._outgoing_cancellation_intent = False
        self._last_transition = None
        self._transition_history.clear()
        self._is_unresolved = False
        self._unresolved_diagnostic = None
        self._last_processed_index = -1
        self._last_received_index = -1
        self._last_received_open_time = None
        self._received_indices.clear()
        self._set_counter = 0
        self._structural_epoch = 0
        self._epoch_choch_event_pos = None
        self._last_received_event_pos = None
        self._last_choch_time = None
        self._last_choch_c2_index = None
        self._last_choch_event_time = None

    def reduce(self, observation: TJLStructuralObservation) -> TJLSnapshot:
        """Atomically evaluates a structural observation and advances state."""
        if not isinstance(observation, TJLStructuralObservation):
            raise TypeError(f"reduce requires TJLStructuralObservation, got {type(observation).__name__}")

        # Consistency checks between observation and reducer configuration
        if observation.source_engine_id != self._source_engine_id:
            raise ValueError(
                f"Observation source_engine_id mismatch: expected '{self._source_engine_id}', got '{observation.source_engine_id}'"
            )
        if observation.symbol_feed_id != self._symbol_feed_id:
            raise ValueError(
                f"Observation symbol_feed_id mismatch: expected '{self._symbol_feed_id}', got '{observation.symbol_feed_id}'"
            )
        if observation.source_timeframe != self._source_timeframe:
            raise ValueError(
                f"Observation source_timeframe mismatch: expected '{self._source_timeframe}', got '{observation.source_timeframe}'"
            )

        # Duplicate and chronological checks using candle_open_time
        if observation.candle_index in self._received_indices:
            raise ValueError(f"Duplicate observation candle index detected: {observation.candle_index}")
        if (
            self._last_received_open_time is not None
            and observation.candle_open_time <= self._last_received_open_time
        ):
            raise ValueError(
                f"Non-chronological observation open_time: {observation.candle_open_time} <= {self._last_received_open_time}"
            )

        # Monotonic observation event position check (strictly increasing)
        if (
            self._last_received_event_pos is not None
            and observation.observation_event_pos <= self._last_received_event_pos
        ):
            raise ValueError(
                f"Non-strictly-increasing observation_event_pos: {observation.observation_event_pos} <= {self._last_received_event_pos}"
            )

        # Authoritative Structural Epoch Check
        if observation.structural_epoch != self._structural_epoch:
            raise ValueError(
                f"Observation structural_epoch ({observation.structural_epoch}) does not match reducer epoch ({self._structural_epoch})"
            )

        # Direction consistency check
        if (
            self._current_direction is not None
            and observation.direction != self._current_direction
            and not observation.is_choch_event
        ):
            raise ValueError(
                f"Direction changed spontaneously from {self._current_direction} to {observation.direction} without is_choch_event=True"
            )

        # Authoritative Event-Position Provenance Checks
        if observation.ch_point is not None or observation.cl_point is not None:
            if observation.pair_confirmation_event_pos is None:
                raise ValueError("Observation with confirmed point requires explicit pair_confirmation_event_pos")
            if observation.pair_confirmation_event_pos > observation.observation_event_pos:
                raise ValueError(
                    f"pair_confirmation_event_pos ({observation.pair_confirmation_event_pos}) lies beyond observation_event_pos ({observation.observation_event_pos})"
                )
            if self._structural_epoch > 0 and not observation.is_choch_event:
                if observation.epoch_choch_event_pos is None:
                    raise ValueError(f"Post-CHOCH epoch {self._structural_epoch} requires explicit epoch_choch_event_pos")
                if observation.epoch_choch_event_pos != self._epoch_choch_event_pos:
                    raise ValueError(
                        f"Observation epoch_choch_event_pos ({observation.epoch_choch_event_pos}) does not match reducer epoch CHOCH pos ({self._epoch_choch_event_pos})"
                    )
                if observation.pair_confirmation_event_pos <= self._epoch_choch_event_pos:
                    raise ValueError(
                        f"Pre-CHOCH point (confirmed at pos {observation.pair_confirmation_event_pos}) cannot be used in structural epoch {self._structural_epoch} (CHOCH at pos {self._epoch_choch_event_pos})"
                    )

        if observation.tentative_p3 is not None:
            if observation.p3_identification_event_pos is None:
                raise ValueError("Observation with tentative_p3 requires explicit p3_identification_event_pos")
            if observation.p3_identification_event_pos > observation.observation_event_pos:
                raise ValueError(
                    f"p3_identification_event_pos ({observation.p3_identification_event_pos}) lies beyond observation_event_pos ({observation.observation_event_pos})"
                )
            if self._structural_epoch > 0 and not observation.is_choch_event:
                if observation.epoch_choch_event_pos is None:
                    raise ValueError(f"Post-CHOCH epoch {self._structural_epoch} requires explicit epoch_choch_event_pos")
                if observation.epoch_choch_event_pos != self._epoch_choch_event_pos:
                    raise ValueError(
                        f"Observation epoch_choch_event_pos ({observation.epoch_choch_event_pos}) does not match reducer epoch CHOCH pos ({self._epoch_choch_event_pos})"
                    )
                if observation.p3_identification_event_pos <= self._epoch_choch_event_pos:
                    raise ValueError(
                        f"Pre-CHOCH P3 (identified at pos {observation.p3_identification_event_pos}) cannot be used in structural epoch {self._structural_epoch} (CHOCH at pos {self._epoch_choch_event_pos})"
                    )

        # -----------------------------------------------------------------
        # Stage mutation in local working variables to ensure full atomicity
        # -----------------------------------------------------------------
        staged_direction = observation.direction
        staged_current_set = self._current_eligible_set
        staged_historical_sets = list(self._historical_sets)
        staged_physical_levels = dict(self._physical_levels)
        staged_role_zones = dict(self._role_zones)
        staged_all_labeled = list(self._all_labeled_zones)
        staged_transition_history = list(self._transition_history)
        staged_outgoing_cancellation = False
        staged_cancelled_set_id: Optional[str] = None
        staged_cancelled_fp: Optional[TJLFingerprint] = None
        staged_is_unresolved = self._is_unresolved
        staged_unresolved_diag = self._unresolved_diagnostic
        staged_last_processed = self._last_processed_index
        staged_set_counter = self._set_counter
        staged_epoch = self._structural_epoch
        staged_epoch_choch_event_pos = self._epoch_choch_event_pos
        staged_choch_time = self._last_choch_time
        staged_last_choch_c2_index = self._last_choch_c2_index
        staged_last_choch_event_time = self._last_choch_event_time
        newly_labeled: List[TJLZone] = []

        # 1. Unresolved State Handling
        if observation.is_unresolved or staged_is_unresolved:
            staged_is_unresolved = True
            staged_unresolved_diag = observation.unresolved_diagnostic or staged_unresolved_diag
            record = TJLTransitionRecord(
                transition_type=TJLTransitionType.BLOCKED_UNRESOLVED,
                outgoing_cancellation_intent=False,
                current_set=staged_current_set,
                newly_labeled_zones=(),
                transition_candle_index=observation.candle_index,
                transition_time=observation.availability_time,
                outgoing_cancelled_set_id=None,
                outgoing_cancelled_fingerprint=None,
                diagnostic=staged_unresolved_diag,
            )
            # Do NOT append receipt diagnostic to authoritative transition history, but update receipt metadata
            self._received_indices.add(observation.candle_index)
            self._last_received_index = observation.candle_index
            self._last_received_open_time = observation.candle_open_time
            self._last_received_event_pos = observation.observation_event_pos
            self._is_unresolved = staged_is_unresolved
            self._unresolved_diagnostic = staged_unresolved_diag
            self._last_transition = record
            self._outgoing_cancellation_intent = False
            return self.get_snapshot()

        # 2. Source CHOCH Invalidation
        if observation.is_choch_event:
            had_active_set = staged_current_set is not None
            if had_active_set:
                assert staged_current_set is not None
                staged_cancelled_set_id = staged_current_set.set_id
                staged_cancelled_fp = staged_current_set.fingerprint
                staged_current_set = None
                staged_outgoing_cancellation = True
            else:
                staged_outgoing_cancellation = False

            assert observation.new_choch_direction is not None
            staged_direction = observation.new_choch_direction
            staged_epoch += 1
            staged_epoch_choch_event_pos = observation.observation_event_pos
            staged_choch_time = observation.candle_open_time
            staged_last_choch_c2_index = observation.candle_index
            staged_last_choch_event_time = observation.availability_time

            record = TJLTransitionRecord(
                transition_type=TJLTransitionType.CHOCH_INVALIDATION,
                outgoing_cancellation_intent=staged_outgoing_cancellation,
                current_set=None,
                newly_labeled_zones=(),
                transition_candle_index=observation.candle_index,
                transition_time=observation.availability_time,
                outgoing_cancelled_set_id=staged_cancelled_set_id,
                outgoing_cancelled_fingerprint=staged_cancelled_fp,
                diagnostic="Invalidated by source CHOCH confirmation",
            )
            staged_transition_history.append(record)

            self._current_direction = staged_direction
            self._current_eligible_set = None
            self._outgoing_cancellation_intent = staged_outgoing_cancellation
            self._last_transition = record
            self._transition_history = staged_transition_history
            self._last_processed_index = observation.candle_index
            self._last_received_index = observation.candle_index
            self._last_received_open_time = observation.candle_open_time
            self._last_received_event_pos = observation.observation_event_pos
            self._received_indices.add(observation.candle_index)
            self._structural_epoch = staged_epoch
            self._epoch_choch_event_pos = staged_epoch_choch_event_pos
            self._last_choch_time = staged_choch_time
            self._last_choch_c2_index = staged_last_choch_c2_index
            self._last_choch_event_time = staged_last_choch_event_time
            return self.get_snapshot()

        # 3. Label Confirmed Swing Points and Compute Zones
        ch_zone: Optional[TJLZone] = None
        cl_zone: Optional[TJLZone] = None

        if observation.ch_point is not None:
            ch_candle = observation.source_candle_lookup.get(observation.ch_point.candle_index)
            if ch_candle is None:
                raise ValueError(
                    f"Missing source candle {observation.ch_point.candle_index} for confirmed high in lookup"
                )
            ch_label = TJLLabel.TJL1 if staged_direction == Direction.UPWARD else TJLLabel.TJL2_A_PLUS
            ch_level_id = StableLevelId(
                symbol_feed_id=self._symbol_feed_id,
                source_timeframe=self._source_timeframe,
                source_open_time=ch_candle.open_time,
                side=TJLSide.HIGH,
            )
            # Physical level geometry validation against cached
            if ch_level_id in staged_physical_levels:
                cached = staged_physical_levels[ch_level_id]
                if (
                    cached.lower_price != ch_candle.upper_body_edge
                    or cached.upper_price != ch_candle.high
                    or cached.source_candle_index != ch_candle.index
                    or cached.source_candle_open_time != ch_candle.open_time
                ):
                    raise ValueError(f"Conflicting physical level geometry for existing {ch_level_id}")
            else:
                staged_physical_levels[ch_level_id] = PhysicalLevel(
                    level_id=ch_level_id,
                    lower_price=ch_candle.upper_body_edge,
                    upper_price=ch_candle.high,
                    is_line=(ch_candle.upper_body_edge == ch_candle.high),
                    source_candle_index=ch_candle.index,
                    source_candle_open_time=ch_candle.open_time,
                )
            phys = staged_physical_levels[ch_level_id]

            # Contextual role zone
            role_key = (ch_level_id, ch_label)
            if role_key in staged_role_zones:
                ch_zone = staged_role_zones[role_key]
            else:
                conf_idx = (
                    observation.ch_point.confirmed_bar_index
                    if observation.ch_point.confirmed_bar_index is not None
                    else observation.candle_index
                )
                ch_zone = TJLZone(
                    level_id=ch_level_id,
                    label=ch_label,
                    lower_price=phys.lower_price,
                    upper_price=phys.upper_price,
                    is_line=phys.is_line,
                    source_candle_index=phys.source_candle_index,
                    source_candle_open_time=phys.source_candle_open_time,
                    confirmed_candle_index=conf_idx,
                    confirmed_time=observation.ch_point.confirmed_time,
                )
                staged_role_zones[role_key] = ch_zone
                staged_all_labeled.append(ch_zone)
                newly_labeled.append(ch_zone)

        if observation.cl_point is not None:
            cl_candle = observation.source_candle_lookup.get(observation.cl_point.candle_index)
            if cl_candle is None:
                raise ValueError(
                    f"Missing source candle {observation.cl_point.candle_index} for confirmed low in lookup"
                )
            cl_label = TJLLabel.TJL2_A_PLUS if staged_direction == Direction.UPWARD else TJLLabel.TJL1
            cl_level_id = StableLevelId(
                symbol_feed_id=self._symbol_feed_id,
                source_timeframe=self._source_timeframe,
                source_open_time=cl_candle.open_time,
                side=TJLSide.LOW,
            )
            # Physical level geometry validation against cached
            if cl_level_id in staged_physical_levels:
                cached = staged_physical_levels[cl_level_id]
                if (
                    cached.lower_price != cl_candle.low
                    or cached.upper_price != cl_candle.lower_body_edge
                    or cached.source_candle_index != cl_candle.index
                    or cached.source_candle_open_time != cl_candle.open_time
                ):
                    raise ValueError(f"Conflicting physical level geometry for existing {cl_level_id}")
            else:
                staged_physical_levels[cl_level_id] = PhysicalLevel(
                    level_id=cl_level_id,
                    lower_price=cl_candle.low,
                    upper_price=cl_candle.lower_body_edge,
                    is_line=(cl_candle.low == cl_candle.lower_body_edge),
                    source_candle_index=cl_candle.index,
                    source_candle_open_time=cl_candle.open_time,
                )
            phys = staged_physical_levels[cl_level_id]

            # Contextual role zone
            role_key = (cl_level_id, cl_label)
            if role_key in staged_role_zones:
                cl_zone = staged_role_zones[role_key]
            else:
                conf_idx = (
                    observation.cl_point.confirmed_bar_index
                    if observation.cl_point.confirmed_bar_index is not None
                    else observation.candle_index
                )
                cl_zone = TJLZone(
                    level_id=cl_level_id,
                    label=cl_label,
                    lower_price=phys.lower_price,
                    upper_price=phys.upper_price,
                    is_line=phys.is_line,
                    source_candle_index=phys.source_candle_index,
                    source_candle_open_time=phys.source_candle_open_time,
                    confirmed_candle_index=conf_idx,
                    confirmed_time=observation.cl_point.confirmed_time,
                )
                staged_role_zones[role_key] = cl_zone
                staged_all_labeled.append(cl_zone)
                newly_labeled.append(cl_zone)

        # 4. Current Eligible Set Lifecycle Evaluation
        has_full_structure = (
            observation.ch_point is not None
            and observation.cl_point is not None
            and observation.tentative_p3 is not None
        )

        if not has_full_structure:
            if staged_current_set is not None:
                # Continuation break (t1): record new labels, retain previous current set
                transition_type = TJLTransitionType.CONTINUATION_RETAINED
                staged_outgoing_cancellation = False
            else:
                # Before first eligible set
                transition_type = (
                    TJLTransitionType.LABELS_ONLY if newly_labeled else TJLTransitionType.IDEMPOTENT_NO_OP
                )
                staged_outgoing_cancellation = False
        else:
            assert observation.ch_point is not None
            assert observation.cl_point is not None
            assert observation.tentative_p3 is not None

            fp = TJLFingerprint(
                source_engine_id=self._source_engine_id,
                direction=staged_direction,
                ch_point_id=observation.ch_point.candle_index,
                cl_point_id=observation.cl_point.candle_index,
                p3_point_id=observation.tentative_p3.candle_index,
            )

            assert ch_zone is not None
            assert cl_zone is not None
            tjl1_zone = ch_zone if staged_direction == Direction.UPWARD else cl_zone
            tjl2_zone = cl_zone if staged_direction == Direction.UPWARD else ch_zone

            if staged_current_set is None:
                # First Set Creation
                staged_set_counter += 1
                new_set = CurrentEligibleSet(
                    set_id=f"SET_{staged_set_counter}",
                    fingerprint=fp,
                    direction=staged_direction,
                    source_engine_id=self._source_engine_id,
                    symbol_feed_id=self._symbol_feed_id,
                    source_timeframe=self._source_timeframe,
                    tjl1_zone=tjl1_zone,
                    tjl2_zone=tjl2_zone,
                    p3_source_index=observation.tentative_p3.candle_index,
                    p3_open_time=observation.tentative_p3.candle_open_time,
                    p3_price=observation.tentative_p3.price,
                    eligibility_available_time=observation.availability_time,  # Preserves None if unknown!
                    created_at_candle_index=observation.candle_index,
                )
                staged_current_set = new_set
                staged_historical_sets.append(new_set)
                staged_outgoing_cancellation = False
                transition_type = TJLTransitionType.FIRST_CREATION
            else:
                if fp == staged_current_set.fingerprint:
                    # Idempotent re-observation: preserve set without refreshing availability
                    staged_outgoing_cancellation = False
                    transition_type = TJLTransitionType.IDEMPOTENT_NO_OP
                else:
                    # Set Replacement (t2 pullback): new set, emit outgoing cancellation intent
                    staged_cancelled_set_id = staged_current_set.set_id
                    staged_cancelled_fp = staged_current_set.fingerprint
                    staged_set_counter += 1
                    new_set = CurrentEligibleSet(
                        set_id=f"SET_{staged_set_counter}",
                        fingerprint=fp,
                        direction=staged_direction,
                        source_engine_id=self._source_engine_id,
                        symbol_feed_id=self._symbol_feed_id,
                        source_timeframe=self._source_timeframe,
                        tjl1_zone=tjl1_zone,
                        tjl2_zone=tjl2_zone,
                        p3_source_index=observation.tentative_p3.candle_index,
                        p3_open_time=observation.tentative_p3.candle_open_time,
                        p3_price=observation.tentative_p3.price,
                        eligibility_available_time=observation.availability_time,
                        created_at_candle_index=observation.candle_index,
                    )
                    staged_current_set = new_set
                    staged_historical_sets.append(new_set)
                    staged_outgoing_cancellation = True
                    transition_type = TJLTransitionType.SET_REPLACEMENT

        record = TJLTransitionRecord(
            transition_type=transition_type,
            outgoing_cancellation_intent=staged_outgoing_cancellation,
            current_set=staged_current_set,
            newly_labeled_zones=tuple(newly_labeled),
            transition_candle_index=observation.candle_index,
            transition_time=observation.availability_time,
            outgoing_cancelled_set_id=staged_cancelled_set_id,
            outgoing_cancelled_fingerprint=staged_cancelled_fp,
            diagnostic=None,
        )
        staged_transition_history.append(record)

        # -------------------------------------------------------------
        # Commit all staged state mutations
        # -------------------------------------------------------------
        self._current_direction = staged_direction
        self._current_eligible_set = staged_current_set
        self._historical_sets = staged_historical_sets
        self._physical_levels = staged_physical_levels
        self._role_zones = staged_role_zones
        self._all_labeled_zones = staged_all_labeled
        self._transition_history = staged_transition_history
        self._outgoing_cancellation_intent = staged_outgoing_cancellation
        self._last_transition = record
        self._last_processed_index = observation.candle_index
        self._last_received_index = observation.candle_index
        self._last_received_open_time = observation.candle_open_time
        self._last_received_event_pos = observation.observation_event_pos
        self._received_indices.add(observation.candle_index)
        self._set_counter = staged_set_counter
        self._structural_epoch = staged_epoch
        self._last_choch_time = staged_choch_time

        return self.get_snapshot()

    def get_snapshot(self) -> TJLSnapshot:
        """Returns an immutable snapshot of the reducer execution state."""
        return TJLSnapshot(
            source_engine_id=self._source_engine_id,
            symbol_feed_id=self._symbol_feed_id,
            source_timeframe=self._source_timeframe,
            direction=self._current_direction,
            current_eligible_set=self._current_eligible_set,
            all_labeled_zones=tuple(self._all_labeled_zones),
            historical_sets=tuple(self._historical_sets),
            outgoing_cancellation_intent=self._outgoing_cancellation_intent,
            last_transition=self._last_transition,
            transition_history=tuple(self._transition_history),
            is_unresolved=self._is_unresolved,
            unresolved_diagnostic=self._unresolved_diagnostic,
            last_processed_index=self._last_processed_index,
            last_received_index=self._last_received_index if self._last_received_index >= 0 else self._last_processed_index,
            structural_epoch=self._structural_epoch,
        )
