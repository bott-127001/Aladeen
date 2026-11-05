"""Coordinated Market Structure Marking (MSM) and Change of Character (CHOCH) Engine.

Scope & Design Boundary:
-------------------------
Coordinates sequential candle processing across the accepted deterministic MSMEngine
and ChochDetector without duplicating MSM state transitions or inventing unapproved
trading heuristics.
Strictly read-only calculation logic. Zero order execution, zero network access,
zero MT5 dependencies, zero Plotly/Dash UI code, and zero mutable external state.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd

from .choch_detector import ChochDetector
from .choch_types import (
    ChochDiagnostic,
    ChochSnapshot,
    ConfirmedChoch,
)
from .engine import MSMEngine
from .types import (
    Direction,
    MSMConfig,
    MSMSnapshot,
    StrategyCandle,
    SwingPoint,
)
from .validator import adapt_candles, validate_start_candle


@dataclass(frozen=True)
class CoordinatorSnapshot:
    """Immutable snapshot of coordinated MSM and CHOCH execution state.

    Attributes:
        msm_snapshot: Authoritative MSM snapshot (frozen at last pre-ambiguity state if unresolved).
        choch_snapshot: Authoritative CHOCH snapshot (frozen at last pre-ambiguity state if unresolved).
        confirmed_choch_events: Historical list of confirmed CHOCH events.
        active_direction: Authoritative structural marking direction.
        is_unresolved: True if an ambiguous transition (e.g. c1 == p2) occurred.
        last_processed_index: Source index of the last authoritatively processed completed candle.
        unresolved_diagnostic: Diagnostic record explaining the ambiguity if unresolved.
        unresolved_candle_index: Source index of the candle where ambiguity occurred.
        last_received_index: Source index of the latest received candle (tracks input while unresolved).
    """
    msm_snapshot: MSMSnapshot
    choch_snapshot: ChochSnapshot
    confirmed_choch_events: Tuple[ConfirmedChoch, ...]
    active_direction: Direction
    is_unresolved: bool
    last_processed_index: int
    unresolved_diagnostic: Optional[ChochDiagnostic] = None
    unresolved_candle_index: Optional[int] = None
    last_received_index: int = -1


class MSMChochCoordinator:
    """Sequential coordinator linking MSMEngine and ChochDetector lifecycle transitions."""

    def __init__(self, config: MSMConfig) -> None:
        self.config = config
        self._msm_engine = MSMEngine(config)
        self._choch_detector = ChochDetector(config.direction)
        self._confirmed_choch_events: List[ConfirmedChoch] = []
        self._candle_lookup: Dict[int, StrategyCandle] = {}
        self._completed_candles: List[StrategyCandle] = []
        self._is_unresolved: bool = False
        self._unresolved_diagnostic: Optional[ChochDiagnostic] = None
        self._unresolved_candle_index: Optional[int] = None
        self._last_processed_index: int = -1
        self._last_received_index: int = -1

    @property
    def direction(self) -> Direction:
        return self._msm_engine.direction

    @property
    def confirmed_choch_events(self) -> Tuple[ConfirmedChoch, ...]:
        return tuple(self._confirmed_choch_events)

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
        """Resets coordinator to clean initial state."""
        self.__init__(self.config)

    def process_candles(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> CoordinatorSnapshot:
        """Processes a sequence of candles in clean batch execution.

        Validates all candles and start configuration upfront before mutating run state.
        """
        candles = adapt_candles(data)
        validate_start_candle(self.config, candles)
        self.reset()

        for c in candles:
            self._ingest_candle(c)

        return self.get_snapshot()

    def process_candle(self, candle: StrategyCandle) -> CoordinatorSnapshot:
        """Processes a single sequentially delivered candle incrementally."""
        if not isinstance(candle, StrategyCandle):
            adapted = adapt_candles([candle])
            candle = adapted[0]

        self._ingest_candle(candle)
        return self.get_snapshot()

    def replay_candles(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> List[CoordinatorSnapshot]:
        """Replays candles bar-by-bar from a clean state and returns snapshots after each candle."""
        candles = adapt_candles(data)
        validate_start_candle(self.config, candles)
        self.reset()

        snapshots: List[CoordinatorSnapshot] = []
        for c in candles:
            self._ingest_candle(c)
            snapshots.append(self.get_snapshot())

        return snapshots

    def _ingest_candle(self, candle: StrategyCandle) -> None:
        """Ingests a single candle with atomic staged transitions and unresolved containment."""
        if not isinstance(candle, StrategyCandle):
            raise TypeError(f"Ingest candle requires StrategyCandle instance, got {type(candle).__name__}")

        if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
            # Forming bars cause zero state mutations
            return

        # Unresolved containment: if already unresolved, do NOT advance authoritative state!
        if self._is_unresolved:
            self._last_received_index = candle.index
            return

        # Validate ordering and uniqueness against authoritative history
        if self._completed_candles:
            last_completed = self._completed_candles[-1]
            if candle.index in self._candle_lookup:
                raise ValueError(f"Duplicate candle source index detected: {candle.index}")
            if candle.open_time <= last_completed.open_time:
                raise ValueError(
                    f"Non-chronological candle open_time: {candle.open_time} <= {last_completed.open_time}"
                )

        # -------------------------------------------------------------
        # Stage the entire transition in a staged working copy
        # -------------------------------------------------------------
        msm_engine_copy = copy.deepcopy(self._msm_engine)
        choch_detector_copy = copy.deepcopy(self._choch_detector)
        completed_candles_copy = list(self._completed_candles)
        candle_lookup_copy = dict(self._candle_lookup)
        confirmed_events_copy = list(self._confirmed_choch_events)

        # Stage candle addition
        candle_lookup_copy[candle.index] = candle
        completed_candles_copy.append(candle)
        chronological_pos = len(completed_candles_copy) - 1
        candle_positions = {c.index: i for i, c in enumerate(completed_candles_copy)}

        # 1. Stage MSM advance
        msm_snap = msm_engine_copy.process_candle(candle)

        # Extract confirmed high/low for QML
        confirmed_high: Optional[SwingPoint] = None
        confirmed_low: Optional[SwingPoint] = None
        if msm_snap.confirmed_pairs:
            latest_pair = msm_snap.confirmed_pairs[-1]
            confirmed_high = latest_pair.high
            confirmed_low = latest_pair.low

        # 2. Stage CHOCH detector advance
        choch_snap = choch_detector_copy.process_candle(
            candle=candle,
            chronological_pos=chronological_pos,
            msm_direction=msm_snap.direction,
            last_support=msm_snap.last_support,
            last_resistance=msm_snap.last_resistance,
            tentative_point=msm_snap.tentative_point,
            candle_lookup=candle_lookup_copy,
            confirmed_high=confirmed_high,
            confirmed_low=confirmed_low,
            candle_positions=candle_positions,
        )

        # 3. Check for unresolved same-close condition
        if choch_snap.is_unresolved:
            # Containment: do NOT commit staged engine changes.
            # Preserve authoritative pre-ambiguity state.
            self._is_unresolved = True
            self._unresolved_candle_index = candle.index
            self._unresolved_diagnostic = next(
                (d for d in choch_snap.diagnostics if d.is_unresolved),
                None,
            )
            self._last_received_index = candle.index
            return

        # 4. Check for confirmed CHOCH event
        if choch_snap.confirmed_choch is not None:
            event = choch_snap.confirmed_choch

            # Validate restart reference BEFORE appending event or restarting
            p3_source_idx = event.point_3_source_index
            restart_pos = next(
                (i for i, c in enumerate(completed_candles_copy) if c.index == p3_source_idx),
                None,
            )
            if restart_pos is None:
                raise ValueError(
                    f"Missing restart reference candle: Point 3 source index {p3_source_idx} "
                    f"not found in completed candles history"
                )

            # Stage restart on child engines
            msm_engine_copy.restart_after_choch(
                new_direction=event.new_direction,
                restart_reference_pos=restart_pos,
                first_eligible_pullback_pos=event.first_eligible_pullback_pos,
            )
            choch_detector_copy.reset_for_new_direction(event.new_direction)
            confirmed_events_copy.append(event)

        # -------------------------------------------------------------
        # Commit staged transition: all stages and validations succeeded
        # -------------------------------------------------------------
        self._msm_engine = msm_engine_copy
        self._choch_detector = choch_detector_copy
        self._completed_candles = completed_candles_copy
        self._candle_lookup = candle_lookup_copy
        self._confirmed_choch_events = confirmed_events_copy
        self._last_processed_index = candle.index
        self._last_received_index = candle.index

    def get_snapshot(self) -> CoordinatorSnapshot:
        """Returns an immutable snapshot of coordinated execution state."""
        return CoordinatorSnapshot(
            msm_snapshot=self._msm_engine.get_snapshot(),
            choch_snapshot=self._choch_detector.get_snapshot(),
            confirmed_choch_events=tuple(self._confirmed_choch_events),
            active_direction=self._msm_engine.direction,
            is_unresolved=self._is_unresolved,
            last_processed_index=self._last_processed_index,
            unresolved_diagnostic=self._unresolved_diagnostic,
            unresolved_candle_index=self._unresolved_candle_index,
            last_received_index=self._last_received_index if self._last_received_index >= 0 else self._last_processed_index,
        )
