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
from .iss_tracking import extract_internal_points, extract_tracking_points
from .iss_types import (
    CandidateIdentity,
    ConfirmedISSEvent,
    FrozenBoundary,
    ISSCombinedResult,
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
    attempted_points: Optional[List[InternalPoint]] = None
    tracking_points: List[InternalPoint] = field(default_factory=list)
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
        self._last_received_open_time: Optional[datetime] = None
        self._last_received_index: int = -1
        self._candidate_seq: int = 0
        self._is_unresolved: bool = False
        self._unresolved_dependency: Optional[str] = None

    @property
    def direction(self) -> Direction:
        """Returns the current authoritative main marking direction."""
        return self._main_coordinator.direction

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

    @property
    def last_received_index(self) -> int:
        return self._last_received_index if self._last_received_index >= 0 else self._last_processed_index

    def get_main_coordinator_snapshot(self) -> Any:
        """Public accessor returning the authoritative main MSM/CHOCH coordinator snapshot."""
        return self._main_coordinator.get_snapshot()

    def get_combined_result(self) -> ISSCombinedResult:
        """Public accessor returning an immutable combined result of ISS and main coordinator snapshots."""
        return ISSCombinedResult(
            iss_snapshot=self.get_snapshot(),
            main_coordinator_snapshot=self.get_main_coordinator_snapshot(),
            confirmed_iss_events=self.confirmed_events,
        )

    def reset(self) -> None:
        """Resets engine to clean initial state."""
        self.__init__(self.config)

    def process_candles(
        self, data: Union[pd.DataFrame, List[StrategyCandle], List[dict]]
    ) -> ISSSnapshot:
        """Processes a sequence of candles in clean batch execution.

        Calculates a fresh run on an isolated temporary engine so that any
        mid-batch failure or validation error leaves existing state 100% unmutated.
        Atomically replaces engine state only upon success.
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
        self._last_received_open_time = temp_engine._last_received_open_time
        self._last_received_index = temp_engine._last_received_index
        self._candidate_seq = temp_engine._candidate_seq
        self._is_unresolved = temp_engine._is_unresolved
        self._unresolved_dependency = temp_engine._unresolved_dependency

        return self.get_snapshot()

    def process_candle(self, candle: Union[StrategyCandle, dict]) -> ISSSnapshot:
        """Processes a single sequentially delivered candle incrementally.

        Policy for dictionary inputs:
        Dictionary inputs must explicitly supply an integer 'index'. Inferred index
        arithmetic is strictly prohibited.
        """
        if not isinstance(candle, StrategyCandle):
            if isinstance(candle, dict):
                if "index" not in candle or candle["index"] is None:
                    raise ValueError("Incremental candle dictionary must explicitly provide an integer 'index'.")
                if isinstance(candle["index"], bool) or not isinstance(candle["index"], int):
                    raise TypeError(f"Candle index must be int, got {type(candle['index']).__name__}")
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
                last_received_index=self.last_received_index,
                confirmed_events=tuple(self._confirmed_events),
                diagnostic_type=ISSDiagnosticType.WAITING_FOR_MAIN_PREREQUISITES,
                is_unresolved=self.is_unresolved,
                unresolved_dependency=self._unresolved_dependency,
            )

        visible_points = ()
        attempted_pts = None
        tracking_pts = ()

        if cand.lifecycle_status in (
            ISSLifecycleStatus.ELIGIBLE_SEARCH,
            ISSLifecycleStatus.CONFIRMED,
        ):
            visible_points = tuple(cand.internal_points)
        elif cand.lifecycle_status == ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY:
            visible_points = tuple(cand.attempted_points) if cand.attempted_points else tuple(cand.internal_points)
            attempted_pts = tuple(cand.attempted_points) if cand.attempted_points else None
            tracking_pts = tuple(cand.tracking_points)

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
            attempted_points=attempted_pts,
            tracking_points=tracking_pts,
            active_zones=visible_zones,
            confirmed_events=tuple(self._confirmed_events),
            is_tracking_only=cand.is_tracking_only,
            last_processed_index=self._last_processed_index,
            last_received_index=self.last_received_index,
            diagnostic_type=cand.diagnostic_type,
            diagnostic_message=cand.diagnostic_message,
            is_unresolved=self.is_unresolved,
            unresolved_dependency=self._unresolved_dependency,
        )

    def _ingest_candle(self, candle: StrategyCandle) -> None:
        """Ingests a single candle with transactional lifecycle coordination.

        Entire transition is executed on staged working copies. If any validation
        or internal engine exception occurs, self is left 100% unmutated.
        """
        if not isinstance(candle, StrategyCandle):
            raise TypeError(f"Ingest candle requires StrategyCandle instance, got {type(candle).__name__}")

        if candle.is_forming or candle.bar_status != "CONFIRMED_COMPLETED":
            return

        if candle.index in self._received_indices:
            raise ValueError(f"Duplicate candle source index detected: {candle.index}")
        latest_received_time = (
            self._last_received_open_time
            if self._last_received_open_time is not None
            else self._last_processed_open_time
        )
        if latest_received_time is not None and candle.open_time <= latest_received_time:
            raise ValueError(
                f"Non-chronological candle open_time: {candle.open_time} <= {latest_received_time}"
            )

        # -------------------------------------------------------------
        # Stage the entire transition on staged working copies
        # -------------------------------------------------------------
        main_coord_copy = copy.deepcopy(self._main_coordinator)
        cand_copy = copy.deepcopy(self._active_candidate)
        confirmed_events_copy = list(self._confirmed_events)
        completed_candles_copy = list(self._completed_candles)
        candle_lookup_copy = dict(self._candle_lookup)
        received_indices_copy = set(self._received_indices)
        candidate_seq_copy = self._candidate_seq
        is_unresolved_copy = self._is_unresolved
        unresolved_dep_copy = self._unresolved_dependency
        last_processed_index_copy = self._last_processed_index
        last_processed_open_time_copy = self._last_processed_open_time
        last_received_index_copy = candle.index
        last_received_open_time_copy = candle.open_time

        # Ingest into main coordinator
        prev_choch_count = len(main_coord_copy.confirmed_choch_events)
        main_snap = main_coord_copy.process_candle(candle)

        received_indices_copy.add(candle.index)

        # Check main coordinator unresolved status
        if main_coord_copy.is_unresolved:
            is_unresolved_copy = True
            unresolved_dep_copy = "MAIN_CHOCH_IDENTIFICATION_CLOSE_AMBIGUITY"
            if cand_copy:
                cand_copy.diagnostic_type = ISSDiagnosticType.PAUSED_BY_UNRESOLVED_MAIN
                cand_copy.diagnostic_message = (
                    "Execution paused: main integrated path is unresolved (c1 == p2 dependency)."
                )
            # R29.3: Freeze authoritative processed markers; advance received markers only
            self._main_coordinator = main_coord_copy
            self._active_candidate = cand_copy
            self._received_indices = received_indices_copy
            self._last_received_open_time = last_received_open_time_copy
            self._last_received_index = last_received_index_copy
            self._is_unresolved = is_unresolved_copy
            self._unresolved_dependency = unresolved_dep_copy
            return

        completed_candles_copy.append(candle)
        candle_lookup_copy[candle.index] = candle
        last_processed_index_copy = candle.index
        last_processed_open_time_copy = candle.open_time

        # -------------------------------------------------------------
        # 1. Step Active Candidate Internal Structure First (if active)
        # -------------------------------------------------------------
        candidate_confirmed_this_bar = False

        if cand_copy is not None and cand_copy.lifecycle_status in (
            ISSLifecycleStatus.ELIGIBLE_SEARCH,
            ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY,
        ):
            cand_main_dir = cand_copy.identity.main_direction
            internal_snap = cand_copy.internal_msm_engine.process_candle(candle)

            if cand_copy.lifecycle_status == ISSLifecycleStatus.ELIGIBLE_SEARCH:
                extracted_points = extract_internal_points(
                    internal_snap=internal_snap,
                    main_direction=cand_main_dir,
                    boundary=cand_copy.boundary,
                )

                # Progressive out-of-bounds rejection
                out_of_bounds_point: Optional[InternalPoint] = None
                for pt in extracted_points:
                    if not pt.is_inside_boundary:
                        out_of_bounds_point = pt
                        break

                if out_of_bounds_point is not None:
                    cand_copy.lifecycle_status = ISSLifecycleStatus.OUT_OF_BOUNDS_REJECTED
                    cand_copy.diagnostic_type = ISSDiagnosticType.MARKED_POINT_OUT_OF_BOUNDS
                    cand_copy.diagnostic_message = (
                        f"Marked Point {out_of_bounds_point.point_number} ({out_of_bounds_point.role}) "
                        f"body edge {out_of_bounds_point.body_edge_price} outside boundary "
                        f"[{cand_copy.boundary.min_price}, {cand_copy.boundary.max_price}]."
                    )
                    # Clean up all tracking/active flags
                    cand_copy.internal_points = []
                    cand_copy.tracking_points = []
                    cand_copy.active_zones = []
                    cand_copy.is_tracking_only = False
                    cand_copy.attempted_points = None
                else:
                    cand_copy.internal_points = extracted_points

                    # Point 5 identification check
                    if len(extracted_points) == 5:
                        close_inside = cand_copy.boundary.contains_price(candle.close)
                        if close_inside:
                            candidate_confirmed_this_bar = True
                            cand_copy.lifecycle_status = ISSLifecycleStatus.CONFIRMED
                            cand_copy.diagnostic_type = ISSDiagnosticType.CONFIRMED_COMPLETION_INSIDE
                            cand_copy.diagnostic_message = (
                                "ISS confirmed: all 5 points inside boundary and completion close inside."
                            )

                            pt3 = extracted_points[2]
                            pt4 = extracted_points[3]
                            c3 = candle_lookup_copy[pt3.source_candle_index]
                            c4 = candle_lookup_copy[pt4.source_candle_index]
                            conf_avail = candle.close_time  # Unknown stays None

                            if cand_main_dir == Direction.DOWNWARD:
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

                            cand_copy.active_zones = [zone_l3, zone_l4]
                            event = ConfirmedISSEvent(
                                candidate_id=cand_copy.identity.candidate_id,
                                main_direction=cand_main_dir,
                                confirmation_candle_index=candle.index,
                                confirmation_time=conf_avail,
                                completion_close_price=candle.close,
                                captured_boundary=cand_copy.boundary,
                                internal_points=tuple(extracted_points),
                                level_3_zone=zone_l3,
                                level_4_zone=zone_l4,
                            )
                            cand_copy.confirmed_event = event
                            confirmed_events_copy.append(event)
                        else:
                            # Outside-range completion: check whether main continuation also occurred on this candle
                            # If tentative point was confirmed/broken by main continuation, candidate is cancelled!
                            # Otherwise, if main structure remains intact, candidate enters tracking only
                            msm_tentative = main_snap.msm_snapshot.tentative_point
                            if msm_tentative is None and len(main_coord_copy.confirmed_choch_events) == prev_choch_count:
                                # Main continuation broke level 3 on this same candle!
                                cand_copy.lifecycle_status = ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED
                                cand_copy.diagnostic_type = ISSDiagnosticType.CANCELLED_BY_MAIN_CONTINUATION
                                cand_copy.diagnostic_message = "Cancelled by main continuation break on completion candle."
                                cand_copy.internal_points = []
                                cand_copy.tracking_points = []
                                cand_copy.active_zones = []
                                cand_copy.is_tracking_only = False
                                cand_copy.attempted_points = None
                            else:
                                cand_copy.lifecycle_status = ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
                                cand_copy.diagnostic_type = ISSDiagnosticType.COMPLETION_CLOSE_OUTSIDE_RANGE
                                cand_copy.diagnostic_message = (
                                    f"Completion candle close {candle.close} outside boundary "
                                    f"[{cand_copy.boundary.min_price}, {cand_copy.boundary.max_price}]. Tracking only."
                                )
                                cand_copy.is_tracking_only = True
                                cand_copy.attempted_points = list(extracted_points)
                                cand_copy.tracking_points = extract_tracking_points(
                                    internal_snap=internal_snap,
                                    main_direction=cand_main_dir,
                                    boundary=cand_copy.boundary,
                                )
                                cand_copy.active_zones = []

            elif cand_copy.lifecycle_status == ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY:
                # Tracking only: continue internal MSM solely for tracking
                cand_copy.tracking_points = extract_tracking_points(
                    internal_snap=internal_snap,
                    main_direction=cand_main_dir,
                    boundary=cand_copy.boundary,
                )

        # -------------------------------------------------------------
        # 2. Main CHOCH and Continuation Coordination
        # -------------------------------------------------------------
        # Check if Main CHOCH confirmed on this candle
        if len(main_coord_copy.confirmed_choch_events) > prev_choch_count:
            if cand_copy and cand_copy.lifecycle_status in (
                ISSLifecycleStatus.ELIGIBLE_SEARCH,
                ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY,
            ):
                cand_copy.lifecycle_status = ISSLifecycleStatus.MAIN_CHOCH_CANCELLED
                cand_copy.diagnostic_type = ISSDiagnosticType.CANCELLED_BY_MAIN_CHOCH
                cand_copy.diagnostic_message = "Cancelled by main CHOCH confirmation."
                # R29.2: Clean cancellation cleanup
                cand_copy.internal_points = []
                cand_copy.tracking_points = []
                cand_copy.active_zones = []
                cand_copy.is_tracking_only = False
                cand_copy.attempted_points = None

            self._commit_staged_transition(
                main_coord=main_coord_copy,
                candidate=cand_copy,
                confirmed_events=confirmed_events_copy,
                completed_candles=completed_candles_copy,
                candle_lookup=candle_lookup_copy,
                received_indices=received_indices_copy,
                last_processed_index=last_processed_index_copy,
                last_processed_open_time=last_processed_open_time_copy,
                last_received_index=last_received_index_copy,
                last_received_open_time=last_received_open_time_copy,
                candidate_seq=candidate_seq_copy,
                is_unresolved=is_unresolved_copy,
                unresolved_dependency=unresolved_dep_copy,
            )
            return

        # Inspect current authoritative main MSM structure
        msm_snap = main_snap.msm_snapshot
        current_main_dir = main_coord_copy.direction

        main_level_2: Optional[SwingPoint] = (
            msm_snap.last_resistance
            if current_main_dir == Direction.DOWNWARD
            else msm_snap.last_support
        )
        main_level_3: Optional[SwingPoint] = msm_snap.tentative_point

        # R29.1: If tentative point disappeared while we were in unconfirmed search or tracking-only,
        # main continuation break has confirmed/removed level 3! Cancel candidate cleanly!
        if main_level_3 is None and not candidate_confirmed_this_bar:
            if cand_copy and cand_copy.lifecycle_status in (
                ISSLifecycleStatus.ELIGIBLE_SEARCH,
                ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY,
            ):
                cand_copy.lifecycle_status = ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED
                cand_copy.diagnostic_type = ISSDiagnosticType.CANCELLED_BY_MAIN_CONTINUATION
                cand_copy.diagnostic_message = "Cancelled by main continuation break."
                # R29.2: Clean cancellation cleanup
                cand_copy.internal_points = []
                cand_copy.tracking_points = []
                cand_copy.active_zones = []
                cand_copy.is_tracking_only = False
                cand_copy.attempted_points = None

            self._commit_staged_transition(
                main_coord=main_coord_copy,
                candidate=cand_copy,
                confirmed_events=confirmed_events_copy,
                completed_candles=completed_candles_copy,
                candle_lookup=candle_lookup_copy,
                received_indices=received_indices_copy,
                last_processed_index=last_processed_index_copy,
                last_processed_open_time=last_processed_open_time_copy,
                last_received_index=last_received_index_copy,
                last_received_open_time=last_received_open_time_copy,
                candidate_seq=candidate_seq_copy,
                is_unresolved=is_unresolved_copy,
                unresolved_dependency=unresolved_dep_copy,
            )
            return

        # Check if Main Level 2 is confirmed and Main Level 3 exists
        if main_level_2 is not None and main_level_2.is_confirmed and main_level_3 is not None:
            is_new_identification = False
            if cand_copy is None:
                is_new_identification = True
            else:
                prev_id = cand_copy.identity
                if (
                    prev_id.main_level_3_identified_bar_index != main_level_3.identified_bar_index
                    or prev_id.main_direction != current_main_dir
                ):
                    is_new_identification = True

            if is_new_identification:
                candidate_seq_copy += 1
                cand_id = (
                    f"iss_cand_{current_main_dir.value.lower()}_"
                    f"{main_level_3.candle_index}_bar{main_level_3.identified_bar_index}_{candidate_seq_copy}"
                )
                boundary = FrozenBoundary(
                    min_price=min(main_level_2.price, main_level_3.price),
                    max_price=max(main_level_2.price, main_level_3.price),
                    main_level_2_price=main_level_2.price,
                    main_level_3_price=main_level_3.price,
                    frozen_at_candle_index=candle.index,
                    frozen_at_time=candle.close_time,  # Unknown stays None
                )
                identity = CandidateIdentity(
                    candidate_id=cand_id,
                    sequence_number=candidate_seq_copy,
                    main_direction=current_main_dir,
                    main_level_2_index=main_level_2.candle_index,
                    main_level_2_price=main_level_2.price,
                    main_level_3_index=main_level_3.candle_index,
                    main_level_3_price=main_level_3.price,
                    main_level_3_identified_bar_index=main_level_3.identified_bar_index,
                    frozen_at_candle_index=candle.index,
                    frozen_at_time=candle.close_time,  # Unknown stays None
                )
                internal_dir = (
                    Direction.UPWARD
                    if current_main_dir == Direction.DOWNWARD
                    else Direction.DOWNWARD
                )
                # Pullback scan begins strictly after identifying candle's open time
                internal_msm = MSMEngine(
                    MSMConfig(
                        direction=internal_dir,
                        start_candle_time=main_level_3.candle_open_time,
                        strictly_after_candle_time=candle.open_time,
                    )
                )
                l3_candles = [c for c in completed_candles_copy if c.open_time >= main_level_3.candle_open_time]
                if l3_candles:
                    internal_msm.process_candles(l3_candles)

                cand_copy = _CandidateTrackingState(
                    identity=identity,
                    boundary=boundary,
                    internal_msm_engine=internal_msm,
                    lifecycle_status=ISSLifecycleStatus.ELIGIBLE_SEARCH,
                    diagnostic_type=ISSDiagnosticType.ELIGIBLE_SEARCH_ACTIVE,
                    diagnostic_message="Fresh ISS search opened.",
                )

        # Commit all staged mutations atomically
        self._commit_staged_transition(
            main_coord=main_coord_copy,
            candidate=cand_copy,
            confirmed_events=confirmed_events_copy,
            completed_candles=completed_candles_copy,
            candle_lookup=candle_lookup_copy,
            received_indices=received_indices_copy,
            last_processed_index=last_processed_index_copy,
            last_processed_open_time=last_processed_open_time_copy,
            last_received_index=last_received_index_copy,
            last_received_open_time=last_received_open_time_copy,
            candidate_seq=candidate_seq_copy,
            is_unresolved=is_unresolved_copy,
            unresolved_dependency=unresolved_dep_copy,
        )

    def _commit_staged_transition(
        self,
        main_coord: MSMChochCoordinator,
        candidate: Optional[_CandidateTrackingState],
        confirmed_events: List[ConfirmedISSEvent],
        completed_candles: List[StrategyCandle],
        candle_lookup: Dict[int, StrategyCandle],
        received_indices: Set[int],
        last_processed_index: int,
        last_processed_open_time: Optional[datetime],
        last_received_index: int,
        last_received_open_time: Optional[datetime],
        candidate_seq: int,
        is_unresolved: bool,
        unresolved_dependency: Optional[str],
    ) -> None:
        """Atomically commits staged working copies to live engine instance."""
        self._main_coordinator = main_coord
        self._active_candidate = candidate
        self._confirmed_events = confirmed_events
        self._completed_candles = completed_candles
        self._candle_lookup = candle_lookup
        self._received_indices = received_indices
        self._last_processed_open_time = last_processed_open_time
        self._last_processed_index = last_processed_index
        self._last_received_open_time = last_received_open_time
        self._last_received_index = last_received_index
        self._candidate_seq = candidate_seq
        self._is_unresolved = is_unresolved
        self._unresolved_dependency = unresolved_dependency
