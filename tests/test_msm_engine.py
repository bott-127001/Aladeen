"""Acceptance and regression tests for the deterministic MSM Engine.

Scope & Design Boundary:
-------------------------
- Independent of MT5, Dash, Plotly, network, and persistence.
- Verifies the MSM Engine against all acceptance fixtures in tests/fixtures/msm_acceptance.json.
- Verifies state transitions, batch vs sequential parity, prefix immutability, and focused regressions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
import pandas as pd

from aladeen.strategy.types import (
    CandleColor,
    Direction,
    EngineState,
    MSMConfig,
    MSMSnapshot,
    StrategyCandle,
    SwingPoint,
    TrendStatus,
)
from aladeen.strategy.engine import MSMEngine


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "msm_acceptance.json"


@pytest.fixture(scope="module")
def acceptance_data() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestMSMAcceptanceFixtures:
    """Verifies all documented acceptance fixtures against the MSM engine."""

    def test_msm_01_upward_standard(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-01"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert snapshot.state == EngineState.SEARCHING_PULLBACK
        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]

        # Confirmed High
        assert pair.high.price == 107.0
        assert pair.high.candle_index == 2
        assert pair.high.identified_bar_index == 4  # Identified at bar 4
        assert pair.high.confirmed_bar_index == 6   # Confirmed at break bar 6
        assert pair.high.event_bar_index == 6

        # Confirmed Low (Tied at 102 between 4 and 5 -> latest is 5)
        assert pair.low.price == 102.0
        assert pair.low.candle_index == 5
        assert pair.low.identified_bar_index == 6
        assert pair.low.confirmed_bar_index == 6
        assert pair.low.event_bar_index == 6

        # Pointers & Status
        assert snapshot.last_support is not None
        assert snapshot.last_support.candle_index == 5
        assert snapshot.search_start_index == 5
        assert snapshot.next_eligible_pullback_index is None  # Next candle not in buffer
        assert snapshot.next_eligible_pullback_position == 7
        assert snapshot.trend_status == TrendStatus.MARKING_UPWARD.value

    def test_msm_02_downward_standard(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-02"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.DOWNWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert snapshot.state == EngineState.SEARCHING_PULLBACK
        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]

        # Confirmed Low
        assert pair.low.price == 192.0
        assert pair.low.candle_index == 2
        assert pair.low.identified_bar_index == 4
        assert pair.low.confirmed_bar_index == 6

        # Confirmed High (Tied at 197 between 4 and 5 -> latest is 5)
        assert pair.high.price == 197.0
        assert pair.high.candle_index == 5
        assert pair.high.identified_bar_index == 6
        assert pair.high.confirmed_bar_index == 6

        # Pointers & Status
        assert snapshot.last_resistance is not None
        assert snapshot.last_resistance.candle_index == 5
        assert snapshot.search_start_index == 5
        assert snapshot.next_eligible_pullback_index is None  # Next candle not in buffer
        assert snapshot.next_eligible_pullback_position == 7
        assert snapshot.trend_status == TrendStatus.MARKING_DOWNWARD.value

    def test_msm_03_strict_equality_failures(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-03"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert snapshot.state == EngineState.WAITING_FOR_BREAK
        assert len(snapshot.confirmed_pairs) == 0
        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.price == 104.0
        assert snapshot.tentative_point.candle_index == 1
        assert snapshot.tentative_point.identified_bar_index == 4
        assert snapshot.tentative_point.confirmed_bar_index is None

    def test_msm_04_flat_candle_interruption(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-04"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert snapshot.state == EngineState.SEARCHING_PULLBACK
        assert len(snapshot.confirmed_pairs) == 0
        assert snapshot.tentative_point is None

    def test_msm_05_empty_range_skip(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-05"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert snapshot.state == EngineState.SEARCHING_PULLBACK
        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]
        assert pair.high.price == 107.0
        assert pair.high.candle_index == 3
        assert pair.low.price == 102.0
        assert pair.low.candle_index == 6
        assert snapshot.search_start_index == 6

    def test_msm_06_waiting_lockout(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-06"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshots = engine.replay(fix["candles"])

        # At bar 5 (before break at bar 6): lockout active, pullback (4, 5) ignored
        s5 = snapshots[5]
        assert s5.state == EngineState.WAITING_FOR_BREAK
        assert len(s5.confirmed_pairs) == 0
        assert s5.tentative_point is not None
        assert s5.tentative_point.price == 107.0
        assert s5.tentative_point.candle_index == 0

        # At bar 6: closing break occurs!
        s6 = snapshots[6]
        assert s6.state == EngineState.SEARCHING_PULLBACK
        assert len(s6.confirmed_pairs) == 1
        pair = s6.confirmed_pairs[0]
        assert pair.high.price == 107.0
        assert pair.high.candle_index == 0
        assert pair.low.price == 100.0
        assert pair.low.candle_index == 0
        assert pair.confirmation_bar_index == 6
        assert s6.search_start_index == 0

    def test_msm_07_forming_bar_exclusion(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-07"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert snapshot.state == EngineState.WAITING_FOR_BREAK
        assert len(snapshot.confirmed_pairs) == 0
        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.price == 105.0
        assert snapshot.tentative_point.candle_index == 1

    def test_msm_08a_tied_tentative_high_upward(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-08A"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]
        assert pair.high.price == 105.0
        assert pair.high.candle_index == 1
        assert pair.low.price == 100.0
        assert pair.low.candle_index == 4

    def test_msm_08b_tied_tentative_low_downward(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-08B"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.DOWNWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]
        assert pair.low.price == 195.0
        assert pair.low.candle_index == 1
        assert pair.high.price == 200.0
        assert pair.high.candle_index == 4

    def test_msm_09_downward_equality(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-09"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.DOWNWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert snapshot.state == EngineState.WAITING_FOR_BREAK
        assert len(snapshot.confirmed_pairs) == 0
        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.price == 192.0
        assert snapshot.tentative_point.candle_index == 1

    def test_msm_10_flat_winning_extreme(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-10"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]
        assert pair.high.price == 106.0
        assert pair.high.candle_index == 1
        assert pair.low.price == 102.0
        assert pair.low.candle_index == 4
        assert snapshot.search_start_index == 4

    def test_msm_11a_red_candle_upward_break(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-11A"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]
        assert pair.high.price == 105.0
        assert pair.high.candle_index == 0
        assert pair.low.price == 100.0
        assert pair.low.candle_index == 2
        assert pair.confirmation_bar_index == 3
        assert snapshot.search_start_index == 2

    def test_msm_11b_green_candle_downward_break(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-11B"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.DOWNWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]
        assert pair.low.price == 195.0
        assert pair.low.candle_index == 0
        assert pair.high.price == 200.0
        assert pair.high.candle_index == 2
        assert pair.confirmation_bar_index == 3
        assert snapshot.search_start_index == 2

    def test_msm_12_two_pairs_and_trend_status(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-12"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        assert len(snapshot.confirmed_pairs) == 2
        p1 = snapshot.confirmed_pairs[0]
        p2 = snapshot.confirmed_pairs[1]
        assert p1.high.price == 105.0 and p1.high.candle_index == 1
        assert p1.low.price == 101.0 and p1.low.candle_index == 3
        assert p2.high.price == 111.0 and p2.high.candle_index == 5
        assert p2.low.price == 105.0 and p2.low.candle_index == 7
        assert snapshot.search_start_index == 7
        assert snapshot.trend_status == TrendStatus.UPWARD_TREND.value

    def test_msm_13a_missing_start_candle_rejection(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-13A"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        with pytest.raises(ValueError, match="Invalid starting candle"):
            engine.process_candles(fix["candles"])

    def test_msm_13b_forming_start_candle_rejection(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-13B"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        with pytest.raises(ValueError, match="Invalid starting candle"):
            engine.process_candles(fix["candles"])

    def test_msm_14_prefix_consistency_and_replay(self, acceptance_data):
        fix = acceptance_data["fixtures"]["MSM-14"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshots = engine.replay(fix["candles"])

        # Prefix 0..4 (index 4)
        s4 = snapshots[4]
        assert s4.state == EngineState.WAITING_FOR_BREAK
        assert len(s4.confirmed_pairs) == 0
        assert s4.tentative_point is not None
        assert s4.tentative_point.price == 107.0
        assert s4.tentative_point.candle_index == 2
        assert s4.tentative_point.identified_bar_index == 4

        # Prefix 0..6 (index 6)
        s6 = snapshots[6]
        assert s6.state == EngineState.SEARCHING_PULLBACK
        assert len(s6.confirmed_pairs) == 1
        p1 = s6.confirmed_pairs[0]
        assert p1.high.price == 107.0 and p1.high.candle_index == 2
        assert p1.high.identified_bar_index == 4
        assert p1.high.confirmed_bar_index == 6
        assert p1.low.price == 102.0 and p1.low.candle_index == 5
        assert s6.search_start_index == 5

        # Prefix 0..9 (index 9)
        s9 = snapshots[9]
        assert len(s9.confirmed_pairs) == 1
        p1_extended = s9.confirmed_pairs[0]
        assert p1_extended.high.price == 107.0 and p1_extended.high.candle_index == 2
        assert p1_extended.low.price == 102.0 and p1_extended.low.candle_index == 5

        # Reviewer correction verified: Tentative high is at index 7 with price 111.0
        assert s9.state == EngineState.WAITING_FOR_BREAK
        assert s9.tentative_point is not None
        assert s9.tentative_point.price == 111.0
        assert s9.tentative_point.candle_index == 7
        assert s9.tentative_point.identified_bar_index == 9


class TestMSMFocusedRegressions:
    """Targeted edge-case and regression tests specified in Perplexity reviews."""

    def test_r7_1_non_zero_and_noncontiguous_source_indices(self):
        """Source indices (e.g. 100, 110, 120...) are preserved and separated from buffer positions."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        candles = [
            {"index": 100, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 110, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 120, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 108.0, "low": 104.0, "close": 107.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 130, "open_time": base_time + timedelta(hours=12), "open": 107.0, "high": 107.5, "low": 103.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 140, "open_time": base_time + timedelta(hours=16), "open": 104.0, "high": 104.5, "low": 101.5, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 150, "open_time": base_time + timedelta(hours=20), "open": 102.0, "high": 105.0, "low": 101.0, "close": 103.5, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 160, "open_time": base_time + timedelta(hours=24), "open": 103.5, "high": 110.0, "low": 103.0, "close": 109.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert len(snapshot.confirmed_pairs) == 1
        p = snapshot.confirmed_pairs[0]
        # Must report source indices 120 and 150, NOT buffer positions 2 and 5!
        assert p.high.candle_index == 120
        assert p.low.candle_index == 150
        assert p.high.identified_bar_index == 140
        assert p.high.confirmed_bar_index == 160
        assert snapshot.search_start_index == 150
        assert snapshot.next_eligible_pullback_index is None
        assert snapshot.next_eligible_pullback_position == 7

    def test_r7_1_manual_start_after_earlier_input_rows(self):
        """When manual start is after earlier historical rows, earlier rows are ignored for marking."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        start_time = base_time + timedelta(hours=12)
        candles = [
            {"index": 0, "open_time": base_time, "open": 50.0, "high": 55.0, "low": 49.0, "close": 54.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 54.0, "high": 56.0, "low": 53.0, "close": 55.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 55.0, "high": 55.5, "low": 51.0, "close": 52.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            # Actual Start Candle: Index 3
            {"index": 3, "open_time": start_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 4, "open_time": start_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 5, "open_time": start_time + timedelta(hours=8), "open": 105.0, "high": 108.0, "low": 104.0, "close": 107.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 6, "open_time": start_time + timedelta(hours=12), "open": 107.0, "high": 107.5, "low": 103.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 7, "open_time": start_time + timedelta(hours=16), "open": 104.0, "high": 104.5, "low": 101.5, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 8, "open_time": start_time + timedelta(hours=20), "open": 102.0, "high": 105.0, "low": 101.0, "close": 103.5, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 9, "open_time": start_time + timedelta(hours=24), "open": 103.5, "high": 110.0, "low": 103.0, "close": 109.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=start_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert len(snapshot.confirmed_pairs) == 1
        p = snapshot.confirmed_pairs[0]
        assert p.high.candle_index == 5
        assert p.low.candle_index == 8
        assert snapshot.search_start_index == 8

    def test_r7_2_strict_validation_on_all_entry_points(self):
        """Strict validation rejects booleans as prices, strings, NaT, and invalid direction."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)

        # Invalid direction
        with pytest.raises(ValueError, match="Invalid direction"):
            MSMConfig(start_candle_time=base_time, direction="SIDEWAYS")

        # Naive start time
        naive_time = datetime(2026, 10, 1, 0, 0)
        with pytest.raises(ValueError, match="must be timezone-aware"):
            MSMConfig(start_candle_time=naive_time, direction=Direction.UPWARD)

        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)

        # Boolean in open price
        with pytest.raises(TypeError, match="must be numeric"):
            engine.process_candle({
                "index": 0, "open_time": base_time, "open": True, "high": 105.0, "low": 99.0, "close": 104.0,
                "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"
            })

        # String in open price
        with pytest.raises(TypeError, match="must be numeric"):
            engine.process_candle({
                "index": 0, "open_time": base_time, "open": "100.0", "high": 105.0, "low": 99.0, "close": 104.0,
                "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"
            })

        # Contradictory completion evidence
        with pytest.raises(ValueError, match="Contradictory completion evidence"):
            engine.process_candle({
                "index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0,
                "is_forming": True, "bar_status": "CONFIRMED_COMPLETED"
            })

        # Close time earlier than open time
        with pytest.raises(ValueError, match="strictly later than open_time"):
            engine.process_candle({
                "index": 0, "open_time": base_time, "close_time": base_time - timedelta(hours=1),
                "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0,
                "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"
            })

    def test_r7_3_repeated_batch_and_replay_resets_fresh(self, acceptance_data):
        """Calling process_candles or replay repeatedly executes a clean fresh run without duplicating history."""
        fix = acceptance_data["fixtures"]["MSM-01"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)

        # First run
        snap1 = engine.process_candles(fix["candles"])
        assert len(snap1.confirmed_pairs) == 1

        # Second run on same engine with same data: MUST NOT duplicate pairs!
        snap2 = engine.process_candles(fix["candles"])
        assert len(snap2.confirmed_pairs) == 1
        assert snap1 == snap2

    def test_r7_3_incremental_streaming_rejects_duplicate_or_out_of_order(self):
        """Incremental process_candle rejects duplicate timestamps and out-of-order candles."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)

        c0 = StrategyCandle(0, base_time, 100.0, 102.0, 99.0, 101.0, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        engine.process_candle(c0)

        # Duplicate timestamp
        with pytest.raises(ValueError, match="Duplicate candle source index detected|duplicate or out-of-order"):
            engine.process_candle(c0)

        # Earlier timestamp (out of order)
        c_past = StrategyCandle(1, base_time - timedelta(hours=4), 98.0, 100.0, 97.0, 99.0, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        with pytest.raises(ValueError, match="duplicate or out-of-order"):
            engine.process_candle(c_past)

    def test_r7_4_identification_provenance_retained_after_confirmation(self, acceptance_data):
        """Confirmed points retain original tentative identification provenance."""
        fix = acceptance_data["fixtures"]["MSM-01"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        snapshot = engine.process_candles(fix["candles"])

        pair = snapshot.confirmed_pairs[0]
        # Tentative high was identified at bar 4 upon pullback (3, 4) completion
        assert pair.high.identified_bar_index == 4
        # Confirmed at break candle 6
        assert pair.high.confirmed_bar_index == 6
        assert pair.high.identified_bar_index != pair.high.confirmed_bar_index

    def test_fail_closed_transactional_validation(self):
        """If batch input has an invalid candle, engine state is not mutated."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)

        # Good batch first
        good_candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        s_initial = engine.process_candles(good_candles)
        assert s_initial.last_processed_index == 1

        # Poisoned batch: starts good, but candle 2 has non-finite price
        poisoned_batch = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": float("inf"), "high": 108.0, "low": 100.0, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        with pytest.raises(ValueError, match="must be finite"):
            engine.process_candles(poisoned_batch)

        # Engine state should remain valid (fail-closed)
        snap_after = engine.get_snapshot()
        assert snap_after.last_processed_index == 1

    def test_near_but_unequal_prices_not_ties(self):
        """Strict body edge comparison does not treat near prices as ties."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.000000, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.000001, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 105.5, "low": 101.0, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 102.0, "high": 102.5, "low": 99.0, "close": 100.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.candle_index == 1
        assert snapshot.tentative_point.price == 104.000001

    def test_confirmation_on_inclusive_endpoint_when_break_candle_wins_extreme(self):
        """The break candle itself is inside the inclusive confirmed opposite level search window."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 105.5, "low": 102.0, "close": 103.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 103.0, "high": 103.5, "low": 100.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 95.0, "high": 108.0, "low": 94.0, "close": 107.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]
        assert pair.low.candle_index == 4
        assert pair.low.price == 95.0
        assert snapshot.search_start_index == 4

    def test_two_pair_downward_trend(self):
        """Two completed pairs with strictly lower highs and strictly lower lows yield Downward trend."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        candles = [
            # Cycle 1
            {"index": 0, "open_time": base_time, "open": 200.0, "high": 201.0, "low": 198.0, "close": 199.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 193.0, "high": 193.5, "low": 190.0, "close": 191.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 191.0, "high": 195.0, "low": 190.5, "close": 194.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 194.0, "high": 198.0, "low": 193.5, "close": 197.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 196.0, "high": 196.5, "low": 188.0, "close": 189.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            # Cycle 2
            {"index": 5, "open_time": base_time + timedelta(hours=20), "open": 183.0, "high": 183.5, "low": 180.0, "close": 181.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 6, "open_time": base_time + timedelta(hours=24), "open": 181.0, "high": 185.0, "low": 180.5, "close": 184.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 7, "open_time": base_time + timedelta(hours=28), "open": 184.0, "high": 188.0, "low": 183.5, "close": 187.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 8, "open_time": base_time + timedelta(hours=32), "open": 186.0, "high": 186.5, "low": 178.0, "close": 179.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.DOWNWARD)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert len(snapshot.confirmed_pairs) == 2
        p1 = snapshot.confirmed_pairs[0]
        p2 = snapshot.confirmed_pairs[1]
        assert p1.high.price == 197.0
        assert p1.low.price == 191.0
        assert p2.high.price == 187.0
        assert p2.low.price == 181.0
        assert snapshot.trend_status == TrendStatus.DOWNWARD_TREND.value

    def test_equality_yields_trend_not_confirmed(self):
        """When newer high equals older high or newer low equals older low, status is Trend not confirmed."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.5, "low": 99.0, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 102.0, "high": 106.0, "low": 101.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 105.5, "low": 102.0, "close": 103.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 103.0, "high": 103.5, "low": 100.5, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 102.0, "high": 108.0, "low": 101.5, "close": 107.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 5, "open_time": base_time + timedelta(hours=20), "open": 107.0, "high": 112.0, "low": 106.5, "close": 111.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 6, "open_time": base_time + timedelta(hours=24), "open": 111.0, "high": 111.5, "low": 102.0, "close": 103.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 7, "open_time": base_time + timedelta(hours=28), "open": 103.0, "high": 103.5, "low": 100.5, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 8, "open_time": base_time + timedelta(hours=32), "open": 102.0, "high": 115.0, "low": 101.5, "close": 114.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert len(snapshot.confirmed_pairs) == 2
        p1 = snapshot.confirmed_pairs[0]
        p2 = snapshot.confirmed_pairs[1]
        assert p1.low.price == 101.0
        assert p2.low.price == 101.0  # Equal to L1!
        assert snapshot.trend_status == TrendStatus.NOT_CONFIRMED.value

    def test_unconfirmed_latest_bar_changes_cause_no_completed_state_change(self):
        """Ingesting forming or unconfirmed candles does not advance completed state."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        completed = [
            StrategyCandle(0, base_time, 100.0, 102.0, 99.0, 101.0, is_forming=False, bar_status="CONFIRMED_COMPLETED"),
            StrategyCandle(1, base_time + timedelta(hours=4), 101.0, 106.0, 100.5, 105.0, is_forming=False, bar_status="CONFIRMED_COMPLETED"),
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)
        engine.process_candles(completed)
        snap1 = engine.get_snapshot()

        forming = StrategyCandle(
            2, base_time + timedelta(hours=8), 105.0, 200.0, 50.0, 199.0, is_forming=True, bar_status="FORMING"
        )
        snap2 = engine.process_candle(forming)

        assert snap1.state == snap2.state
        assert snap1.tentative_point == snap2.tentative_point
        assert snap1.confirmed_pairs == snap2.confirmed_pairs
        assert snap1.last_processed_index == snap2.last_processed_index

    def test_bar_becoming_confirmed_in_later_snapshot(self):
        """A candle previously seen as forming is processed once confirmed in a later snapshot."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)

        engine.process_candle(StrategyCandle(0, base_time, 100.0, 102.0, 99.0, 101.0, is_forming=False, bar_status="CONFIRMED_COMPLETED"))
        engine.process_candle(StrategyCandle(1, base_time + timedelta(hours=4), 101.0, 106.0, 100.5, 105.0, is_forming=False, bar_status="CONFIRMED_COMPLETED"))

        forming_bar = StrategyCandle(2, base_time + timedelta(hours=8), 105.0, 105.5, 102.0, 103.0, is_forming=True, bar_status="UNCONFIRMED_LATEST")
        s_forming = engine.process_candle(forming_bar)
        assert s_forming.last_processed_index == 1

        completed_bar = StrategyCandle(2, base_time + timedelta(hours=8), 105.0, 105.5, 102.0, 103.0, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        s_completed = engine.process_candle(completed_bar)
        assert s_completed.last_processed_index == 2

    def test_batch_sequential_and_replay_parity(self, acceptance_data):
        """Batch processing, sequential processing, and replay produce identical final snapshots."""
        fix = acceptance_data["fixtures"]["MSM-01"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )

        engine_batch = MSMEngine(config)
        snap_batch = engine_batch.process_candles(fix["candles"])

        engine_seq = MSMEngine(config)
        candles = [
            StrategyCandle(
                c["index"],
                datetime.fromisoformat(c["open_time"]),
                c["open"],
                c["high"],
                c["low"],
                c["close"],
                is_forming=c["is_forming"],
                bar_status=c["bar_status"],
                close_time=datetime.fromisoformat(c["close_time"]) if "close_time" in c and c["close_time"] else None,
            )
            for c in fix["candles"]
        ]
        for c in candles:
            snap_seq = engine_seq.process_candle(c)

        engine_rep = MSMEngine(config)
        snapshots = engine_rep.replay(fix["candles"])
        snap_replay = snapshots[-1]

        assert snap_batch == snap_seq == snap_replay

    def test_input_dataframe_immutability(self, acceptance_data):
        """Passing a DataFrame or list to the engine does not mutate the caller's data."""
        fix = acceptance_data["fixtures"]["MSM-01"]
        df_original = pd.DataFrame(
            [
                {
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "is_forming": False,
                    "bar_status": "CONFIRMED_COMPLETED",
                }
                for c in fix["candles"]
            ],
            index=pd.to_datetime([c["open_time"] for c in fix["candles"]]),
        )
        df_copy = df_original.copy(deep=True)

        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )
        engine = MSMEngine(config)
        engine.process_candles(df_original)

        pd.testing.assert_frame_equal(df_original, df_copy)

    # -------------------------------------------------------------------------
    # Regressions specifically requested in Review R8 (R8.1 - R8.5)
    # -------------------------------------------------------------------------

    def test_r8_1_unconfirmed_row_before_start_candle_agreement(self):
        """R8.1: An unconfirmed row before the selected completed start produces agreement across batch, seq, and replay."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        start_time = base_time + timedelta(hours=4)

        candles = [
            # Position 0: Unconfirmed row before start
            {"index": 0, "open_time": base_time, "open": 50.0, "high": 55.0, "low": 49.0, "close": 54.0, "is_forming": True, "bar_status": "UNCONFIRMED_LATEST"},
            # Position 1: Completed row, selected start
            {"index": 1, "open_time": start_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": start_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 3, "open_time": start_time + timedelta(hours=8), "open": 105.0, "high": 108.0, "low": 104.0, "close": 107.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 4, "open_time": start_time + timedelta(hours=12), "open": 107.0, "high": 107.5, "low": 103.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 5, "open_time": start_time + timedelta(hours=16), "open": 104.0, "high": 104.5, "low": 101.5, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 6, "open_time": start_time + timedelta(hours=20), "open": 102.0, "high": 105.0, "low": 101.0, "close": 103.5, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 7, "open_time": start_time + timedelta(hours=24), "open": 103.5, "high": 110.0, "low": 103.0, "close": 109.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=start_time, direction=Direction.UPWARD)

        # Batch
        engine_batch = MSMEngine(config)
        snap_batch = engine_batch.process_candles(candles)

        # Sequential
        engine_seq = MSMEngine(config)
        for c_dict in candles:
            engine_seq.process_candle(c_dict)
        snap_seq = engine_seq.get_snapshot()

        # Replay
        engine_rep = MSMEngine(config)
        snapshots = engine_rep.replay(candles)
        snap_replay = snapshots[-1]

        # All 3 modes must agree exactly on confirmed pairs and search start
        assert snap_batch == snap_seq == snap_replay
        assert len(snap_batch.confirmed_pairs) == 1
        p = snap_batch.confirmed_pairs[0]
        assert p.high.candle_index == 3
        assert p.low.candle_index == 6
        assert snap_batch.search_start_index == 6

    def test_r8_2_missing_completion_fields_rejected(self):
        """R8.2: Dictionary and StrategyCandle without explicit completion fields are rejected."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)

        # Missing is_forming
        with pytest.raises(ValueError, match="explicit 'is_forming' and 'bar_status'"):
            engine.process_candles([
                {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "bar_status": "CONFIRMED_COMPLETED"}
            ])

        # Missing bar_status
        with pytest.raises(ValueError, match="explicit 'is_forming' and 'bar_status'"):
            engine.process_candles([
                {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "is_forming": False}
            ])

        # Direct StrategyCandle construction without required completion fields
        with pytest.raises(TypeError, match="missing 2 required positional arguments"):
            StrategyCandle(0, base_time, 100.0, 105.0, 99.0, 104.0)  # type: ignore

    def test_r8_2_unknown_status_and_both_contradictory_combinations_rejected(self):
        """R8.2: Unknown bar_status and both contradiction directions are rejected."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)

        # Unknown status
        with pytest.raises(ValueError, match="Unknown bar_status 'UNKNOWN_STATUS'"):
            StrategyCandle(0, base_time, 100.0, 105.0, 99.0, 104.0, is_forming=False, bar_status="UNKNOWN_STATUS")

        # Contradiction 1: is_forming=True with CONFIRMED_COMPLETED
        with pytest.raises(ValueError, match="Contradictory completion evidence: is_forming=True"):
            StrategyCandle(0, base_time, 100.0, 105.0, 99.0, 104.0, is_forming=True, bar_status="CONFIRMED_COMPLETED")

        # Contradiction 2: is_forming=False with UNCONFIRMED_LATEST
        with pytest.raises(ValueError, match="Contradictory completion evidence: is_forming=False"):
            StrategyCandle(0, base_time, 100.0, 105.0, 99.0, 104.0, is_forming=False, bar_status="UNCONFIRMED_LATEST")

        # Contradiction 3: is_forming=False with FORMING
        with pytest.raises(ValueError, match="Contradictory completion evidence: is_forming=False"):
            StrategyCandle(0, base_time, 100.0, 105.0, 99.0, 104.0, is_forming=False, bar_status="FORMING")

    def test_r8_3_direct_object_nat_and_invalid_tzoffset_rejected(self):
        """R8.3: Direct-object/config NaT and invalid/naive timezone offsets are rejected."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)

        # NaT in open_time
        with pytest.raises(ValueError, match="cannot be NaT or NaN"):
            StrategyCandle(0, pd.NaT, 100.0, 105.0, 99.0, 104.0, is_forming=False, bar_status="CONFIRMED_COMPLETED")

        # NaT in start_candle_time
        with pytest.raises(ValueError, match="cannot be NaT or NaN"):
            MSMConfig(start_candle_time=pd.NaT, direction=Direction.UPWARD)

        # Naive datetime in open_time
        naive = datetime(2026, 10, 1, 0, 0)
        with pytest.raises(ValueError, match="must be timezone-aware"):
            StrategyCandle(0, naive, 100.0, 105.0, 99.0, 104.0, is_forming=False, bar_status="CONFIRMED_COMPLETED")

        # Timezone object where utcoffset() returns None
        from datetime import tzinfo
        class NoneOffsetTZ(tzinfo):
            def utcoffset(self, dt):
                return None
            def tzname(self, dt):
                return "NoneOffset"
            def dst(self, dt):
                return None

        bad_tz = NoneOffsetTZ()
        dt_bad_tz = datetime(2026, 10, 1, 0, 0, tzinfo=bad_tz)
        with pytest.raises(ValueError, match="must be timezone-aware"):
            StrategyCandle(0, dt_bad_tz, 100.0, 105.0, 99.0, 104.0, is_forming=False, bar_status="CONFIRMED_COMPLETED")

        with pytest.raises(ValueError, match="must be timezone-aware"):
            MSMConfig(start_candle_time=dt_bad_tz, direction=Direction.UPWARD)

        # Close time earlier than open time
        with pytest.raises(ValueError, match="strictly later than open_time"):
            StrategyCandle(
                0, base_time, 100.0, 105.0, 99.0, 104.0,
                is_forming=False, bar_status="CONFIRMED_COMPLETED",
                close_time=base_time - timedelta(hours=1),
            )

    def test_r8_3_non_utc_aware_inputs_normalized_to_utc(self):
        """R8.3: Non-UTC timezone-aware timestamps are normalized to UTC."""
        tz_plus5 = timezone(timedelta(hours=5))
        local_time = datetime(2026, 10, 1, 5, 0, tzinfo=tz_plus5)  # 2026-10-01 00:00 UTC

        candle = StrategyCandle(
            0, local_time, 100.0, 105.0, 99.0, 104.0,
            is_forming=False, bar_status="CONFIRMED_COMPLETED"
        )
        assert candle.open_time.tzinfo == timezone.utc
        assert candle.open_time == datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)

        config = MSMConfig(start_candle_time=local_time, direction=Direction.UPWARD)
        assert config.start_candle_time.tzinfo == timezone.utc
        assert config.start_candle_time == datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)

    def test_r8_4_noncontiguous_source_ids_with_unknown_next_candle(self):
        """R8.4: With noncontiguous source IDs, unknown next candle has next_eligible_pullback_index=None."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        candles = [
            {"index": 100, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 110, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 120, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 108.0, "low": 104.0, "close": 107.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 130, "open_time": base_time + timedelta(hours=12), "open": 107.0, "high": 107.5, "low": 103.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 140, "open_time": base_time + timedelta(hours=16), "open": 104.0, "high": 104.5, "low": 101.5, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 150, "open_time": base_time + timedelta(hours=20), "open": 102.0, "high": 105.0, "low": 101.0, "close": 103.5, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 160, "open_time": base_time + timedelta(hours=24), "open": 103.5, "high": 110.0, "low": 103.0, "close": 109.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        # Break occurred at index 160. Next candle not in buffer -> MUST NOT fabricate index 161!
        assert snapshot.next_eligible_pullback_index is None
        assert snapshot.next_eligible_pullback_position == 7

    def test_r8_4_duplicate_source_ids_and_fractional_boolean_index_rejection(self):
        """R8.4: Duplicate source IDs and lossy conversions (1.5, True) are rejected."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)

        # Duplicate source IDs
        dup_candles = [
            {"index": 100, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 100, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        with pytest.raises(ValueError, match="Duplicate candle source index detected: 100"):
            engine.process_candles(dup_candles)

        # Fractional index: 1.5 must be rejected with TypeError (not silently truncated to 1)
        with pytest.raises(TypeError, match="must be int"):
            engine.process_candles([
                {"index": 1.5, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"}
            ])

        # Boolean index: True must be rejected with TypeError
        with pytest.raises(TypeError, match="must be int"):
            engine.process_candles([
                {"index": True, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"}
            ])

    def test_r8_5_confirmed_point_with_unknown_confirmation_time_retains_none_event_time(self):
        """R8.5: When confirmation availability is unknown (confirmed_time=None), event_time is None (does not fall back)."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        t_id = base_time + timedelta(hours=16)

        point = SwingPoint(
            price=107.0,
            candle_index=2,
            candle_open_time=base_time + timedelta(hours=8),
            identified_bar_index=4,
            identified_time=t_id,
            confirmed_bar_index=6,
            confirmed_time=None,  # Availability unknown!
        )

        assert point.is_confirmed is True
        assert point.event_bar_index == 6
        # Must NOT fall back to identified_time!
        assert point.event_time is None

    # -------------------------------------------------------------------------
    # Regression Suite: MSMConfig.earliest_pullback_time
    # -------------------------------------------------------------------------

    def test_earliest_pullback_time_none_preserves_prior_behavior(self):
        """earliest_pullback_time=None strictly preserves standard MSM pullback detection."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 104.0, "high": 104.5, "low": 101.0, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 102.0, "high": 102.5, "low": 99.0, "close": 100.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=None)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.candle_index == 0
        assert snapshot.tentative_point.price == 104.0

    def test_earliest_pullback_time_ignores_prior_pullback(self):
        """A valid pullback occurring strictly before earliest_pullback_time is ignored."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        # Pullback 1 at bars 1-2 (before boundary at hours=12)
        # Pullback 2 at bars 4-5 (after boundary at hours=12)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 104.0, "high": 104.5, "low": 101.0, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 102.0, "high": 102.5, "low": 99.0, "close": 100.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 100.0, "high": 108.0, "low": 99.5, "close": 107.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 107.0, "high": 107.5, "low": 104.0, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 5, "open_time": base_time + timedelta(hours=20), "open": 105.0, "high": 105.5, "low": 102.0, "close": 103.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        # Set earliest pullback time to hours=16 (Bar 4)
        boundary_time = base_time + timedelta(hours=16)
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=boundary_time)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        # Pullback 1 (bars 1-2) must be skipped. Pullback 2 (bars 4-5) must be detected!
        # Search window for tentative high from start (Bar 0) through Bar 3 -> Bar 3 has UB=107.0
        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.candle_index == 3
        assert snapshot.tentative_point.price == 107.0
        assert snapshot.tentative_point.identified_bar_index == 5

    def test_earliest_pullback_time_accepts_exact_boundary_pullback(self):
        """A pullback beginning exactly at earliest_pullback_time timestamp is accepted."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        boundary_time = base_time + timedelta(hours=4)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": boundary_time, "open": 104.0, "high": 104.5, "low": 101.0, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 102.0, "high": 102.5, "low": 99.0, "close": 100.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=boundary_time)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.candle_index == 0
        assert snapshot.tentative_point.price == 104.0

    def test_earliest_pullback_time_batch_sequential_replay_parity(self):
        """Batch, incremental sequential ingest, and step-by-step replay produce identical state."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        boundary_time = base_time + timedelta(hours=8)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 104.0, "high": 104.5, "low": 101.0, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": boundary_time, "open": 102.0, "high": 106.0, "low": 101.5, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 105.0, "high": 105.5, "low": 102.0, "close": 103.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 103.0, "high": 103.5, "low": 100.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=boundary_time)

        # 1. Batch
        e_batch = MSMEngine(config)
        s_batch = e_batch.process_candles(candles)

        # 2. Sequential
        e_seq = MSMEngine(config)
        for c in candles:
            s_seq = e_seq.process_candle(c)

        # 3. Replay
        e_rep = MSMEngine(config)
        snaps_rep = e_rep.replay(candles)
        s_rep = snaps_rep[-1]

        assert s_batch.state == s_seq.state == s_rep.state
        assert s_batch.tentative_point == s_seq.tentative_point == s_rep.tentative_point
        assert s_batch.confirmed_pairs == s_seq.confirmed_pairs == s_rep.confirmed_pairs

    def test_earliest_pullback_time_with_unconfirmed_row_before_boundary(self):
        """Unconfirmed forming rows before boundary are filtered without corrupting completed buffer positions."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        boundary_time = base_time + timedelta(hours=12)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            # Unconfirmed latest row that is filtered by adapt_candles
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 104.0, "high": 104.5, "low": 101.0, "close": 102.0, "is_forming": True, "bar_status": "FORMING"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 104.0, "high": 107.0, "low": 103.5, "close": 106.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 3, "open_time": boundary_time, "open": 106.0, "high": 106.5, "low": 103.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 104.0, "high": 104.5, "low": 101.0, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=boundary_time)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        # Forming bar at index 1 excluded; completed buffer has index 0, 2, 3, 4
        # Pullback at index 3-4 detected; tentative high from index 0 through 2 -> index 2 has UB=106.0
        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.candle_index == 2
        assert snapshot.tentative_point.price == 106.0
        assert snapshot.tentative_point.identified_bar_index == 4

    def test_earliest_pullback_time_beyond_dataset(self):
        """earliest_pullback_time lying strictly beyond all available candles keeps engine in SEARCHING_PULLBACK."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        boundary_time = base_time + timedelta(hours=48)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 104.0, "high": 104.5, "low": 101.0, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 102.0, "high": 102.5, "low": 99.0, "close": 100.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=boundary_time)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert snapshot.state == EngineState.SEARCHING_PULLBACK
        assert snapshot.tentative_point is None

    def test_earliest_pullback_time_with_noncontiguous_source_ids(self):
        """earliest_pullback_time works reliably with noncontiguous arbitrary candle IDs."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        boundary_time = base_time + timedelta(hours=10)
        candles = [
            {"index": 501, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 709, "open_time": base_time + timedelta(hours=5), "open": 104.0, "high": 107.0, "low": 103.5, "close": 106.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 822, "open_time": boundary_time, "open": 106.0, "high": 106.5, "low": 103.0, "close": 104.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 999, "open_time": base_time + timedelta(hours=15), "open": 104.0, "high": 104.5, "low": 101.0, "close": 102.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=boundary_time)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.candle_index == 709
        assert snapshot.tentative_point.identified_bar_index == 999

    def test_earliest_pullback_time_invalid_timestamp_rejected_fail_closed(self):
        """Naive or non-datetime earliest_pullback_time is rejected fail-closed upfront in MSMConfig."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        # Naive datetime
        naive_dt = datetime(2026, 10, 1, 12, 0)
        with pytest.raises(ValueError, match="must be timezone-aware"):
            MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=naive_dt)

        # Invalid type
        with pytest.raises(TypeError, match="must be datetime"):
            MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=12345)

    def test_earliest_pullback_time_preserves_historical_search_reference(self):
        """Historical extreme-search reference remains at start_candle while forward scan is delayed."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        boundary_time = base_time + timedelta(hours=16)
        # Bar 0 is start reference with UB=110.0 (highest in entire series)
        # Bars 1-3 rise and fall
        # Bars 4-5 pullback after boundary
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 108.0, "high": 108.2, "low": 105.0, "close": 106.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 106.0, "high": 107.0, "low": 105.5, "close": 106.5, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 106.5, "high": 106.8, "low": 104.0, "close": 105.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 4, "open_time": boundary_time, "open": 105.0, "high": 105.2, "low": 102.0, "close": 103.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
            {"index": 5, "open_time": base_time + timedelta(hours=20), "open": 103.0, "high": 103.2, "low": 100.0, "close": 101.0, "is_forming": False, "bar_status": "CONFIRMED_COMPLETED"},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD, earliest_pullback_time=boundary_time)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        # Pullback at bars 4-5 searches from Bar 0 through Bar 3 -> Bar 0 is selected with UB=110.0
        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.candle_index == 0
        assert snapshot.tentative_point.price == 110.0
        assert snapshot.search_start_index == 0

