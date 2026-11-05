"""Unit and Integration Tests for CHOCH Strategy Engine and MSM Coordinator.

Scope & Design Boundary:
-------------------------
Verifies Change of Character detection, zone calculation, prerequisite binding,
sequential/batch parity, and MSM coordination under strict offline requirements.
Zero MT5 dependencies, zero UI/Plotly/Dash dependencies, zero order execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from aladeen.strategy import (
    ChochCandidate,
    ChochDetector,
    ChochDiagnosticType,
    ChochType,
    ChochZone,
    ChochZoneType,
    ConfirmedChoch,
    Direction,
    MSMChochCoordinator,
    MSMConfig,
    StrategyCandle,
    SwingPoint,
)


@pytest.fixture
def choch_fixtures():
    path = Path(__file__).parent / "fixtures" / "choch_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


class TestCHOCHExecution:

    def test_choch_bearish_basic_end_to_end_execution(self, choch_fixtures):
        """Bearish CHOCH confirms at candle 9; SBR, QML, and Double Top zones match requirements."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        coordinator = MSMChochCoordinator(config)
        snapshot = coordinator.process_candles(fix["candles"])

        assert len(coordinator.confirmed_choch_events) == 1
        event = coordinator.confirmed_choch_events[0]

        assert event.choch_type == ChochType.BEARISH_CHOCH
        assert event.broken_level_type == "LAST_SUPPORT"
        assert event.broken_level_price == 1.105
        assert event.broken_level_source_index == 4
        assert event.c1_candle_index == 8
        assert event.c2_candle_index == 9
        assert event.c1_chronological_pos == 8
        assert event.c2_chronological_pos == 9
        assert event.point_3_source_index == 5
        assert event.new_direction == Direction.DOWNWARD
        assert event.first_eligible_pullback_pos == 10

        assert len(event.zones) == 3
        sbr = next(z for z in event.zones if z.zone_type == ChochZoneType.SBR)
        qml = next(z for z in event.zones if z.zone_type == ChochZoneType.QML_A_PLUS)
        dt = next(z for z in event.zones if z.zone_type == ChochZoneType.DOUBLE_TOP)

        assert sbr.source_candle_index == 4
        assert sbr.lower_price == 1.104
        assert sbr.upper_price == 1.105

        assert qml.source_candle_index == 1
        assert qml.lower_price == 1.135
        assert qml.upper_price == 1.140

        assert dt.source_candle_index == 5
        assert dt.lower_price == 1.155
        assert dt.upper_price == 1.160

    def test_choch_bullish_basic_end_to_end_execution(self, choch_fixtures):
        """Bullish CHOCH rejects Candle 8 equality touch and confirms at Candle 10."""
        fix = choch_fixtures["choch_bullish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.DOWNWARD,
        )
        coordinator = MSMChochCoordinator(config)
        snapshot = coordinator.process_candles(fix["candles"])

        assert len(coordinator.confirmed_choch_events) == 1
        event = coordinator.confirmed_choch_events[0]

        assert event.choch_type == ChochType.BULLISH_CHOCH
        assert event.broken_level_type == "LAST_RESISTANCE"
        assert event.broken_level_price == 1.245
        assert event.broken_level_source_index == 1
        assert event.c1_candle_index == 9
        assert event.c2_candle_index == 10
        assert event.c1_chronological_pos == 9
        assert event.c2_chronological_pos == 10
        assert event.point_3_source_index == 5
        assert event.new_direction == Direction.UPWARD
        assert event.first_eligible_pullback_pos == 11

        assert len(event.zones) == 3
        rbs = next(z for z in event.zones if z.zone_type == ChochZoneType.RBS)
        qml = next(z for z in event.zones if z.zone_type == ChochZoneType.QML_A_PLUS)
        db = next(z for z in event.zones if z.zone_type == ChochZoneType.DOUBLE_BOTTOM)

        assert rbs.source_candle_index == 1
        assert rbs.lower_price == 1.245
        assert rbs.upper_price == 1.248

        assert qml.source_candle_index == 1
        assert qml.lower_price == 1.210
        assert qml.upper_price == 1.215

        assert db.source_candle_index == 5
        assert db.lower_price == 1.180
        assert db.upper_price == 1.185

    def test_rejection_single_close(self, choch_fixtures):
        """A single qualifying close beyond level does not confirm CHOCH."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        snap = detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, {8: c8}, identified_bar_pos=7)

        assert snap.candidate is not None
        assert snap.candidate.close_count == 1
        assert snap.confirmed_choch is None

    def test_rejection_exact_equality_touch(self, choch_fixtures):
        """A close exactly equal to support/resistance level fails closed."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.100, 1.105, False, "CONFIRMED_COMPLETED")
        snap = detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, {8: c8}, identified_bar_pos=7)

        assert snap.candidate is None
        assert snap.confirmed_choch is None
        assert any(d.diagnostic_type == ChochDiagnosticType.EQUALITY_REJECTED for d in snap.diagnostics)

    def test_nonconsecutive_closes_rejected(self):
        """Non-adjacent qualifying closes cannot be combined across an intervening candle."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.095, 1.115, 1.092, 1.108, False, "CONFIRMED_COMPLETED")
        c10 = StrategyCandle(10, datetime(2026, 10, 2, 16, tzinfo=timezone.utc), 1.108, 1.110, 1.085, 1.090, False, "CONFIRMED_COMPLETED")
        lookup = {8: c8, 9: c9, 10: c10}

        # c8: qualifies as c1
        detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, lookup, identified_bar_pos=7)
        assert detector.candidate is not None
        assert detector.candidate.c1_candle_index == 8

        # c9: fails (close = 1.108 > 1.105) -> resets candidate
        detector.process_candle(c9, 9, Direction.UPWARD, support, None, p3, lookup, identified_bar_pos=7)
        assert detector.candidate is None

        # c10: qualifies as NEW c1 (not combined with c8)
        detector.process_candle(c10, 10, Direction.UPWARD, support, None, p3, lookup, identified_bar_pos=7)
        assert detector.confirmed_choch is None
        assert detector.candidate is not None
        assert detector.candidate.c1_candle_index == 10

    def test_wick_crossing_only_rejected(self):
        """Wick pierces level, but close remains above -> rejected."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.115, 1.080, 1.106, False, "CONFIRMED_COMPLETED")
        snap = detector.process_candle(c, 8, Direction.UPWARD, support, None, p3, {8: c}, identified_bar_pos=7)
        assert snap.candidate is None
        assert any(d.diagnostic_type == ChochDiagnosticType.WICK_CROSSING_ONLY_REJECTED for d in snap.diagnostics)

    def test_color_independence_mixed_colors_confirmed(self):
        """Green c1 and red c2 both strictly below support confirm Bearish CHOCH."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)
        c_high = SwingPoint(price=1.135, candle_index=1, candle_open_time=datetime(2026, 10, 1, 4, tzinfo=timezone.utc), identified_bar_index=3)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.090, 1.100, 1.085, 1.098, False, "CONFIRMED_COMPLETED")
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.100, 1.102, 1.080, 1.085, False, "CONFIRMED_COMPLETED")

        c_p3 = StrategyCandle(5, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), 1.145, 1.160, 1.142, 1.155, False, "CONFIRMED_COMPLETED")
        c_sup = StrategyCandle(3, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), 1.120, 1.122, 1.100, 1.105, False, "CONFIRMED_COMPLETED")
        c_h = StrategyCandle(1, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), 1.105, 1.140, 1.102, 1.135, False, "CONFIRMED_COMPLETED")
        lookup = {1: c_h, 3: c_sup, 5: c_p3, 8: c8, 9: c9}

        detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, lookup, c_high, identified_bar_pos=7)
        detector.process_candle(c9, 9, Direction.UPWARD, support, None, p3, lookup, c_high, identified_bar_pos=7)

        assert detector.confirmed_choch is not None
        assert detector.confirmed_choch.choch_type == ChochType.BEARISH_CHOCH

    def test_missing_point_3_fails_closed(self):
        """Two closes below support when active Point 3 is absent fails closed."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)

        c4 = StrategyCandle(4, datetime(2026, 10, 1, 16, tzinfo=timezone.utc), 1.100, 1.102, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        c5 = StrategyCandle(5, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), 1.095, 1.098, 1.080, 1.085, False, "CONFIRMED_COMPLETED")

        detector.process_candle(c4, 4, Direction.UPWARD, support, None, None, {4: c4, 5: c5})
        detector.process_candle(c5, 5, Direction.UPWARD, support, None, None, {4: c4, 5: c5})

        assert detector.candidate is None
        assert detector.confirmed_choch is None
        assert any(d.diagnostic_type == ChochDiagnosticType.ACTIVE_POINT_3_ABSENT for d in detector.diagnostics)

    def test_continuation_reset_clears_pending_choch(self):
        """Continuation break above tentative high confirms cycle and resets pending CHOCH count."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, {8: c8}, identified_bar_pos=7)
        assert detector.candidate is not None

        # Price breaks continuation; MSM cycle completes, tentative_point becomes None
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.150, 1.170, 1.148, 1.165, False, "CONFIRMED_COMPLETED")
        detector.process_candle(c9, 9, Direction.UPWARD, support, None, None, {8: c8, 9: c9}, identified_bar_pos=7)

        assert detector.candidate is None
        assert any(d.diagnostic_type == ChochDiagnosticType.PREREQUISITE_CHANGED for d in detector.diagnostics)

    def test_zero_width_zones_preserved_as_price_lines(self, choch_fixtures):
        """Zero-wick swing candles produce thickness-0 zones with is_line=True."""
        fix = choch_fixtures["choch_zero_width_zones_preserved_as_price_lines"]
        orig = fix["original_candles"]

        c_high = StrategyCandle(1, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), orig["confirmed_high"]["open"], orig["confirmed_high"]["high"], orig["confirmed_high"]["low"], orig["confirmed_high"]["close"], False, "CONFIRMED_COMPLETED")
        c_low = StrategyCandle(3, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), orig["confirmed_low"]["open"], orig["confirmed_low"]["high"], orig["confirmed_low"]["low"], orig["confirmed_low"]["close"], False, "CONFIRMED_COMPLETED")
        c_p3 = StrategyCandle(5, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), orig["point_3"]["open"], orig["point_3"]["high"], orig["point_3"]["low"], orig["point_3"]["close"], False, "CONFIRMED_COMPLETED")

        qml = ChochZone.from_candle(ChochZoneType.QML_A_PLUS, c_high, is_high_side=True)
        assert qml.is_line is True
        assert qml.lower_price == qml.upper_price == 1.135

        sbr = ChochZone.from_candle(ChochZoneType.SBR, c_low, is_high_side=False)
        assert sbr.is_line is True
        assert sbr.lower_price == sbr.upper_price == 1.105

        dt = ChochZone.from_candle(ChochZoneType.DOUBLE_TOP, c_p3, is_high_side=True)
        assert dt.is_line is False
        assert dt.lower_price == 1.155
        assert dt.upper_price == 1.160

    def test_unresolved_same_close_diagnostic_and_downstream_non_publication(self, choch_fixtures):
        """When Point 3 is identified at the same close that breaches support (c1 == p2), emits UNRESOLVED diagnostic and publishes NO CHOCH."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c7 = StrategyCandle(7, datetime(2026, 10, 2, 4, tzinfo=timezone.utc), 1.095, 1.100, 1.085, 1.090, False, "CONFIRMED_COMPLETED")
        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.090, 1.098, 1.088, 1.092, False, "CONFIRMED_COMPLETED")
        lookup = {7: c7, 8: c8}

        snap7 = detector.process_candle(c7, 7, Direction.UPWARD, support, None, p3, lookup, identified_bar_pos=7)
        assert snap7.is_unresolved is True
        assert any(d.diagnostic_type == ChochDiagnosticType.UNRESOLVED_SAME_CLOSE for d in snap7.diagnostics)
        assert snap7.candidate is None
        assert snap7.confirmed_choch is None

        # Next candle 8 also closes below support, but path is blocked by unresolved status
        snap8 = detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, lookup, identified_bar_pos=7)
        assert snap8.confirmed_choch is None
        assert snap8.is_unresolved is True

    def test_arbitrary_noncontiguous_source_ids(self):
        """Adjacency is strictly governed by chronological positions, not numeric source IDs."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=300, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=300)
        p3 = SwingPoint(price=1.155, candle_index=500, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=700)
        c_high = SwingPoint(price=1.135, candle_index=100, candle_open_time=datetime(2026, 10, 1, 4, tzinfo=timezone.utc), identified_bar_index=300)

        c850 = StrategyCandle(850, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        c950 = StrategyCandle(950, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.095, 1.098, 1.080, 1.085, False, "CONFIRMED_COMPLETED")

        lookup = {
            100: StrategyCandle(100, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), 1.105, 1.140, 1.102, 1.135, False, "CONFIRMED_COMPLETED"),
            300: StrategyCandle(300, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), 1.120, 1.122, 1.100, 1.105, False, "CONFIRMED_COMPLETED"),
            500: StrategyCandle(500, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), 1.145, 1.160, 1.142, 1.155, False, "CONFIRMED_COMPLETED"),
            850: c850,
            950: c950,
        }
        candle_positions = {100: 1, 300: 3, 500: 5, 700: 7, 850: 8, 950: 9}

        detector.process_candle(c850, 8, Direction.UPWARD, support, None, p3, lookup, c_high, candle_positions=candle_positions)
        detector.process_candle(c950, 9, Direction.UPWARD, support, None, p3, lookup, c_high, candle_positions=candle_positions)

        assert detector.confirmed_choch is not None
        assert detector.confirmed_choch.c1_candle_index == 850
        assert detector.confirmed_choch.c2_candle_index == 950
        assert detector.confirmed_choch.c1_chronological_pos == 8
        assert detector.confirmed_choch.c2_chronological_pos == 9

    def test_batch_vs_sequential_parity(self, choch_fixtures):
        """Batch execution produces identical output to sequential step-by-step ingestion."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )

        coord_batch = MSMChochCoordinator(config)
        snap_batch = coord_batch.process_candles(fix["candles"])

        coord_seq = MSMChochCoordinator(config)
        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"])
        for c in candles:
            coord_seq.process_candle(c)
        snap_seq = coord_seq.get_snapshot()

        assert snap_batch == snap_seq

    def test_extended_sequence_genuine_new_direction_msm_pair(self, choch_fixtures):
        """Verifies that after CHOCH confirms at candle 9, the restarted MSM engine completes a genuine new-direction pair."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        coordinator = MSMChochCoordinator(config)
        coordinator.process_candles(fix["candles"])

        assert len(coordinator.confirmed_choch_events) == 1
        assert coordinator.direction == Direction.DOWNWARD

        new_candles = [
            StrategyCandle(10, datetime(2026, 10, 2, 16, tzinfo=timezone.utc), 1.085, 1.088, 1.070, 1.075, False, "CONFIRMED_COMPLETED"),
            StrategyCandle(11, datetime(2026, 10, 2, 20, tzinfo=timezone.utc), 1.075, 1.090, 1.072, 1.085, False, "CONFIRMED_COMPLETED"),
            StrategyCandle(12, datetime(2026, 10, 3, 0, tzinfo=timezone.utc), 1.085, 1.095, 1.082, 1.092, False, "CONFIRMED_COMPLETED"),
            StrategyCandle(13, datetime(2026, 10, 3, 4, tzinfo=timezone.utc), 1.092, 1.094, 1.060, 1.065, False, "CONFIRMED_COMPLETED"),
        ]

        for c in new_candles:
            coordinator.process_candle(c)

        snap = coordinator.get_snapshot()
        pairs = snap.msm_snapshot.confirmed_pairs
        assert len(pairs) == 2
        assert pairs[0].pair_index == 1
        assert pairs[1].pair_index == 2

        downward_pair = pairs[1]
        assert downward_pair.confirmation_bar_index == 13
        assert snap.msm_snapshot.last_resistance is not None

    # =========================================================================
    # Regressions for HANDOFF-021 (R20.1 - R20.7)
    # =========================================================================

    def test_two_successive_opposite_direction_choch_events(self, choch_fixtures):
        """R20.1: Tests two successive opposite-direction CHOCH events (Bearish then Bullish) and intervening candles."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        coordinator = MSMChochCoordinator(config)
        coordinator.process_candles(fix["candles"])

        # 1. Bearish CHOCH confirmed on Candle 9
        assert len(coordinator.confirmed_choch_events) == 1
        assert coordinator.confirmed_choch_events[0].choch_type == ChochType.BEARISH_CHOCH
        assert coordinator.direction == Direction.DOWNWARD

        # Intervening candles in new DOWNWARD cycle:
        # Candle 10: Downward continuation push
        # Candle 11: Pullback start (green candle)
        # Candle 12: Pullback continuation -> identifies tentative low (Point 3) at Candle 11!
        # Candle 13: Continuation break below tentative low -> confirms first DOWNWARD pair!
        # Candle 14: Downward continuation push -> establishes Point 3 trough at Candle 14
        # Candle 15: Pullback candle
        # Candle 16: Second pullback candle -> identifies Point 3 trough
        # Candle 17: c1 close above last resistance!
        # Candle 18: c2 close above last resistance! -> Bullish CHOCH!
        extra_candles = [
            StrategyCandle(10, datetime(2026, 10, 2, 16, tzinfo=timezone.utc), 1.085, 1.088, 1.070, 1.075, False, "CONFIRMED_COMPLETED"),
            StrategyCandle(11, datetime(2026, 10, 2, 20, tzinfo=timezone.utc), 1.075, 1.090, 1.072, 1.085, False, "CONFIRMED_COMPLETED"),
            StrategyCandle(12, datetime(2026, 10, 3, 0, tzinfo=timezone.utc), 1.085, 1.095, 1.082, 1.092, False, "CONFIRMED_COMPLETED"),
            StrategyCandle(13, datetime(2026, 10, 3, 4, tzinfo=timezone.utc), 1.092, 1.094, 1.060, 1.065, False, "CONFIRMED_COMPLETED"),  # Confirms downward pair! Resistance established at UB=1.092
            StrategyCandle(14, datetime(2026, 10, 3, 8, tzinfo=timezone.utc), 1.065, 1.068, 1.040, 1.045, False, "CONFIRMED_COMPLETED"),  # Potential Point 3 trough: low=1.040, LB=1.045
            StrategyCandle(15, datetime(2026, 10, 3, 12, tzinfo=timezone.utc), 1.045, 1.060, 1.044, 1.055, False, "CONFIRMED_COMPLETED"), # Upward pullback 1
            StrategyCandle(16, datetime(2026, 10, 3, 16, tzinfo=timezone.utc), 1.055, 1.070, 1.052, 1.068, False, "CONFIRMED_COMPLETED"), # Upward pullback 2 -> Identifies Point 3 at candle 14!
            StrategyCandle(17, datetime(2026, 10, 3, 20, tzinfo=timezone.utc), 1.068, 1.100, 1.066, 1.095, False, "CONFIRMED_COMPLETED"), # c1 close > Resistance (1.095 > 1.092)
            StrategyCandle(18, datetime(2026, 10, 4, 0, tzinfo=timezone.utc), 1.095, 1.105, 1.092, 1.102, False, "CONFIRMED_COMPLETED"),  # c2 close > Resistance (1.102 > 1.092) -> Bullish CHOCH!
        ]

        for c in extra_candles:
            coordinator.process_candle(c)

        # 2. Bullish CHOCH confirmed on Candle 18
        events = coordinator.confirmed_choch_events
        assert len(events) == 2, f"Expected 2 confirmed CHOCH events, got {len(events)}"
        assert events[0].choch_type == ChochType.BEARISH_CHOCH
        assert events[1].choch_type == ChochType.BULLISH_CHOCH
        assert coordinator.direction == Direction.UPWARD

    def test_old_event_not_re_emitted_after_restart(self, choch_fixtures):
        """R20.1: Tests that a confirmed CHOCH event is NOT exposed or re-emitted on subsequent candles after restart."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        coordinator = MSMChochCoordinator(config)
        coordinator.process_candles(fix["candles"])

        # CHOCH confirmed at candle 9
        assert len(coordinator.confirmed_choch_events) == 1

        # Detector internal confirmed_choch must be None following coordinator restart
        detector = coordinator._choch_detector
        assert detector.confirmed_choch is None

        # Next candle 10 is processed in new DOWNWARD cycle
        c10 = StrategyCandle(10, datetime(2026, 10, 2, 16, tzinfo=timezone.utc), 1.085, 1.088, 1.070, 1.075, False, "CONFIRMED_COMPLETED")
        snap = coordinator.process_candle(c10)

        # Snapshot for candle 10 must NOT return old confirmed event
        assert snap.choch_snapshot.confirmed_choch is None
        assert len(coordinator.confirmed_choch_events) == 1

    def test_decreasing_noncontiguous_source_ids_with_unknown_availability_times(self):
        """R20.2: Decreasing unique source IDs with unknown availability times are ordered strictly by chronological position."""
        detector = ChochDetector(Direction.UPWARD)
        # Unique source IDs that DECREASE: 900 -> 800 -> 700 -> 600
        support = SwingPoint(price=1.105, candle_index=900, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=900)
        p3 = SwingPoint(price=1.155, candle_index=800, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=700) # identified at bar 700
        c_high = SwingPoint(price=1.135, candle_index=950, candle_open_time=datetime(2026, 10, 1, 4, tzinfo=timezone.utc), identified_bar_index=900)

        c600 = StrategyCandle(600, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        c500 = StrategyCandle(500, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.095, 1.098, 1.080, 1.085, False, "CONFIRMED_COMPLETED")

        lookup = {
            950: StrategyCandle(950, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), 1.105, 1.140, 1.102, 1.135, False, "CONFIRMED_COMPLETED"),
            900: StrategyCandle(900, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), 1.120, 1.122, 1.100, 1.105, False, "CONFIRMED_COMPLETED"),
            800: StrategyCandle(800, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), 1.145, 1.160, 1.142, 1.155, False, "CONFIRMED_COMPLETED"),
            600: c600,
            500: c500,
        }
        # Point 3 identified at chronological position 7 (source ID 700)
        # Candle 600 is pos 8 (> 7)
        # Candle 500 is pos 9 (== 8 + 1)
        candle_positions = {950: 1, 900: 3, 800: 5, 700: 7, 600: 8, 500: 9}

        detector.process_candle(c600, 8, Direction.UPWARD, support, None, p3, lookup, c_high, candle_positions=candle_positions)
        detector.process_candle(c500, 9, Direction.UPWARD, support, None, p3, lookup, c_high, candle_positions=candle_positions)

        # Must confirm CHOCH despite source IDs decreasing (600 -> 500 < 700)
        assert detector.confirmed_choch is not None
        assert detector.confirmed_choch.c1_candle_index == 600
        assert detector.confirmed_choch.c2_candle_index == 500
        assert detector.confirmed_choch.c1_chronological_pos == 8
        assert detector.confirmed_choch.c2_chronological_pos == 9

    def test_unknown_point_3_identification_time_stays_none(self):
        """R20.2: Unknown Point 3 identification time remains None, not fabricated from candle_open_time."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        # identified_time is explicitly None
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7, identified_time=None)
        c_high = SwingPoint(price=1.135, candle_index=1, candle_open_time=datetime(2026, 10, 1, 4, tzinfo=timezone.utc), identified_bar_index=3)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.095, 1.098, 1.080, 1.085, False, "CONFIRMED_COMPLETED")

        lookup = {
            1: StrategyCandle(1, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), 1.105, 1.140, 1.102, 1.135, False, "CONFIRMED_COMPLETED"),
            3: StrategyCandle(3, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), 1.120, 1.122, 1.100, 1.105, False, "CONFIRMED_COMPLETED"),
            5: StrategyCandle(5, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), 1.145, 1.160, 1.142, 1.155, False, "CONFIRMED_COMPLETED"),
            8: c8,
            9: c9,
        }

        detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, lookup, c_high, identified_bar_pos=7)
        assert detector.candidate is not None
        assert detector.candidate.point_3_identified_at is None

        detector.process_candle(c9, 9, Direction.UPWARD, support, None, p3, lookup, c_high, identified_bar_pos=7)
        assert detector.confirmed_choch is not None
        assert detector.confirmed_choch.point_3_identified_at is None

    def test_broken_level_or_point_3_identity_changing_mid_candidate(self):
        """R20.3: Candidate is immediately invalidated if prerequisite level or Point 3 changes before c2."""
        detector = ChochDetector(Direction.UPWARD)
        support1 = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3_1 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        detector.process_candle(c8, 8, Direction.UPWARD, support1, None, p3_1, {8: c8}, identified_bar_pos=7)
        assert detector.candidate is not None

        # Level changes to a new support level before c2
        support2 = SwingPoint(price=1.090, candle_index=6, candle_open_time=datetime(2026, 10, 2, 0, tzinfo=timezone.utc), identified_bar_index=6)
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.095, 1.098, 1.080, 1.085, False, "CONFIRMED_COMPLETED")

        # Even though close 1.085 < 1.090, the old candidate bound to support1 was invalidated
        detector.process_candle(c9, 9, Direction.UPWARD, support2, None, p3_1, {8: c8, 9: c9}, identified_bar_pos=7)
        assert any(d.diagnostic_type == ChochDiagnosticType.PREREQUISITE_CHANGED for d in detector.diagnostics)
        assert detector.confirmed_choch is None

    def test_direct_detector_forming_unconfirmed_input(self):
        """R20.4: Direct detector calls reject forming/unconfirmed candles without mutating state."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        forming_candle = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.080, 1.085, True, "FORMING")
        snap = detector.process_candle(forming_candle, 8, Direction.UPWARD, support, None, p3, {}, identified_bar_pos=7)

        assert snap.candidate is None
        assert snap.confirmed_choch is None
        assert snap.last_processed_pos == -1
        assert any(d.diagnostic_type == ChochDiagnosticType.FORMING_CANDLE_REJECTED for d in snap.diagnostics)

    def test_duplicate_and_out_of_order_detector_and_coordinator_input(self):
        """R20.4 & R20.5: Duplicate or non-chronological candles are rejected with ValueError."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c1 = StrategyCandle(1, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), 1.100, 1.110, 1.095, 1.105, False, "CONFIRMED_COMPLETED")
        c2 = StrategyCandle(2, datetime(2026, 10, 1, 8, tzinfo=timezone.utc), 1.105, 1.115, 1.100, 1.110, False, "CONFIRMED_COMPLETED")
        detector.process_candle(c1, 1, Direction.UPWARD, support, None, p3, {1: c1}, identified_bar_pos=7)
        detector.process_candle(c2, 2, Direction.UPWARD, support, None, p3, {1: c1, 2: c2}, identified_bar_pos=7)

        # Out-of-order chronological position in detector
        with pytest.raises(ValueError, match="Out of order or duplicate chronological position"):
            detector.process_candle(c1, 1, Direction.UPWARD, support, None, p3, {1: c1, 2: c2}, identified_bar_pos=7)

        # Duplicate candle in coordinator
        config = MSMConfig(start_candle_time=datetime(2026, 10, 1, 4, tzinfo=timezone.utc), direction=Direction.UPWARD)
        coord = MSMChochCoordinator(config)
        coord.process_candle(c1)
        with pytest.raises(ValueError, match="Duplicate candle source index detected"):
            coord.process_candle(c1)

    def test_rejected_batch_sequential_input_preserves_previous_state(self, choch_fixtures):
        """R20.5: If input validation fails, coordinator preserves its previous state and does not reset."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        coordinator = MSMChochCoordinator(config)
        coordinator.process_candles(fix["candles"])

        # Prior state has 1 confirmed CHOCH event
        assert len(coordinator.confirmed_choch_events) == 1

        # Attempt to run process_candles with invalid data (missing start candle)
        bad_data = [
            {"index": 99, "open_time": "2026-12-01T00:00:00+00:00", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"}
        ]
        with pytest.raises(ValueError, match="Invalid starting candle"):
            coordinator.process_candles(bad_data)

        # State is preserved!
        assert len(coordinator.confirmed_choch_events) == 1
        assert coordinator.direction == Direction.DOWNWARD

    def test_missing_start_with_only_earlier_candles(self):
        """R20.5: When all candles precede requested start, fails closed with ValueError and preserves state."""
        config = MSMConfig(start_candle_time=datetime(2026, 10, 2, 0, tzinfo=timezone.utc), direction=Direction.UPWARD)
        coord = MSMChochCoordinator(config)

        # All candles strictly before start_candle_time
        earlier_candles = [
            StrategyCandle(1, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), 1.1, 1.2, 1.0, 1.15, False, "CONFIRMED_COMPLETED"),
            StrategyCandle(2, datetime(2026, 10, 1, 8, tzinfo=timezone.utc), 1.15, 1.25, 1.1, 1.2, False, "CONFIRMED_COMPLETED"),
        ]

        with pytest.raises(ValueError, match="Invalid starting candle"):
            coord.process_candles(earlier_candles)

    def test_missing_restart_reference_raises_error(self, choch_fixtures, monkeypatch):
        """R20.5 & R21: Missing restart reference candle in completed candles history raises ValueError and leaves state 100% unchanged."""
        from aladeen.strategy.choch_types import ChochSnapshot
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        coordinator = MSMChochCoordinator(config)

        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"])
        for c in candles[:8]:
            coordinator.process_candle(c)

        snap_before = coordinator.get_snapshot()

        # Manually construct an event referencing a nonexistent point_3_source_index
        bad_event = ConfirmedChoch(
            choch_type=ChochType.BEARISH_CHOCH,
            broken_level_type="LAST_SUPPORT",
            broken_level_price=1.105,
            broken_level_source_index=4,
            c1_candle_index=8,
            c2_candle_index=9,
            c1_chronological_pos=8,
            c2_chronological_pos=9,
            c1_open_time=datetime(2026, 10, 2, 8, tzinfo=timezone.utc),
            c2_open_time=datetime(2026, 10, 2, 12, tzinfo=timezone.utc),
            confirmation_time=None,
            point_3_source_index=9999,  # Missing!
            point_3_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc),
            point_3_identified_bar_index=7,
            point_3_identified_at=None,
            zones=(
                ChochZone.from_candle(ChochZoneType.SBR, candles[4], is_high_side=False),
                ChochZone.from_candle(ChochZoneType.QML_A_PLUS, candles[1], is_high_side=True),
                ChochZone.from_candle(ChochZoneType.DOUBLE_TOP, candles[5], is_high_side=True),
            ),
            new_direction=Direction.DOWNWARD,
            restart_reference_candle_index=9999,
            restart_reference_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc),
            first_eligible_pullback_pos=10,
        )

        monkeypatch.setattr(
            coordinator._choch_detector,
            "process_candle",
            lambda *args, **kwargs: ChochSnapshot(
                active_direction=Direction.UPWARD,
                last_processed_pos=9,
                last_processed_index=candles[9].index,
                candidate=None,
                confirmed_choch=bad_event,
            ),
        )

        with pytest.raises(ValueError, match="Missing restart reference candle"):
            coordinator.process_candle(candles[9])

        snap_after = coordinator.get_snapshot()
        assert snap_after == snap_before
        assert len(coordinator.confirmed_choch_events) == 0
        assert coordinator.last_processed_index == candles[7].index

    def test_unresolved_path_never_publishes_dependent_confirmation_or_restart(self, choch_fixtures):
        """R20.6: An unresolved same-close path never publishes dependent confirmation or restart."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c7 = StrategyCandle(7, datetime(2026, 10, 2, 4, tzinfo=timezone.utc), 1.095, 1.100, 1.085, 1.090, False, "CONFIRMED_COMPLETED")
        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.090, 1.098, 1.080, 1.085, False, "CONFIRMED_COMPLETED")
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.085, 1.088, 1.070, 1.075, False, "CONFIRMED_COMPLETED")

        lookup = {7: c7, 8: c8, 9: c9}
        snap7 = detector.process_candle(c7, 7, Direction.UPWARD, support, None, p3, lookup, identified_bar_pos=7)
        assert snap7.is_unresolved is True

        snap8 = detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, lookup, identified_bar_pos=7)
        assert snap8.is_unresolved is True
        assert snap8.confirmed_choch is None
        assert any(d.diagnostic_type == ChochDiagnosticType.BLOCKED_BY_UNRESOLVED_STATE for d in snap8.diagnostics)

        snap9 = detector.process_candle(c9, 9, Direction.UPWARD, support, None, p3, lookup, identified_bar_pos=7)
        assert snap9.is_unresolved is True
        assert snap9.confirmed_choch is None

    def test_missing_qml_source_withholds_whole_event(self):
        """R20.7: If confirmed_high/confirmed_low is missing, confirmation is withheld (no partial 2-zone event)."""
        detector = ChochDetector(Direction.UPWARD)
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.095, 1.098, 1.080, 1.085, False, "CONFIRMED_COMPLETED")

        c_sup = StrategyCandle(3, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), 1.120, 1.122, 1.100, 1.105, False, "CONFIRMED_COMPLETED")
        c_p3 = StrategyCandle(5, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), 1.145, 1.160, 1.142, 1.155, False, "CONFIRMED_COMPLETED")
        lookup = {3: c_sup, 5: c_p3, 8: c8, 9: c9}

        # c_high is NOT provided (None)
        detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, lookup, confirmed_high=None, identified_bar_pos=7)
        detector.process_candle(c9, 9, Direction.UPWARD, support, None, p3, lookup, confirmed_high=None, identified_bar_pos=7)

        assert detector.confirmed_choch is None
        assert any(d.diagnostic_type == ChochDiagnosticType.REQUIRED_ZONE_PROVENANCE_MISSING for d in detector.diagnostics)

    def test_batch_sequential_replay_prefix_consistency(self, choch_fixtures):
        """R20.5: Verifies that batch execution, sequential ingestion, and replay_candles yield identical state at every step."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )

        coordinator = MSMChochCoordinator(config)
        replay_snapshots = coordinator.replay_candles(fix["candles"])

        coord_seq = MSMChochCoordinator(config)
        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"])

        for i, c in enumerate(candles):
            seq_snap = coord_seq.process_candle(c)
            replay_snap = replay_snapshots[i]
            assert seq_snap == replay_snap

        coord_batch = MSMChochCoordinator(config)
        final_batch_snap = coord_batch.process_candles(fix["candles"])
        assert final_batch_snap == replay_snapshots[-1]

    def test_unresolved_containment_freezes_authoritative_state_across_later_candles(self, choch_fixtures):
        """R21.1: Ambiguous same-close freeze: authoritative state and history remain fixed; subsequent continuation and break candles do not advance state."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        coordinator = MSMChochCoordinator(config)
        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"])

        # Ingest candles up to candle 6 (prior to ambiguous candle 7)
        for c in candles[:7]:
            coordinator.process_candle(c)

        snap_pre_ambiguity = coordinator.get_snapshot()
        assert snap_pre_ambiguity.is_unresolved is False
        assert snap_pre_ambiguity.last_processed_index == candles[6].index

        # Modify candle 7 so that close is 1.090 < support (1.105), simultaneously identifying P3 and closing below support
        orig_c7 = candles[7]
        ambig_c7 = StrategyCandle(
            index=orig_c7.index,
            open_time=orig_c7.open_time,
            open=1.130,
            high=1.132,
            low=1.085,
            close=1.090,  # Below support 1.105!
            is_forming=False,
            bar_status="CONFIRMED_COMPLETED",
            close_time=orig_c7.close_time,
        )

        # Candle 7 triggers ambiguous same-close (c1 == p2)
        snap7 = coordinator.process_candle(ambig_c7)
        assert snap7.is_unresolved is True
        assert snap7.unresolved_candle_index == ambig_c7.index
        assert snap7.unresolved_diagnostic is not None
        assert snap7.unresolved_diagnostic.diagnostic_type == ChochDiagnosticType.UNRESOLVED_SAME_CLOSE
        # Authoritative MSM and CHOCH state remain frozen at pre-ambiguity state
        assert snap7.msm_snapshot == snap_pre_ambiguity.msm_snapshot
        assert snap7.last_processed_index == candles[6].index
        assert snap7.last_received_index == ambig_c7.index

        # Now feed subsequent candles (would-be MSM continuation, then would-be CHOCH breaks)
        subsequent_candles = [
            # Candle 8 closes strictly below support
            candles[8],
            # Additional continuation candles that would form new swing points under assumed continuation
            StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.085, 1.150, 1.080, 1.145, False, "CONFIRMED_COMPLETED"),
            StrategyCandle(10, datetime(2026, 10, 2, 16, tzinfo=timezone.utc), 1.145, 1.180, 1.140, 1.175, False, "CONFIRMED_COMPLETED"),
        ]

        for c in subsequent_candles:
            snap = coordinator.process_candle(c)
            # Authoritative integrated structure remains 100% fixed at pre-ambiguity state!
            assert snap.is_unresolved is True
            assert snap.msm_snapshot == snap_pre_ambiguity.msm_snapshot
            assert snap.confirmed_choch_events == ()
            assert snap.last_processed_index == candles[6].index
            assert snap.last_received_index == c.index
            assert snap.unresolved_candle_index == ambig_c7.index

    def test_independent_runs_process_normally_while_another_is_unresolved(self, choch_fixtures):
        """R21.2: One coordinator encountering ambiguity does not affect independent coordinator runs."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(start_candle_time=datetime.fromisoformat(fix["start_candle_time"]), direction=Direction.UPWARD)

        coord_a = MSMChochCoordinator(config)
        coord_b = MSMChochCoordinator(config)

        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"])

        # Feed coordinator A with ambiguous candle 7
        for c in candles[:7]:
            coord_a.process_candle(c)
        orig_c7 = candles[7]
        ambig_c7 = StrategyCandle(orig_c7.index, orig_c7.open_time, 1.130, 1.132, 1.085, 1.090, False, "CONFIRMED_COMPLETED", orig_c7.close_time)
        coord_a.process_candle(ambig_c7)
        assert coord_a.is_unresolved is True
        assert len(coord_a.confirmed_choch_events) == 0

        # Coordinator B processes clean settled data and confirms CHOCH normally
        coord_b.process_candles(fix["candles"])
        assert coord_b.is_unresolved is False
        assert len(coord_b.confirmed_choch_events) == 1
        assert coord_b.direction == Direction.DOWNWARD

    def test_detector_or_restart_exception_leaves_both_child_engines_unchanged(self, choch_fixtures, monkeypatch):
        """R21.4: An unexpected detector exception during transition leaves both child engines and coordinator state 100% unmutated."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(start_candle_time=datetime.fromisoformat(fix["start_candle_time"]), direction=Direction.UPWARD)
        coordinator = MSMChochCoordinator(config)

        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"])
        for c in candles[:8]:
            coordinator.process_candle(c)

        msm_before = coordinator._msm_engine.get_snapshot()
        choch_before = coordinator._choch_detector.get_snapshot()
        snap_before = coordinator.get_snapshot()

        # Monkeypatch detector to raise an error during evaluation of candle 9
        def crashing_process_candle(*args, **kwargs):
            raise RuntimeError("Simulated detector crash")

        monkeypatch.setattr(coordinator._choch_detector, "process_candle", crashing_process_candle)

        with pytest.raises(RuntimeError, match="Simulated detector crash"):
            coordinator.process_candle(candles[8])

        # State is 100% intact!
        assert coordinator._msm_engine.get_snapshot() == msm_before
        assert coordinator._choch_detector.get_snapshot() == choch_before
        assert coordinator.get_snapshot() == snap_before

    def test_valid_input_processed_successfully_after_rejected_transition(self, choch_fixtures):
        """R21.5: Valid input is processed normally and commits cleanly after a rejected transition."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(start_candle_time=datetime.fromisoformat(fix["start_candle_time"]), direction=Direction.UPWARD)
        coordinator = MSMChochCoordinator(config)

        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"])
        for c in candles[:8]:
            coordinator.process_candle(c)

        snap_before = coordinator.get_snapshot()

        # Try to ingest an invalid candle (duplicate index)
        with pytest.raises(ValueError, match="Duplicate candle source index detected"):
            coordinator.process_candle(candles[7])

        assert coordinator.get_snapshot() == snap_before

        # Now ingest the valid next candle (candle 8)
        snap_after = coordinator.process_candle(candles[8])
        assert snap_after.last_processed_index == candles[8].index
        assert snap_after.choch_snapshot.candidate is not None
        assert snap_after.choch_snapshot.candidate.c1_candle_index == candles[8].index

    def test_unresolved_boundary_validates_received_chronology_and_uniqueness(self, choch_fixtures):
        """Offline Qualification: Duplicate or out-of-order received input after unresolved boundary is rejected with ValueError."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(start_candle_time=datetime.fromisoformat(fix["start_candle_time"]), direction=Direction.UPWARD)
        coordinator = MSMChochCoordinator(config)

        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"])

        # Feed up to candle 6
        for c in candles[:7]:
            coordinator.process_candle(c)

        # Candle 7 triggers ambiguous same-close
        orig_c7 = candles[7]
        ambig_c7 = StrategyCandle(orig_c7.index, orig_c7.open_time, 1.130, 1.132, 1.085, 1.090, False, "CONFIRMED_COMPLETED", orig_c7.close_time)
        coordinator.process_candle(ambig_c7)
        assert coordinator.is_unresolved is True
        assert coordinator.last_received_index == ambig_c7.index

        # Attempt to pass duplicate index after unresolved boundary
        dup_candle = StrategyCandle(ambig_c7.index, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.090, 1.095, 1.085, 1.092, False, "CONFIRMED_COMPLETED")
        with pytest.raises(ValueError, match="Duplicate candle source index detected"):
            coordinator.process_candle(dup_candle)

        # Attempt to pass non-chronological timestamp after unresolved boundary
        earlier_candle = StrategyCandle(99, datetime(2026, 10, 2, 2, tzinfo=timezone.utc), 1.090, 1.095, 1.085, 1.092, False, "CONFIRMED_COMPLETED")
        with pytest.raises(ValueError, match="Non-chronological candle open_time"):
            coordinator.process_candle(earlier_candle)

        # Authoritative state and receipt index remain intact
        assert coordinator.is_unresolved is True
        assert coordinator.last_received_index == ambig_c7.index
        assert coordinator.last_processed_index == candles[6].index

    def test_failed_batch_does_not_replace_previously_successful_run(self, choch_fixtures):
        """Offline Qualification: A failed batch run on an isolated temporary coordinator leaves the previously successful run completely intact."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(start_candle_time=datetime.fromisoformat(fix["start_candle_time"]), direction=Direction.UPWARD)
        coordinator = MSMChochCoordinator(config)

        # 1. Run successful batch
        snap_initial = coordinator.process_candles(fix["candles"])
        assert len(coordinator.confirmed_choch_events) == 1
        assert coordinator.direction == Direction.DOWNWARD

        # 2. Prepare a batch where candle 8 is non-chronological
        from aladeen.strategy.validator import adapt_candles
        bad_batch = adapt_candles(fix["candles"])
        # Corrupt candle open_time for mid-batch failure
        bad_candle = StrategyCandle(8, datetime(2026, 10, 1, 0, tzinfo=timezone.utc), 1.0, 1.1, 0.9, 1.05, False, "CONFIRMED_COMPLETED")
        bad_batch_list = [c if i != 8 else bad_candle for i, c in enumerate(bad_batch)]

        with pytest.raises(ValueError):
            coordinator.process_candles(bad_batch_list)

        # Prior successful run is 100% preserved!
        snap_after_failure = coordinator.get_snapshot()
        assert snap_after_failure == snap_initial
        assert len(coordinator.confirmed_choch_events) == 1
        assert coordinator.direction == Direction.DOWNWARD
