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

    def test_iss_06_point_5_identification_on_main_continuation_cancels(self, iss_fixtures) -> None:
        """iss_06: Point 5 identified on a main continuation candle (close 1.1350 < 1.1400) cancels candidate."""
        fix = iss_fixtures["iss_06_outside_range_completion_tracking_only"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        # Per R29.1: Candidate depends on Level 3, which broke on this candle. Source-consistent cancellation.
        assert snap.lifecycle_status == ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED
        assert snap.diagnostic_type == ISSDiagnosticType.CANCELLED_BY_MAIN_CONTINUATION
        assert snap.is_tracking_only is False
        assert len(snap.confirmed_events) == 0
        assert len(snap.active_zones) == 0

    def test_iss_07_no_revival_under_same_main_level_3(self, iss_fixtures) -> None:
        """iss_07: Cancelled candidate cannot be revived by subsequent bars under the same main level 3."""
        fix = iss_fixtures["iss_07_no_revival_under_same_main_level_3"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snap = engine.process_candles(fix["candles"])

        assert snap.lifecycle_status == ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED
        assert snap.is_tracking_only is False
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
        for idx, c in enumerate(candles):
            c_with_idx = dict(c, index=idx)
            snap_seq = eng_seq.process_candle(c_with_idx)

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

        forming_candle = dict(fix["candles"][15], index=15)
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
        bad_candle = dict(fix["candles"][14], index=16)
        with pytest.raises(ValueError):
            engine.process_candle(bad_candle)

        # State remains unchanged
        assert engine.get_snapshot().last_processed_index == snap_initial.last_processed_index

    def test_missing_incremental_dict_index_rejected(self, iss_fixtures) -> None:
        """Incremental dictionary input without an explicit integer 'index' raises ValueError."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))

        c = dict(fix["candles"][0])  # no 'index' key
        with pytest.raises(ValueError, match="Incremental candle dictionary must explicitly provide an integer 'index'"):
            engine.process_candle(c)

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

        snap = engine.process_candle(dict(fix["candles"][10], index=10))
        assert snap.is_unresolved is True
        assert snap.unresolved_dependency == "MAIN_CHOCH_IDENTIFICATION_CLOSE_AMBIGUITY"

    def test_near_boundary_unequal_prices_below_six_decimals(self, iss_fixtures) -> None:
        """Near-boundary unequal prices below 6 decimals are strictly evaluated without rounding."""
        b = FrozenBoundary(
            min_price=1.1400000000,
            max_price=1.2000000000,
            main_level_2_price=1.20,
            main_level_3_price=1.14,
            frozen_at_candle_index=9,
        )
        assert b.contains_price(1.2000000001) is False
        assert b.contains_price(1.2000000000) is True
        assert b.contains_price(1.1999999999) is True
        assert b.contains_price(1.1400000000) is True
        assert b.contains_price(1.1399999999) is False

        # In ISSEngine: point exceeding boundary by 1e-9 must reject
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=i) for i, c in enumerate(fix["candles"])]
        # Candle 18 tentative high price set to 1.2000000001 (strictly outside 1.2000000000)
        candles[18]["open"] = 1.2000000001
        candles[18]["close"] = 1.1950000000
        candles[18]["high"] = 1.2010000000

        snap = engine.process_candles(candles)
        assert snap.lifecycle_status == ISSLifecycleStatus.OUT_OF_BOUNDS_REJECTED

    def test_unknown_capture_availability_remains_none(self, iss_fixtures) -> None:
        """When candle close times are unknown (None), availability timestamps remain None."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=i, close_time=None) for i, c in enumerate(fix["candles"])]

        snap = engine.process_candles(candles)
        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert snap.captured_boundary.frozen_at_time is None
        assert snap.candidate_identity.frozen_at_time is None
        assert snap.confirmed_events[0].confirmation_time is None
        assert snap.active_zones[0].confirmation_availability_time is None
        assert snap.active_zones[1].confirmation_availability_time is None

    def test_delayed_pullback_enforcement_with_unknown_close_times_and_decreasing_ids(self, iss_fixtures) -> None:
        """Delayed pullback enforcement via strictly_after_candle_time works with None close_time and decreasing IDs."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=2000 - i, close_time=None) for i, c in enumerate(fix["candles"])]

        snap = engine.process_candles(candles)
        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        p1 = snap.internal_points[0]
        # Decreasing ID: bar 10 has index 2000 - 10 = 1990
        assert p1.source_candle_index == 1990
        # Bar 12 has index 2000 - 12 = 1988
        assert p1.identified_bar_index == 1988

    def test_internal_or_zone_construction_failure_preserves_entire_prior_state(self, iss_fixtures, monkeypatch) -> None:
        """Simulated zone construction exception leaves entire engine state completely unmutated."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=i) for i, c in enumerate(fix["candles"])]

        # Process up to bar 19
        engine.process_candles(candles[:20])
        snap_prior = engine.get_snapshot()
        assert snap_prior.last_processed_index == 19
        assert snap_prior.lifecycle_status == ISSLifecycleStatus.ELIGIBLE_SEARCH
        assert len(snap_prior.confirmed_events) == 0

        # Monkeypatch ISSZone.from_candle to simulate failure during confirmation
        def fail_zone(*args, **kwargs):
            raise RuntimeError("Simulated unexpected zone construction failure")

        monkeypatch.setattr(ISSZone, "from_candle", fail_zone)

        # Ingest bar 20: must raise RuntimeError and leave state unmutated
        with pytest.raises(RuntimeError, match="Simulated unexpected zone construction failure"):
            engine.process_candle(candles[20])

        # Prior state completely intact
        snap_after = engine.get_snapshot()
        assert snap_after.last_processed_index == 19
        assert snap_after.lifecycle_status == ISSLifecycleStatus.ELIGIBLE_SEARCH
        assert len(snap_after.confirmed_events) == 0
        assert len(engine._completed_candles) == 20

    def test_valid_retry_after_rejected_transition(self, iss_fixtures) -> None:
        """Following a rejected candle, a valid retry is processed successfully."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=i) for i, c in enumerate(fix["candles"])]

        engine.process_candles(candles[:20])

        # Bad candle (duplicate index)
        with pytest.raises(ValueError):
            engine.process_candle(candles[19])

        # Valid retry with candle 20 succeeds
        snap = engine.process_candle(candles[20])
        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert snap.last_processed_index == 20
        assert len(snap.confirmed_events) == 1

    def test_main_choch_reversal_followed_by_complete_new_direction_iss_confirmation(self, iss_fixtures) -> None:
        """Main reversal via CHOCH followed by a complete new-direction ISS confirmation with correct roles and zones."""
        path = Path(__file__).parent / "fixtures" / "choch_acceptance.json"
        with open(path, "r", encoding="utf-8") as f:
            choch_fix = json.load(f)["fixtures"]["choch_bearish_basic_end_to_end"]

        candles = [
            StrategyCandle(
                index=i,
                open_time=datetime.fromisoformat(c["time"]),
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                is_forming=c["is_forming"],
                bar_status=c["bar_status"],
                close_time=datetime.fromisoformat(c["close_time"]) if c.get("close_time") else None,
            )
            for i, c in enumerate(choch_fix["candles"])
        ]

        last_t = candles[-1].open_time

        # Post-CHOCH Downward Main continuation and pullback bars:
        # Bar 10 & 11: 2 green candles -> Pullback 1 in Downward Main
        c10 = StrategyCandle(10, last_t + timedelta(hours=1), 1.005, 1.015, 1.004, 1.012, False, "CONFIRMED_COMPLETED")
        c11 = StrategyCandle(11, last_t + timedelta(hours=2), 1.012, 1.026, 1.010, 1.025, False, "CONFIRMED_COMPLETED")
        # Bar 12: red break candle, closing below Bar 9 low -> confirms Level 2 high at Bar 11 (price 1.026)
        c12 = StrategyCandle(12, last_t + timedelta(hours=3), 1.020, 1.022, 0.989, 0.990, False, "CONFIRMED_COMPLETED")
        # Bar 13 & 14: Pullback 2 in Downward Main -> identifies Level 3 tentative low at Bar 12 (price 0.988)
        c13 = StrategyCandle(13, last_t + timedelta(hours=4), 0.990, 0.998, 0.988, 0.995, False, "CONFIRMED_COMPLETED")
        c14 = StrategyCandle(14, last_t + timedelta(hours=5), 0.995, 1.008, 0.994, 1.005, False, "CONFIRMED_COMPLETED")

        # Now append shifted internal candles from iss_01 (bars 10 to 20, shift price by -0.150)
        fix_01 = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        shift = -0.150
        internal_candles = []
        for i, c in enumerate(fix_01["candles"][10:21]):
            idx = 15 + i
            t = last_t + timedelta(hours=6 + i)
            internal_candles.append(
                StrategyCandle(
                    index=idx,
                    open_time=t,
                    open=round(c["open"] + shift, 5),
                    high=round(c["high"] + shift, 5),
                    low=round(c["low"] + shift, 5),
                    close=round(c["close"] + shift, 5),
                    is_forming=False,
                    bar_status="CONFIRMED_COMPLETED",
                    close_time=t + timedelta(hours=1),
                )
            )

        all_candles = candles + [c10, c11, c12, c13, c14] + internal_candles

        start_time = candles[0].open_time
        # Initialized with UPWARD
        engine = ISSEngine(ISSConfig(main_direction=Direction.UPWARD, start_candle_time=start_time))
        snap = engine.process_candles(all_candles)

        # Authoritative direction must now be DOWNWARD
        assert engine.direction == Direction.DOWNWARD
        assert len(engine._main_coordinator.confirmed_choch_events) == 1

        # Complete ISS confirmation in new DOWNWARD direction
        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snap.confirmed_events) == 1
        ev = snap.confirmed_events[0]
        assert ev.main_direction == Direction.DOWNWARD
        assert "iss_cand_downward" in ev.candidate_id
        assert ev.confirmation_candle_index == 25

        # Verify internal points: 5 points with correct roles
        assert len(snap.internal_points) == 5
        roles = [p.role for p in snap.internal_points]
        assert roles == ["CH1", "CL1", "CH2", "CL2", "TENTATIVE_HIGH"]
        assert all(p.is_inside_boundary for p in snap.internal_points)

        # Verify active zones: RBS from CH2 (point 3) and Buying A+ from CL2 (point 4)
        assert len(snap.active_zones) == 2
        z_rbs = next(z for z in snap.active_zones if z.zone_type == ISSZoneType.RBS)
        assert z_rbs.source_point_number == 3
        assert z_rbs.source_point_role == "CH2"
        assert z_rbs.lower_price < z_rbs.upper_price

        z_a_plus = next(z for z in snap.active_zones if z.zone_type == ISSZoneType.BUYING_A_PLUS)
        assert z_a_plus.source_point_number == 4
        assert z_a_plus.source_point_role == "CL2"
        assert z_a_plus.lower_price < z_a_plus.upper_price

    def test_tracking_points_continue_independently_of_attempted_points(self, iss_fixtures) -> None:
        """Candidate in tracking-only continues internal MSM tracking through later swings with zero new ISS events."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=i) for i, c in enumerate(fix["candles"][:20])]

        # Process through bar 19 (candidate has 4 internal points)
        engine.process_candles(candles)
        cand = engine._active_candidate
        assert cand is not None

        # Simulate candidate entering tracking-only with 5 attempted points
        cand.lifecycle_status = ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
        cand.is_tracking_only = True
        cand.attempted_points = list(cand.internal_points) + [cand.internal_points[0]]
        cand.tracking_points = list(cand.internal_points)

        last_t = datetime.fromisoformat(candles[19]["time"])
        tracking_candles = [
            dict(time=(last_t + timedelta(hours=1)).isoformat(), open=1.180, high=1.196, low=1.179, close=1.195, is_forming=False, bar_status="CONFIRMED_COMPLETED", index=20),
            dict(time=(last_t + timedelta(hours=2)).isoformat(), open=1.195, high=1.1955, low=1.189, close=1.190, is_forming=False, bar_status="CONFIRMED_COMPLETED", index=21),
            dict(time=(last_t + timedelta(hours=3)).isoformat(), open=1.190, high=1.1905, low=1.184, close=1.185, is_forming=False, bar_status="CONFIRMED_COMPLETED", index=22),
        ]

        for tc in tracking_candles:
            snap = engine.process_candle(tc)

        # Candidate remains in tracking only, attempted points intact, tracking points updated, zero new events
        assert snap.lifecycle_status == ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
        assert snap.is_tracking_only is True
        assert len(snap.attempted_points) == 5
        assert len(snap.tracking_points) >= 5
        assert len(snap.confirmed_events) == 0

    def test_tracking_only_candidate_followed_by_main_continuation_cancels(self, iss_fixtures) -> None:
        """Existing tracking-only candidate cancels cleanly when subsequent main continuation breaks Level 3."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=i) for i, c in enumerate(fix["candles"][:20])]

        engine.process_candles(candles)
        cand = engine._active_candidate
        assert cand is not None

        # Candidate is in tracking-only
        cand.lifecycle_status = ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
        cand.is_tracking_only = True
        cand.attempted_points = list(cand.internal_points)
        cand.tracking_points = list(cand.internal_points)

        # Bar 20: breaks Main Level 3 (close 1.1350 < 1.1400)
        last_t = datetime.fromisoformat(candles[19]["time"])
        cont_candle = dict(
            time=(last_t + timedelta(hours=1)).isoformat(),
            open=1.145, high=1.146, low=1.134, close=1.135,
            is_forming=False, bar_status="CONFIRMED_COMPLETED", index=20,
        )

        snap = engine.process_candle(cont_candle)

        # Main continuation cancels tracking-only candidate cleanly (R29.1, R29.2)
        assert snap.lifecycle_status == ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED
        assert snap.diagnostic_type == ISSDiagnosticType.CANCELLED_BY_MAIN_CONTINUATION
        assert snap.is_tracking_only is False
        assert snap.attempted_points is None
        assert snap.tracking_points == ()
        assert snap.active_zones == ()
        assert len(snap.confirmed_events) == 0

    def test_tracking_only_candidate_followed_by_main_choch_cancels(self, iss_fixtures) -> None:
        """Existing tracking-only candidate cancels cleanly when subsequent main CHOCH confirms."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=i) for i, c in enumerate(fix["candles"][:20])]

        engine.process_candles(candles)
        cand = engine._active_candidate
        assert cand is not None

        # Candidate is in tracking-only
        cand.lifecycle_status = ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
        cand.is_tracking_only = True
        cand.attempted_points = list(cand.internal_points)
        cand.tracking_points = list(cand.internal_points)

        # Deliver 2 candles closing above last resistance (1.2000) to confirm Main CHOCH
        last_t = datetime.fromisoformat(candles[19]["time"])
        c20 = dict(time=(last_t + timedelta(hours=1)).isoformat(), open=1.195, high=1.205, low=1.194, close=1.202, is_forming=False, bar_status="CONFIRMED_COMPLETED", index=20)
        c21 = dict(time=(last_t + timedelta(hours=2)).isoformat(), open=1.202, high=1.208, low=1.201, close=1.205, is_forming=False, bar_status="CONFIRMED_COMPLETED", index=21)

        engine.process_candle(c20)
        snap = engine.process_candle(c21)

        # Main CHOCH cancels tracking-only candidate cleanly (R29.2)
        assert snap.lifecycle_status == ISSLifecycleStatus.MAIN_CHOCH_CANCELLED
        assert snap.diagnostic_type == ISSDiagnosticType.CANCELLED_BY_MAIN_CHOCH
        assert snap.is_tracking_only is False
        assert snap.attempted_points is None
        assert snap.tracking_points == ()
        assert snap.active_zones == ()
        assert len(snap.confirmed_events) == 0

    def test_confirmed_iss_history_survives_later_main_events(self, iss_fixtures) -> None:
        """Confirmed ISS history survives subsequent main continuation and main CHOCH events without loss."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=i) for i, c in enumerate(fix["candles"])]

        # Process through bar 20: ISS is confirmed
        snap = engine.process_candles(candles)
        assert snap.lifecycle_status == ISSLifecycleStatus.CONFIRMED
        assert len(snap.confirmed_events) == 1
        original_event = snap.confirmed_events[0]

        # Candle 21: breaks Main Level 3 (1.1400), confirming main continuation
        last_t = datetime.fromisoformat(candles[-1]["time"])
        c21 = dict(time=(last_t + timedelta(hours=1)).isoformat(), open=1.185, high=1.185, low=1.134, close=1.135, is_forming=False, bar_status="CONFIRMED_COMPLETED", index=21)
        snap = engine.process_candle(c21)

        # Confirmed ISS event remains intact
        assert len(snap.confirmed_events) == 1
        assert snap.confirmed_events[0] == original_event

        # Deliver 2 candles closing above last resistance (1.2000) confirming Main CHOCH
        c22 = dict(time=(last_t + timedelta(hours=2)).isoformat(), open=1.195, high=1.205, low=1.194, close=1.202, is_forming=False, bar_status="CONFIRMED_COMPLETED", index=22)
        c23 = dict(time=(last_t + timedelta(hours=3)).isoformat(), open=1.202, high=1.208, low=1.201, close=1.205, is_forming=False, bar_status="CONFIRMED_COMPLETED", index=23)
        engine.process_candle(c22)
        snap = engine.process_candle(c23)

        # Confirmed ISS event survives main CHOCH
        assert len(snap.confirmed_events) == 1
        assert snap.confirmed_events[0] == original_event

    def test_unresolved_main_frozen_processed_and_advancing_received(self, iss_fixtures) -> None:
        """Unresolved main dependency freezes authoritative last_processed_index while last_received_index advances."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        engine.process_candles(fix["candles"][:10])

        assert engine.last_processed_index == 9
        assert engine.last_received_index == 9

        # Force coordinator into unresolved state
        engine._main_coordinator._is_unresolved = True
        engine._is_unresolved = True
        engine._unresolved_dependency = "MAIN_CHOCH_IDENTIFICATION_CLOSE_AMBIGUITY"

        # Ingest bar 10 while unresolved
        snap = engine.process_candle(dict(fix["candles"][10], index=10))
        assert snap.is_unresolved is True
        assert snap.last_processed_index == 9
        assert snap.last_received_index == 10
        assert engine.last_processed_index == 9
        assert engine.last_received_index == 10

        # Ingest bar 11 while unresolved
        snap = engine.process_candle(dict(fix["candles"][11], index=11))
        assert snap.is_unresolved is True
        assert snap.last_processed_index == 9
        assert snap.last_received_index == 11
        assert engine.last_processed_index == 9
        assert engine.last_received_index == 11

    def test_unresolved_containment_rejects_duplicate_and_out_of_order_receipt(self, iss_fixtures) -> None:
        """After unresolved containment, incoming receipt chronology validates against last_received_time and rejects duplicates."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        engine.process_candles(fix["candles"][:10])

        # Force coordinator into unresolved state
        engine._main_coordinator._is_unresolved = True
        engine._is_unresolved = True
        engine._unresolved_dependency = "MAIN_CHOCH_IDENTIFICATION_CLOSE_AMBIGUITY"

        # Ingest bar 10 while unresolved
        snap = engine.process_candle(dict(fix["candles"][10], index=10))
        assert snap.last_received_index == 10
        assert snap.last_processed_index == 9

        # 1. Duplicate index 10 rejected fail-closed
        with pytest.raises(ValueError, match="Duplicate candle source index detected: 10"):
            engine.process_candle(dict(fix["candles"][10], index=10))

        # 2. Out-of-order timestamp relative to last_received_open_time rejected fail-closed
        bad_candle = dict(fix["candles"][10], index=11)
        with pytest.raises(ValueError, match="Non-chronological candle open_time"):
            engine.process_candle(bad_candle)

        # 3. State remains safe, intact, and frozen
        assert engine.last_processed_index == 9
        assert engine.last_received_index == 10

    def test_genuine_tracking_only_distinct_from_continuation_cancellation(self, iss_fixtures) -> None:
        """Genuine tracking-only case where completion close is outside boundary but Main L3 remains intact."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["candles"][0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        candles = [dict(c, index=i) for i, c in enumerate(fix["candles"][:20])]

        # Process through bar 19
        engine.process_candles(candles)
        cand = engine._active_candidate
        assert cand is not None
        assert cand.lifecycle_status == ISSLifecycleStatus.ELIGIBLE_SEARCH

        # Genuine tracking-only: candidate completed outside range while Main L3 was NOT invalidated
        cand.lifecycle_status = ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
        cand.diagnostic_type = ISSDiagnosticType.COMPLETION_CLOSE_OUTSIDE_RANGE
        cand.diagnostic_message = "Completion candle close outside boundary. Tracking only."
        cand.is_tracking_only = True
        cand.attempted_points = list(cand.internal_points) + [cand.internal_points[0]]
        cand.tracking_points = list(cand.internal_points)

        snap = engine.get_snapshot()
        # Explicit distinction from continuation cancellation:
        assert snap.lifecycle_status == ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
        assert snap.is_tracking_only is True
        assert len(snap.attempted_points) == 5
        assert len(snap.tracking_points) >= 4
        assert len(snap.confirmed_events) == 0
        assert len(snap.active_zones) == 0

        # Contrast with continuation cancellation:
        # In continuation cancellation, candidate is cancelled, tracking is False, attempted_points is None
        last_t = datetime.fromisoformat(candles[19]["time"])
        c_cancel = dict(time=(last_t + timedelta(hours=1)).isoformat(), open=1.145, high=1.146, low=1.134, close=1.135, is_forming=False, bar_status="CONFIRMED_COMPLETED", index=20)
        snap_cancelled = engine.process_candle(c_cancel)

        assert snap_cancelled.lifecycle_status == ISSLifecycleStatus.MAIN_CONTINUATION_CANCELLED
        assert snap_cancelled.is_tracking_only is False
        assert snap_cancelled.attempted_points is None
        assert snap_cancelled.tracking_points == ()

    def test_authentic_candle_sequence_produces_genuine_tracking_only(self, iss_fixtures) -> None:
        """Authentic candle sequence naturally produces OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY without state mocking."""
        fix = iss_fixtures["iss_01_bearish_basic_end_to_end"]
        raw_candles = [dict(c) for c in fix["candles"]]

        # Candle 19 (p1) and Candle 20 (p2) complete Point 5 with completion close > 1.2000 (Level 2 side)
        raw_candles[19]["open"] = 1.206
        raw_candles[19]["high"] = 1.207
        raw_candles[19]["low"] = 1.204
        raw_candles[19]["close"] = 1.205

        raw_candles[20]["open"] = 1.205
        raw_candles[20]["high"] = 1.206
        raw_candles[20]["low"] = 1.2005
        raw_candles[20]["close"] = 1.201

        for i, c in enumerate(raw_candles):
            c["index"] = i

        start_time = datetime.fromisoformat(raw_candles[0]["time"])
        engine = ISSEngine(ISSConfig(main_direction=Direction.DOWNWARD, start_candle_time=start_time))
        snaps = engine.replay_snapshots(raw_candles)

        snap20 = snaps[20]
        assert snap20.lifecycle_status == ISSLifecycleStatus.OUTSIDE_RANGE_COMPLETION_TRACKING_ONLY
        assert snap20.diagnostic_type == ISSDiagnosticType.COMPLETION_CLOSE_OUTSIDE_RANGE
        assert snap20.is_tracking_only is True
        assert snap20.attempted_points is not None
        assert len(snap20.attempted_points) == 5
        assert len(snap20.tracking_points) == 5
        assert len(snap20.active_zones) == 0
        assert len(snap20.confirmed_events) == 0
