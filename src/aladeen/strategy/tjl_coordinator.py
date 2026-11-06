"""Trend Joining Level (TJL) Candle Coordinator.

Scope & Design Boundary:
-------------------------
- Coordinates sequential completed-candle processing by linking the accepted
  MSMChochCoordinator to the pure TJLReducer.
- Does NOT duplicate MSM or CHOCH detection or state transitions.
- Strictly read-only calculation logic. Zero order execution, zero network access,
  zero MT5 dependencies, and zero Plotly/Dash UI code.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd

from .coordinator import CoordinatorSnapshot, MSMChochCoordinator
from .types import Direction, MSMConfig, StrategyCandle, SwingPoint
from .tjl_reducer import TJLReducer
from .tjl_types import (
    CurrentEligibleSet,
    TJLSnapshot,
    TJLStructuralObservation,
    TJLTransitionRecord,
    TJLZone,
)
from .validator import adapt_candles, validate_start_candle


class TJLCoordinator:
    """Sequential coordinator wiring MSMChochCoordinator to TJLReducer."""

    def __init__(
        self,
        config: MSMConfig,
        symbol_feed_id: str,
        source_timeframe: str,
        source_engine_id: Optional[str] = None,
    ) -> None:
        if not isinstance(config, MSMConfig):
            raise TypeError(f"config must be MSMConfig, got {type(config).__name__}")
        if not isinstance(symbol_feed_id, str) or not symbol_feed_id.strip():
            raise ValueError(f"symbol_feed_id must be non-empty string, got {symbol_feed_id!r}")
        if not isinstance(source_timeframe, str) or not source_timeframe.strip():
            raise ValueError(f"source_timeframe must be non-empty string, got {source_timeframe!r}")

        self.config: MSMConfig = config
        self.symbol_feed_id: str = symbol_feed_id
        self.source_timeframe: str = source_timeframe
        self.source_engine_id: str = source_engine_id or f"ENGINE_{symbol_feed_id}_{source_timeframe}"

        self._main_coordinator = MSMChochCoordinator(config)
        self._reducer = TJLReducer(
            source_engine_id=self.source_engine_id,
            symbol_feed_id=self.symbol_feed_id,
            source_timeframe=self.source_timeframe,
        )
        self._candle_lookup: Dict[int, StrategyCandle] = {}
        self._prev_choch_count: int = 0

    @property
    def direction(self) -> Direction:
        return self._main_coordinator.direction

    @property
    def is_unresolved(self) -> bool:
        return self._reducer.is_unresolved

    @property
    def last_processed_index(self) -> int:
        return self._reducer.last_processed_index

    @property
    def last_received_index(self) -> int:
        return self._reducer.last_received_index

    def reset(self) -> None:
        """Resets coordinator to clean initial state."""
        self._main_coordinator.reset()
        self._reducer.reset()
        self._candle_lookup.clear()
        self._prev_choch_count = 0

    def process_candles(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> TJLSnapshot:
        """Processes a sequence of candles in clean batch execution.

        Calculates a fresh run on an isolated temporary coordinator so that any
        mid-batch failure or validation error cannot corrupt existing state.
        Atomically replaces coordinator state only upon success.
        """
        candles = adapt_candles(data)
        validate_start_candle(self.config, candles)

        temp_coord = TJLCoordinator(
            config=self.config,
            symbol_feed_id=self.symbol_feed_id,
            source_timeframe=self.source_timeframe,
            source_engine_id=self.source_engine_id,
        )
        for c in candles:
            temp_coord._ingest_candle(c)

        # Atomically replace state
        self._main_coordinator = temp_coord._main_coordinator
        self._reducer = temp_coord._reducer
        self._candle_lookup = temp_coord._candle_lookup
        self._prev_choch_count = temp_coord._prev_choch_count

        return self.get_snapshot()

    def process_candle(self, candle: Union[StrategyCandle, dict]) -> TJLSnapshot:
        """Processes a single sequentially delivered candle incrementally."""
        if not isinstance(candle, StrategyCandle):
            adapted = adapt_candles([candle])
            candle = adapted[0]

        self._ingest_candle(candle)
        return self.get_snapshot()

    def replay_candles(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> List[TJLSnapshot]:
        """Replays candles bar-by-bar from a clean state and returns snapshots after each candle.

        Executed on an isolated temporary coordinator without mutating live coordinator state.
        """
        candles = adapt_candles(data)
        validate_start_candle(self.config, candles)

        temp_coord = TJLCoordinator(
            config=self.config,
            symbol_feed_id=self.symbol_feed_id,
            source_timeframe=self.source_timeframe,
            source_engine_id=self.source_engine_id,
        )
        snapshots: List[TJLSnapshot] = []
        for c in candles:
            temp_coord._ingest_candle(c)
            snapshots.append(temp_coord.get_snapshot())

        return snapshots

    def _ingest_candle(self, candle: StrategyCandle) -> None:
        """Ingests a single candle with fully staged, atomic transaction semantics."""
        if not isinstance(candle, StrategyCandle):
            raise TypeError(f"Ingest candle requires StrategyCandle instance, got {type(candle).__name__}")

        if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
            # Forming bars cause zero state mutations
            return

        # Stage entire transaction in temporary working copies
        main_coord_copy = copy.deepcopy(self._main_coordinator)
        reducer_copy = copy.deepcopy(self._reducer)
        candle_lookup_copy = dict(self._candle_lookup)
        prev_choch_count_copy = self._prev_choch_count

        # 1. Stage candle addition to lookup
        candle_lookup_copy[candle.index] = candle

        # 2. Stage underlying MSMChochCoordinator advancement
        coord_snap = main_coord_copy.process_candle(candle)

        # 3. Check for confirmed CHOCH event on this bar
        current_choch_count = len(coord_snap.confirmed_choch_events)
        is_choch_event = current_choch_count > prev_choch_count_copy
        if is_choch_event:
            latest_choch = coord_snap.confirmed_choch_events[-1]
            new_choch_direction = latest_choch.new_direction
            obs_direction = (
                Direction.UPWARD
                if new_choch_direction == Direction.DOWNWARD
                else Direction.DOWNWARD
            )
        else:
            obs_direction = coord_snap.active_direction
            new_choch_direction = None

        # 4. Extract current-epoch confirmed high and low using authoritative event positions
        ch_point: Optional[SwingPoint] = None
        cl_point: Optional[SwingPoint] = None
        if coord_snap.msm_snapshot.confirmed_pairs:
            latest_pair = coord_snap.msm_snapshot.confirmed_pairs[-1]
            if coord_snap.confirmed_choch_events:
                latest_choch = coord_snap.confirmed_choch_events[-1]
                candle_positions = {c.index: i for i, c in enumerate(main_coord_copy._completed_candles)}
                pair_conf_pos = candle_positions.get(latest_pair.confirmation_bar_index)
                if pair_conf_pos is not None and pair_conf_pos > latest_choch.c2_chronological_pos:
                    ch_point = latest_pair.high
                    cl_point = latest_pair.low
            else:
                ch_point = latest_pair.high
                cl_point = latest_pair.low

        # 5. Build structural observation preserving unknown close time as None
        observation = TJLStructuralObservation(
            source_engine_id=self.source_engine_id,
            symbol_feed_id=self.symbol_feed_id,
            source_timeframe=self.source_timeframe,
            direction=obs_direction,
            candle_index=candle.index,
            candle_open_time=candle.open_time,
            availability_time=candle.close_time,  # Strictly None if close_time is unknown!
            ch_point=ch_point,
            cl_point=cl_point,
            tentative_p3=coord_snap.msm_snapshot.tentative_point,
            is_choch_event=is_choch_event,
            new_choch_direction=new_choch_direction,
            structural_epoch=self._reducer.structural_epoch,
            is_unresolved=coord_snap.is_unresolved,
            unresolved_diagnostic=(
                coord_snap.unresolved_diagnostic.diagnostic_type.value
                if coord_snap.unresolved_diagnostic
                else None
            ),
            source_candle_lookup=candle_lookup_copy,
        )

        # 6. Stage reducer advance
        reducer_copy.reduce(observation)

        # -------------------------------------------------------------
        # Commit all staged components only after ALL steps succeed
        # -------------------------------------------------------------
        self._main_coordinator = main_coord_copy
        self._reducer = reducer_copy
        self._candle_lookup = candle_lookup_copy
        self._prev_choch_count = current_choch_count

    def get_snapshot(self) -> TJLSnapshot:
        """Returns an immutable snapshot of the TJL execution state."""
        return self._reducer.get_snapshot()
