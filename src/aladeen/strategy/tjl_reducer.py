"""Pure Trend Joining Level (TJL) lifecycle reducer and state machine.

Scope & Design Boundary:
-------------------------
- Pure calculation and state transition logic independent of MT5, UI, or IO.
- Consumes validated structural observations (TJLStructuralObservation).
- Strictly immutable snapshots and event records.
- Enforces stable level identity formula, idempotent re-observation, and
  atomic set replacement with outgoing cancellation intent.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from .types import Direction, StrategyCandle, SwingPoint
from .tjl_types import (
    CurrentEligibleSet,
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
    """Pure lifecycle state machine managing TJL labels, geometry, and current-set eligibility."""

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
        self._labeled_zones: Dict[StableLevelId, TJLZone] = {}
        self._all_labeled_zones: List[TJLZone] = []
        self._outgoing_cancellation_intent: bool = False
        self._last_transition: Optional[TJLTransitionRecord] = None
        self._is_unresolved: bool = False
        self._unresolved_diagnostic: Optional[str] = None
        self._last_processed_index: int = -1
        self._last_received_index: int = -1
        self._last_received_candle_time: Optional[datetime] = None
        self._received_indices: Set[int] = set()
        self._set_counter: int = 0

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

    def reset(self) -> None:
        """Resets the reducer to initial clean state."""
        self._current_direction = None
        self._current_eligible_set = None
        self._historical_sets.clear()
        self._labeled_zones.clear()
        self._all_labeled_zones.clear()
        self._outgoing_cancellation_intent = False
        self._last_transition = None
        self._is_unresolved = False
        self._unresolved_diagnostic = None
        self._last_processed_index = -1
        self._last_received_index = -1
        self._last_received_candle_time = None
        self._received_indices.clear()
        self._set_counter = 0

    def reduce(self, observation: TJLStructuralObservation) -> TJLSnapshot:
        """Atomically evaluates a structural observation and advances state.

        Guarantees:
        - Atomic execution: errors leave the reducer state completely unmutated.
        - Unresolved containment: blocks speculative eligibility, freezes last_processed_index.
        - CHOCH invalidation: immediately removes active set, preserves history.
        - Idempotence: re-observation with same fingerprint produces zero replacements or availability refreshes.
        """
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

        # Duplicate and chronological checks
        if observation.candle_index in self._received_indices:
            raise ValueError(f"Duplicate observation candle index detected: {observation.candle_index}")
        if (
            self._last_received_candle_time is not None
            and observation.candle_time is not None
            and observation.candle_time <= self._last_received_candle_time
        ):
            raise ValueError(
                f"Non-chronological observation time: {observation.candle_time} <= {self._last_received_candle_time}"
            )

        # -----------------------------------------------------------------
        # Stage mutation in local working variables to ensure full atomicity
        # -----------------------------------------------------------------
        staged_direction = observation.direction
        staged_current_set = self._current_eligible_set
        staged_historical_sets = list(self._historical_sets)
        staged_labeled_zones = dict(self._labeled_zones)
        staged_all_labeled = list(self._all_labeled_zones)
        staged_outgoing_cancellation = False
        staged_is_unresolved = self._is_unresolved
        staged_unresolved_diag = self._unresolved_diagnostic
        staged_last_processed = self._last_processed_index
        staged_set_counter = self._set_counter
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
                transition_time=observation.candle_time,
                diagnostic=staged_unresolved_diag,
            )
            # Commit receipt metadata without advancing authoritative processed state
            self._received_indices.add(observation.candle_index)
            self._last_received_index = observation.candle_index
            self._last_received_candle_time = observation.candle_time
            self._is_unresolved = staged_is_unresolved
            self._unresolved_diagnostic = staged_unresolved_diag
            self._last_transition = record
            return self.get_snapshot()

        # 2. Source CHOCH Invalidation
        if observation.is_choch_event:
            had_active_set = staged_current_set is not None
            if had_active_set:
                staged_current_set = None
                staged_outgoing_cancellation = True
            else:
                staged_outgoing_cancellation = False

            if observation.new_choch_direction is not None:
                staged_direction = observation.new_choch_direction

            record = TJLTransitionRecord(
                transition_type=TJLTransitionType.CHOCH_INVALIDATION,
                outgoing_cancellation_intent=staged_outgoing_cancellation,
                current_set=None,
                newly_labeled_zones=(),
                transition_candle_index=observation.candle_index,
                transition_time=observation.candle_time,
                diagnostic="Invalidated by source CHOCH confirmation",
            )
            # Commit CHOCH invalidation transition
            self._current_direction = staged_direction
            self._current_eligible_set = None
            self._outgoing_cancellation_intent = staged_outgoing_cancellation
            self._last_transition = record
            self._last_processed_index = observation.candle_index
            self._last_received_index = observation.candle_index
            self._last_received_candle_time = observation.candle_time
            self._received_indices.add(observation.candle_index)
            return self.get_snapshot()

        # 3. Label Confirmed Swing Points and Compute Zones
        # Bullish (UPWARD): TJL1 = CH (high-side), TJL2 / A+ = CL (low-side)
        # Bearish (DOWNWARD): TJL1 = CL (low-side), TJL2 / A+ = CH (high-side)
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
            if ch_level_id in staged_labeled_zones:
                ch_zone = staged_labeled_zones[ch_level_id]
            else:
                ch_zone = TJLZone.from_candle(
                    candle=ch_candle,
                    label=ch_label,
                    is_high_side=True,
                    feed_id=self._symbol_feed_id,
                    timeframe=self._source_timeframe,
                    confirmed_candle_index=observation.ch_point.confirmed_bar_index or observation.candle_index,
                    confirmed_time=observation.ch_point.confirmed_time,
                )
                staged_labeled_zones[ch_level_id] = ch_zone
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
            if cl_level_id in staged_labeled_zones:
                cl_zone = staged_labeled_zones[cl_level_id]
            else:
                cl_zone = TJLZone.from_candle(
                    candle=cl_candle,
                    label=cl_label,
                    is_high_side=False,
                    feed_id=self._symbol_feed_id,
                    timeframe=self._source_timeframe,
                    confirmed_candle_index=observation.cl_point.confirmed_bar_index or observation.candle_index,
                    confirmed_time=observation.cl_point.confirmed_time,
                )
                staged_labeled_zones[cl_level_id] = cl_zone
                staged_all_labeled.append(cl_zone)
                newly_labeled.append(cl_zone)

        # 4. Current Eligible Set Lifecycle Evaluation
        has_full_structure = (
            observation.ch_point is not None
            and observation.cl_point is not None
            and observation.tentative_p3 is not None
        )

        if not has_full_structure:
            # Missing one or more elements (e.g. active P3 cleared during continuation break)
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
            # Full structure present: CH, CL, and active tentative P3
            assert observation.ch_point is not None
            assert observation.cl_point is not None
            assert observation.tentative_p3 is not None

            # Construct unique structural fingerprint
            fp = TJLFingerprint(
                source_engine_id=self._source_engine_id,
                direction=staged_direction,
                ch_point_id=observation.ch_point.candle_index,
                cl_point_id=observation.cl_point.candle_index,
                p3_point_id=observation.tentative_p3.candle_index,
            )

            # Assign zone roles according to direction
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
                    eligibility_available_time=observation.candle_time,
                    created_at_candle_index=observation.candle_index,
                )
                staged_current_set = new_set
                staged_historical_sets.append(new_set)
                staged_outgoing_cancellation = False
                transition_type = TJLTransitionType.FIRST_CREATION
            else:
                # Current set exists: compare fingerprint
                if fp == staged_current_set.fingerprint:
                    # Idempotent re-observation: preserve set without refreshing availability
                    staged_outgoing_cancellation = False
                    transition_type = TJLTransitionType.IDEMPOTENT_NO_OP
                else:
                    # Set Replacement (t2 pullback): new set, emit outgoing cancellation intent
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
                        eligibility_available_time=observation.candle_time,
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
            transition_time=observation.candle_time,
            diagnostic=None,
        )

        # -------------------------------------------------------------
        # Commit all staged state mutations
        # -------------------------------------------------------------
        self._current_direction = staged_direction
        self._current_eligible_set = staged_current_set
        self._historical_sets = staged_historical_sets
        self._labeled_zones = staged_labeled_zones
        self._all_labeled_zones = staged_all_labeled
        self._outgoing_cancellation_intent = staged_outgoing_cancellation
        self._last_transition = record
        self._last_processed_index = observation.candle_index
        self._last_received_index = observation.candle_index
        self._last_received_candle_time = observation.candle_time
        self._received_indices.add(observation.candle_index)
        self._set_counter = staged_set_counter

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
            is_unresolved=self._is_unresolved,
            unresolved_diagnostic=self._unresolved_diagnostic,
            last_processed_index=self._last_processed_index,
            last_received_index=self._last_received_index if self._last_received_index >= 0 else self._last_processed_index,
        )
