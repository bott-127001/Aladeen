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
        """Ingests a single candle with atomic staged transitions and unresolved containment."""
        if not isinstance(candle, StrategyCandle):
            raise TypeError(f"Ingest candle requires StrategyCandle instance, got {type(candle).__name__}")

        if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
            # Forming bars cause zero state mutations
            return

        # Stage candle addition
        self._candle_lookup[candle.index] = candle

        # Advance underlying MSMChochCoordinator
        coord_snap = self._main_coordinator.process_candle(candle)

        # Check for confirmed CHOCH event on this bar
        current_choch_count = len(coord_snap.confirmed_choch_events)
        is_choch_event = current_choch_count > self._prev_choch_count
        self._prev_choch_count = current_choch_count

        # Extract current-epoch confirmed high and low
        ch_point: Optional[SwingPoint] = None
        cl_point: Optional[SwingPoint] = None
        if coord_snap.msm_snapshot.confirmed_pairs:
            latest_pair = coord_snap.msm_snapshot.confirmed_pairs[-1]
            ch_point = latest_pair.high
            cl_point = latest_pair.low

        # Build structural observation
        observation = TJLStructuralObservation(
            source_engine_id=self.source_engine_id,
            symbol_feed_id=self.symbol_feed_id,
            source_timeframe=self.source_timeframe,
            direction=coord_snap.active_direction,
            candle_index=candle.index,
            candle_time=candle.close_time or candle.open_time,
            ch_point=ch_point,
            cl_point=cl_point,
            tentative_p3=coord_snap.msm_snapshot.tentative_point,
            is_choch_event=is_choch_event,
            new_choch_direction=coord_snap.active_direction if is_choch_event else None,
            is_unresolved=coord_snap.is_unresolved,
            unresolved_diagnostic=(
                coord_snap.unresolved_diagnostic.diagnostic_type.value
                if coord_snap.unresolved_diagnostic
                else None
            ),
            source_candle_lookup=self._candle_lookup,
        )

        # Ingest observation into pure reducer
        self._reducer.reduce(observation)

    def get_snapshot(self) -> TJLSnapshot:
        """Returns an immutable snapshot of the TJL execution state."""
        return self._reducer.get_snapshot()
