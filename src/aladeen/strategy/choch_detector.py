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

from datetime import datetime
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
        self._last_processed_open_time: Optional[datetime] = None

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

    @property
    def last_processed_pos(self) -> int:
        return self._last_processed_pos

    @property
    def last_processed_index(self) -> int:
        return self._last_processed_index

    def reset_for_new_direction(self, new_direction: Direction) -> None:
        """Resets pending candidate and confirmed event state when switching structural direction."""
        self._direction = new_direction
        self._candidate = None
        self._confirmed_choch = None
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
        identified_bar_pos: Optional[int] = None,
        candle_positions: Optional[Dict[int, int]] = None,
    ) -> ChochSnapshot:
        """Evaluates a single completed candle for Change of Character transitions."""
        # Clear transient single-transition event output so previous confirmation is not re-emitted
        self._confirmed_choch = None

        if not isinstance(candle, StrategyCandle):
            raise TypeError(f"process_candle requires StrategyCandle instance, got {type(candle).__name__}")

        # Guard: direct calls must be restricted to confirmed completed candles
        if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
            self._diagnostics.append(
                ChochDiagnostic(
                    diagnostic_type=ChochDiagnosticType.FORMING_CANDLE_REJECTED,
                    candle_index=candle.index,
                    chronological_pos=chronological_pos,
                    candle_open_time=candle.open_time,
                    message="Forming or unconfirmed candle cannot advance CHOCH state or confirm candidates.",
                )
            )
            return self.get_snapshot()

        # Chronological ordering and uniqueness validation before state mutation
        if self._last_processed_pos >= 0:
            if chronological_pos <= self._last_processed_pos:
                raise ValueError(
                    f"Out of order or duplicate chronological position: {chronological_pos} <= {self._last_processed_pos}"
                )
            if self._last_processed_open_time is not None and candle.open_time <= self._last_processed_open_time:
                raise ValueError(
                    f"Non-chronological candle open_time: {candle.open_time} <= {self._last_processed_open_time}"
                )

        # Unresolved guard: no dependent candidate, confirmation, or restart may occur while unresolved
        if self._is_unresolved:
            self._diagnostics.append(
                ChochDiagnostic(
                    diagnostic_type=ChochDiagnosticType.BLOCKED_BY_UNRESOLVED_STATE,
                    candle_index=candle.index,
                    chronological_pos=chronological_pos,
                    candle_open_time=candle.open_time,
                    message="CHOCH evaluation blocked pending reconciliation of unresolved same-close event.",
                    is_unresolved=True,
                )
            )
            self._last_processed_pos = chronological_pos
            self._last_processed_index = candle.index
            self._last_processed_open_time = candle.open_time
            return self.get_snapshot()

        # Commit input coordinates after validation
        self._last_processed_pos = chronological_pos
        self._last_processed_index = candle.index
        self._last_processed_open_time = candle.open_time

        # If direction changed externally, reset candidate state and confirmed event
        if msm_direction != self._direction:
            self.reset_for_new_direction(msm_direction)

        # Check prerequisite binding for existing candidate
        if self._candidate is not None:
            if not self._is_candidate_valid_for_prerequisites(
                candidate=self._candidate,
                current_direction=msm_direction,
                broken_level=last_support if msm_direction == Direction.UPWARD else last_resistance,
                tentative_p3=tentative_point,
            ):
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.PREREQUISITE_CHANGED,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message="Prerequisite level, Point 3 identity, or cycle changed; in-progress CHOCH sequence reset.",
                    )
                )
                self._candidate = None

        if msm_direction == Direction.UPWARD:
            self._evaluate_upward(
                candle=candle,
                chronological_pos=chronological_pos,
                last_support=last_support,
                tentative_point=tentative_point,
                candle_lookup=candle_lookup,
                confirmed_high=confirmed_high,
                identified_bar_pos=identified_bar_pos,
                candle_positions=candle_positions,
            )
        else:
            self._evaluate_downward(
                candle=candle,
                chronological_pos=chronological_pos,
                last_resistance=last_resistance,
                tentative_point=tentative_point,
                candle_lookup=candle_lookup,
                confirmed_low=confirmed_low,
                identified_bar_pos=identified_bar_pos,
                candle_positions=candle_positions,
            )

        return self.get_snapshot()

    def _is_candidate_valid_for_prerequisites(
        self,
        candidate: ChochCandidate,
        current_direction: Direction,
        broken_level: Optional[SwingPoint],
        tentative_p3: Optional[SwingPoint],
    ) -> bool:
        """Verifies that an active candidate remains fully bound to its prerequisite identity."""
        if candidate.direction != current_direction:
            return False
        if broken_level is None:
            return False
        if broken_level.candle_index != candidate.broken_level_source_index:
            return False
        if broken_level.price != candidate.broken_level_price:
            return False
        if tentative_p3 is None:
            return False
        if tentative_p3.candle_index != candidate.point_3_source_index:
            return False
        if tentative_p3.identified_bar_index != candidate.point_3_identified_bar_index:
            return False
        if tentative_p3.identified_time != candidate.point_3_identified_at:
            return False
        return True

    def _resolve_identification_pos(
        self,
        tentative_point: SwingPoint,
        identified_bar_pos: Optional[int],
        candle_positions: Optional[Dict[int, int]],
    ) -> Optional[int]:
        """Resolves Point 3 identification bar to its chronological position."""
        if identified_bar_pos is not None:
            return identified_bar_pos
        if candle_positions is not None:
            return candle_positions.get(tentative_point.identified_bar_index)
        return None

    def _evaluate_upward(
        self,
        candle: StrategyCandle,
        chronological_pos: int,
        last_support: Optional[SwingPoint],
        tentative_point: Optional[SwingPoint],
        candle_lookup: Dict[int, StrategyCandle],
        confirmed_high: Optional[SwingPoint],
        identified_bar_pos: Optional[int],
        candle_positions: Optional[Dict[int, int]],
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

        # Timing relative to Point 3 identification: strictly chronological, never arbitrary IDs
        p3_id_time = tentative_point.identified_time
        id_pos = self._resolve_identification_pos(tentative_point, identified_bar_pos, candle_positions)

        if p3_id_time is not None and candle.close_time is not None:
            is_strictly_before = candle.close_time < p3_id_time
            is_same_close = candle.close_time == p3_id_time
        elif id_pos is not None:
            is_strictly_before = chronological_pos < id_pos
            is_same_close = chronological_pos == id_pos
        else:
            # Cannot establish chronological relation without availability time or position lookup
            if candle.close < support_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.CLOSES_BEFORE_POINT_3_IDENTIFICATION,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message="Point 3 identification timing cannot be established; fails closed.",
                    )
                )
            return

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

        # Source-settled later-candle path: candle completed strictly after Point 3 identification
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
            self._candidate = ChochCandidate(
                direction=Direction.UPWARD,
                broken_level_price=support_price,
                broken_level_source_index=last_support.candle_index,
                point_3_source_index=tentative_point.candle_index,
                point_3_identified_bar_index=tentative_point.identified_bar_index,
                point_3_identified_at=tentative_point.identified_time,
                c1_candle_index=candle.index,
                c1_chronological_pos=chronological_pos,
                c1_open_time=candle.open_time,
                c1_close=candle.close,
                close_count=1,
            )
        else:
            # Candidate active; check if immediately consecutive in chronological positions
            if chronological_pos == self._candidate.c1_chronological_pos + 1:
                # Validate that all 3 required source candles exist before confirming event
                support_candle = candle_lookup.get(last_support.candle_index)
                p3_candle = candle_lookup.get(tentative_point.candle_index)
                high_candle = candle_lookup.get(confirmed_high.candle_index) if confirmed_high else None

                if support_candle is None or p3_candle is None or confirmed_high is None or high_candle is None:
                    self._diagnostics.append(
                        ChochDiagnostic(
                            diagnostic_type=ChochDiagnosticType.REQUIRED_ZONE_PROVENANCE_MISSING,
                            candle_index=candle.index,
                            chronological_pos=chronological_pos,
                            candle_open_time=candle.open_time,
                            message="Missing required candle provenance for 3 zones (SBR, QML, Double Top); confirmation withheld.",
                        )
                    )
                    return

                # Build exactly 3 zones
                sbr_zone = ChochZone.from_candle(ChochZoneType.SBR, support_candle, is_high_side=False)
                qml_zone = ChochZone.from_candle(ChochZoneType.QML_A_PLUS, high_candle, is_high_side=True)
                double_top_zone = ChochZone.from_candle(ChochZoneType.DOUBLE_TOP, p3_candle, is_high_side=True)
                zones = (sbr_zone, qml_zone, double_top_zone)

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
                    point_3_identified_bar_index=tentative_point.identified_bar_index,
                    point_3_identified_at=tentative_point.identified_time,
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
                self._candidate = ChochCandidate(
                    direction=Direction.UPWARD,
                    broken_level_price=support_price,
                    broken_level_source_index=last_support.candle_index,
                    point_3_source_index=tentative_point.candle_index,
                    point_3_identified_bar_index=tentative_point.identified_bar_index,
                    point_3_identified_at=tentative_point.identified_time,
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
        identified_bar_pos: Optional[int],
        candle_positions: Optional[Dict[int, int]],
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

        # Timing relative to Point 3 identification: strictly chronological, never arbitrary IDs
        p3_id_time = tentative_point.identified_time
        id_pos = self._resolve_identification_pos(tentative_point, identified_bar_pos, candle_positions)

        if p3_id_time is not None and candle.close_time is not None:
            is_strictly_before = candle.close_time < p3_id_time
            is_same_close = candle.close_time == p3_id_time
        elif id_pos is not None:
            is_strictly_before = chronological_pos < id_pos
            is_same_close = chronological_pos == id_pos
        else:
            # Cannot establish chronological relation without availability time or position lookup
            if candle.close > resistance_price:
                self._diagnostics.append(
                    ChochDiagnostic(
                        diagnostic_type=ChochDiagnosticType.CLOSES_BEFORE_POINT_3_IDENTIFICATION,
                        candle_index=candle.index,
                        chronological_pos=chronological_pos,
                        candle_open_time=candle.open_time,
                        message="Point 3 identification timing cannot be established; fails closed.",
                    )
                )
            return

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

        # Source-settled later-candle path: candle completed strictly after Point 3 identification
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
            self._candidate = ChochCandidate(
                direction=Direction.DOWNWARD,
                broken_level_price=resistance_price,
                broken_level_source_index=last_resistance.candle_index,
                point_3_source_index=tentative_point.candle_index,
                point_3_identified_bar_index=tentative_point.identified_bar_index,
                point_3_identified_at=tentative_point.identified_time,
                c1_candle_index=candle.index,
                c1_chronological_pos=chronological_pos,
                c1_open_time=candle.open_time,
                c1_close=candle.close,
                close_count=1,
            )
        else:
            # Candidate active; check if immediately consecutive in chronological positions
            if chronological_pos == self._candidate.c1_chronological_pos + 1:
                # Validate that all 3 required source candles exist before confirming event
                resistance_candle = candle_lookup.get(last_resistance.candle_index)
                p3_candle = candle_lookup.get(tentative_point.candle_index)
                low_candle = candle_lookup.get(confirmed_low.candle_index) if confirmed_low else None

                if resistance_candle is None or p3_candle is None or confirmed_low is None or low_candle is None:
                    self._diagnostics.append(
                        ChochDiagnostic(
                            diagnostic_type=ChochDiagnosticType.REQUIRED_ZONE_PROVENANCE_MISSING,
                            candle_index=candle.index,
                            chronological_pos=chronological_pos,
                            candle_open_time=candle.open_time,
                            message="Missing required candle provenance for 3 zones (RBS, QML, Double Bottom); confirmation withheld.",
                        )
                    )
                    return

                # Build exactly 3 zones
                rbs_zone = ChochZone.from_candle(ChochZoneType.RBS, resistance_candle, is_high_side=True)
                qml_zone = ChochZone.from_candle(ChochZoneType.QML_A_PLUS, low_candle, is_high_side=False)
                double_bottom_zone = ChochZone.from_candle(ChochZoneType.DOUBLE_BOTTOM, p3_candle, is_high_side=False)
                zones = (rbs_zone, qml_zone, double_bottom_zone)

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
                    point_3_identified_bar_index=tentative_point.identified_bar_index,
                    point_3_identified_at=tentative_point.identified_time,
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
                self._candidate = ChochCandidate(
                    direction=Direction.DOWNWARD,
                    broken_level_price=resistance_price,
                    broken_level_source_index=last_resistance.candle_index,
                    point_3_source_index=tentative_point.candle_index,
                    point_3_identified_bar_index=tentative_point.identified_bar_index,
                    point_3_identified_at=tentative_point.identified_time,
                    c1_candle_index=candle.index,
                    c1_chronological_pos=chronological_pos,
                    c1_open_time=candle.open_time,
                    c1_close=candle.close,
                    close_count=1,
                )

    def get_snapshot(self) -> ChochSnapshot:
        """Returns an immutable snapshot of current detector state."""
        return ChochSnapshot(
            active_direction=self._direction,
            last_processed_pos=self._last_processed_pos,
            last_processed_index=self._last_processed_index,
            candidate=self._candidate,
            confirmed_choch=self._confirmed_choch,
            diagnostics=tuple(self._diagnostics),
            is_unresolved=self._is_unresolved,
        )
