"""Acceptance and regression tests for the deterministic MSM Engine.

Scope & Design Boundary:
-------------------------
- Independent of MT5, Dash, Plotly, network, and persistence.
- Verifies the MSM Engine against all acceptance fixtures in tests/fixtures/msm_acceptance.json.
- Verifies state transitions, batch vs sequential parity, prefix immutability, and comprehensive regressions:
  - Nonzero and noncontiguous source indices (R7.1)
  - Manual start after earlier historical rows (R7.1)
  - Validation at every public entry point (R7.2)
  - Repeated batch/replay calls and extended snapshot idempotence (R7.3)
  - Tentative identification provenance retention upon confirmation (R7.4)
  - Atomic transactional failure rejection (fail-closed)
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
        assert snapshot.next_eligible_pullback_index == 7
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
        assert snapshot.next_eligible_pullback_index == 7
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
        snapshot = engine.process_candles(fix["candles"])

        assert snapshot.state == EngineState.SEARCHING_PULLBACK
        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]
        assert pair.high.price == 107.0
        assert pair.high.candle_index == 0
        assert pair.low.price == 100.0
        assert pair.low.candle_index == 0
        assert snapshot.search_start_index == 0

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
        assert snapshot.search_start_index == 4

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
        assert snapshot.search_start_index == 4

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

        # Pair 1
        assert p1.high.price == 105.0 and p1.high.candle_index == 1
        assert p1.low.price == 101.0 and p1.low.candle_index == 3

        # Pair 2
        assert p2.high.price == 111.0 and p2.high.candle_index == 5
        assert p2.low.price == 105.0 and p2.low.candle_index == 7

        # Trend Status
        assert snapshot.trend_status == TrendStatus.UPWARD_TREND.value
        assert snapshot.search_start_index == 7

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
        assert len(snapshots) == 10

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
            {"index": 100, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            {"index": 110, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0},
            {"index": 120, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 108.0, "low": 104.0, "close": 107.0},
            {"index": 130, "open_time": base_time + timedelta(hours=12), "open": 107.0, "high": 107.5, "low": 103.0, "close": 104.0},
            {"index": 140, "open_time": base_time + timedelta(hours=16), "open": 104.0, "high": 104.5, "low": 101.5, "close": 102.0},
            {"index": 150, "open_time": base_time + timedelta(hours=20), "open": 102.0, "high": 105.0, "low": 101.0, "close": 103.5},
            {"index": 160, "open_time": base_time + timedelta(hours=24), "open": 103.5, "high": 110.0, "low": 103.0, "close": 109.0},
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
        assert snapshot.next_eligible_pullback_index == 161

    def test_r7_1_manual_start_after_earlier_input_rows(self):
        """When manual start is after earlier historical rows, earlier rows are ignored for marking."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        # 3 earlier historical rows before the start candle at index 3
        start_time = base_time + timedelta(hours=12)
        candles = [
            {"index": 0, "open_time": base_time, "open": 50.0, "high": 55.0, "low": 49.0, "close": 54.0},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 54.0, "high": 56.0, "low": 53.0, "close": 55.0},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 55.0, "high": 55.5, "low": 51.0, "close": 52.0},
            # Actual Start Candle: Index 3
            {"index": 3, "open_time": start_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            {"index": 4, "open_time": start_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0},
            {"index": 5, "open_time": start_time + timedelta(hours=8), "open": 105.0, "high": 108.0, "low": 104.0, "close": 107.0},
            {"index": 6, "open_time": start_time + timedelta(hours=12), "open": 107.0, "high": 107.5, "low": 103.0, "close": 104.0},
            {"index": 7, "open_time": start_time + timedelta(hours=16), "open": 104.0, "high": 104.5, "low": 101.5, "close": 102.0},
            {"index": 8, "open_time": start_time + timedelta(hours=20), "open": 102.0, "high": 105.0, "low": 101.0, "close": 103.5},
            {"index": 9, "open_time": start_time + timedelta(hours=24), "open": 103.5, "high": 110.0, "low": 103.0, "close": 109.0},
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
            engine.process_candle({"index": 0, "open_time": base_time, "open": True, "high": 105.0, "low": 99.0, "close": 104.0})

        # String in open price
        with pytest.raises(TypeError, match="must be numeric"):
            engine.process_candle({"index": 0, "open_time": base_time, "open": "100.0", "high": 105.0, "low": 99.0, "close": 104.0})

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
                "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0
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

        c0 = StrategyCandle(0, base_time, 100.0, 102.0, 99.0, 101.0)
        engine.process_candle(c0)

        # Duplicate timestamp
        with pytest.raises(ValueError, match="duplicate or out-of-order"):
            engine.process_candle(c0)

        # Earlier timestamp (out of order)
        c_past = StrategyCandle(1, base_time - timedelta(hours=4), 98.0, 100.0, 97.0, 99.0)
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
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0},
        ]
        s_initial = engine.process_candles(good_candles)
        assert s_initial.last_processed_index == 1

        # Poisoned batch: starts good, but candle 2 has non-finite price
        poisoned_batch = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": float("inf"), "high": 108.0, "low": 100.0, "close": 105.0},
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
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.000000},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.000001},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 105.5, "low": 101.0, "close": 102.0},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 102.0, "high": 102.5, "low": 99.0, "close": 100.0},
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
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 105.5, "low": 102.0, "close": 103.0},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 103.0, "high": 103.5, "low": 100.0, "close": 101.0},
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 95.0, "high": 108.0, "low": 94.0, "close": 107.0},
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
            {"index": 0, "open_time": base_time, "open": 200.0, "high": 201.0, "low": 198.0, "close": 199.0},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 193.0, "high": 193.5, "low": 190.0, "close": 191.0},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 191.0, "high": 195.0, "low": 190.5, "close": 194.0},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 194.0, "high": 198.0, "low": 193.5, "close": 197.0},
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 196.0, "high": 196.5, "low": 188.0, "close": 189.0},
            # Cycle 2
            {"index": 5, "open_time": base_time + timedelta(hours=20), "open": 183.0, "high": 183.5, "low": 180.0, "close": 181.0},
            {"index": 6, "open_time": base_time + timedelta(hours=24), "open": 181.0, "high": 185.0, "low": 180.5, "close": 184.0},
            {"index": 7, "open_time": base_time + timedelta(hours=28), "open": 184.0, "high": 188.0, "low": 183.5, "close": 187.0},
            {"index": 8, "open_time": base_time + timedelta(hours=32), "open": 186.0, "high": 186.5, "low": 178.0, "close": 179.0},
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
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.5, "low": 99.0, "close": 102.0},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 102.0, "high": 106.0, "low": 101.5, "close": 105.0},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 105.5, "low": 102.0, "close": 103.0},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 103.0, "high": 103.5, "low": 100.5, "close": 101.0},
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 102.0, "high": 108.0, "low": 101.5, "close": 107.0},
            {"index": 5, "open_time": base_time + timedelta(hours=20), "open": 107.0, "high": 112.0, "low": 106.5, "close": 111.0},
            {"index": 6, "open_time": base_time + timedelta(hours=24), "open": 111.0, "high": 111.5, "low": 102.0, "close": 103.0},
            {"index": 7, "open_time": base_time + timedelta(hours=28), "open": 103.0, "high": 103.5, "low": 100.5, "close": 101.0},
            {"index": 8, "open_time": base_time + timedelta(hours=32), "open": 102.0, "high": 115.0, "low": 101.5, "close": 114.0},
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
            StrategyCandle(0, base_time, 100.0, 102.0, 99.0, 101.0),
            StrategyCandle(1, base_time + timedelta(hours=4), 101.0, 106.0, 100.5, 105.0),
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

        engine.process_candle(StrategyCandle(0, base_time, 100.0, 102.0, 99.0, 101.0))
        engine.process_candle(StrategyCandle(1, base_time + timedelta(hours=4), 101.0, 106.0, 100.5, 105.0))

        forming_bar = StrategyCandle(2, base_time + timedelta(hours=8), 105.0, 105.5, 102.0, 103.0, is_forming=True, bar_status="FORMING")
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
                datetime.fromisoformat(c["close_time"]),
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
