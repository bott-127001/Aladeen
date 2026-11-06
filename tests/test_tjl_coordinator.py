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
        """[Directive 3] Full candle sequence with comprehensive assertions at every significant prefix."""
        fix = tjl_fixtures["tjl_09_source_choch_eligibility_invalidation_and_gap"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )

        candles = adapt_candles(fix["candles"])
        # Process prefixes 0 through 8: Bullish structure
        for c in candles[:8]:
            coord.process_candle(c)

        # 1. Prefix 7: Bullish Set 1 created and active
        s7 = coord.get_snapshot()
        assert s7.current_eligible_set is not None
        assert s7.current_eligible_set.set_id == "SET_1"
        assert s7.current_eligible_set.fingerprint == ("ENGINE_EURUSD_H1", "UPWARD", 1, 4, 5)
        assert s7.direction == Direction.UPWARD
        assert s7.structural_epoch == 0

        # Prefix 8: Retains Set 1
        s8 = coord.process_candle(candles[8])
        assert s8.current_eligible_set == s7.current_eligible_set

        # 2. Prefix 9: Bearish CHOCH Confirmation & Invalidation
        s9 = coord.process_candle(candles[9])
        assert s9.direction == Direction.DOWNWARD
        assert s9.structural_epoch == 1
        assert s9.current_eligible_set is None
        assert s9.outgoing_cancellation_intent is True
        assert s9.last_transition is not None
        assert s9.last_transition.transition_type == TJLTransitionType.CHOCH_INVALIDATION
        assert s9.last_transition.outgoing_cancelled_set_id == "SET_1"
        assert s9.last_transition.outgoing_cancelled_fingerprint == ("ENGINE_EURUSD_H1", "UPWARD", 1, 4, 5)

        # 3. Gap prefixes 10, 11, 12, 13: strictly no eligible set, idempotent no-ops, zero cancellation leakage
        last_t = candles[-1].open_time
        c10 = StrategyCandle(index=10, open_time=last_t + timedelta(hours=1), open=1.095, high=1.098, low=1.070, close=1.075, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=2))
        c11 = StrategyCandle(index=11, open_time=last_t + timedelta(hours=2), open=1.075, high=1.078, low=1.050, close=1.055, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=3))
        c12 = StrategyCandle(index=12, open_time=last_t + timedelta(hours=3), open=1.055, high=1.070, low=1.052, close=1.065, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=4))
        c13 = StrategyCandle(index=13, open_time=last_t + timedelta(hours=4), open=1.065, high=1.080, low=1.062, close=1.075, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=5))

        for gap_c in [c10, c11, c12, c13]:
            s_gap = coord.process_candle(gap_c)
            assert s_gap.current_eligible_set is None
            assert s_gap.outgoing_cancellation_intent is False
            assert s_gap.direction == Direction.DOWNWARD
            assert s_gap.structural_epoch == 1
            assert s_gap.last_transition is not None
            assert s_gap.last_transition.transition_type == TJLTransitionType.IDEMPOTENT_NO_OP
            assert s_gap.last_transition.outgoing_cancelled_set_id is None

        # 4. Prefix 14: Downward break confirming first pair in epoch 1 -> LABELS_ONLY, current_eligible_set is None
        c14 = StrategyCandle(index=14, open_time=last_t + timedelta(hours=5), open=1.075, high=1.076, low=1.040, close=1.045, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=6))
        s14 = coord.process_candle(c14)
        assert s14.current_eligible_set is None
        assert s14.outgoing_cancellation_intent is False
        assert s14.direction == Direction.DOWNWARD
        assert s14.structural_epoch == 1
        assert s14.last_transition is not None
        assert s14.last_transition.transition_type == TJLTransitionType.LABELS_ONLY
        assert len(s14.last_transition.newly_labeled_zones) == 2
        # Verify newly labeled roles: CL (candle 11) is TJL1, CH (candle 14 break resistance) is TJL2_A_PLUS
        z_cl = next(z for z in s14.last_transition.newly_labeled_zones if z.source_candle_index == 11)
        assert z_cl.label == TJLLabel.TJL1
        assert z_cl.level_id.side == TJLSide.LOW
        z_ch = next(z for z in s14.last_transition.newly_labeled_zones if z.source_candle_index == 14)
        assert z_ch.label == TJLLabel.TJL2_A_PLUS
        assert z_ch.level_id.side == TJLSide.HIGH

        # 5. Prefix 15: Pullback candle 1 (no tentative P3 yet)
        c15 = StrategyCandle(index=15, open_time=last_t + timedelta(hours=6), open=1.045, high=1.060, low=1.042, close=1.055, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=7))
        s15 = coord.process_candle(c15)
        assert s15.current_eligible_set is None
        assert s15.last_transition is not None
        assert s15.last_transition.transition_type == TJLTransitionType.IDEMPOTENT_NO_OP

        # 6. Prefix 16: Pullback candle 2 completes -> new tentative P3 identified -> FIRST_CREATION of Set 2!
        c16 = StrategyCandle(index=16, open_time=last_t + timedelta(hours=7), open=1.055, high=1.070, low=1.052, close=1.065, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=8))
        s16 = coord.process_candle(c16)
        assert s16.direction == Direction.DOWNWARD
        assert s16.structural_epoch == 1
        assert s16.outgoing_cancellation_intent is False
        assert s16.last_transition is not None
        assert s16.last_transition.transition_type == TJLTransitionType.FIRST_CREATION
        assert s16.current_eligible_set is not None

        new_set = s16.current_eligible_set
        assert new_set.set_id == "SET_2"
        assert new_set.direction == Direction.DOWNWARD
        assert new_set.fingerprint == ("ENGINE_EURUSD_H1", "DOWNWARD", 14, 11, 14)
        assert new_set.p3_source_index == 14
        assert new_set.eligibility_available_time == c16.close_time

        # Exact zone identities and geometry
        assert new_set.tjl1_zone.label == TJLLabel.TJL1
        assert new_set.tjl1_zone.source_candle_index == 11
        assert new_set.tjl1_zone.level_id.side == TJLSide.LOW
        assert new_set.tjl1_zone.lower_price == c11.low == 1.050
        assert new_set.tjl1_zone.upper_price == c11.lower_body_edge == 1.055

        assert new_set.tjl2_zone.label == TJLLabel.TJL2_A_PLUS
        assert new_set.tjl2_zone.source_candle_index == 14
        assert new_set.tjl2_zone.level_id.side == TJLSide.HIGH
        assert new_set.tjl2_zone.lower_price == c14.upper_body_edge == 1.075
        assert new_set.tjl2_zone.upper_price == c14.high == 1.076

        # Audit trail: exactly 2 historical sets preserved
        assert len(s16.historical_sets) == 2
        assert s16.historical_sets[0].set_id == "SET_1"
        assert s16.historical_sets[1].set_id == "SET_2"

        # Immutable cancellation history correctly records Set 1 cancellation at CHOCH
        choch_trans = next(t for t in s16.transition_history if t.transition_type == TJLTransitionType.CHOCH_INVALIDATION)
        assert choch_trans.outgoing_cancelled_set_id == "SET_1"
        assert choch_trans.outgoing_cancelled_fingerprint == ("ENGINE_EURUSD_H1", "UPWARD", 1, 4, 5)

    def test_failure_injection_after_main_coordinator_rollback_and_valid_retry(self, tjl_fixtures) -> None:
        """[Directive 6] Injected failure after main-coordinator advance leaves live coordinator, reducer, lookup, CHOCH count, and epoch completely untouched; retry matches reference run identically."""
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

        # Capture complete pre-failure state across ALL components
        main_coord_snap_before = coord._main_coordinator.get_snapshot()
        reducer_snap_before = coord._reducer.get_snapshot()
        tjl_snap_before = coord.get_snapshot()
        lookup_before = dict(coord._candle_lookup)
        prev_choch_count_before = coord._prev_choch_count
        reducer_epoch_before = coord._reducer.structural_epoch
        reducer_set_counter_before = coord._reducer._set_counter
        reducer_physical_levels_before = dict(coord._reducer._physical_levels)
        reducer_role_zones_before = dict(coord._reducer._role_zones)
        reducer_all_labeled_before = list(coord._reducer._all_labeled_zones)
        reducer_transition_history_before = list(coord._reducer._transition_history)

        # Monkeypatch the live reducer to simulate a failure AFTER main coordinator advance
        orig_reduce = coord._reducer.reduce

        def failing_reduce(obs):
            raise RuntimeError("Injected downstream failure after main coordinator advance")

        coord._reducer.reduce = failing_reduce

        # Attempt to deliver candle 5 -> must raise RuntimeError
        with pytest.raises(RuntimeError, match="Injected downstream failure"):
            coord.process_candle(candles[5])

        # Assert all live components are 100% complete-state identical!
        assert coord._main_coordinator.get_snapshot() == main_coord_snap_before
        assert coord._reducer.get_snapshot() == reducer_snap_before
        assert coord.get_snapshot() == tjl_snap_before
        assert coord._candle_lookup == lookup_before
        assert coord._prev_choch_count == prev_choch_count_before
        assert coord._reducer.structural_epoch == reducer_epoch_before
        assert coord._reducer._set_counter == reducer_set_counter_before
        assert coord._reducer._physical_levels == reducer_physical_levels_before
        assert coord._reducer._role_zones == reducer_role_zones_before
        assert coord._reducer._all_labeled_zones == reducer_all_labeled_before
        assert coord._reducer._transition_history == reducer_transition_history_before

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

        # Retried coordinator state matches independent clean reference run identically
        assert coord.get_snapshot() == coord_ref.get_snapshot()
        assert coord._main_coordinator.get_snapshot() == coord_ref._main_coordinator.get_snapshot()
        assert coord._reducer.get_snapshot() == coord_ref._reducer.get_snapshot()
        assert coord._candle_lookup == coord_ref._candle_lookup
        assert coord._reducer.structural_epoch == coord_ref._reducer.structural_epoch

    def test_actual_candle_driven_post_choch_recovery_decreasing_source_ids(self, tjl_fixtures) -> None:
        """[Directive 4] Repeat complete 17-candle CHOCH recovery sequence with decreasing unique source IDs and semantic time mapping."""
        fix = tjl_fixtures["tjl_09_source_choch_eligibility_invalidation_and_gap"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        candles = adapt_candles(fix["candles"])
        last_t = candles[-1].open_time
        c10 = StrategyCandle(index=10, open_time=last_t + timedelta(hours=1), open=1.095, high=1.098, low=1.070, close=1.075, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=2))
        c11 = StrategyCandle(index=11, open_time=last_t + timedelta(hours=2), open=1.075, high=1.078, low=1.050, close=1.055, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=3))
        c12 = StrategyCandle(index=12, open_time=last_t + timedelta(hours=3), open=1.055, high=1.070, low=1.052, close=1.065, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=4))
        c13 = StrategyCandle(index=13, open_time=last_t + timedelta(hours=4), open=1.065, high=1.080, low=1.062, close=1.075, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=5))
        c14 = StrategyCandle(index=14, open_time=last_t + timedelta(hours=5), open=1.075, high=1.076, low=1.040, close=1.045, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=6))
        c15 = StrategyCandle(index=15, open_time=last_t + timedelta(hours=6), open=1.045, high=1.060, low=1.042, close=1.055, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=7))
        c16 = StrategyCandle(index=16, open_time=last_t + timedelta(hours=7), open=1.055, high=1.070, low=1.052, close=1.065, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=last_t + timedelta(hours=8))

        full_sequence = candles + [c10, c11, c12, c13, c14, c15, c16]

        # Map to strictly decreasing IDs: 900, 890, 880, ... 740
        decreasing_candles = []
        for i, c in enumerate(full_sequence):
            decreasing_candles.append(StrategyCandle(
                index=900 - (i * 10),
                open_time=c.open_time,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
                close_time=c.close_time,
            ))

        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        snaps = coord.replay_candles(decreasing_candles)

        # 1. Prefix 7 (ID 830, time of candle 7): Set 1 created
        s7 = snaps[7]
        assert s7.current_eligible_set is not None
        assert s7.current_eligible_set.set_id == "SET_1"
        assert s7.current_eligible_set.fingerprint == ("ENGINE_EURUSD_H1", "UPWARD", 890, 860, 850)
        assert s7.current_eligible_set.tjl1_zone.level_id.source_open_time == candles[1].open_time
        assert s7.current_eligible_set.tjl2_zone.level_id.source_open_time == candles[4].open_time

        # 2. Prefix 9 (ID 810, time of candle 9): CHOCH Invalidation
        s9 = snaps[9]
        assert s9.direction == Direction.DOWNWARD
        assert s9.structural_epoch == 1
        assert s9.current_eligible_set is None
        assert s9.outgoing_cancellation_intent is True
        assert s9.last_transition.outgoing_cancelled_set_id == "SET_1"
        assert s9.last_transition.outgoing_cancelled_fingerprint == ("ENGINE_EURUSD_H1", "UPWARD", 890, 860, 850)

        # 3. Gap prefixes 10–13: No eligible sets
        for k in range(10, 14):
            assert snaps[k].current_eligible_set is None
            assert snaps[k].outgoing_cancellation_intent is False

        # 4. Prefix 14 (ID 760): First pair in epoch 1 -> LABELS_ONLY
        s14 = snaps[14]
        assert s14.current_eligible_set is None
        assert s14.last_transition.transition_type == TJLTransitionType.LABELS_ONLY
        assert len(s14.last_transition.newly_labeled_zones) == 2

        # 5. Prefix 16 (ID 740): Bearish Set 2 created with exact semantic roles and prices!
        s16 = snaps[16]
        assert s16.current_eligible_set is not None
        new_set = s16.current_eligible_set
        assert new_set.set_id == "SET_2"
        assert new_set.direction == Direction.DOWNWARD
        assert new_set.fingerprint == ("ENGINE_EURUSD_H1", "DOWNWARD", 760, 790, 760)
        # Roles and prices are semantically identical to the normal-ID run
        assert new_set.tjl1_zone.label == TJLLabel.TJL1
        assert new_set.tjl1_zone.level_id.side == TJLSide.LOW
        assert new_set.tjl1_zone.lower_price == 1.050
        assert new_set.tjl1_zone.upper_price == 1.055
        assert new_set.tjl1_zone.level_id.source_open_time == c11.open_time

        assert new_set.tjl2_zone.label == TJLLabel.TJL2_A_PLUS
        assert new_set.tjl2_zone.level_id.side == TJLSide.HIGH
        assert new_set.tjl2_zone.lower_price == 1.075
        assert new_set.tjl2_zone.upper_price == 1.076
        assert new_set.tjl2_zone.level_id.source_open_time == c14.open_time

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
        """[Directive 5] Compare fresh-batch, sequential, and replay outputs at every prefix across continuation replacement and CHOCH recovery, with known and unknown availability."""
        # Case A: Continuation replacement (Bearish lifecycle tjl_06)
        fix_06 = tjl_fixtures["tjl_06_pullback_t2_replacement_and_cancellation_intent"]
        candles_06 = adapt_candles(fix_06["candles"])
        start_06 = datetime.fromisoformat(fix_06["start_candle_time"])

        coord_seq_06 = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_06),
            symbol_feed_id="FEED_GBPUSD_H1", source_timeframe="H1", source_engine_id="ENGINE_GBPUSD_H1",
        )
        coord_replay_06 = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_06),
            symbol_feed_id="FEED_GBPUSD_H1", source_timeframe="H1", source_engine_id="ENGINE_GBPUSD_H1",
        )
        replays_06 = coord_replay_06.replay_candles(candles_06)

        for k in range(len(candles_06)):
            seq_snap = coord_seq_06.process_candle(candles_06[k])
            replay_snap = replays_06[k]
            # Fresh batch coordinator at this exact prefix
            batch_coord = TJLCoordinator(
                config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_06),
                symbol_feed_id="FEED_GBPUSD_H1", source_timeframe="H1", source_engine_id="ENGINE_GBPUSD_H1",
            )
            batch_snap = batch_coord.process_candles(candles_06[:k+1])
            assert seq_snap == replay_snap == batch_snap

        # Case B: CHOCH recovery with unknown close availability (close_time = None)
        fix_09 = tjl_fixtures["tjl_09_source_choch_eligibility_invalidation_and_gap"]
        start_09 = datetime.fromisoformat(fix_09["start_candle_time"])
        candles_09 = adapt_candles(fix_09["candles"])
        last_t = candles_09[-1].open_time
        c10 = StrategyCandle(index=10, open_time=last_t + timedelta(hours=1), open=1.095, high=1.098, low=1.070, close=1.075, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=None)
        c11 = StrategyCandle(index=11, open_time=last_t + timedelta(hours=2), open=1.075, high=1.078, low=1.050, close=1.055, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=None)
        c12 = StrategyCandle(index=12, open_time=last_t + timedelta(hours=3), open=1.055, high=1.070, low=1.052, close=1.065, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=None)
        c13 = StrategyCandle(index=13, open_time=last_t + timedelta(hours=4), open=1.065, high=1.080, low=1.062, close=1.075, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=None)
        c14 = StrategyCandle(index=14, open_time=last_t + timedelta(hours=5), open=1.075, high=1.076, low=1.040, close=1.045, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=None)
        c15 = StrategyCandle(index=15, open_time=last_t + timedelta(hours=6), open=1.045, high=1.060, low=1.042, close=1.055, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=None)
        c16 = StrategyCandle(index=16, open_time=last_t + timedelta(hours=7), open=1.055, high=1.070, low=1.052, close=1.065, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=None)

        # Strip close_time across all candles to test unknown availability prefix consistency
        recovery_seq_unknown = [
            StrategyCandle(index=c.index, open_time=c.open_time, open=c.open, high=c.high, low=c.low, close=c.close, is_forming=False, bar_status="CONFIRMED_COMPLETED", close_time=None)
            for c in (candles_09 + [c10, c11, c12, c13, c14, c15, c16])
        ]

        coord_seq_rec = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_09),
            symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1", source_engine_id="ENGINE_EURUSD_H1",
        )
        coord_replay_rec = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_09),
            symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1", source_engine_id="ENGINE_EURUSD_H1",
        )
        replays_rec = coord_replay_rec.replay_candles(recovery_seq_unknown)

        for k in range(len(recovery_seq_unknown)):
            seq_snap = coord_seq_rec.process_candle(recovery_seq_unknown[k])
            replay_snap = replays_rec[k]
            batch_coord = TJLCoordinator(
                config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_09),
                symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1", source_engine_id="ENGINE_EURUSD_H1",
            )
            batch_snap = batch_coord.process_candles(recovery_seq_unknown[:k+1])
            assert seq_snap == replay_snap == batch_snap

    def test_forming_bar_leaves_completed_candle_state_unchanged(
        self, tjl_fixtures: Mapping[str, Any]
    ) -> None:
        """[HANDOFF-043] Forming bar receipt causes zero mutations to live completed-candle state."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        candles = adapt_candles(fix["candles"])
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        snap_completed = coord.process_candles(candles[:8])
        assert snap_completed.current_eligible_set is not None

        # Deliver a forming candle (is_forming=True, bar_status="FORMING")
        forming_candle = StrategyCandle(
            index=candles[7].index + 1,
            open_time=candles[7].open_time + timedelta(hours=1),
            open=1.146,
            high=1.160,
            low=1.144,
            close=1.158,
            is_forming=True,
            bar_status="FORMING",
        )
        snap_after_forming = coord.process_candle(forming_candle)
        assert snap_after_forming == snap_completed
        assert coord.get_snapshot() == snap_completed

    def test_fresh_batch_failure_preserves_previous_live_state(
        self, tjl_fixtures: Mapping[str, Any]
    ) -> None:
        """[HANDOFF-043] Failure in fresh-batch process_candles preserves previous live state 100% untouched."""
        fix = tjl_fixtures["tjl_01_bullish_basic_end_to_end"]
        candles = adapt_candles(fix["candles"])
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        snap_live = coord.process_candles(candles[:6])
        assert coord.get_snapshot() == snap_live

        # Attempt batch with invalid data that causes mid-batch failure (non-chronological open_time)
        bad_candles = list(candles[:6]) + [
            StrategyCandle(
                index=99,
                open_time=candles[2].open_time,  # Non-chronological open_time!
                open=1.130,
                high=1.140,
                low=1.120,
                close=1.135,
                is_forming=False,
                bar_status="CONFIRMED_COMPLETED",
            )
        ]
        with pytest.raises(Exception):
            coord.process_candles(bad_candles)

        # Assert live state completely preserved
        assert coord.get_snapshot() == snap_live
