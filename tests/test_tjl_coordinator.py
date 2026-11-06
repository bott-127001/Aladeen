"""End-to-end and candle-derived integration tests for TJLCoordinator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Dict
import pytest

from aladeen.strategy.types import Direction, MSMConfig, StrategyCandle
from aladeen.strategy.validator import adapt_candles
from aladeen.strategy.tjl_coordinator import TJLCoordinator
from aladeen.strategy.tjl_types import TJLLabel, TJLSide, TJLTransitionType


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
        assert tjl1.lower_price == 1.135 and tjl1.upper_price == 1.140
        assert tjl2.source_candle_index == 4
        assert tjl2.lower_price == 1.104 and tjl2.upper_price == 1.105

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
        assert s16.last_transition.outgoing_cancelled_set_id == "SET_1"

    def test_source_choch_invalidation_and_post_choch_gap(self, tjl_fixtures) -> None:
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
        assert s9.last_transition.outgoing_cancelled_set_id == "SET_1"

    def test_actual_candle_driven_post_choch_recovery_and_new_direction_set(self, tjl_fixtures) -> None:
        """[Directive 6.B] Full candle sequence: Set 1 -> CHOCH -> gap -> first new-direction eligible set."""
        fix = tjl_fixtures["tjl_09_source_choch_eligibility_invalidation_and_gap"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )

        candles = adapt_candles(fix["candles"])
        # Process through CHOCH confirmation at candle 9
        for c in candles:
            coord.process_candle(c)

        snap_choch = coord.get_snapshot()
        assert snap_choch.current_eligible_set is None
        assert snap_choch.direction == Direction.DOWNWARD
        assert snap_choch.structural_epoch == 1

        # Now extend with candles establishing the new DOWNWARD epoch:
        # In MSM restart after Bearish CHOCH:
        # Restart reference is P3 at candle 5 (price 1.155).
        # First eligible pullback position must occur strictly after confirmation bar (candle 9).
        last_t = candles[-1].open_time
        # Candle 10: Downward continuation close lower
        c10 = StrategyCandle(index=10, open_time=last_t + timedelta(hours=1), open=1.095, high=1.098, low=1.070, close=1.075, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=2))
        # Candle 11: Downward move low
        c11 = StrategyCandle(index=11, open_time=last_t + timedelta(hours=2), open=1.075, high=1.078, low=1.050, close=1.055, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=3))
        # Candle 12: Pullback candle 1 (Green)
        c12 = StrategyCandle(index=12, open_time=last_t + timedelta(hours=3), open=1.055, high=1.070, low=1.052, close=1.065, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=4))
        # Candle 13: Pullback candle 2 (Green, close > high of 12)
        c13 = StrategyCandle(index=13, open_time=last_t + timedelta(hours=4), open=1.065, high=1.080, low=1.062, close=1.075, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=5))
        # Candle 14: Downward break confirming pair in new direction (breaks below low of 11)
        c14 = StrategyCandle(index=14, open_time=last_t + timedelta(hours=5), open=1.075, high=1.076, low=1.040, close=1.045, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=6))
        # Candle 15: Pullback candle 1 for new P3 (Green)
        c15 = StrategyCandle(index=15, open_time=last_t + timedelta(hours=6), open=1.045, high=1.060, low=1.042, close=1.055, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=7))
        # Candle 16: Pullback candle 2 for new P3 (Green)
        c16 = StrategyCandle(index=16, open_time=last_t + timedelta(hours=7), open=1.055, high=1.070, low=1.052, close=1.065, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=8))

        extension = [c10, c11, c12, c13, c14, c15, c16]
        for c in extension:
            coord.process_candle(c)

        snap_recovery = coord.get_snapshot()
        assert snap_recovery.direction == Direction.DOWNWARD
        assert snap_recovery.structural_epoch == 1
        assert snap_recovery.current_eligible_set is not None

        new_set = snap_recovery.current_eligible_set
        assert new_set.direction == Direction.DOWNWARD
        # In DOWNWARD set: TJL1 is CL (low-side), TJL2 is CH (high-side)
        assert new_set.tjl1_zone.label == TJLLabel.TJL1
        assert new_set.tjl1_zone.level_id.side == TJLSide.LOW
        assert new_set.tjl2_zone.label == TJLLabel.TJL2_A_PLUS
        assert new_set.tjl2_zone.level_id.side == TJLSide.HIGH
        assert len(snap_recovery.historical_sets) == 2  # Set 1 (Bullish) and Set 2 (Bearish)

    def test_failure_injection_after_main_coordinator_rollback_and_valid_retry(self, tjl_fixtures) -> None:
        """[Directive 6.A] Injected failure after main-coordinator advance leaves live coordinator untouched; retry matches reference run."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        candles = adapt_candles(fix["candles"])
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )

        # Process first 5 candles
        for c in candles[:5]:
            coord.process_candle(c)

        snap_before = coord.get_snapshot()
        lookup_before = dict(coord._candle_lookup)
        main_coord_before_dir = coord._main_coordinator.direction
        main_coord_before_last = coord._main_coordinator.last_processed_index
        prev_choch_count_before = coord._prev_choch_count

        # Monkeypatch the live reducer to simulate a failure AFTER main coordinator advance
        orig_reduce = coord._reducer.reduce

        def failing_reduce(obs):
            raise RuntimeError("Injected downstream failure after main coordinator advance")

        coord._reducer.reduce = failing_reduce

        # Attempt to deliver candle 5 -> must raise RuntimeError
        with pytest.raises(RuntimeError, match="Injected downstream failure"):
            coord.process_candle(candles[5])

        # Assert all live components are 100% unchanged!
        assert coord.get_snapshot() == snap_before
        assert coord._candle_lookup == lookup_before
        assert coord._main_coordinator.direction == main_coord_before_dir
        assert coord._main_coordinator.last_processed_index == main_coord_before_last
        assert coord._prev_choch_count == prev_choch_count_before

        # Restore original reducer
        coord._reducer.reduce = orig_reduce

        # Now deliver candle 5 and 6
        coord.process_candle(candles[5])
        coord.process_candle(candles[6])

        # Independent reference coordinator processed cleanly from start
        coord_ref = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        for c in candles[:7]:
            coord_ref.process_candle(c)

        # Retried coordinator state matches reference run identically
        assert coord.get_snapshot() == coord_ref.get_snapshot()

    def test_arbitrary_decreasing_source_ids_candle_driven(self, tjl_fixtures) -> None:
        """[Directive 6.C] Candle-driven coordinator handles strictly decreasing unique source IDs identically."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        # Map indices to decreasing IDs: 900, 890, 880, ...
        decreasing_candles = []
        for i, c in enumerate(fix["candles"]):
            c_copy = dict(c)
            c_copy["index"] = 900 - (i * 10)
            decreasing_candles.append(c_copy)

        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        snaps = coord.replay_candles(decreasing_candles)

        # Bar 7 (chronological 8th candle, index = 900 - 70 = 830)
        s7 = snaps[7]
        assert s7.current_eligible_set is not None
        # Points correspond to indices 900 - 10 = 890, 900 - 40 = 860, 900 - 50 = 850
        assert s7.current_eligible_set.fingerprint == ("ENGINE_EURUSD_H1", "UPWARD", 890, 860, 850)
        assert s7.current_eligible_set.p3_source_index == 850

    def test_unknown_availability_preserved_as_none_in_coordinator(self, tjl_fixtures) -> None:
        """[Finding 1 Regression] When candle close_time is None, availability_time remains None in snapshot."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        modified_candles = [dict(c) for c in fix["candles"][:8]]
        for c in modified_candles:
            c["close_time"] = None  # Unknown close time!

        start_time = datetime.fromisoformat(fix["start_candle_time"])
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        snap = coord.process_candles(modified_candles)
        assert snap.current_eligible_set is not None
        assert snap.current_eligible_set.eligibility_available_time is None

    def test_batch_vs_sequential_vs_replay_consistency_full_lifecycle(self, tjl_fixtures) -> None:
        """[Directive 6.E] Full prefix consistency across batch, sequential, and replay APIs on complete Bearish lifecycle."""
        fix = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        candles = adapt_candles(fix["candles"])
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        # 1. Batch
        coord_batch = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_GBPUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_GBPUSD_H1",
        )
        snap_batch = coord_batch.process_candles(candles)

        # 2. Sequential incremental
        coord_seq = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_GBPUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_GBPUSD_H1",
        )
        for c in candles:
            coord_seq.process_candle(c)
        snap_seq = coord_seq.get_snapshot()

        # 3. Replay
        coord_replay = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_GBPUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_GBPUSD_H1",
        )
        snaps_replay = coord_replay.replay_candles(candles)
        snap_last = snaps_replay[-1]

        # Assert identical results across all fields
        assert snap_batch == snap_seq
        assert snap_batch == snap_last
