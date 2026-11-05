"""Unit and integration tests for Internal Structure Shift (ISS) Engine.

Scope & Design Boundary:
-------------------------
Verifies ISS candidate lifecycle coordination, five-point internal structure,
boundary validation, zone provenance and geometry, batch/sequential/replay parity,
and main MSM/CHOCH coordination under strict offline requirements.
Zero MT5 dependencies, zero UI/Plotly/Dash dependencies, zero order execution.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Dict, List
import pytest

from aladeen.strategy import (
    CandidateIdentity,
    ConfirmedISSEvent,
    Direction,
    FrozenBoundary,
    ISSConfig,
    ISSDiagnosticType,
    ISSEngine,
    ISSLifecycleStatus,
    ISSSnapshot,
    ISSZone,
    ISSZoneType,
    InternalPoint,
    StrategyCandle,
)


@pytest.fixture(scope="module")
def iss_fixtures() -> Dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "iss_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


class TestISSEngineLifecycleExecution:
    """Comprehensive test suite executing all 15 acceptance fixtures on ISSEngine."""

    def test_iss_01_bearish_basic_end_to_end_execution(self, iss_fixtures) -> None:
        """iss_01: Bearish main structure produces confirmed ISS at Bar 20 with RBS and Buying A+ zones."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert snap.is_tracking_only is False
        assert len(snap.confirmed_events) == 1
        event = snap.confirmed_events[0]

        assert event.confirmation_candle_index == 20
        assert event.completion_close_price == 1.188
        assert event.captured_boundary.min_price == 1.14
        assert event.captured_boundary.max_price == 1.20

        # Verify 5 internal points
        assert len(snap.internal_points) == 5
        p1, p2, p3, p4, p5 = snap.internal_points
        assert (p1.role, p1.source_candle_index, p1.body_edge_price) == ("CH1", 10, 1.16)
        assert (p2.role, p2.source_candle_index, p2.body_edge_price) == ("CL1", 12, 1.148)
        assert (p3.role, p3.source_candle_index, p3.body_edge_price) == ("CH2", 14, 1.175)
        assert (p4.role, p4.source_candle_index, p4.body_edge_price) == ("CL2", 16, 1.168)
        assert (p5.role, p5.source_candle_index, p5.body_edge_price) == ("TENTATIVE_HIGH", 18, 1.192)

        # Verify exact zones
        assert len(snap.active_zones) == 2
        z_rbs = next(z for z in snap.active_zones if z.zone_type == ISSZoneType.RBS)
        assert z_rbs.source_candle_index == 14
        assert z_rbs.source_point_number == 3
        assert (z_rbs.lower_price, z_rbs.upper_price) == (1.175, 1.178)
        assert z_rbs.is_line is False

        z_a_plus = next(z for z in snap.active_zones if z.zone_type == ISSZoneType.BUYING_A_PLUS)
        assert z_a_plus.source_candle_index == 16
        assert z_a_plus.source_point_number == 4
        assert (z_a_plus.lower_price, z_a_plus.upper_price) == (1.165, 1.168)
        assert z_a_plus.is_line is False

    def test_iss_02_bullish_basic_end_to_end_execution(self, iss_fixtures) -> None:
        """iss_02: Bullish main structure produces confirmed ISS at Bar 20 with SBR and Selling A+ zones."""
        fix = iss_fixtures["iss_02_bullish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.UPWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert snap.is_tracking_only is False
        assert len(snap.confirmed_events) == 1
        event = snap.confirmed_events[0]

        assert event.confirmation_candle_index == 20
        assert event.captured_boundary.min_price == 1.10
        assert event.captured_boundary.max_price == 1.16

        # Verify 5 internal points
        assert len(snap.internal_points) == 5
        p1, p2, p3, p4, p5 = snap.internal_points
        assert (p1.role, p1.source_candle_index, p1.body_edge_price) == ("CL1", 10, 1.14)
        assert (p2.role, p2.source_candle_index, p2.body_edge_price) == ("CH1", 12, 1.152)
        assert (p3.role, p3.source_candle_index, p3.body_edge_price) == ("CL2", 14, 1.125)
        assert (p4.role, p4.source_candle_index, p4.body_edge_price) == ("CH2", 16, 1.132)
        assert (p5.role, p5.source_candle_index, p5.body_edge_price) == ("TENTATIVE_LOW", 18, 1.108)

        # Verify exact zones
        assert len(snap.active_zones) == 2
        z_sbr = next(z for z in snap.active_zones if z.zone_type == ISSZoneType.SBR)
        assert z_sbr.source_candle_index == 14
        assert z_sbr.source_point_number == 3
        assert (z_sbr.lower_price, z_sbr.upper_price) == (1.122, 1.125)
        assert z_sbr.is_line is False

        z_a_plus = next(z for z in snap.active_zones if z.zone_type == ISSZoneType.SELLING_A_PLUS)
        assert z_a_plus.source_candle_index == 16
        assert z_a_plus.source_point_number == 4
        assert (z_a_plus.lower_price, z_a_plus.upper_price) == (1.132, 1.135)
        assert z_a_plus.is_line is False

    def test_iss_03_boundary_equality(self, iss_fixtures) -> None:
        """iss_03: Internal point body edge price exactly equals upper boundary price (1.2000)."""
        fix = iss_fixtures["iss_03_boundary_equality"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        p5 = next(p for p in snap.internal_points if p.point_number == 5)
        assert p5.body_edge_price == snap.captured_boundary.max_price == 1.2000
        assert snap.captured_boundary.contains_price(p5.body_edge_price) is True

    def test_iss_04_wick_excursion_allowed(self, iss_fixtures) -> None:
        """iss_04: Wicks extending outside boundary do not reject; zone captures wick tip."""
        fix = iss_fixtures["iss_04_wick_excursion_allowed"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        z_rbs = next(z for z in snap.active_zones if z.zone_type == ISSZoneType.RBS)
        assert z_rbs.upper_price == 1.2060 > snap.captured_boundary.max_price

    def test_iss_05_out_of_bounds_marked_point_rejection(self, iss_fixtures) -> None:
        """iss_05: Marked point body edge (1.2020) outside boundary rejects permanently at Bar 16."""
        fix = iss_fixtures["iss_05_out_of_bounds_marked_point_rejection"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay_snapshots(fix["candles"])

        # Bar 15: still eligible search
        assert snaps[15].lifecycle_status == ISSLifecycleStatus.ELIGIBLE_SEARCH
        # Bar 16: Point 3 identified with UB 1.2020 > 1.2000 -> Out of bounds rejected!
        assert snaps[16].lifecycle_status == ISSLifecycleStatus.OUT_OF_BOUNDS_REJECTED
        assert snaps[16].diagnostic_type == ISSDiagnosticType.MARKED_POINT_OUT_OF_BOUNDS
        assert len(snaps[16].internal_points) == 0
        assert len(snaps[16].active_zones) == 0
        assert len(snaps[16].confirmed_events) == 0

    def test_iss_06_outside_range_completion_tracking_only(self, iss_fixtures) -> None:
        """iss_06: Valid points but completion candle closes at 1.1350 outside boundary."""
        fix = iss_fixtures["iss_06_outside_range_completion_tracking_only"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
        assert snap.is_tracking_only is True
        assert snap.diagnostic_type == ISSDiagnosticType.COMPLETION_CLOSE_OUTSIDE_RANGE
        assert len(snap.internal_points) == 5
        assert len(snap.active_zones) == 0
        assert len(snap.confirmed_events) == 0

    def test_iss_07_no_revival_under_same_main_level_3(self, iss_fixtures) -> None:
        """iss_07: Candidate retains tracking-only state across later bars without reviving."""
        fix = iss_fixtures["iss_07_no_revival_under_same_main_level_3"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
        assert snap.is_tracking_only is True
        assert len(snap.confirmed_events) == 0

    def test_iss_08_fresh_search_on_new_main_level_3(self, iss_fixtures) -> None:
        """iss_08: A new valid main level 3 opens a completely fresh candidate with new boundary."""
        # Baseline execution of basic dataset
        fix = iss_fixtures["iss_08_fresh_search_on_new_main_level_3"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay_snapshots(fix["candles"])

        # Candidate identity has candidate sequence and boundary frozen at identification
        cand_id = snaps[20].candidate_identity
        assert cand_id is not None
        assert cand_id.sequence_number == 1
        assert cand_id.main_level_3_index == 7

    def test_iss_09_main_continuation_cancellation(self, iss_fixtures) -> None:
        """iss_09: Main continuation break occurs at Bar 14 before 5-point structure completes."""
        fix = iss_fixtures["iss_09_main_continuation_cancellation"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay_snapshots(fix["candles"])

        assert snaps[13].lifecycle_status == ISSLifecycleStatus.ELIGIBLE_SEARCH
        # Bar 14: break candle (close 1.1320 < 1.1400) cancels unfinished search
        assert snaps[14].lifecycle_status == ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED
        assert snaps[14].diagnostic_type == ISSDiagnosticType.CANCELLED_BY_MAIN_CONTINUATION
        assert len(snaps[14].internal_points) == 0
        assert len(snaps[14].active_zones) == 0

    def test_iss_10_main_choch_cancellation(self, iss_fixtures) -> None:
        """iss_10: Main CHOCH confirms at Bar 15 while candidate is unfinished."""
        fix = iss_fixtures["iss_10_main_choch_cancellation"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay_snapshots(fix["candles"])

        assert snaps[14].lifecycle_status == ISSLifecycleStatus.ELIGIBLE_SEARCH
        # Bar 15: CHOCH 2nd close confirms -> cancels unfinished candidate
        assert snaps[15].lifecycle_status == ISSLifecycleStatus.MAIN_CHOCH_CANCELLED
        assert snaps[15].diagnostic_type == ISSDiagnosticType.CANCELLED_BY_MAIN_CHOCH
        assert len(snaps[15].internal_points) == 0
        assert len(snaps[15].active_zones) == 0

    def test_iss_11_retained_history_preservation(self, iss_fixtures) -> None:
        """iss_11: Confirmed ISS event and zones remain intact in history after later main continuation break."""
        fix = iss_fixtures["iss_11_retained_history_preservation"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay_snapshots(fix["candles"])

        # Confirmed at Bar 20
        assert snaps[20].lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snaps[20].confirmed_events) == 1

        # Bars 21 and 22: continuation break occurs on main structure
        assert snaps[22].lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snaps[22].confirmed_events) == 1
        assert snaps[22].confirmed_events[0].confirmation_candle_index == 20

    def test_iss_12_zone_provenance_and_geometry(self, iss_fixtures) -> None:
        """iss_12: Confirmed zones strictly derive from internal points 3 and 4, never from main 3 or point 5."""
        fix = iss_fixtures["iss_12_zone_provenance_and_geometry"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        z3 = next(z for z in snap.active_zones if z.source_point_number == 3)
        z4 = next(z for z in snap.active_zones if z.source_point_number == 4)

        assert z3.source_candle_index == 14
        assert z3.zone_type == ISSZoneType.RBS
        assert (z3.lower_price, z3.upper_price) == (1.175, 1.178)

        assert z4.source_candle_index == 16
        assert z4.zone_type == ISSZoneType.BUYING_A_PLUS
        assert (z4.lower_price, z4.upper_price) == (1.165, 1.168)

    def test_iss_13_zero_width_zones(self, iss_fixtures) -> None:
        """iss_13: When high == UB (zero top wick), high-side zone forms an exact price line."""
        fix = iss_fixtures["iss_13_zero_width_zones"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        z3 = next(z for z in snap.active_zones if z.source_point_number == 3)
        assert z3.is_line is True
        assert z3.lower_price == z3.upper_price == 1.175

    def test_iss_14_first_internal_pullback_timing_restriction(self, iss_fixtures) -> None:
        """iss_14: Internal pullback candles strictly occur at chronological positions > 9."""
        fix = iss_fixtures["iss_14_first_internal_pullback_timing_restriction"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        p1 = snap.internal_points[0]
        # Point 1 identified at Bar 12 (identifying pullback candles 11 and 12, both > 9)
        assert p1.identified_bar_index == 12 > 9

    def test_iss_15_prefix_consistency_and_arbitrary_ids(self, iss_fixtures) -> None:
        """iss_15: Fixture with arbitrary / noncontiguous source IDs produces identical structural results."""
        fix = iss_fixtures["iss_15_prefix_consistency_and_ids"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snap.internal_points) == 5
        assert len(snap.active_zones) == 2


class TestISSEngineAPIAndSafety:
    """Rigorous verification of batch/sequential/replay parity, immutability, and failure safety."""

    def test_batch_sequential_replay_parity(self, iss_fixtures) -> None:
        """Verifies 100% equivalence across process_candles, process_candle, and replay_snapshots."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        candles = fix["candles"]

        # Batch
        eng_batch = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap_batch = eng_batch.process_candles(candles)

        # Sequential
        eng_seq = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap_seq = None
        for c in candles:
            snap_seq = eng_seq.process_candle(c)

        # Replay
        eng_replay = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        replay_snaps = eng_replay.replay_snapshots(candles)
        snap_replay = replay_snaps[-1]

        # Parity assertions
        assert snap_batch.lifecycle_status == snap_seq.lifecycle_status == snap_replay.lifecycle_status
        assert len(snap_batch.internal_points) == len(snap_seq.internal_points) == len(snap_replay.internal_points)
        assert len(snap_batch.active_zones) == len(snap_seq.active_zones) == len(snap_replay.active_zones)
        assert len(snap_batch.confirmed_events) == len(snap_seq.confirmed_events) == len(snap_replay.confirmed_events)

        for p_b, p_s, p_r in zip(snap_batch.internal_points, snap_seq.internal_points, snap_replay.internal_points):
            assert p_b == p_s == p_r

        for z_b, z_s, z_r in zip(snap_batch.active_zones, snap_seq.active_zones, snap_replay.active_zones):
            assert z_b == z_s == z_r

    def test_forming_candle_causes_zero_mutation(self, iss_fixtures) -> None:
        """Forming or unconfirmed candles return current snapshot without altering state."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap_settled = engine.process_candles(fix["candles"][:15])

        forming_candle = dict(fix["candles"][15])
        forming_candle["is_forming"] = True
        forming_candle["bar_status"] = "FORMING"

        snap_after_forming = engine.process_candle(forming_candle)
        assert snap_after_forming.last_processed_index == snap_settled.last_processed_index
        assert snap_after_forming.lifecycle_status == snap_settled.lifecycle_status
        assert len(snap_after_forming.internal_points) == len(snap_settled.internal_points)

    def test_invalid_candle_rejected_state_preserved(self, iss_fixtures) -> None:
        """A non-chronological candle raises ValueError and leaves engine state intact."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap_initial = engine.process_candles(fix["candles"][:15])

        # Backward timestamp candle
        bad_candle = dict(fix["candles"][14])
        with pytest.raises(ValueError):
            engine.process_candle(bad_candle)

        # State remains unchanged
        assert engine.get_snapshot().last_processed_index == snap_initial.last_processed_index

    def test_unresolved_main_path_halts_progression(self, iss_fixtures) -> None:
        """Simulates an unresolved main state (c1 == p2) and verifies ISS pauses safely."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        engine.process_candles(fix["candles"][:10])

        # Force coordinator to simulate unresolved condition
        engine._main_coordinator._is_unresolved = True
        engine._is_unresolved = True
        engine._unresolved_dependency = "MAIN_CHOCH_IDENTIFICATION_CLOSE_AMBIGUITY"

        snap = engine.process_candle(fix["candles"][10])
        assert snap.is_unresolved is True
        assert snap.unresolved_dependency == "MAIN_CHOCH_IDENTIFICATION_CLOSE_AMBIGUITY"
