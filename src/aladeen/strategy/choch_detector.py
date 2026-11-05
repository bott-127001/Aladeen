"""Deterministic Change of Character (CHOCH) Detector.

Scope & Design Boundary:
-------------------------
Implements pure mathematical detection of Change of Character transitions
according to the approved specifications in `docs/requirements/choch-acceptance.md`
and `docs/requirements/approved-clarifications.md`.
Strictly read-only calculation logic. Zero order execution, zero network access,
zero MT5 dependencies, zero Plotly/Dash UI code, and zero mutable external state.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .choch_types import (
    ChochCandidate,
    ChochDiagnostic,
    ChochDiagnosticType,
    ChochSnapshot,
    ChochType,
    ChochZone,
    ChochZoneType,
    ConfirmedChoch,
)
from .types import Direction, StrategyCandle, SwingPoint


class ChochDetector:
    """Deterministic, sequential detector for Change of Character events."""

    def __init__(self, initial_direction: Direction) -> None:
        self._direction = initial_direction
        self._candidate: Optional[ChochCandidate] = None
        self._confirmed_choch: Optional[ConfirmedChoch] = None
        self._diagnostics: List[ChochDiagnostic] = []
        self._is_unresolved: bool = False
        self._last_processed_pos: int = -1
        self._last_processed_index: int = -1

    @property
    def direction(self) -> Direction:
        return self._direction

    @property
    def candidate(self) -> Optional[ChochCandidate]:
        return self._candidate

    @property
    def confirmed_choch(self) -> Optional[ConfirmedChoch]:
        return self._confirmed_choch

    @property
    def diagnostics(self) -> Tuple[ChochDiagnostic, ...]:
        return tuple(self._diagnostics)

    @property
    def is_unresolved(self) -> bool:
        return self._is_unresolved

    def reset_for_new_direction(self, new_direction: Direction) -> None:
        """Resets pending candidate state when switching structural direction."""
        self._direction = new_direction
        self._candidate = None
        self._is_unresolved = False

    def process_candle(
        self,
        candle: StrategyCandle,
        chronological_pos: int,
        msm_direction: Direction,
        last_support: Optional[SwingPoint],
        last_resistance: Optional[SwingPoint],
        tentative_point: Optional[SwingPoint],
        candle_lookup: Dict[int, StrategyCandle],
        confirmed_high: Optional[SwingPoint] = None,
        confirmed_low: Optional[SwingPoint] = None,
    ) -> ChochSnapshot:
        """Evaluates a single completed candle for Change of Character transitions."""
        self._last_processed_pos = chronological_pos
        self._last_processed_index = candle.index

        # If direction changed externally, reset candidate state
        if msm_direction != self._direction:
            self.reset_for_new_direction(msm_direction)

        # Check for cycle continuation break: if active candidate exists but tentative Point 3 was confirmed or lost
        if self._candidate is not None:
            if tentative_point is None or tentative_point.candle_index != self._candidate.point_3_source_index:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.CONTINUATION_RESET,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message="Tentative Point 3 lost or confirmed via continuation; in-progress CHOCH sequence reset.",
                    )
                )
                self._candidate = None

        if msm_direction == Direction.UPWARD:
            self._evaluate_upward(
                candle,
                chronological_pos,
                last_support,
                tentative_point,
                candle_lookup,
                confirmed_high,
            )
        else:
            self._evaluate_downward(
                candle,
                chronological_pos,
                last_resistance,
                tentative_point,
                candle_lookup,
                confirmed_low,
            )

        return self.get_snapshot()

    def _evaluate_upward(
        self,
        candle: StrategyCandle,
        chronological_pos: int,
        last_support: Optional[SwingPoint],
        tentative_point: Optional[SwingPoint],
        candle_lookup: Dict[int, StrategyCandle],
        confirmed_high: Optional[SwingPoint],
    ) -> None:
        if last_support is None:
            return

        support_price = last_support.price

        # Check Point 3 prerequisite
        if tentative_point is None:
            if candle.close < support_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.ACTIVE_POINT_3_ABSENT,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message="Close below Last Support without an active Tentative Point 3 fails closed.",
                    )
                )
            return

        # Timing relative to Point 3 identification
        p3_id_time = tentative_point.identified_time
        if p3_id_time is not None and candle.close_time is not None:
            is_strictly_before = candle.close_time < p3_id_time
            is_same_close = candle.close_time == p3_id_time
        else:
            is_strictly_before = candle.index < tentative_point.identified_bar_index
            is_same_close = candle.index == tentative_point.identified_bar_index

        if is_strictly_before:
            if candle.close < support_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.CLOSES_BEFORE_POINT_3_IDENTIFICATION,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Candle index {candle.index} completed strictly before Point 3 identification; ineligible.",
                    )
                )
            return

        # Narrowly scoped same-close question
        if is_same_close:
            if candle.close < support_price:
                self._is_unresolved = True
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.UNRESOLVED_SAME_CLOSE,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message="Candle simultaneously established Point 3 and closed below Last Support; isolated pending source reconciliation.",
                        is_unresolved=True,
                    )
                )
            return

        # Source-settled later-candle path: candle.index > p3_id_bar
        # If candidate is active and this candle fails to close strictly below support:
        if candle.close >= support_price:
            if self._candidate is not None:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.SECOND_CLOSE_FAILED,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Second close ({candle.close}) failed to close below Last Support ({support_price}); sequence reset.",
                    )
                )
                self._candidate = None

            if candle.close == support_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.EQUALITY_REJECTED,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Close {candle.close} exactly equals Last Support {support_price}; strict inequality required.",
                    )
                )
            elif candle.low < support_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.WICK_CROSSING_ONLY_REJECTED,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Wick pierced Last Support (low={candle.low} < {support_price}) but close ({candle.close}) did not break.",
                    )
                )
            return

        # Qualifying close below support: candle.close < support_price
        if self._candidate is None:
            # First qualifying close (c1)
            p3_time = tentative_point.identified_time if tentative_point.identified_time else tentative_point.candle_open_time
            self._candidate = ChochCandidate(
                direction=Direction.UPWARD,
                broken_level_price=support_price,
                broken_level_source_index=last_support.candle_index,
                point_3_source_index=tentative_point.candle_index,
                point_3_identified_at=p3_time,
                c1_candle_index=candle.index,
                c1_chronological_pos=chronological_pos,
                c1_open_time=candle.open_time,
                c1_close=candle.close,
                close_count=1,
            )
        else:
            # Candidate active; check if immediately consecutive in chronological positions
            if chronological_pos == self._candidate.c1_chronological_pos + 1:
                # Confirmed Bearish CHOCH!
                p3_candle = candle_lookup[tentative_point.candle_index]
                support_candle = candle_lookup[last_support.candle_index]
                high_candle = candle_lookup[confirmed_high.candle_index] if confirmed_high else None

                # Build 3 zones
                sbr_zone = ChochZone.from_candle(ChochZoneType.SBR, support_candle, is_high_side=False)
                double_top_zone = ChochZone.from_candle(ChochZoneType.DOUBLE_TOP, p3_candle, is_high_side=True)
                if high_candle is not None:
                    qml_zone = ChochZone.from_candle(ChochZoneType.QML_A_PLUS, high_candle, is_high_side=True)
                    zones = (sbr_zone, qml_zone, double_top_zone)
                else:
                    zones = (sbr_zone, double_top_zone)

                p3_time = tentative_point.identified_time if tentative_point.identified_time else tentative_point.candle_open_time
                self._confirmed_choch = ConfirmedChoch(
                    choch_type=ChochType.BEARISH_CHOCH,
                    broken_level_type="LAST_SUPPORT",
                    broken_level_price=support_price,
                    broken_level_source_index=last_support.candle_index,
                    c1_candle_index=self._candidate.c1_candle_index,
                    c2_candle_index=candle.index,
                    c1_chronological_pos=self._candidate.c1_chronological_pos,
                    c2_chronological_pos=chronological_pos,
                    c1_open_time=self._candidate.c1_open_time,
                    c2_open_time=candle.open_time,
                    confirmation_time=candle.close_time,
                    point_3_source_index=tentative_point.candle_index,
                    point_3_open_time=p3_candle.open_time,
                    point_3_identified_at=p3_time,
                    zones=zones,
                    new_direction=Direction.DOWNWARD,
                    restart_reference_candle_index=tentative_point.candle_index,
                    restart_reference_open_time=p3_candle.open_time,
                    first_eligible_pullback_pos=chronological_pos + 1,
                )
                self._candidate = None
            else:
                # Non-consecutive: reset candidate to this candle as new c1
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.NON_CONSECUTIVE_REJECTED,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Qualifying close at pos {chronological_pos} not adjacent to c1 at pos {self._candidate.c1_chronological_pos}.",
                    )
                )
                p3_time = tentative_point.identified_time if tentative_point.identified_time else tentative_point.candle_open_time
                self._candidate = ChochCandidate(
                    direction=Direction.UPWARD,
                    broken_level_price=support_price,
                    broken_level_source_index=last_support.candle_index,
                    point_3_source_index=tentative_point.candle_index,
                    point_3_identified_at=p3_time,
                    c1_candle_index=candle.index,
                    c1_chronological_pos=chronological_pos,
                    c1_open_time=candle.open_time,
                    c1_close=candle.close,
                    close_count=1,
                )

    def _evaluate_downward(
        self,
        candle: StrategyCandle,
        chronological_pos: int,
        last_resistance: Optional[SwingPoint],
        tentative_point: Optional[SwingPoint],
        candle_lookup: Dict[int, StrategyCandle],
        confirmed_low: Optional[SwingPoint],
    ) -> None:
        if last_resistance is None:
            return

        resistance_price = last_resistance.price

        # Check Point 3 prerequisite
        if tentative_point is None:
            if candle.close > resistance_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.ACTIVE_POINT_3_ABSENT,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message="Close above Last Resistance without an active Tentative Point 3 fails closed.",
                    )
                )
            return

        # Timing relative to Point 3 identification
        p3_id_time = tentative_point.identified_time
        if p3_id_time is not None and candle.close_time is not None:
            is_strictly_before = candle.close_time < p3_id_time
            is_same_close = candle.close_time == p3_id_time
        else:
            is_strictly_before = candle.index < tentative_point.identified_bar_index
            is_same_close = candle.index == tentative_point.identified_bar_index

        if is_strictly_before:
            if candle.close > resistance_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.CLOSES_BEFORE_POINT_3_IDENTIFICATION,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Candle index {candle.index} completed strictly before Point 3 identification; ineligible.",
                    )
                )
            return

        # Narrowly scoped same-close question
        if is_same_close:
            if candle.close > resistance_price:
                self._is_unresolved = True
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.UNRESOLVED_SAME_CLOSE,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message="Candle simultaneously established Point 3 and closed above Last Resistance; isolated pending source reconciliation.",
                        is_unresolved=True,
                    )
                )
            return

        # Source-settled later-candle path: candle.index > p3_id_bar
        # If candidate is active and this candle fails to close strictly above resistance:
        if candle.close <= resistance_price:
            if self._candidate is not None:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.SECOND_CLOSE_FAILED,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Second close ({candle.close}) failed to close above Last Resistance ({resistance_price}); sequence reset.",
                    )
                )
                self._candidate = None

            if candle.close == resistance_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.EQUALITY_REJECTED,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Close {candle.close} exactly equals Last Resistance {resistance_price}; strict inequality required.",
                    )
                )
            elif candle.high > resistance_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.WICK_CROSSING_ONLY_REJECTED,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Wick pierced Last Resistance (high={candle.high} > {resistance_price}) but close ({candle.close}) did not break.",
                    )
                )
            return

        # Qualifying close above resistance: candle.close > resistance_price
        if self._candidate is None:
            # First qualifying close (c1)
            p3_time = tentative_point.identified_time if tentative_point.identified_time else tentative_point.candle_open_time
            self._candidate = ChochCandidate(
                direction=Direction.DOWNWARD,
                broken_level_price=resistance_price,
                broken_level_source_index=last_resistance.candle_index,
                point_3_source_index=tentative_point.candle_index,
                point_3_identified_at=p3_time,
                c1_candle_index=candle.index,
                c1_chronological_pos=chronological_pos,
                c1_open_time=candle.open_time,
                c1_close=candle.close,
                close_count=1,
            )
        else:
            # Candidate active; check if immediately consecutive in chronological positions
            if chronological_pos == self._candidate.c1_chronological_pos + 1:
                # Confirmed Bullish CHOCH!
                p3_candle = candle_lookup[tentative_point.candle_index]
                res_candle = candle_lookup[last_resistance.candle_index]
                low_candle = candle_lookup[confirmed_low.candle_index] if confirmed_low else None

                # Build 3 zones
                rbs_zone = ChochZone.from_candle(ChochZoneType.RBS, res_candle, is_high_side=True)
                double_bottom_zone = ChochZone.from_candle(ChochZoneType.DOUBLE_BOTTOM, p3_candle, is_high_side=False)
                if low_candle is not None:
                    qml_zone = ChochZone.from_candle(ChochZoneType.QML_A_PLUS, low_candle, is_high_side=False)
                    zones = (rbs_zone, qml_zone, double_bottom_zone)
                else:
                    zones = (rbs_zone, double_bottom_zone)

                p3_time = tentative_point.identified_time if tentative_point.identified_time else tentative_point.candle_open_time
                self._confirmed_choch = ConfirmedChoch(
                    choch_type=ChochType.BULLISH_CHOCH,
                    broken_level_type="LAST_RESISTANCE",
                    broken_level_price=resistance_price,
                    broken_level_source_index=last_resistance.candle_index,
                    c1_candle_index=self._candidate.c1_candle_index,
                    c2_candle_index=candle.index,
                    c1_chronological_pos=self._candidate.c1_chronological_pos,
                    c2_chronological_pos=chronological_pos,
                    c1_open_time=self._candidate.c1_open_time,
                    c2_open_time=candle.open_time,
                    confirmation_time=candle.close_time,
                    point_3_source_index=tentative_point.candle_index,
                    point_3_open_time=p3_candle.open_time,
                    point_3_identified_at=p3_time,
                    zones=zones,
                    new_direction=Direction.UPWARD,
                    restart_reference_candle_index=tentative_point.candle_index,
                    restart_reference_open_time=p3_candle.open_time,
                    first_eligible_pullback_pos=chronological_pos + 1,
                )
                self._candidate = None
            else:
                # Non-consecutive: reset candidate to this candle as new c1
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.NON_CONSECUTIVE_REJECTED,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message=f"Qualifying close at pos {chronological_pos} not adjacent to c1 at pos {self._candidate.c1_chronological_pos}.",
                    )
                )
                p3_time = tentative_point.identified_time if tentative_point.identified_time else tentative_point.candle_open_time
                self._candidate = ChochCandidate(
                    direction=Direction.DOWNWARD,
                    broken_level_price=resistance_price,
                    broken_level_source_index=last_resistance.candle_index,
                    point_3_source_index=tentative_point.candle_index,
                    point_3_identified_at=p3_time,
                    c1_candle_index=candle.index,
                    c1_chronological_pos=chronological_pos,
                    c1_open_time=candle.open_time,
                    c1_close=candle.close,
                    close_count=1,
                )

    def get_snapshot(self) -> ChochSnapshot:
        """Returns an immutable snapshot of detector state."""
        return ChochSnapshot(
            active_direction=self._direction,
            last_processed_pos=self._last_processed_pos,
            last_processed_index=self._last_processed_index,
            candidate=self._candidate,
            confirmed_choch=self._confirmed_choch,
            diagnostics=tuple(self._diagnostics),
            is_unresolved=self._is_unresolved,
        )
