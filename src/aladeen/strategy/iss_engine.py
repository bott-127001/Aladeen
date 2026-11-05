"""Internal Structure Shift (ISS) Detection Engine.

Scope & Design Boundary:
-------------------------
Coordinates Market Structure Marking (MSM) and Change of Character (CHOCH)
to detect valid Internal Structure Shift (ISS) candidates within a captured
main-level structural boundary.
Strictly read-only calculation logic. Zero order execution, zero network access,
zero MT5 dependencies, zero Plotly/Dash UI code, and zero mutable external state.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import pandas as pd

from .coordinator import MSMChochCoordinator
from .engine import MSMEngine
from .iss_types import (
    CandidateIdentity,
    ConfirmedISSEvent,
    FrozenBoundary,
    ISSConfig,
    ISSDiagnosticType,
    ISSLifecycleStatus,
    ISSSnapshot,
    ISSZone,
    ISSZoneType,
    InternalPoint,
)
from .types import Direction, MSMConfig, StrategyCandle, SwingPoint, validate_and_normalize_timestamp
from .validator import adapt_candles, validate_start_candle


@dataclass
class _CandidateTrackingState:
    """Internal mutable tracking state for an in-flight or terminal candidate."""
    identity: CandidateIdentity
    boundary: FrozenBoundary
    internal_msm_engine: MSMEngine
    lifecycle_status: ISSLifecycleStatus
    internal_points: List[InternalPoint] = field(default_factory=list)
    active_zones: List[ISSZone] = field(default_factory=list)
    diagnostic_type: Optional[ISSDiagnosticType] = None
    diagnostic_message: Optional[str] = None
    is_tracking_only: bool = False
    confirmed_event: Optional[ConfirmedISSEvent] = None


class ISSEngine:
    """Sequential engine detecting Internal Structure Shift (ISS) and coordinating lifecycles."""

    def __init__(self, config: ISSConfig) -> None:
        self.config = config
        self._main_coordinator = MSMChochCoordinator(
            MSMConfig(
                start_candle_time=config.start_candle_time,
                direction=config.main_direction,
            )
        )
        self._active_candidate: Optional[_CandidateTrackingState] = None
        self._confirmed_events: List[ConfirmedISSEvent] = []
        self._completed_candles: List[StrategyCandle] = []
        self._candle_lookup: Dict[int, StrategyCandle] = {}
        self._received_indices: Set[int] = set()
        self._last_processed_open_time: Optional[datetime] = None
        self._last_processed_index: int = -1
        self._candidate_seq: int = 0
        self._is_unresolved: bool = False
        self._unresolved_dependency: Optional[str] = None

    @property
    def confirmed_events(self) -> Tuple[ConfirmedISSEvent, ...]:
        return tuple(self._confirmed_events)

    @property
    def active_zones(self) -> Tuple[ISSZone, ...]:
        if self._active_candidate and self._active_candidate.lifecycle_status == ISSLifecycleStatus.CONFIRMED:
            return tuple(self._active_candidate.active_zones)
        return ()

    @property
    def is_unresolved(self) -> bool:
        return self._is_unresolved or self._main_coordinator.is_unresolved

    @property
    def last_processed_index(self) -> int:
        return self._last_processed_index

    def reset(self) -> None:
        """Resets engine to clean initial state."""
        self.__init__(self.config)

    def process_candles(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> ISSSnapshot:
        """Processes a sequence of candles in clean batch execution.

        Executes on an isolated temporary instance so that mid-batch failure
        or validation error cannot corrupt or replace existing state.
        """
        candles = adapt_candles(data)
        validate_start_candle(
            MSMConfig(start_candle_time=self.config.start_candle_time, direction=self.config.main_direction),
            candles,
        )

        temp_engine = ISSEngine(self.config)
        for c in candles:
            temp_engine._ingest_candle(c)

        # Atomically commit successful run state
        self._main_coordinator = temp_engine._main_coordinator
        self._active_candidate = temp_engine._active_candidate
        self._confirmed_events = temp_engine._confirmed_events
        self._completed_candles = temp_engine._completed_candles
        self._candle_lookup = temp_engine._candle_lookup
        self._received_indices = temp_engine._received_indices
        self._last_processed_open_time = temp_engine._last_processed_open_time
        self._last_processed_index = temp_engine._last_processed_index
        self._candidate_seq = temp_engine._candidate_seq
        self._is_unresolved = temp_engine._is_unresolved
        self._unresolved_dependency = temp_engine._unresolved_dependency

        return self.get_snapshot()

    def process_candle(self, candle: Union[StrategyCandle, dict]) -> ISSSnapshot:
        """Processes a single sequentially delivered candle incrementally."""
        if not isinstance(candle, StrategyCandle):
            if isinstance(candle, dict) and "index" not in candle:
                c_dict = dict(candle)
                c_dict["index"] = self._last_processed_index + 1
                adapted = adapt_candles([c_dict])
            else:
                adapted = adapt_candles([candle])
            candle = adapted[0]

        self._ingest_candle(candle)
        return self.get_snapshot()

    def replay_snapshots(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> List[ISSSnapshot]:
        """Replays candles bar-by-bar from a clean state and returns snapshots after each candle."""
        candles = adapt_candles(data)
        validate_start_candle(
            MSMConfig(start_candle_time=self.config.start_candle_time, direction=self.config.main_direction),
            candles,
        )

        temp_engine = ISSEngine(self.config)
        snapshots: List[ISSSnapshot] = []
        for c in candles:
            temp_engine._ingest_candle(c)
            snapshots.append(temp_engine.get_snapshot())

        return snapshots

    def get_snapshot(self) -> ISSSnapshot:
        """Returns an immutable snapshot of current engine state."""
        cand = self._active_candidate
        if cand is None:
            return ISSSnapshot(
                lifecycle_status=ISSLifecycleStatus.PENDING_PREREQUISITES,
                last_processed_index=self._last_processed_index,
                confirmed_events=tuple(self._confirmed_events),
                diagnostic_type=ISSDiagnosticType.WAITING_FOR_MAIN_PREREQUISITES,
                is_unresolved=self.is_unresolved,
                unresolved_dependency=self._unresolved_dependency,
            )

        # Points are exposed only when eligible or tracking-only (hidden if rejected/cancelled)
        visible_points = (
            tuple(cand.internal_points)
            if cand.lifecycle_status in (
                ISSLifecycleStatus.ELIGIBLE_SEARCH,
                ISSLifecycleStatus.CONFIRMED,
                ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY,
            )
            else ()
        )

        visible_zones = (
            tuple(cand.active_zones)
            if cand.lifecycle_status == ISSLifecycleStatus.CONFIRMED
            else ()
        )

        return ISSSnapshot(
            lifecycle_status=cand.lifecycle_status,
            candidate_identity=cand.identity,
            captured_boundary=cand.boundary,
            internal_points=visible_points,
            active_zones=visible_zones,
            confirmed_events=tuple(self._confirmed_events),
            is_tracking_only=cand.is_tracking_only,
            last_processed_index=self._last_processed_index,
            diagnostic_type=cand.diagnostic_type,
            diagnostic_message=cand.diagnostic_message,
            is_unresolved=self.is_unresolved,
            unresolved_dependency=self._unresolved_dependency,
        )

    def _ingest_candle(self, candle: StrategyCandle) -> None:
        """Ingests a single candle with transactional lifecycle coordination."""
        if not isinstance(candle, StrategyCandle):
            raise TypeError(f"Ingest candle requires StrategyCandle instance, got {type(candle).__name__}")

        if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
            return

        if candle.index in self._received_indices:
            raise ValueError(f"Duplicate candle source index detected: {candle.index}")
        if self._last_processed_open_time is not None and candle.open_time <= self._last_processed_open_time:
            raise ValueError(
                f"Non-chronological candle open_time: {candle.open_time} <= {self._last_processed_open_time}"
            )

        # Ingest into main coordinator
        prev_choch_count = len(self._main_coordinator.confirmed_choch_events)
        main_snap = self._main_coordinator.process_candle(candle)

        self._received_indices.add(candle.index)
        self._last_processed_open_time = candle.open_time
        self._last_processed_index = candle.index
        self._completed_candles.append(candle)
        self._candle_lookup[candle.index] = candle

        # Check main coordinator unresolved status
        if self._main_coordinator.is_unresolved:
            self._is_unresolved = True
            self._unresolved_dependency = "MAIN_CHOCH_IDENTIFICATION_CLOSE_AMBIGUITY"
            if self._active_candidate:
                self._active_candidate.diagnostic_type = ISSDiagnosticType.PAUSED_BY_UNRESOLVED_MAIN
                self._active_candidate.diagnostic_message = (
                    "Execution paused: main integrated path is unresolved (c1 == p2 dependency)."
                )
            return

        # -------------------------------------------------------------
        # 1. Step Active Candidate Internal Structure First (if active)
        # -------------------------------------------------------------
        cand = self._active_candidate
        candidate_completed_this_bar = False

        if cand is not None and cand.lifecycle_status in (
            ISSLifecycleStatus.ELIGIBLE_SEARCH,
            ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY,
        ):
            internal_snap = cand.internal_msm_engine.process_candle(candle)
            extracted_points = self._extract_internal_points(
                internal_snap=internal_snap,
                main_direction=self.config.main_direction,
                boundary=cand.boundary,
            )

            # Progressive out-of-bounds rejection: check if ANY marked point is out of bounds
            out_of_bounds_point: Optional[InternalPoint] = None
            for pt in extracted_points:
                if not pt.is_inside_boundary:
                    out_of_bounds_point = pt
                    break

            if out_of_bounds_point is not None:
                cand.lifecycle_status = ISSLifecycleStatus.OUT_OF_BOUNDS_REJECTED
                cand.diagnostic_type = ISSDiagnosticType.MARKED_POINT_OUT_OF_BOUNDS
                cand.diagnostic_message = (
                    f"Marked Point {out_of_bounds_point.point_number} ({out_of_bounds_point.role}) "
                    f"body edge {out_of_bounds_point.body_edge_price} outside boundary "
                    f"[{cand.boundary.min_price}, {cand.boundary.max_price}]."
                )
                cand.internal_points = []
                cand.active_zones = []
            else:
                cand.internal_points = extracted_points

                # If in ELIGIBLE_SEARCH and Point 5 identified:
                if cand.lifecycle_status == ISSLifecycleStatus.ELIGIBLE_SEARCH and len(extracted_points) == 5:
                    candidate_completed_this_bar = True
                    close_inside = cand.boundary.contains_price(candle.close)
                    if close_inside:
                        cand.lifecycle_status = ISSLifecycleStatus.CONFIRMED
                        cand.diagnostic_type = ISSDiagnosticType.CONFIRMED_COMPLETION_INSIDE
                        cand.diagnostic_message = "ISS confirmed: all 5 points inside boundary and completion close inside."

                        pt3 = extracted_points[2]
                        pt4 = extracted_points[3]
                        c3 = self._candle_lookup[pt3.source_candle_index]
                        c4 = self._candle_lookup[pt4.source_candle_index]
                        conf_avail = candle.close_time

                        if self.config.main_direction == Direction.DOWNWARD:
                            zone_l3 = ISSZone.from_candle(
                                zone_type=ISSZoneType.RBS,
                                candle=c3,
                                is_high_side=True,
                                source_point_number=3,
                                source_point_role=pt3.role,
                                confirmation_availability_time=conf_avail,
                            )
                            zone_l4 = ISSZone.from_candle(
                                zone_type=ISSZoneType.BUYING_A_PLUS,
                                candle=c4,
                                is_high_side=False,
                                source_point_number=4,
                                source_point_role=pt4.role,
                                confirmation_availability_time=conf_avail,
                            )
                        else:
                            zone_l3 = ISSZone.from_candle(
                                zone_type=ISSZoneType.SBR,
                                candle=c3,
                                is_high_side=False,
                                source_point_number=3,
                                source_point_role=pt3.role,
                                confirmation_availability_time=conf_avail,
                            )
                            zone_l4 = ISSZone.from_candle(
                                zone_type=ISSZoneType.SELLING_A_PLUS,
                                candle=c4,
                                is_high_side=True,
                                source_point_number=4,
                                source_point_role=pt4.role,
                                confirmation_availability_time=conf_avail,
                            )

                        cand.active_zones = [zone_l3, zone_l4]
                        event = ConfirmedISSEvent(
                            candidate_id=cand.identity.candidate_id,
                            main_direction=self.config.main_direction,
                            confirmation_candle_index=candle.index,
                            confirmation_time=candle.close_time,
                            completion_close_price=candle.close,
                            captured_boundary=cand.boundary,
                            internal_points=tuple(extracted_points),
                            level_3_zone=zone_l3,
                            level_4_zone=zone_l4,
                        )
                        cand.confirmed_event = event
                        self._confirmed_events.append(event)
                    else:
                        cand.lifecycle_status = ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
                        cand.diagnostic_type = ISSDiagnosticType.COMPLETION_CLOSE_OUTSIDE_RANGE
                        cand.diagnostic_message = (
                            f"Completion candle close {candle.close} outside boundary "
                            f"[{cand.boundary.min_price}, {cand.boundary.max_price}]. Tracking only."
                        )
                        cand.is_tracking_only = True
                        cand.active_zones = []

        # -------------------------------------------------------------
        # 2. Main CHOCH and Continuation Coordination
        # -------------------------------------------------------------
        # Check if Main CHOCH confirmed on this candle
        if len(self._main_coordinator.confirmed_choch_events) > prev_choch_count:
            if self._active_candidate and self._active_candidate.lifecycle_status in (
                ISSLifecycleStatus.ELIGIBLE_SEARCH,
                ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY,
            ):
                self._active_candidate.lifecycle_status = ISSLifecycleStatus.MAIN_CHOCH_CANCELLED
                self._active_candidate.diagnostic_type = ISSDiagnosticType.CANCELLED_BY_MAIN_CHOCH
                self._active_candidate.diagnostic_message = "Cancelled by main CHOCH confirmation."
                self._active_candidate.internal_points = []
                self._active_candidate.active_zones = []
            return

        # Inspect main MSM structure
        msm_snap = main_snap.msm_snapshot
        main_level_2: Optional[SwingPoint] = (
            msm_snap.last_resistance
            if self.config.main_direction == Direction.DOWNWARD
            else msm_snap.last_support
        )
        main_level_3: Optional[SwingPoint] = msm_snap.tentative_point

        # If tentative point disappeared while we were in UNFINISHED eligible search, main continuation cancelled it!
        if main_level_3 is None and not candidate_completed_this_bar:
            if self._active_candidate and self._active_candidate.lifecycle_status == ISSLifecycleStatus.ELIGIBLE_SEARCH:
                self._active_candidate.lifecycle_status = ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED
                self._active_candidate.diagnostic_type = ISSDiagnosticType.CANCELLED_BY_MAIN_CONTINUATION
                self._active_candidate.diagnostic_message = "Cancelled by main continuation break."
                self._active_candidate.internal_points = []
                self._active_candidate.active_zones = []
            return

        # Check if Main Level 2 is confirmed
        if main_level_2 is None or not main_level_2.is_confirmed or main_level_3 is None:
            return

        # Main Level 2 and Main Level 3 exist!
        # Check if we need to start a fresh candidate
        is_new_identification = False
        if self._active_candidate is None:
            is_new_identification = True
        else:
            prev_id = self._active_candidate.identity
            if prev_id.main_level_3_identified_bar_index != main_level_3.identified_bar_index:
                is_new_identification = True

        if is_new_identification:
            # Create a brand new candidate
            self._candidate_seq += 1
            cand_id = (
                f"iss_cand_{self.config.main_direction.value.lower()}_"
                f"{main_level_3.candle_index}_bar{main_level_3.identified_bar_index}_{self._candidate_seq}"
            )
            boundary = FrozenBoundary(
                min_price=round(min(main_level_2.price, main_level_3.price), 6),
                max_price=round(max(main_level_2.price, main_level_3.price), 6),
                main_level_2_price=main_level_2.price,
                main_level_3_price=main_level_3.price,
                frozen_at_candle_index=candle.index,
                frozen_at_time=candle.close_time or candle.open_time,
            )
            identity = CandidateIdentity(
                candidate_id=cand_id,
                sequence_number=self._candidate_seq,
                main_direction=self.config.main_direction,
                main_level_2_index=main_level_2.candle_index,
                main_level_2_price=main_level_2.price,
                main_level_3_index=main_level_3.candle_index,
                main_level_3_price=main_level_3.price,
                main_level_3_identified_bar_index=main_level_3.identified_bar_index,
                frozen_at_candle_index=candle.index,
                frozen_at_time=candle.close_time or candle.open_time,
            )
            internal_dir = (
                Direction.UPWARD
                if self.config.main_direction == Direction.DOWNWARD
                else Direction.DOWNWARD
            )
            earliest_pb_time = candle.close_time or candle.open_time
            internal_msm = MSMEngine(
                MSMConfig(
                    direction=internal_dir,
                    start_candle_time=main_level_3.candle_open_time,
                    earliest_pullback_time=earliest_pb_time,
                )
            )
            # Seed internal MSM engine with historical reference candle through current candle
            l3_candles = [c for c in self._completed_candles if c.open_time >= main_level_3.candle_open_time]
            if l3_candles:
                internal_msm.process_candles(l3_candles)

            self._active_candidate = _CandidateTrackingState(
                identity=identity,
                boundary=boundary,
                internal_msm_engine=internal_msm,
                lifecycle_status=ISSLifecycleStatus.ELIGIBLE_SEARCH,
                diagnostic_type=ISSDiagnosticType.ELIGIBLE_SEARCH_ACTIVE,
                diagnostic_message="Fresh ISS search opened.",
            )

    def _extract_internal_points(
        self,
        internal_snap: Any,
        main_direction: Direction,
        boundary: FrozenBoundary,
    ) -> List[InternalPoint]:
        """Extracts progressive internal points (1..5) from internal MSM snapshot."""
        points: List[InternalPoint] = []
        pairs = internal_snap.confirmed_pairs

        if main_direction == Direction.DOWNWARD:
            # Bearish Main -> Internal is UPWARD
            # Pair 1: CH1 (high), CL1 (low)
            if len(pairs) >= 1:
                p1 = pairs[0]
                points.append(
                    InternalPoint(
                        point_number=1,
                        role="CH1",
                        source_candle_index=p1.high.candle_index,
                        candle_open_time=p1.high.candle_open_time,
                        body_edge_price=p1.high.price,
                        is_confirmed=True,
                        identified_bar_index=p1.high.identified_bar_index,
                        confirmed_bar_index=p1.high.confirmed_bar_index,
                        is_inside_boundary=boundary.contains_price(p1.high.price),
                    )
                )
                points.append(
                    InternalPoint(
                        point_number=2,
                        role="CL1",
                        source_candle_index=p1.low.candle_index,
                        candle_open_time=p1.low.candle_open_time,
                        body_edge_price=p1.low.price,
                        is_confirmed=True,
                        identified_bar_index=p1.low.identified_bar_index,
                        confirmed_bar_index=p1.low.confirmed_bar_index,
                        is_inside_boundary=boundary.contains_price(p1.low.price),
                    )
                )

            # Pair 2: CH2 (high), CL2 (low)
            if len(pairs) >= 2:
                p2 = pairs[1]
                points.append(
                    InternalPoint(
                        point_number=3,
                        role="CH2",
                        source_candle_index=p2.high.candle_index,
                        candle_open_time=p2.high.candle_open_time,
                        body_edge_price=p2.high.price,
                        is_confirmed=True,
                        identified_bar_index=p2.high.identified_bar_index,
                        confirmed_bar_index=p2.high.confirmed_bar_index,
                        is_inside_boundary=boundary.contains_price(p2.high.price),
                    )
                )
                points.append(
                    InternalPoint(
                        point_number=4,
                        role="CL2",
                        source_candle_index=p2.low.candle_index,
                        candle_open_time=p2.low.candle_open_time,
                        body_edge_price=p2.low.price,
                        is_confirmed=True,
                        identified_bar_index=p2.low.identified_bar_index,
                        confirmed_bar_index=p2.low.confirmed_bar_index,
                        is_inside_boundary=boundary.contains_price(p2.low.price),
                    )
                )

            # Tentative point: Point 1, 3, or 5 depending on number of confirmed pairs
            tp = internal_snap.tentative_point
            if tp is not None:
                if len(pairs) == 0:
                    points.append(
                        InternalPoint(
                            point_number=1,
                            role="TENTATIVE_HIGH",
                            source_candle_index=tp.candle_index,
                            candle_open_time=tp.candle_open_time,
                            body_edge_price=tp.price,
                            is_confirmed=False,
                            identified_bar_index=tp.identified_bar_index,
                            is_inside_boundary=boundary.contains_price(tp.price),
                        )
                    )
                elif len(pairs) == 1:
                    points.append(
                        InternalPoint(
                            point_number=3,
                            role="TENTATIVE_HIGH",
                            source_candle_index=tp.candle_index,
                            candle_open_time=tp.candle_open_time,
                            body_edge_price=tp.price,
                            is_confirmed=False,
                            identified_bar_index=tp.identified_bar_index,
                            is_inside_boundary=boundary.contains_price(tp.price),
                        )
                    )
                elif len(pairs) == 2:
                    points.append(
                        InternalPoint(
                            point_number=5,
                            role="TENTATIVE_HIGH",
                            source_candle_index=tp.candle_index,
                            candle_open_time=tp.candle_open_time,
                            body_edge_price=tp.price,
                            is_confirmed=False,
                            identified_bar_index=tp.identified_bar_index,
                            is_inside_boundary=boundary.contains_price(tp.price),
                        )
                    )

        else:
            # Bullish Main -> Internal is DOWNWARD
            # Pair 1: CL1 (low), CH1 (high)
            if len(pairs) >= 1:
                p1 = pairs[0]
                points.append(
                    InternalPoint(
                        point_number=1,
                        role="CL1",
                        source_candle_index=p1.low.candle_index,
                        candle_open_time=p1.low.candle_open_time,
                        body_edge_price=p1.low.price,
                        is_confirmed=True,
                        identified_bar_index=p1.low.identified_bar_index,
                        confirmed_bar_index=p1.low.confirmed_bar_index,
                        is_inside_boundary=boundary.contains_price(p1.low.price),
                    )
                )
                points.append(
                    InternalPoint(
                        point_number=2,
                        role="CH1",
                        source_candle_index=p1.high.candle_index,
                        candle_open_time=p1.high.candle_open_time,
                        body_edge_price=p1.high.price,
                        is_confirmed=True,
                        identified_bar_index=p1.high.identified_bar_index,
                        confirmed_bar_index=p1.high.confirmed_bar_index,
                        is_inside_boundary=boundary.contains_price(p1.high.price),
                    )
                )

            # Pair 2: CL2 (low), CH2 (high)
            if len(pairs) >= 2:
                p2 = pairs[1]
                points.append(
                    InternalPoint(
                        point_number=3,
                        role="CL2",
                        source_candle_index=p2.low.candle_index,
                        candle_open_time=p2.low.candle_open_time,
                        body_edge_price=p2.low.price,
                        is_confirmed=True,
                        identified_bar_index=p2.low.identified_bar_index,
                        confirmed_bar_index=p2.low.confirmed_bar_index,
                        is_inside_boundary=boundary.contains_price(p2.low.price),
                    )
                )
                points.append(
                    InternalPoint(
                        point_number=4,
                        role="CH2",
                        source_candle_index=p2.high.candle_index,
                        candle_open_time=p2.high.candle_open_time,
                        body_edge_price=p2.high.price,
                        is_confirmed=True,
                        identified_bar_index=p2.high.identified_bar_index,
                        confirmed_bar_index=p2.high.confirmed_bar_index,
                        is_inside_boundary=boundary.contains_price(p2.high.price),
                    )
                )

            tp = internal_snap.tentative_point
            if tp is not None:
                if len(pairs) == 0:
                    points.append(
                        InternalPoint(
                            point_number=1,
                            role="TENTATIVE_LOW",
                            source_candle_index=tp.candle_index,
                            candle_open_time=tp.candle_open_time,
                            body_edge_price=tp.price,
                            is_confirmed=False,
                            identified_bar_index=tp.identified_bar_index,
                            is_inside_boundary=boundary.contains_price(tp.price),
                        )
                    )
                elif len(pairs) == 1:
                    points.append(
                        InternalPoint(
                            point_number=3,
                            role="TENTATIVE_LOW",
                            source_candle_index=tp.candle_index,
                            candle_open_time=tp.candle_open_time,
                            body_edge_price=tp.price,
                            is_confirmed=False,
                            identified_bar_index=tp.identified_bar_index,
                            is_inside_boundary=boundary.contains_price(tp.price),
                        )
                    )
                elif len(pairs) == 2:
                    points.append(
                        InternalPoint(
                            point_number=5,
                            role="TENTATIVE_LOW",
                            source_candle_index=tp.candle_index,
                            candle_open_time=tp.candle_open_time,
                            body_edge_price=tp.price,
                            is_confirmed=False,
                            identified_bar_index=tp.identified_bar_index,
                            is_inside_boundary=boundary.contains_price(tp.price),
                        )
                    )

        return points
