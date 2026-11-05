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
        assert pair.high.event_bar_index == 6

        # Confirmed Low (Tied at 102 between 4 and 5 -> latest is 5)
        assert pair.low.price == 102.0
        assert pair.low.candle_index == 5
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
        assert pair.low.event_bar_index == 6

        # Confirmed High (Tied at 197 between 4 and 5 -> latest is 5)
        assert pair.high.price == 197.0
        assert pair.high.candle_index == 5
        assert pair.high.event_bar_index == 6

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

        # Pullback (1, 2) rejected due to equality. Pullback (3, 4) accepted.
        # Tentative high in [0, 2] tied at 104 between 0 and 1 -> selects index 1.
        # Candle 5 closes at 104.0 == 104.0 -> strict closing break fails!
        assert snapshot.state == EngineState.WAITING_FOR_BREAK
        assert len(snapshot.confirmed_pairs) == 0
        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.price == 104.0
        assert snapshot.tentative_point.candle_index == 1
        assert snapshot.tentative_point.event_bar_index == 4

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

        # Pullback (0, 1) skipped due to empty range [0, -1]. Search start retained at 0.
        # Pullback (4, 5) accepted. Tentative high at index 3 (107.0).
        # Candle 6 breaks 107.0. Confirmed low in [3, 6] tied at 102 between 5 and 6 -> selects index 6.
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

        # Pullback (1, 2) establishes tentative high at index 0 (107.0).
        # Pullback (4, 5) is locked out / ignored.
        # Candle 6 breaks 107.0.
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

        # Bar 4 is forming. Tentative high established at bar 3 (index 1, price 105.0).
        # Bar 4 break does not confirm.
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
        # Tentative high in [0, 1] tied at 105 -> selects index 1
        assert pair.high.price == 105.0
        assert pair.high.candle_index == 1
        # Confirmed low in [1, 4] tied at 100 between 3 and 4 -> selects index 4
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
        # Tentative low in [0, 1] tied at 195 -> selects index 1
        assert pair.low.price == 195.0
        assert pair.low.candle_index == 1
        # Confirmed high in [1, 4] tied at 200 between 3 and 4 -> selects index 4
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

        # Pullback (1, 2) rejected. Pullback (2, 3) accepted.
        # Tentative low in [0, 1] tied at 192 -> selects index 1.
        # Candle 4 close = 192.0 == 192.0 -> strict closing break fails.
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
        # Tentative high at flat candle 1 (106.0)
        assert pair.high.price == 106.0
        assert pair.high.candle_index == 1
        # Confirmed low in [1, 4] tied at 102 between 3 and 4 -> selects index 4
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
        # Confirmed low in [0, 3] tied at 100 between 0 and 2 -> selects index 2
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
        # Confirmed high in [0, 3] tied at 200 between 0 and 2 -> selects index 2
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

        # Trend Status: H2 (111) > H1 (105) and L2 (105) > L1 (101) -> Upward trend
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

        # Replay evaluation bar-by-bar
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
        assert s4.tentative_point.event_bar_index == 4

        # Prefix 0..6 (index 6)
        s6 = snapshots[6]
        assert s6.state == EngineState.SEARCHING_PULLBACK
        assert len(s6.confirmed_pairs) == 1
        p1 = s6.confirmed_pairs[0]
        assert p1.high.price == 107.0 and p1.high.candle_index == 2
        assert p1.low.price == 102.0 and p1.low.candle_index == 5
        assert s6.search_start_index == 5

        # Prefix 0..9 (index 9)
        s9 = snapshots[9]
        # Historical Pair 1 remains strictly identical to prefix 0..6
        assert len(s9.confirmed_pairs) == 1
        p1_extended = s9.confirmed_pairs[0]
        assert p1_extended.high.price == 107.0 and p1_extended.high.candle_index == 2
        assert p1_extended.low.price == 102.0 and p1_extended.low.candle_index == 5

        # Candles 8 and 9 form the second pullback
        # Tentative high in [5, 7] is candle 7 with price 111.0
        assert s9.state == EngineState.WAITING_FOR_BREAK
        assert s9.tentative_point is not None
        assert s9.tentative_point.price == 111.0
        assert s9.tentative_point.candle_index == 7
        assert s9.tentative_point.event_bar_index == 9


class TestMSMFocusedRegressions:
    """Targeted edge-case and regression tests specified in Perplexity review."""

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

        # Pullback at (2, 3). Search window [0, 1].
        # Candle 1 (104.000001) > Candle 0 (104.000000). Index 1 must win strictly, not tie.
        assert snapshot.tentative_point is not None
        assert snapshot.tentative_point.candle_index == 1
        assert snapshot.tentative_point.price == 104.000001

    def test_confirmation_on_inclusive_endpoint_when_break_candle_wins_extreme(self):
        """The break candle itself is inside the inclusive confirmed opposite level search window."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        candles = [
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 101.0, "high": 106.0, "low": 100.5, "close": 105.0},
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 105.5, "low": 102.0, "close": 103.0}, # Red p1, low=102
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 103.0, "high": 103.5, "low": 100.0, "close": 101.0}, # Red p2, close 101 < 102
            # Candle 4 breaks 105.0 by closing at 107.0, but its open is very low (95.0), making LB=95.0 the lowest!
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 95.0, "high": 108.0, "low": 94.0, "close": 107.0},
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert len(snapshot.confirmed_pairs) == 1
        pair = snapshot.confirmed_pairs[0]
        # Break candle 4 itself has LB = min(95.0, 107.0) = 95.0, which is the lowest in [1, 4]!
        assert pair.low.candle_index == 4
        assert pair.low.price == 95.0
        assert snapshot.search_start_index == 4

    def test_two_pair_downward_trend(self):
        """Two completed pairs with strictly lower highs and strictly lower lows yield Downward trend."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        candles = [
            # Cycle 1
            {"index": 0, "open_time": base_time, "open": 200.0, "high": 201.0, "low": 198.0, "close": 199.0},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 193.0, "high": 193.5, "low": 190.0, "close": 191.0}, # Trough 1: LB=191.0, UB=193.0
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 191.0, "high": 195.0, "low": 190.5, "close": 194.0}, # Green p1, high=195.0
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 194.0, "high": 198.0, "low": 193.5, "close": 197.0}, # Green p2, close 197 > 195 (UB=197.0)
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 196.0, "high": 196.5, "low": 188.0, "close": 189.0}, # Break 1: close 189 < 191. Confirmed High in [1, 4]: candle 3 UB=197.0. Confirmed Low: candle 1 LB=191.0. Next search_start = 3.
            # Cycle 2
            {"index": 5, "open_time": base_time + timedelta(hours=20), "open": 183.0, "high": 183.5, "low": 180.0, "close": 181.0}, # Trough 2: LB=181.0, UB=183.0
            {"index": 6, "open_time": base_time + timedelta(hours=24), "open": 181.0, "high": 185.0, "low": 180.5, "close": 184.0}, # Green p1, high=185.0
            {"index": 7, "open_time": base_time + timedelta(hours=28), "open": 184.0, "high": 188.0, "low": 183.5, "close": 187.0}, # Green p2, close 187 > 185 (UB=187.0)
            {"index": 8, "open_time": base_time + timedelta(hours=32), "open": 186.0, "high": 186.5, "low": 178.0, "close": 179.0}, # Break 2: close 179 < 181. Confirmed High in [5, 8]: candle 7 UB=187.0. Confirmed Low: candle 5 LB=181.0.
        ]
        config = MSMConfig(start_candle_time=base_time, direction=Direction.DOWNWARD)
        engine = MSMEngine(config)
        snapshot = engine.process_candles(candles)

        assert len(snapshot.confirmed_pairs) == 2
        p1 = snapshot.confirmed_pairs[0]
        p2 = snapshot.confirmed_pairs[1]

        # Pair 1: H1 = 197.0 (idx 3), L1 = 191.0 (idx 1)
        assert p1.high.price == 197.0
        assert p1.low.price == 191.0

        # Pair 2: H2 = 187.0 (idx 7), L2 = 181.0 (idx 5)
        assert p2.high.price == 187.0
        assert p2.low.price == 181.0

        # H2 (187) < H1 (197) and L2 (181) < L1 (191) -> Downward trend
        assert snapshot.trend_status == TrendStatus.DOWNWARD_TREND.value

    def test_equality_yields_trend_not_confirmed(self):
        """When newer high equals older high or newer low equals older low, status is Trend not confirmed."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        # In this dataset: Pair 1 has H1=105.0, L1=101.0. Pair 2 has H2=111.0, but L2=101.0 (equal to L1)!
        candles = [
            # Cycle 1
            {"index": 0, "open_time": base_time, "open": 100.0, "high": 102.5, "low": 99.0, "close": 102.0},
            {"index": 1, "open_time": base_time + timedelta(hours=4), "open": 102.0, "high": 106.0, "low": 101.5, "close": 105.0}, # Peak 1 UB=105.0
            {"index": 2, "open_time": base_time + timedelta(hours=8), "open": 105.0, "high": 105.5, "low": 102.0, "close": 103.0},
            {"index": 3, "open_time": base_time + timedelta(hours=12), "open": 103.0, "high": 103.5, "low": 100.5, "close": 101.0}, # LB=101.0
            {"index": 4, "open_time": base_time + timedelta(hours=16), "open": 102.0, "high": 108.0, "low": 101.5, "close": 107.0}, # Break 1
            # Cycle 2
            {"index": 5, "open_time": base_time + timedelta(hours=20), "open": 107.0, "high": 112.0, "low": 106.5, "close": 111.0}, # Peak 2 UB=111.0
            {"index": 6, "open_time": base_time + timedelta(hours=24), "open": 111.0, "high": 111.5, "low": 102.0, "close": 103.0}, # Red p1, low=102.0
            {"index": 7, "open_time": base_time + timedelta(hours=28), "open": 103.0, "high": 103.5, "low": 100.5, "close": 101.0}, # Red p2, close 101 < 102. LB=101.0 (EQUAL to L1!)
            {"index": 8, "open_time": base_time + timedelta(hours=32), "open": 102.0, "high": 115.0, "low": 101.5, "close": 114.0}, # Breaks 111.0
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

        # Ingest forming candle with crazy numbers
        forming = StrategyCandle(
            2, base_time + timedelta(hours=8), 105.0, 200.0, 50.0, 199.0, is_forming=True, bar_status="FORMING"
        )
        snap2 = engine.process_candle(forming)

        # Snapshot state must remain strictly identical
        assert snap1.state == snap2.state
        assert snap1.tentative_point == snap2.tentative_point
        assert snap1.confirmed_pairs == snap2.confirmed_pairs
        assert snap1.last_processed_index == snap2.last_processed_index

    def test_bar_becoming_confirmed_in_later_snapshot(self):
        """A candle previously seen as forming is processed once confirmed in a later snapshot."""
        base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        config = MSMConfig(start_candle_time=base_time, direction=Direction.UPWARD)
        engine = MSMEngine(config)

        # Feed candles 0 and 1 completed
        engine.process_candle(StrategyCandle(0, base_time, 100.0, 102.0, 99.0, 101.0))
        engine.process_candle(StrategyCandle(1, base_time + timedelta(hours=4), 101.0, 106.0, 100.5, 105.0))

        # Bar 2 arrives as forming
        forming_bar = StrategyCandle(2, base_time + timedelta(hours=8), 105.0, 105.5, 102.0, 103.0, is_forming=True)
        s_forming = engine.process_candle(forming_bar)
        assert s_forming.last_processed_index == 1

        # In next tick, bar 2 is completed!
        completed_bar = StrategyCandle(2, base_time + timedelta(hours=8), 105.0, 105.5, 102.0, 103.0, is_forming=False)
        s_completed = engine.process_candle(completed_bar)
        assert s_completed.last_processed_index == 2

    def test_batch_sequential_and_replay_parity(self, acceptance_data):
        """Batch processing, sequential processing, and replay produce identical final snapshots."""
        fix = acceptance_data["fixtures"]["MSM-01"]
        config = MSMConfig(
            start_candle_time=datetime.fromisoformat(fix["start_candle_time"]),
            direction=Direction.UPWARD,
        )

        # Batch
        engine_batch = MSMEngine(config)
        snap_batch = engine_batch.process_candles(fix["candles"])

        # Sequential
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

        # Replay
        engine_rep = MSMEngine(config)
        snapshots = engine_rep.replay(fix["candles"])
        snap_replay = snapshots[-1]

        # Assert exact agreement across all 3 modes
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

        # Assert df_original was not mutated in any way
        pd.testing.assert_frame_equal(df_original, df_copy)
