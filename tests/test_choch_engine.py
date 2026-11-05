"""Execution tests for Change of Character (CHOCH) Detector and Coordinator.

Scope & Design Boundary:
-------------------------
- Independent of MT5, Dash, Plotly, network, and persistent storage.
- Tests executable transitions, zone constructions, equality outcomes,
  unresolved same-close handling, and post-confirmation restart with
  genuine new-direction MSM cycle completion.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
import pandas as pd

from aladeen.strategy.types import (
    Direction,
    EngineState,
    MSMConfig,
    StrategyCandle,
)
from aladeen.strategy.choch_types import (
    ChochDiagnosticType,
    ChochType,
    ChochZoneType,
)
from aladeen.strategy.choch_detector import ChochDetector
from aladeen.strategy.coordinator import MSMChochCoordinator


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "choch_acceptance.json"


@pytest.fixture(scope="module")
def choch_fixtures() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


class TestCHOCHExecution:
    """Verifies runtime execution of CHOCH detection, zone generation, and MSM restart."""

    def test_bearish_end_to_end_confirmation_and_zones(self, choch_fixtures):
        """Exercises complete Bearish CHOCH confirmation at candle 9 with SBR from candle 4."""
        fix = choch_fixtures["choch_bearish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        coordinator = MSMChochCoordinator(config)
        snap = coordinator.process_candles(fix["candles"])

        assert len(snap.confirmed_choch_events) == 1
        event = snap.confirmed_choch_events[0]
        assert event.choch_type == ChochType.BEARISH_CHOCH
        assert event.c1_candle_index == 8
        assert event.c2_candle_index == 9
        assert event.broken_level_type == "LAST_SUPPORT"
        assert event.broken_level_price == 1.105
        assert event.broken_level_source_index == 4  # Candle 4 verified via tie-breaker
        assert event.new_direction == Direction.DOWNWARD
        assert snap.active_direction == Direction.DOWNWARD

        # Verify zones
        zone_map = {z.zone_type: z for z in event.zones}
        assert ChochZoneType.SBR in zone_map
        assert ChochZoneType.QML_A_PLUS in zone_map
        assert ChochZoneType.DOUBLE_TOP in zone_map

        # SBR from candle 4: [1.104, 1.105]
        sbr = zone_map[ChochZoneType.SBR]
        assert sbr.source_candle_index == 4
        assert sbr.lower_price == 1.104
        assert sbr.upper_price == 1.105
        assert sbr.is_line is False

        # QML / A+ from candle 1: [1.135, 1.140]
        qml = zone_map[ChochZoneType.QML_A_PLUS]
        assert qml.source_candle_index == 1
        assert qml.lower_price == 1.135
        assert qml.upper_price == 1.140

        # Double Top from candle 5: [1.155, 1.160]
        dt = zone_map[ChochZoneType.DOUBLE_TOP]
        assert dt.source_candle_index == 5
        assert dt.lower_price == 1.155
        assert dt.upper_price == 1.160

        # MSM engine restarted in DOWNWARD with search_start at candle 5
        assert snap.msm_snapshot.direction == Direction.DOWNWARD
        assert snap.msm_snapshot.search_start_index == 5
        assert snap.msm_snapshot.next_eligible_pullback_position == 10  # Strictly after c2 (pos 9)

    def test_bullish_end_to_end_equality_at_8_and_confirmation_at_10(self, choch_fixtures):
        """Exercises Bullish CHOCH: candle 8 equality rejected, confirmed at candle 10."""
        fix = choch_fixtures["choch_bullish_basic_end_to_end"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.DOWNWARD,
        )
        coordinator = MSMChochCoordinator(config)
        snap = coordinator.process_candles(fix["candles"])

        assert len(snap.confirmed_choch_events) == 1
        event = snap.confirmed_choch_events[0]
        assert event.choch_type == ChochType.BULLISH_CHOCH
        assert event.broken_level_type == "LAST_RESISTANCE"
        assert event.broken_level_price == 1.245
        assert event.broken_level_source_index == 1  # Candle 1 has max UB 1.245
        assert event.c1_candle_index == 9
        assert event.c2_candle_index == 10
        assert event.new_direction == Direction.UPWARD
        assert snap.active_direction == Direction.UPWARD

        # Verify Candle 8 equality rejection diagnostic
        diag_types = [d.diagnostic_type for d in snap.choch_snapshot.diagnostics]
        assert ChochDiagnosticType.EQUALITY_REJECTED in diag_types

        # Verify zones
        zone_map = {z.zone_type: z for z in event.zones}
        assert ChochZoneType.RBS in zone_map
        assert ChochZoneType.QML_A_PLUS in zone_map
        assert ChochZoneType.DOUBLE_BOTTOM in zone_map

        # RBS from candle 1: [1.245, 1.248]
        rbs = zone_map[ChochZoneType.RBS]
        assert rbs.source_candle_index == 1
        assert rbs.lower_price == 1.245
        assert rbs.upper_price == 1.248

        # QML from candle 1: [1.210, 1.215]
        qml = zone_map[ChochZoneType.QML_A_PLUS]
        assert qml.source_candle_index == 1
        assert qml.lower_price == 1.210
        assert qml.upper_price == 1.215

        # Double Bottom from candle 5: [1.180, 1.185]
        db = zone_map[ChochZoneType.DOUBLE_BOTTOM]
        assert db.source_candle_index == 5
        assert db.lower_price == 1.180
        assert db.upper_price == 1.185

        # Forward scan boundary strictly after confirmation candle 10 (pos 10 -> min pos 11)
        assert event.first_eligible_pullback_pos == 11
        assert snap.msm_snapshot.next_eligible_pullback_position == 11

    def test_single_qualifying_close_rejected(self, choch_fixtures):
        """Candle c1 qualifies, but c2 fails above support -> sequence resets."""
        fix = choch_fixtures["choch_bearish_single_qualifying_close_rejected"]
        candles = [
            StrategyCandle(
                index=8 + i,
                open_time=datetime.fromisoformat(c["time"]),
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
                close_time=datetime.fromisoformat(c["close_time"]),
            )
            for i, c in enumerate(fix["candidate_candles"])
        ]
        detector = ChochDetector(Direction.UPWARD)
        lookup = {c.index: c for c in candles}

        # Create mock swing points
        from aladeen.strategy.types import SwingPoint
        support = SwingPoint(
            price=1.105,
            candle_index=3,
            candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
            identified_bar_index=3,
        )
        p3 = SwingPoint(
            price=1.155,
            candle_index=5,
            candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc),
            identified_bar_index=7,
            identified_time=datetime(2026, 10, 2, 4, tzinfo=timezone.utc),
        )

        # Candle 8 (index 8, pos 8): close=1.095 < 1.105 -> c1 recorded
        snap1 = detector.process_candle(candles[0], 8, Direction.UPWARD, support, None, p3, lookup)
        assert snap1.candidate is not None
        assert snap1.candidate.c1_candle_index == 8
        assert snap1.confirmed_choch is None

        # Candle 9 (index 9, pos 9): close=1.110 >= 1.105 -> reset
        snap2 = detector.process_candle(candles[1], 9, Direction.UPWARD, support, None, p3, lookup)
        assert snap2.candidate is None
        assert snap2.confirmed_choch is None
        diag_types = [d.diagnostic_type for d in snap2.diagnostics]
        assert ChochDiagnosticType.SECOND_CLOSE_FAILED in diag_types

    def test_equality_rejected_on_first_or_second_close(self, choch_fixtures):
        """Exact equality touch on either close fails closed."""
        detector = ChochDetector(Direction.UPWARD)
        from aladeen.strategy.types import SwingPoint
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7, identified_time=datetime(2026, 10, 2, 4, tzinfo=timezone.utc))

        c_eq1 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.105, False, "CONFIRMED_COMPLETED", close_time=datetime(2026, 10, 2, 12, tzinfo=timezone.utc))
        snap = detector.process_candle(c_eq1, 8, Direction.UPWARD, support, None, p3, {8: c_eq1})
        assert snap.candidate is None
        assert any(d.diagnostic_type == ChochDiagnosticType.EQUALITY_REJECTED for d in snap.diagnostics)

    def test_nonconsecutive_closes_rejected(self):
        """Non-adjacent qualifying closes cannot be combined across an intervening candle."""
        detector = ChochDetector(Direction.UPWARD)
        from aladeen.strategy.types import SwingPoint
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.095, 1.115, 1.092, 1.108, False, "CONFIRMED_COMPLETED")
        c10 = StrategyCandle(10, datetime(2026, 10, 2, 16, tzinfo=timezone.utc), 1.108, 1.110, 1.085, 1.090, False, "CONFIRMED_COMPLETED")
        lookup = {8: c8, 9: c9, 10: c10}

        # c8: qualifies as c1
        detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, lookup)
        assert detector.candidate is not None
        assert detector.candidate.c1_candle_index == 8

        # c9: fails (close = 1.108 > 1.105) -> resets candidate
        detector.process_candle(c9, 9, Direction.UPWARD, support, None, p3, lookup)
        assert detector.candidate is None

        # c10: qualifies as NEW c1 (not combined with c8)
        detector.process_candle(c10, 10, Direction.UPWARD, support, None, p3, lookup)
        assert detector.confirmed_choch is None
        assert detector.candidate is not None
        assert detector.candidate.c1_candle_index == 10

    def test_wick_crossing_only_rejected(self):
        """Wick pierces level, but close remains above -> rejected."""
        detector = ChochDetector(Direction.UPWARD)
        from aladeen.strategy.types import SwingPoint
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.115, 1.080, 1.106, False, "CONFIRMED_COMPLETED")
        snap = detector.process_candle(c, 8, Direction.UPWARD, support, None, p3, {8: c})
        assert snap.candidate is None
        assert any(d.diagnostic_type == ChochDiagnosticType.WICK_CROSSING_ONLY_REJECTED for d in snap.diagnostics)

    def test_color_independence_mixed_colors_confirmed(self):
        """Green c1 and red c2 both strictly below support confirm Bearish CHOCH."""
        detector = ChochDetector(Direction.UPWARD)
        from aladeen.strategy.types import SwingPoint
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)
        c_high = SwingPoint(price=1.135, candle_index=1, candle_open_time=datetime(2026, 10, 1, 4, tzinfo=timezone.utc), identified_bar_index=3)

        # c8: green candle (open 1.090, close 1.098) but close < 1.105
        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.090, 1.100, 1.085, 1.098, False, "CONFIRMED_COMPLETED")
        # c9: red candle (open 1.100, close 1.085) and close < 1.105
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.100, 1.102, 1.080, 1.085, False, "CONFIRMED_COMPLETED")

        c_p3 = StrategyCandle(5, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), 1.145, 1.160, 1.142, 1.155, False, "CONFIRMED_COMPLETED")
        c_sup = StrategyCandle(3, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), 1.120, 1.122, 1.100, 1.105, False, "CONFIRMED_COMPLETED")
        c_h = StrategyCandle(1, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), 1.105, 1.140, 1.102, 1.135, False, "CONFIRMED_COMPLETED")
        lookup = {1: c_h, 3: c_sup, 5: c_p3, 8: c8, 9: c9}

        detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, lookup, c_high)
        detector.process_candle(c9, 9, Direction.UPWARD, support, None, p3, lookup, c_high)

        assert detector.confirmed_choch is not None
        assert detector.confirmed_choch.choch_type == ChochType.BEARISH_CHOCH

    def test_missing_point_3_fails_closed(self):
        """Two closes below support when active Point 3 is absent fails closed."""
        detector = ChochDetector(Direction.UPWARD)
        from aladeen.strategy.types import SwingPoint
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
        from aladeen.strategy.types import SwingPoint
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, {8: c8})
        assert detector.candidate is not None

        # Price breaks continuation; MSM cycle completes, tentative_point becomes None
        c9 = StrategyCandle(9, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.150, 1.170, 1.148, 1.165, False, "CONFIRMED_COMPLETED")
        detector.process_candle(c9, 9, Direction.UPWARD, support, None, None, {8: c8, 9: c9})

        assert detector.candidate is None
        assert any(d.diagnostic_type == ChochDiagnosticType.CONTINUATION_RESET for d in detector.diagnostics)

    def test_zero_width_zones_preserved_as_price_lines(self, choch_fixtures):
        """Zero-wick swing candles produce thickness-0 zones with is_line=True."""
        fix = choch_fixtures["choch_zero_width_zones_preserved_as_price_lines"]
        orig = fix["original_candles"]

        c_high = StrategyCandle(1, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), orig["confirmed_high"]["open"], orig["confirmed_high"]["high"], orig["confirmed_high"]["low"], orig["confirmed_high"]["close"], False, "CONFIRMED_COMPLETED")
        c_low = StrategyCandle(3, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), orig["confirmed_low"]["open"], orig["confirmed_low"]["high"], orig["confirmed_low"]["low"], orig["confirmed_low"]["close"], False, "CONFIRMED_COMPLETED")
        c_p3 = StrategyCandle(5, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), orig["point_3"]["open"], orig["point_3"]["high"], orig["point_3"]["low"], orig["point_3"]["close"], False, "CONFIRMED_COMPLETED")

        from aladeen.strategy.choch_types import ChochZone
        # Confirmed High has high == UB (1.135 == 1.135)
        qml = ChochZone.from_candle(ChochZoneType.QML_A_PLUS, c_high, is_high_side=True)
        assert qml.is_line is True
        assert qml.lower_price == qml.upper_price == 1.135

        # Confirmed Low has low == LB (1.105 == 1.105)
        sbr = ChochZone.from_candle(ChochZoneType.SBR, c_low, is_high_side=False)
        assert sbr.is_line is True
        assert sbr.lower_price == sbr.upper_price == 1.105

        # Point 3 has top wick (1.160 > 1.155)
        dt = ChochZone.from_candle(ChochZoneType.DOUBLE_TOP, c_p3, is_high_side=True)
        assert dt.is_line is False
        assert dt.lower_price == 1.155
        assert dt.upper_price == 1.160

    def test_unresolved_same_close_diagnostic_and_downstream_non_publication(self, choch_fixtures):
        """When Point 3 is identified at the same close that breaches support (c1 == p2), emits UNRESOLVED diagnostic and publishes NO CHOCH."""
        detector = ChochDetector(Direction.UPWARD)
        from aladeen.strategy.types import SwingPoint
        support = SwingPoint(price=1.105, candle_index=3, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=3)
        # Point 3 identified at candle index 7
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=7)

        # Candle 7 completes pullback AND closes at 1.090 < 1.105
        c7 = StrategyCandle(7, datetime(2026, 10, 2, 4, tzinfo=timezone.utc), 1.095, 1.100, 1.085, 1.090, False, "CONFIRMED_COMPLETED")
        # Candle 8 completes strictly after at 1.092 < 1.105
        c8 = StrategyCandle(8, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.090, 1.098, 1.088, 1.092, False, "CONFIRMED_COMPLETED")
        lookup = {7: c7, 8: c8}

        snap7 = detector.process_candle(c7, 7, Direction.UPWARD, support, None, p3, lookup)
        assert snap7.is_unresolved is True
        assert any(d.diagnostic_type == ChochDiagnosticType.UNRESOLVED_SAME_CLOSE for d in snap7.diagnostics)
        assert snap7.candidate is None
        assert snap7.confirmed_choch is None

        # Next candle 8 also closes below support, but path is blocked by unresolved status
        snap8 = detector.process_candle(c8, 8, Direction.UPWARD, support, None, p3, lookup)
        assert snap8.confirmed_choch is None  # Must NOT confirm CHOCH on ambiguous path!

    def test_arbitrary_noncontiguous_source_ids(self):
        """Adjacency is strictly governed by chronological positions, not numeric source IDs."""
        detector = ChochDetector(Direction.UPWARD)
        from aladeen.strategy.types import SwingPoint
        support = SwingPoint(price=1.105, candle_index=300, candle_open_time=datetime(2026, 10, 1, 12, tzinfo=timezone.utc), identified_bar_index=300)
        p3 = SwingPoint(price=1.155, candle_index=500, candle_open_time=datetime(2026, 10, 1, 20, tzinfo=timezone.utc), identified_bar_index=700)
        c_high = SwingPoint(price=1.135, candle_index=100, candle_open_time=datetime(2026, 10, 1, 4, tzinfo=timezone.utc), identified_bar_index=300)

        # Source IDs jump from 850 to 950 (difference = 100), but chronological positions are adjacent (8 and 9)
        c850 = StrategyCandle(850, datetime(2026, 10, 2, 8, tzinfo=timezone.utc), 1.110, 1.120, 1.090, 1.095, False, "CONFIRMED_COMPLETED")
        c950 = StrategyCandle(950, datetime(2026, 10, 2, 12, tzinfo=timezone.utc), 1.095, 1.098, 1.080, 1.085, False, "CONFIRMED_COMPLETED")

        lookup = {
            100: StrategyCandle(100, datetime(2026, 10, 1, 4, tzinfo=timezone.utc), 1.105, 1.140, 1.102, 1.135, False, "CONFIRMED_COMPLETED"),
            300: StrategyCandle(300, datetime(2026, 10, 1, 12, tzinfo=timezone.utc), 1.120, 1.122, 1.100, 1.105, False, "CONFIRMED_COMPLETED"),
            500: StrategyCandle(500, datetime(2026, 10, 1, 20, tzinfo=timezone.utc), 1.145, 1.160, 1.142, 1.155, False, "CONFIRMED_COMPLETED"),
            850: c850,
            950: c950,
        }

        detector.process_candle(c850, 8, Direction.UPWARD, support, None, p3, lookup, c_high)
        detector.process_candle(c950, 9, Direction.UPWARD, support, None, p3, lookup, c_high)

        # Must confirm CHOCH despite ID difference of 100
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

        # Batch
        coord_batch = MSMChochCoordinator(config)
        snap_batch = coord_batch.process_candles(fix["candles"])

        # Sequential
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

        # Verify CHOCH confirmed and direction is DOWNWARD
        assert len(coordinator.confirmed_choch_events) == 1
        assert coordinator.direction == Direction.DOWNWARD

        # Feed new candles strictly after candle 9 in the DOWNWARD direction:
        # Candle 10: Downward continuation push
        # Candle 11 & 12: Upward pullback (2 consecutive green candles)
        # Candle 13: Continuation break below tentative low!
        new_candles = [
            StrategyCandle(10, datetime(2026, 10, 2, 16, tzinfo=timezone.utc), 1.085, 1.088, 1.070, 1.075, False, "CONFIRMED_COMPLETED"),
            StrategyCandle(11, datetime(2026, 10, 2, 20, tzinfo=timezone.utc), 1.075, 1.090, 1.072, 1.085, False, "CONFIRMED_COMPLETED"),  # Pullback 1: Green, High=1.090
            StrategyCandle(12, datetime(2026, 10, 3, 0, tzinfo=timezone.utc), 1.085, 1.095, 1.082, 1.092, False, "CONFIRMED_COMPLETED"),   # Pullback 2: Green, Close=1.092 > High 1.090 -> Tentative Low identified!
            StrategyCandle(13, datetime(2026, 10, 3, 4, tzinfo=timezone.utc), 1.092, 1.094, 1.060, 1.065, False, "CONFIRMED_COMPLETED"),   # Break candle: Close=1.065 < Tentative Low -> Confirms DOWNWARD pair!
        ]

        for c in new_candles:
            coordinator.process_candle(c)

        snap = coordinator.get_snapshot()

        # Both the prior upward pair AND the new downward pair are preserved in history!
        pairs = snap.msm_snapshot.confirmed_pairs
        assert len(pairs) == 2, f"Expected 2 confirmed pairs (1 prior UPWARD + 1 new DOWNWARD), got {len(pairs)}"
        assert pairs[0].pair_index == 1
        assert pairs[1].pair_index == 2

        # Second pair was confirmed in DOWNWARD direction
        downward_pair = pairs[1]
        assert downward_pair.confirmation_bar_index == 13
        assert snap.msm_snapshot.last_resistance is not None
