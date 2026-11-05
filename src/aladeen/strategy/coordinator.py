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

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
import pandas as pd

from .choch_detector import ChochDetector
from .choch_types import (
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
from .validator import adapt_candles


@dataclass(frozen=True)
class CoordinatorSnapshot:
    """Immutable snapshot of coordinated MSM and CHOCH execution state."""
    msm_snapshot: MSMSnapshot
    choch_snapshot: ChochSnapshot
    confirmed_choch_events: Tuple[ConfirmedChoch, ...]
    active_direction: Direction
    is_unresolved: bool
    last_processed_index: int


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
        self._last_processed_index: int = -1

    @property
    def direction(self) -> Direction:
        return self._msm_engine.direction

    @property
    def confirmed_choch_events(self) -> Tuple[ConfirmedChoch, ...]:
        return tuple(self._confirmed_choch_events)

    @property
    def is_unresolved(self) -> bool:
        return self._is_unresolved

    def reset(self) -> None:
        """Resets coordinator to clean initial state."""
        self.__init__(self.config)

    def process_candles(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> CoordinatorSnapshot:
        """Processes a sequence of candles in clean batch execution."""
        candles = adapt_candles(data)
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

    def _ingest_candle(self, candle: StrategyCandle) -> None:
        """Ingests a single candle through MSM and CHOCH detection sequentially."""
        self._candle_lookup[candle.index] = candle
        self._last_processed_index = candle.index

        if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
            # Forming bars cause zero state mutations
            return

        chronological_pos = len(self._completed_candles)
        self._completed_candles.append(candle)

        # 1. Advance MSMEngine
        msm_snap = self._msm_engine.process_candle(candle)

        # Extract latest confirmed high and low for QML zone creation
        confirmed_high: Optional[SwingPoint] = None
        confirmed_low: Optional[SwingPoint] = None
        if msm_snap.confirmed_pairs:
            latest_pair = msm_snap.confirmed_pairs[-1]
            confirmed_high = latest_pair.high
            confirmed_low = latest_pair.low

        # 2. Advance ChochDetector
        choch_snap = self._choch_detector.process_candle(
            candle=candle,
            chronological_pos=chronological_pos,
            msm_direction=msm_snap.direction,
            last_support=msm_snap.last_support,
            last_resistance=msm_snap.last_resistance,
            tentative_point=msm_snap.tentative_point,
            candle_lookup=self._candle_lookup,
            confirmed_high=confirmed_high,
            confirmed_low=confirmed_low,
        )

        # 3. Check for unresolved same-close condition
        if choch_snap.is_unresolved:
            self._is_unresolved = True
            # Fails closed without inventing transition direction or restart
            return

        # 4. Check for confirmed CHOCH event
        if choch_snap.confirmed_choch is not None and (
            not self._confirmed_choch_events
            or self._confirmed_choch_events[-1] != choch_snap.confirmed_choch
        ):
            event = choch_snap.confirmed_choch
            self._confirmed_choch_events.append(event)

            # Find chronological position of Point 3 source candle for restart reference
            p3_source_idx = event.point_3_source_index
            restart_pos = next(
                (i for i, c in enumerate(self._completed_candles) if c.index == p3_source_idx),
                0,
            )

            # Forward scan boundary strictly after confirmation candle
            first_eligible_pullback_pos = event.first_eligible_pullback_pos

            # Restart MSM engine in new direction
            self._msm_engine.restart_after_choch(
                new_direction=event.new_direction,
                restart_reference_pos=restart_pos,
                first_eligible_pullback_pos=first_eligible_pullback_pos,
            )

            # Reset detector for new direction
            self._choch_detector.reset_for_new_direction(event.new_direction)

    def get_snapshot(self) -> CoordinatorSnapshot:
        """Returns an immutable snapshot of coordinated execution state."""
        return CoordinatorSnapshot(
            msm_snapshot=self._msm_engine.get_snapshot(),
            choch_snapshot=self._choch_detector.get_snapshot(),
            confirmed_choch_events=tuple(self._confirmed_choch_events),
            active_direction=self._msm_engine.direction,
            is_unresolved=self._is_unresolved,
            last_processed_index=self._last_processed_index,
        )
