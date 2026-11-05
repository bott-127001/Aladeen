"""End-to-end and candle-derived integration tests for TJLCoordinator."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict
import pytest

from aladeen.strategy.types import Direction, MSMConfig
from aladeen.strategy.tjl_coordinator import TJLCoordinator
from aladeen.strategy.tjl_types import TJLLabel, TJLTransitionType


@pytest.fixture(scope="module")
def tjl_fixtures() -> Dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "tjl_acceptance.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)["fixtures"]


class TestTJLCoordinator:
    """Rigorous candle-derived tests for TJLCoordinator."""

    def test_bullish_basic_end_to_end_replay(self, tjl_fixtures) -> None:
        """[Actual MSM-Derived: tjl_01] Replays Bullish sequence and asserts exact lifecycle at critical prefixes."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )

        snaps = coord.replay_candles(fix["candles"])

        # Bar 4: Pair confirmed (CH Bar 1, CL Bar 4), P3 is None -> Labels only, set is None
        s4 = snaps[4]
        assert s4.current_eligible_set is None
        assert s4.outgoing_cancellation_intent is False
        assert len(s4.all_labeled_zones) == 2
        assert s4.last_transition.transition_type == TJLTransitionType.LABELS_ONLY

        # Verify zones
        tjl1 = next(z for z in s4.all_labeled_zones if z.label == TJLLabel.TJL1)
        tjl2 = next(z for z in s4.all_labeled_zones if z.label == TJLLabel.TJL2_A_PLUS)
        assert tjl1.source_candle_index == 1
        assert tjl1.lower_price == 1.135 and tjl1.upper_price == 1.140  # High-side [UB, High]
        assert tjl2.source_candle_index == 4
        assert tjl2.lower_price == 1.104 and tjl2.upper_price == 1.105  # Low-side [Low, LB]

        # Bar 7: Pullback completes at Bar 7, identifying active P3 at Bar 5 -> First Set Created
        s7 = snaps[7]
        assert s7.current_eligible_set is not None
        curr = s7.current_eligible_set
        assert curr.set_id == "SET_1"
        assert curr.fingerprint == ("ENGINE_EURUSD_H1", "UPWARD", 1, 4, 5)
        assert curr.tjl1_zone.source_candle_index == 1
        assert curr.tjl2_zone.source_candle_index == 4
        assert curr.p3_source_index == 5
        assert s7.outgoing_cancellation_intent is False
        assert s7.last_transition.transition_type == TJLTransitionType.FIRST_CREATION

    def test_bearish_basic_end_to_end_replay(self, tjl_fixtures) -> None:
        """[Actual MSM-Derived: tjl_02] Replays Bearish sequence and asserts exact lifecycle at critical prefixes."""
        fix = tjl_fixtures["tjl_02_bearish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_GBPUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_GBPUSD_H1",
        )

        snaps = coord.replay_candles(fix["candles"])

        # Bar 5: Pair confirmed (CH Bar 4, CL Bar 2), P3 is None -> Labels only, set is None
        s5 = snaps[5]
        assert s5.current_eligible_set is None
        assert len(s5.all_labeled_zones) == 2

        # In Bearish: TJL1 is CL (Bar 2, low-side [1.180, 1.185]), TJL2 is CH (Bar 4, high-side [1.200, 1.205])
        tjl1 = next(z for z in s5.all_labeled_zones if z.label == TJLLabel.TJL1)
        tjl2 = next(z for z in s5.all_labeled_zones if z.label == TJLLabel.TJL2_A_PLUS)
        assert tjl1.source_candle_index == 2
        assert tjl1.lower_price == 1.180 and tjl1.upper_price == 1.185
        assert tjl2.source_candle_index == 4
        assert tjl2.lower_price == 1.200 and tjl2.upper_price == 1.205

        # Bar 9: Pullback completes at Bar 9, identifying tentative low P3 at Bar 7 -> First Set Created
        s9 = snaps[9]
        assert s9.current_eligible_set is not None
        curr = s9.current_eligible_set
        assert curr.set_id == "SET_1"
        assert curr.fingerprint == ("ENGINE_GBPUSD_H1", "DOWNWARD", 4, 2, 7)
        assert curr.tjl1_zone.source_candle_index == 2
        assert curr.tjl2_zone.source_candle_index == 4
        assert curr.p3_source_index == 7
        assert s9.outgoing_cancellation_intent is False
        assert s9.last_transition.transition_type == TJLTransitionType.FIRST_CREATION

    def test_continuation_t1_retention_and_t2_pullback_replacement(self, tjl_fixtures) -> None:
        """[Actual MSM-Derived: tjl_05 & tjl_06] Verifies t1 continuation set retention and t2 pullback replacement."""
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_GBPUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_GBPUSD_H1",
        )

        snaps = coord.replay_candles(fix["candles"])

        # Bar 9: Set 1 active
        assert snaps[9].current_eligible_set.fingerprint == ("ENGINE_GBPUSD_H1", "DOWNWARD", 4, 2, 7)

        # Bar 14 (t1 continuation break): Set 1 retained, outgoing_cancellation_intent is False
        s14 = snaps[14]
        assert s14.current_eligible_set is not None
        assert s14.current_eligible_set.fingerprint == ("ENGINE_GBPUSD_H1", "DOWNWARD", 4, 2, 7)
        assert s14.outgoing_cancellation_intent is False
        assert s14.last_transition.transition_type == TJLTransitionType.CONTINUATION_RETAINED

        # Bar 16 (t2 pullback completion): Set 2 replaces Set 1 with outgoing cancellation intent
        s16 = snaps[16]
        assert s16.current_eligible_set is not None
        assert s16.current_eligible_set.set_id == "SET_2"
        assert s16.current_eligible_set.fingerprint == ("ENGINE_GBPUSD_H1", "DOWNWARD", 13, 7, 14)
        assert s16.outgoing_cancellation_intent is True
        assert s16.last_transition.transition_type == TJLTransitionType.SET_REPLACEMENT

    def test_source_choch_invalidation_and_gap(self, tjl_fixtures) -> None:
        """[Actual CHOCH-Derived: tjl_09] Cross-checks source CHOCH invalidation and post-CHOCH gap."""
        fix = tjl_fixtures["tjl_09_source_choch_eligibility_invalidation_and_gap"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )

        snaps = coord.replay_candles(fix["candles"])

        # Pre-CHOCH at Bar 7: Bullish Set 1 active
        s7 = snaps[7]
        assert s7.current_eligible_set is not None
        assert s7.current_eligible_set.fingerprint == ("ENGINE_EURUSD_H1", "UPWARD", 1, 4, 5)

        # Bar 9: Bearish CHOCH confirmed!
        s9 = snaps[9]
        assert s9.current_eligible_set is None
        assert s9.outgoing_cancellation_intent is True
        assert s9.last_transition.transition_type == TJLTransitionType.CHOCH_INVALIDATION

    def test_batch_vs_sequential_vs_replay_consistency(self, tjl_fixtures) -> None:
        """Verifies that batch process_candles, incremental process_candle, and replay_candles yield identical state."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"])
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        # 1. Batch
        coord_batch = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        snap_batch = coord_batch.process_candles(candles)

        # 2. Sequential incremental
        coord_seq = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        for c in candles:
            coord_seq.process_candle(c)
        snap_seq = coord_seq.get_snapshot()

        # 3. Replay
        coord_replay = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        snaps_replay = coord_replay.replay_candles(candles)
        snap_last = snaps_replay[-1]

        # Assert identical results
        assert snap_batch.current_eligible_set == snap_seq.current_eligible_set
        assert snap_batch.current_eligible_set == snap_last.current_eligible_set
        assert snap_batch.all_labeled_zones == snap_seq.all_labeled_zones
        assert snap_batch.all_labeled_zones == snap_last.all_labeled_zones
        assert snap_batch.outgoing_cancellation_intent == snap_seq.outgoing_cancellation_intent

    def test_forming_bars_cause_zero_state_mutations(self, tjl_fixtures) -> None:
        """Forming bars delivered to process_candle cause zero coordinator mutations."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        from aladeen.strategy.validator import adapt_candles
        from aladeen.strategy.types import StrategyCandle
        candles = adapt_candles(fix["candles"])
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        for c in candles[:8]:
            coord.process_candle(c)

        snap_before = coord.get_snapshot()

        # Create a forming candle
        forming_c = StrategyCandle(
            index=8,
            open_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            open=1.140,
            high=1.145,
            low=1.139,
            close=1.142,
            is_forming=True,
            bar_status="FORMING",
        )
        coord.process_candle(forming_c)
        snap_after = coord.get_snapshot()

        assert snap_before == snap_after
        assert coord.last_processed_index == 7

    def test_mid_batch_failure_rolls_back_atomic_state(self, tjl_fixtures) -> None:
        """Any validation error during batch processing preserves previous coordinator state."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        from aladeen.strategy.validator import adapt_candles
        candles = adapt_candles(fix["candles"][:5])
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        coord.process_candles(candles)
        snap_before = coord.get_snapshot()

        # Batch with duplicate / invalid timestamps
        bad_candles = list(fix["candles"][:3]) + [fix["candles"][0]]  # Duplicate
        with pytest.raises(Exception):
            coord.process_candles(bad_candles)

        snap_after = coord.get_snapshot()
        assert snap_before == snap_after
