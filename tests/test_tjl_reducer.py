"""Unit tests for the pure Trend Joining Level (TJL) lifecycle reducer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from aladeen.strategy.types import Direction, StrategyCandle, SwingPoint
from aladeen.strategy.tjl_reducer import TJLReducer
from aladeen.strategy.tjl_types import (
    CurrentEligibleSet,
    StableLevelId,
    TJLFingerprint,
    TJLLabel,
    TJLSide,
    TJLStructuralObservation,
    TJLTransitionType,
    TJLZone,
)


def _make_candle(
    index: int,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    open_time: datetime,
) -> StrategyCandle:
    return StrategyCandle(
        index=index,
        open_time=open_time,
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        is_forming=False,
        bar_status="CONFIRMED_COMPLETED",
    )


class TestTJLReducer:
    """Rigorous tests for the pure TJL lifecycle reducer."""

    def test_labels_before_first_set_creation(self) -> None:
        """Confirmed points receive labels and zones, but current set is None when P3 is absent."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))

        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)

        obs = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=4,
            candle_open_time=c4.open_time,
            availability_time=t0 + timedelta(hours=5),
            ch_point=ch,
            cl_point=cl,
            tentative_p3=None,  # Not yet found!
            source_candle_lookup={1: c1, 4: c4},
            observation_event_pos=4,
            pair_confirmation_event_pos=4,
        )

        snap = reducer.reduce(obs)
        assert snap.current_eligible_set is None
        assert snap.outgoing_cancellation_intent is False
        assert len(snap.all_labeled_zones) == 2
        assert snap.last_transition is not None
        assert snap.last_transition.transition_type == TJLTransitionType.LABELS_ONLY

        # Bullish: CH is TJL1, CL is TJL2
        z_tjl1 = next(z for z in snap.all_labeled_zones if z.label == TJLLabel.TJL1)
        z_tjl2 = next(z for z in snap.all_labeled_zones if z.label == TJLLabel.TJL2_A_PLUS)
        assert z_tjl1.source_candle_index == 1
        assert z_tjl2.source_candle_index == 4

    def test_first_set_creation_and_timing_preservation(self) -> None:
        """First set is created when CH, CL, and active P3 are present; preserves None when availability is unknown."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.155, t0 + timedelta(hours=5))
        c7 = _make_candle(7, 1.145, 1.150, 1.142, 1.146, t0 + timedelta(hours=7))

        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)

        # Observation with unknown availability time (availability_time=None)
        obs = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=7,
            candle_open_time=c7.open_time,
            availability_time=None,  # Unknown close time!
            ch_point=ch,
            cl_point=cl,
            tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5, 7: c7},
            observation_event_pos=7,
            pair_confirmation_event_pos=4,
            p3_identification_event_pos=7,
        )

        snap = reducer.reduce(obs)
        assert snap.current_eligible_set is not None
        curr = snap.current_eligible_set
        assert curr.set_id == "SET_1"
        assert curr.fingerprint == ("ENGINE_TEST", "UPWARD", 1, 4, 5)
        # Critical regression check: availability_time MUST remain None, NOT open_time!
        assert curr.eligibility_available_time is None
        assert snap.outgoing_cancellation_intent is False
        assert snap.last_transition.transition_type == TJLTransitionType.FIRST_CREATION

    def test_t1_continuation_retains_current_set(self) -> None:
        """At t1 continuation break, newly confirmed points receive labels, but previous current set is retained."""
        reducer = TJLReducer("ENGINE_GBP", "FEED_GBP", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c2 = _make_candle(2, 1.190, 1.192, 1.180, 1.185, t0 + timedelta(hours=2))
        c4 = _make_candle(4, 1.195, 1.205, 1.194, 1.200, t0 + timedelta(hours=4))
        c7 = _make_candle(7, 1.150, 1.152, 1.139, 1.140, t0 + timedelta(hours=7))

        ch1 = SwingPoint(price=1.200, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=5)
        cl1 = SwingPoint(price=1.185, candle_index=2, candle_open_time=c2.open_time, identified_bar_index=2, confirmed_bar_index=5)
        p3_1 = SwingPoint(price=1.140, candle_index=7, candle_open_time=c7.open_time, identified_bar_index=9)

        # 1. Bar 9: First set created
        obs1 = TJLStructuralObservation(
            source_engine_id="ENGINE_GBP",
            symbol_feed_id="FEED_GBP",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=9,
            candle_open_time=t0 + timedelta(hours=9),
            availability_time=t0 + timedelta(hours=10),
            ch_point=ch1,
            cl_point=cl1,
            tentative_p3=p3_1,
            source_candle_lookup={2: c2, 4: c4, 7: c7},
            observation_event_pos=9,
            pair_confirmation_event_pos=5,
            p3_identification_event_pos=9,
        )
        snap1 = reducer.reduce(obs1)
        assert snap1.current_eligible_set is not None
        assert snap1.current_eligible_set.fingerprint == ("ENGINE_GBP", "DOWNWARD", 4, 2, 7)

        # 2. Bar 14: Continuation break confirms new pair (CH=13, CL=7), clears active P3 to None
        c13 = _make_candle(13, 1.160, 1.170, 1.158, 1.168, t0 + timedelta(hours=13))
        ch2 = SwingPoint(price=1.168, candle_index=13, candle_open_time=c13.open_time, identified_bar_index=13, confirmed_bar_index=14)
        cl2 = SwingPoint(price=1.140, candle_index=7, candle_open_time=c7.open_time, identified_bar_index=7, confirmed_bar_index=14)

        obs2 = TJLStructuralObservation(
            source_engine_id="ENGINE_GBP",
            symbol_feed_id="FEED_GBP",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=14,
            candle_open_time=t0 + timedelta(hours=14),
            availability_time=t0 + timedelta(hours=15),
            ch_point=ch2,
            cl_point=cl2,
            tentative_p3=None,  # Cleared by continuation!
            source_candle_lookup={2: c2, 4: c4, 7: c7, 13: c13},
            observation_event_pos=14,
            pair_confirmation_event_pos=14,
        )
        snap2 = reducer.reduce(obs2)
        # Previous set is RETAINED!
        assert snap2.current_eligible_set is not None
        assert snap2.current_eligible_set.fingerprint == ("ENGINE_GBP", "DOWNWARD", 4, 2, 7)
        assert snap2.outgoing_cancellation_intent is False
        assert snap2.last_transition.transition_type == TJLTransitionType.CONTINUATION_RETAINED
        assert len(snap2.all_labeled_zones) == 4

    def test_t2_pullback_replacement_and_outgoing_set_identification(self) -> None:
        """At t2 pullback completion, replacement emits outgoing cancellation identifying outgoing set ID and fingerprint."""
        reducer = TJLReducer("ENGINE_GBP", "FEED_GBP", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c2 = _make_candle(2, 1.190, 1.192, 1.180, 1.185, t0 + timedelta(hours=2))
        c4 = _make_candle(4, 1.195, 1.205, 1.194, 1.200, t0 + timedelta(hours=4))
        c7 = _make_candle(7, 1.150, 1.152, 1.139, 1.140, t0 + timedelta(hours=7))
        c13 = _make_candle(13, 1.160, 1.170, 1.158, 1.168, t0 + timedelta(hours=13))
        c14 = _make_candle(14, 1.140, 1.142, 1.131, 1.132, t0 + timedelta(hours=14))

        ch1 = SwingPoint(price=1.200, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=5)
        cl1 = SwingPoint(price=1.185, candle_index=2, candle_open_time=c2.open_time, identified_bar_index=2, confirmed_bar_index=5)
        p3_1 = SwingPoint(price=1.140, candle_index=7, candle_open_time=c7.open_time, identified_bar_index=9)

        # Set 1 at Bar 9
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_GBP",
            symbol_feed_id="FEED_GBP",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=9,
            candle_open_time=t0 + timedelta(hours=9),
            availability_time=t0 + timedelta(hours=10),
            ch_point=ch1,
            cl_point=cl1,
            tentative_p3=p3_1,
            source_candle_lookup={2: c2, 4: c4, 7: c7},
            observation_event_pos=9,
            pair_confirmation_event_pos=5,
            p3_identification_event_pos=9,
        ))

        # Continuation at Bar 14
        ch2 = SwingPoint(price=1.168, candle_index=13, candle_open_time=c13.open_time, identified_bar_index=13, confirmed_bar_index=14)
        cl2 = SwingPoint(price=1.140, candle_index=7, candle_open_time=c7.open_time, identified_bar_index=7, confirmed_bar_index=14)
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_GBP",
            symbol_feed_id="FEED_GBP",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=14,
            candle_open_time=t0 + timedelta(hours=14),
            availability_time=t0 + timedelta(hours=15),
            ch_point=ch2,
            cl_point=cl2,
            tentative_p3=None,
            source_candle_lookup={2: c2, 4: c4, 7: c7, 13: c13},
            observation_event_pos=14,
            pair_confirmation_event_pos=14,
        ))

        # Pullback complete at Bar 16, identifying new P3 at Bar 14
        p3_2 = SwingPoint(price=1.132, candle_index=14, candle_open_time=c14.open_time, identified_bar_index=16)
        t16 = t0 + timedelta(hours=16)
        snap = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_GBP",
            symbol_feed_id="FEED_GBP",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=16,
            candle_open_time=t16,
            availability_time=t16 + timedelta(hours=1),
            ch_point=ch2,
            cl_point=cl2,
            tentative_p3=p3_2,
            source_candle_lookup={2: c2, 4: c4, 7: c7, 13: c13, 14: c14},
            observation_event_pos=16,
            pair_confirmation_event_pos=14,
            p3_identification_event_pos=16,
        ))

        assert snap.current_eligible_set is not None
        assert snap.current_eligible_set.set_id == "SET_2"
        assert snap.current_eligible_set.fingerprint == ("ENGINE_GBP", "DOWNWARD", 13, 7, 14)
        assert snap.outgoing_cancellation_intent is True
        assert snap.last_transition.transition_type == TJLTransitionType.SET_REPLACEMENT
        assert snap.last_transition.outgoing_cancelled_set_id == "SET_1"
        assert snap.last_transition.outgoing_cancelled_fingerprint == ("ENGINE_GBP", "DOWNWARD", 4, 2, 7)

    def test_cross_direction_same_level_role_assignment(self) -> None:
        """[Finding 3 Regression] Reusing a stable physical level in an opposite direction assigns the correct new contextual role."""
        reducer = TJLReducer("ENGINE_CROSS", "FEED_CROSS", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.155, t0 + timedelta(hours=5))

        # 1. UPWARD structure: CH Bar 1 is TJL1
        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)

        snap1 = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_CROSS",
            symbol_feed_id="FEED_CROSS",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=7,
            candle_open_time=t0 + timedelta(hours=7),
            availability_time=t0 + timedelta(hours=8),
            ch_point=ch,
            cl_point=cl,
            tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5},
            observation_event_pos=7,
            pair_confirmation_event_pos=4,
            p3_identification_event_pos=7,
        ))
        assert snap1.current_eligible_set.tjl1_zone.level_id == ["FEED_CROSS", "H1", c1.open_time.isoformat(), "HIGH"]
        assert snap1.current_eligible_set.tjl1_zone.label == TJLLabel.TJL1

        # 2. CHOCH event to DOWNWARD at Bar 9
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_CROSS",
            symbol_feed_id="FEED_CROSS",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=9,
            candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True,
            new_choch_direction=Direction.DOWNWARD,
            observation_event_pos=9,
        ))

        # 3. DOWNWARD structure: candle 1 is confirmed as Lower Resistance (CH) in DOWNWARD -> receives TJL2_A_PLUS role!
        c10 = _make_candle(10, 1.090, 1.095, 1.080, 1.085, t0 + timedelta(hours=10))
        c12 = _make_candle(12, 1.070, 1.075, 1.060, 1.065, t0 + timedelta(hours=12))
        ch_down = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=10, confirmed_time=t0 + timedelta(hours=10))
        cl_down = SwingPoint(price=1.085, candle_index=10, candle_open_time=c10.open_time, identified_bar_index=10, confirmed_bar_index=10, confirmed_time=t0 + timedelta(hours=10))
        p3_down = SwingPoint(price=1.065, candle_index=12, candle_open_time=c12.open_time, identified_bar_index=14)

        snap2 = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_CROSS",
            symbol_feed_id="FEED_CROSS",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=14,
            candle_open_time=t0 + timedelta(hours=14),
            availability_time=t0 + timedelta(hours=15),
            structural_epoch=1,
            epoch_choch_event_pos=9,
            pair_confirmation_event_pos=10,
            p3_identification_event_pos=14,
            ch_point=ch_down,
            cl_point=cl_down,
            tentative_p3=p3_down,
            source_candle_lookup={1: c1, 10: c10, 12: c12},
            observation_event_pos=14,
        ))

        # In DOWNWARD, CH is TJL2_A_PLUS, while preserving the exact identical level_id!
        set_down = snap2.current_eligible_set
        assert set_down is not None
        assert set_down.tjl2_zone.level_id == ["FEED_CROSS", "H1", c1.open_time.isoformat(), "HIGH"]
        assert set_down.tjl2_zone.label == TJLLabel.TJL2_A_PLUS  # Re-labeled contextually!
        assert set_down.tjl2_zone.level_id == snap1.current_eligible_set.tjl1_zone.level_id

    def test_unresolved_receipt_does_not_reemit_cancellation(self) -> None:
        """[Finding 6 Regression] Unresolved receipt immediately following set replacement does not expose stale cancellation."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.155, t0 + timedelta(hours=5))

        # 1. Set 1 at Bar 7
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=7,
            candle_open_time=t0 + timedelta(hours=7),
            availability_time=t0 + timedelta(hours=8),
            ch_point=SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4),
            cl_point=SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4),
            tentative_p3=SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7),
            source_candle_lookup={1: c1, 4: c4, 5: c5},
            observation_event_pos=7,
            pair_confirmation_event_pos=4,
            p3_identification_event_pos=7,
        ))

        # 2. CHOCH event at Bar 9 emits cancellation
        snap_choch = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=9,
            candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True,
            new_choch_direction=Direction.DOWNWARD,
            observation_event_pos=9,
        ))
        assert snap_choch.outgoing_cancellation_intent is True

        # 3. Subsequent unresolved observation at Bar 10 MUST NOT expose stale cancellation intent!
        snap_unres = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=10,
            candle_open_time=t0 + timedelta(hours=10),
            structural_epoch=1,
            epoch_choch_event_pos=9,
            observation_event_pos=10,
            is_unresolved=True,
            unresolved_diagnostic="CHOCH_AMBIGUITY",
        ))
        assert snap_unres.outgoing_cancellation_intent is False
        assert snap_unres.last_transition.outgoing_cancellation_intent is False

    def test_spontaneous_direction_change_rejected(self) -> None:
        """[Finding 5 Regression] Direction changes without is_choch_event=True are strictly rejected."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))

        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=1,
            candle_open_time=t0 + timedelta(hours=1),
            source_candle_lookup={1: c1},
            observation_event_pos=1,
        ))

        # Deliver next candle with opposite direction but is_choch_event=False
        with pytest.raises(ValueError, match="Direction changed spontaneously"):
            reducer.reduce(TJLStructuralObservation(
                source_engine_id="ENGINE_TEST",
                symbol_feed_id="FEED_TEST",
                source_timeframe="H1",
                direction=Direction.DOWNWARD,
                candle_index=2,
                candle_open_time=t0 + timedelta(hours=2),
                is_choch_event=False,
                source_candle_lookup={1: c1},
                observation_event_pos=2,
            ))

    def test_conflicting_physical_geometry_rejected(self) -> None:
        """[Finding 4 Regression] Conflicting geometry for an already cached StableLevelId raises ValueError without mutating state."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))

        ch1 = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=1)
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=1,
            candle_open_time=c1.open_time,
            ch_point=ch1,
            source_candle_lookup={1: c1},
            observation_event_pos=1,
            pair_confirmation_event_pos=1,
        ))

        # Deliver a conflicting candle at candle_index=2 claiming the SAME open_time but different high!
        c1_conflicting = _make_candle(2, 1.130, 1.150, 1.129, 1.135, c1.open_time)
        ch_conflict = SwingPoint(price=1.135, candle_index=2, candle_open_time=c1.open_time, identified_bar_index=2, confirmed_bar_index=2)

        with pytest.raises(ValueError, match="Conflicting physical level geometry"):
            reducer.reduce(TJLStructuralObservation(
                source_engine_id="ENGINE_TEST",
                symbol_feed_id="FEED_TEST",
                source_timeframe="H1",
                direction=Direction.UPWARD,
                candle_index=2,
                candle_open_time=t0 + timedelta(hours=2),
                ch_point=ch_conflict,
                source_candle_lookup={2: c1_conflicting},
                observation_event_pos=2,
                pair_confirmation_event_pos=2,
            ))

    def test_epoch_timestamp_guard_rejects_pre_choch_points(self) -> None:
        """[Finding 1 Regression] Post-CHOCH structure rejects pre-CHOCH confirmed points based on chronological timestamps, not ID arithmetic."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))

        # 1. Bullish at Bar 4
        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4, confirmed_time=t0 + timedelta(hours=4))
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4, confirmed_time=t0 + timedelta(hours=4))
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=4,
            candle_open_time=c4.open_time,
            ch_point=ch,
            cl_point=cl,
            source_candle_lookup={1: c1, 4: c4},
            observation_event_pos=4,
            pair_confirmation_event_pos=4,
        ))

        # 2. CHOCH to DOWNWARD at Bar 9 (open_time = t0 + 9h)
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=9,
            candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True,
            new_choch_direction=Direction.DOWNWARD,
            observation_event_pos=9,
        ))

        # 3. Post-CHOCH observation at Bar 10 with mismatched structural_epoch=0 is rejected fail-closed
        with pytest.raises(ValueError, match="does not match reducer epoch"):
            reducer.reduce(TJLStructuralObservation(
                source_engine_id="ENGINE_TEST",
                symbol_feed_id="FEED_TEST",
                source_timeframe="H1",
                direction=Direction.DOWNWARD,
                candle_index=10,
                candle_open_time=t0 + timedelta(hours=10),
                structural_epoch=0,  # Mismatch!
                source_candle_lookup={4: c4},
                observation_event_pos=10,
            ))

        # 4. Post-CHOCH observation at Bar 10 with structural_epoch=1 attempts to use CL confirmed at pos 4 (pre-CHOCH confirmation <= 9)
        with pytest.raises(ValueError, match="cannot be used in structural epoch"):
            reducer.reduce(TJLStructuralObservation(
                source_engine_id="ENGINE_TEST",
                symbol_feed_id="FEED_TEST",
                source_timeframe="H1",
                direction=Direction.DOWNWARD,
                candle_index=10,
                candle_open_time=t0 + timedelta(hours=10),
                structural_epoch=1,
                epoch_choch_event_pos=9,
                observation_event_pos=10,
                pair_confirmation_event_pos=4,
                cl_point=cl,
                source_candle_lookup={4: c4},
            ))

    def test_arbitrary_decreasing_source_ids_supported(self) -> None:
        """[Directive 6.C] Supports arbitrary or strictly decreasing unique source candle IDs purely via chronological timestamps."""
        reducer = TJLReducer("ENGINE_DESC", "FEED_DESC", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        # Candle IDs decreasing: 500 -> 400 -> 300 -> 200
        c_high = _make_candle(500, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c_low = _make_candle(400, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c_p3 = _make_candle(300, 1.140, 1.155, 1.139, 1.155, t0 + timedelta(hours=5))
        c_bar7 = _make_candle(200, 1.145, 1.150, 1.142, 1.146, t0 + timedelta(hours=7))

        ch = SwingPoint(price=1.135, candle_index=500, candle_open_time=c_high.open_time, identified_bar_index=500, confirmed_bar_index=400)
        cl = SwingPoint(price=1.105, candle_index=400, candle_open_time=c_low.open_time, identified_bar_index=400, confirmed_bar_index=400)
        p3 = SwingPoint(price=1.155, candle_index=300, candle_open_time=c_p3.open_time, identified_bar_index=200)

        snap = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_DESC",
            symbol_feed_id="FEED_DESC",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=200,
            candle_open_time=c_bar7.open_time,
            availability_time=t0 + timedelta(hours=8),
            ch_point=ch,
            cl_point=cl,
            tentative_p3=p3,
            source_candle_lookup={500: c_high, 400: c_low, 300: c_p3, 200: c_bar7},
            observation_event_pos=3,
            pair_confirmation_event_pos=1,
            p3_identification_event_pos=3,
        ))

        assert snap.current_eligible_set is not None
        assert snap.current_eligible_set.fingerprint == ("ENGINE_DESC", "UPWARD", 500, 400, 300)
        assert snap.current_eligible_set.tjl1_zone.source_candle_index == 500
        assert snap.current_eligible_set.tjl2_zone.source_candle_index == 400

    def test_transition_history_retained_and_immutable(self) -> None:
        """[Directive 5] Transition history preserves full audit log across creation, retention, replacement, and invalidation."""
        reducer = TJLReducer("ENGINE_AUDIT", "FEED_AUDIT", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.155, t0 + timedelta(hours=5))

        # 1. First set at Bar 7
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_AUDIT",
            symbol_feed_id="FEED_AUDIT",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=7,
            candle_open_time=t0 + timedelta(hours=7),
            ch_point=SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4),
            cl_point=SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4),
            tentative_p3=SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7),
            source_candle_lookup={1: c1, 4: c4, 5: c5},
            observation_event_pos=7,
            pair_confirmation_event_pos=4,
            p3_identification_event_pos=7,
        ))

        # 2. CHOCH at Bar 9
        snap = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_AUDIT",
            symbol_feed_id="FEED_AUDIT",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=9,
            candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True,
            new_choch_direction=Direction.DOWNWARD,
            observation_event_pos=9,
        ))

        assert len(snap.transition_history) == 2
        assert snap.transition_history[0].transition_type == TJLTransitionType.FIRST_CREATION
        assert snap.transition_history[1].transition_type == TJLTransitionType.CHOCH_INVALIDATION
        assert snap.transition_history[1].outgoing_cancelled_set_id == "SET_1"

    # =========================================================================
    # [HANDOFF-042 Targeted Regression Tests]
    # =========================================================================

    def test_current_epoch_envelope_stale_points_confirmed_time_none_rejected(self) -> None:
        """[Directive 3.1] Current epoch envelope with stale points where confirmed_time=None is rejected without mutation."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))

        # Bar 4 Bullish Pair
        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=4, candle_open_time=c4.open_time,
            ch_point=ch, cl_point=cl, source_candle_lookup={1: c1, 4: c4},
            observation_event_pos=4, pair_confirmation_event_pos=4,
        ))

        # Bar 9 CHOCH to DOWNWARD -> epoch advances to 1, epoch_choch_event_pos=9
        snap_choch = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=9, candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True, new_choch_direction=Direction.DOWNWARD, observation_event_pos=9,
        ))
        assert reducer.structural_epoch == 1

        # Bar 12: Caller passes structural_epoch=1 but stale points confirmed at event pos 4 (<= 9), confirmed_time=None!
        ch_stale = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4, confirmed_time=None)
        cl_stale = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4, confirmed_time=None)
        
        c12 = _make_candle(12, 1.090, 1.095, 1.085, 1.088, t0 + timedelta(hours=12))
        obs_bad = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.DOWNWARD, candle_index=12, candle_open_time=c12.open_time,
            structural_epoch=1, epoch_choch_event_pos=9, observation_event_pos=12,
            pair_confirmation_event_pos=4,  # Stale event pos <= CHOCH event pos 9!
            ch_point=ch_stale, cl_point=cl_stale, source_candle_lookup={1: c1, 4: c4, 12: c12},
        )

        with pytest.raises(ValueError, match="cannot be used in structural epoch"):
            reducer.reduce(obs_bad)

        # Verify reducer state was NOT mutated
        assert reducer.structural_epoch == 1
        assert reducer.get_snapshot().current_eligible_set is None
        assert len(reducer.get_snapshot().transition_history) == len(snap_choch.transition_history)

    def test_current_epoch_envelope_stale_p3_identification_rejected(self) -> None:
        """[Directive 3.2] Current epoch envelope with stale P3 identification is rejected without mutation."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.155, t0 + timedelta(hours=5))

        # Bar 4 Bullish Pair
        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=4, candle_open_time=c4.open_time,
            ch_point=ch, cl_point=cl, source_candle_lookup={1: c1, 4: c4},
            observation_event_pos=4, pair_confirmation_event_pos=4,
        ))

        # Bar 9 CHOCH -> epoch 1, epoch_choch_event_pos=9
        snap_choch = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=9, candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True, new_choch_direction=Direction.DOWNWARD, observation_event_pos=9,
        ))

        # Bar 14: Valid post-CHOCH confirmed pair (pos 12 > 9), but stale P3 identified at pos 7 (<= 9)
        c10 = _make_candle(10, 1.090, 1.095, 1.080, 1.095, t0 + timedelta(hours=10))
        c11 = _make_candle(11, 1.070, 1.075, 1.060, 1.065, t0 + timedelta(hours=11))
        c14 = _make_candle(14, 1.050, 1.055, 1.045, 1.048, t0 + timedelta(hours=14))
        ch_new = SwingPoint(price=1.095, candle_index=10, candle_open_time=c10.open_time, identified_bar_index=10, confirmed_bar_index=12)
        cl_new = SwingPoint(price=1.065, candle_index=11, candle_open_time=c11.open_time, identified_bar_index=11, confirmed_bar_index=12)
        p3_stale = SwingPoint(price=1.140, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)

        obs_stale_p3 = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.DOWNWARD, candle_index=14, candle_open_time=c14.open_time,
            structural_epoch=1, epoch_choch_event_pos=9, observation_event_pos=14,
            pair_confirmation_event_pos=12,  # Valid post-CHOCH!
            p3_identification_event_pos=7,   # Stale pre-CHOCH identification pos 7 <= 9!
            ch_point=ch_new, cl_point=cl_new, tentative_p3=p3_stale,
            source_candle_lookup={10: c10, 11: c11, 5: c5, 14: c14},
        )

        with pytest.raises(ValueError, match="Pre-CHOCH P3 .* cannot be used in structural epoch"):
            reducer.reduce(obs_stale_p3)

        # Verify state unmutated
        assert reducer.structural_epoch == 1
        assert reducer.get_snapshot().current_eligible_set is None
        assert len(reducer.get_snapshot().transition_history) == len(snap_choch.transition_history)

    def test_event_positions_beyond_observation_rejected(self) -> None:
        """[Directive 3.3] Confirmation or identification events occurring beyond observation position are rejected."""
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)

        # Future pair confirmation event pos > observation_event_pos
        with pytest.raises(ValueError, match="pair_confirmation_event_pos .* lies beyond observation_event_pos"):
            TJLStructuralObservation(
                source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
                direction=Direction.UPWARD, candle_index=4, candle_open_time=c4.open_time,
                ch_point=ch, cl_point=cl, source_candle_lookup={1: c1, 4: c4},
                observation_event_pos=4, pair_confirmation_event_pos=5,
            )

        # Future P3 identification event pos > observation_event_pos
        p3 = SwingPoint(price=1.155, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=5)
        with pytest.raises(ValueError, match="p3_identification_event_pos .* lies beyond observation_event_pos"):
            TJLStructuralObservation(
                source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
                direction=Direction.UPWARD, candle_index=4, candle_open_time=c4.open_time,
                tentative_p3=p3, source_candle_lookup={1: c1, 4: c4},
                observation_event_pos=4, p3_identification_event_pos=6,
            )

    def test_valid_new_epoch_confirmation_of_pre_choch_source_candle_accepted(self) -> None:
        """[Directive 3.4] Valid new-epoch confirmation of a pre-CHOCH source candle is accepted cleanly."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.155, t0 + timedelta(hours=5))  # Pre-CHOCH candle!

        # 1. Bar 4 Bullish Pair
        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=4, candle_open_time=c4.open_time,
            ch_point=ch, cl_point=cl, source_candle_lookup={1: c1, 4: c4},
            observation_event_pos=4, pair_confirmation_event_pos=4,
        ))

        # 2. Bar 9 CHOCH -> epoch 1, epoch_choch_event_pos=9
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=9, candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True, new_choch_direction=Direction.DOWNWARD, observation_event_pos=9,
        ))

        # 3. Bar 16 in epoch 1: Candle 5 (pre-CHOCH origin) confirmed as Lower Resistance at Bar 14 (pos 14 > 9)!
        c11 = _make_candle(11, 1.050, 1.055, 1.045, 1.050, t0 + timedelta(hours=11))
        c15 = _make_candle(15, 1.075, 1.076, 1.069, 1.070, t0 + timedelta(hours=15))
        c16 = _make_candle(16, 1.072, 1.074, 1.060, 1.062, t0 + timedelta(hours=16))

        ch_restart = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=5, confirmed_bar_index=14)
        cl_post = SwingPoint(price=1.050, candle_index=11, candle_open_time=c11.open_time, identified_bar_index=11, confirmed_bar_index=14)
        p3_post = SwingPoint(price=1.070, candle_index=15, candle_open_time=c15.open_time, identified_bar_index=16)

        obs_valid = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.DOWNWARD, candle_index=16, candle_open_time=c16.open_time,
            structural_epoch=1, epoch_choch_event_pos=9, observation_event_pos=16,
            pair_confirmation_event_pos=14,  # Post-CHOCH confirmation event!
            p3_identification_event_pos=16,   # Post-CHOCH identification event!
            ch_point=ch_restart, cl_point=cl_post, tentative_p3=p3_post,
            source_candle_lookup={5: c5, 11: c11, 15: c15, 16: c16},
        )

        snap = reducer.reduce(obs_valid)
        assert snap.current_eligible_set is not None
        assert snap.current_eligible_set.set_id == "SET_1"
        assert snap.current_eligible_set.fingerprint == ("ENGINE_TEST", "DOWNWARD", 5, 11, 15)
        # Verify pre-CHOCH candle 5 correctly formed the TJL2 zone
        assert snap.current_eligible_set.tjl2_zone.source_candle_index == 5
        assert snap.current_eligible_set.tjl2_zone.source_candle_open_time == c5.open_time
        assert snap.current_eligible_set.tjl2_zone.upper_price == 1.155
        assert snap.current_eligible_set.tjl2_zone.lower_price == 1.155

    def test_valid_event_ordering_with_all_close_availability_unknown_accepted(self) -> None:
        """[Directive 3.5] Valid event ordering with all close availability unknown is accepted structurally and preserves None availability."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        # All candles have close_time=None (unknown availability)
        c1 = StrategyCandle(index=1, open_time=t0 + timedelta(hours=1), open=1.130, high=1.140, low=1.129, close=1.135, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c4 = StrategyCandle(index=4, open_time=t0 + timedelta(hours=4), open=1.110, high=1.115, low=1.104, close=1.105, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c5 = StrategyCandle(index=5, open_time=t0 + timedelta(hours=5), open=1.140, high=1.155, low=1.139, close=1.155, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c7 = StrategyCandle(index=7, open_time=t0 + timedelta(hours=7), open=1.145, high=1.150, low=1.142, close=1.146, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")

        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)

        obs = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=7, candle_open_time=c7.open_time,
            availability_time=None,  # Unknown close availability!
            ch_point=ch, cl_point=cl, tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5, 7: c7},
            observation_event_pos=7, pair_confirmation_event_pos=4, p3_identification_event_pos=7,
        )

        snap = reducer.reduce(obs)
        assert snap.current_eligible_set is not None
        assert snap.current_eligible_set.set_id == "SET_1"
        assert snap.current_eligible_set.fingerprint == ("ENGINE_TEST", "UPWARD", 1, 4, 5)
        # Preserves None availability without fallback to open_time
        assert snap.current_eligible_set.eligibility_available_time is None
        assert snap.last_transition.transition_time is None

    def test_decreasing_unique_source_ids_with_unknown_availability_and_pre_choch_source(self) -> None:
        """[Directive 3.6] Repeat valid event ordering, unknown close availability, and pre-CHOCH origin with strictly decreasing unique source IDs."""
        reducer = TJLReducer("ENGINE_DESC_ROBUST", "FEED_DESC_ROBUST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        # Decreasing IDs: 900 -> 800 -> 700 -> 600 -> 500 -> 400 -> 300 -> 200 -> 100
        # All close_time=None
        c_p1 = StrategyCandle(index=900, open_time=t0 + timedelta(hours=1), open=1.130, high=1.140, low=1.129, close=1.135, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c_p2 = StrategyCandle(index=850, open_time=t0 + timedelta(hours=4), open=1.110, high=1.115, low=1.104, close=1.105, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c_orig = StrategyCandle(index=800, open_time=t0 + timedelta(hours=5), open=1.140, high=1.155, low=1.139, close=1.155, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")  # Pre-CHOCH source
        c_choch = StrategyCandle(index=500, open_time=t0 + timedelta(hours=9), open=1.100, high=1.102, low=1.090, close=1.092, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c_low = StrategyCandle(index=400, open_time=t0 + timedelta(hours=11), open=1.050, high=1.055, low=1.045, close=1.050, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c_p3 = StrategyCandle(index=200, open_time=t0 + timedelta(hours=15), open=1.075, high=1.076, low=1.069, close=1.070, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")
        c_obs = StrategyCandle(index=100, open_time=t0 + timedelta(hours=16), open=1.072, high=1.074, low=1.060, close=1.062, close_time=None, is_forming=False, bar_status="CONFIRMED_COMPLETED")

        # 1. Bullish epoch 0 at event pos 1 (index 850)
        ch0 = SwingPoint(price=1.135, candle_index=900, candle_open_time=c_p1.open_time, identified_bar_index=900, confirmed_bar_index=850)
        cl0 = SwingPoint(price=1.105, candle_index=850, candle_open_time=c_p2.open_time, identified_bar_index=850, confirmed_bar_index=850)
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_DESC_ROBUST", symbol_feed_id="FEED_DESC_ROBUST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=850, candle_open_time=c_p2.open_time,
            availability_time=None, ch_point=ch0, cl_point=cl0, source_candle_lookup={900: c_p1, 850: c_p2},
            observation_event_pos=1, pair_confirmation_event_pos=1,
        ))

        # 2. CHOCH to DOWNWARD at event pos 3 (index 500)
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_DESC_ROBUST", symbol_feed_id="FEED_DESC_ROBUST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=500, candle_open_time=c_choch.open_time,
            availability_time=None, is_choch_event=True, new_choch_direction=Direction.DOWNWARD,
            observation_event_pos=3,
        ))
        assert reducer.structural_epoch == 1

        # 3. Epoch 1 First Set at event pos 6 (index 100):
        # Pair (800, 400) confirmed at event pos 5 (> 3), P3 (200) identified at event pos 6 (> 3)
        ch_down = SwingPoint(price=1.155, candle_index=800, candle_open_time=c_orig.open_time, identified_bar_index=800, confirmed_bar_index=300)
        cl_down = SwingPoint(price=1.050, candle_index=400, candle_open_time=c_low.open_time, identified_bar_index=400, confirmed_bar_index=300)
        p3_down = SwingPoint(price=1.070, candle_index=200, candle_open_time=c_p3.open_time, identified_bar_index=100)

        snap = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_DESC_ROBUST", symbol_feed_id="FEED_DESC_ROBUST", source_timeframe="H1",
            direction=Direction.DOWNWARD, candle_index=100, candle_open_time=c_obs.open_time,
            availability_time=None,
            structural_epoch=1, epoch_choch_event_pos=3, observation_event_pos=6,
            pair_confirmation_event_pos=5, p3_identification_event_pos=6,
            ch_point=ch_down, cl_point=cl_down, tentative_p3=p3_down,
            source_candle_lookup={800: c_orig, 400: c_low, 200: c_p3, 100: c_obs},
        ))

        assert snap.current_eligible_set is not None
        assert snap.current_eligible_set.set_id == "SET_1"
        assert snap.current_eligible_set.fingerprint == ("ENGINE_DESC_ROBUST", "DOWNWARD", 800, 400, 200)
        assert snap.current_eligible_set.eligibility_available_time is None
        assert snap.current_eligible_set.tjl2_zone.source_candle_index == 800
        assert snap.current_eligible_set.tjl2_zone.source_candle_open_time == c_orig.open_time

    # =========================================================================
    # [HANDOFF-043 Monotonic Event-Position & Reset Regression Tests]
    # =========================================================================

    def test_repeated_observation_event_pos_rejected_with_later_timestamp(self) -> None:
        """[Directive 3.1] Repeated observation_event_pos with a later timestamp is rejected without mutation."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c2 = _make_candle(2, 1.135, 1.145, 1.134, 1.140, t0 + timedelta(hours=2))

        # Receipt 1: event_pos=1
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=1, candle_open_time=c1.open_time,
            source_candle_lookup={1: c1}, observation_event_pos=1,
        ))
        assert reducer.last_received_event_pos == 1

        # Receipt 2: open_time is later (t0 + 2h), but event_pos is repeated (1)
        obs_repeated = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=2, candle_open_time=c2.open_time,
            source_candle_lookup={2: c2}, observation_event_pos=1,
        )
        with pytest.raises(ValueError, match="Non-strictly-increasing observation_event_pos: 1 <= 1"):
            reducer.reduce(obs_repeated)

        # Assert state unmutated
        assert reducer.last_received_event_pos == 1
        assert reducer.last_processed_index == 1

    def test_decreasing_observation_event_pos_rejected_with_later_timestamp(self) -> None:
        """[Directive 3.2] Decreasing observation_event_pos with a later timestamp is rejected without mutation."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c2 = _make_candle(2, 1.135, 1.145, 1.134, 1.140, t0 + timedelta(hours=2))

        # Receipt 1: event_pos=5
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=1, candle_open_time=c1.open_time,
            source_candle_lookup={1: c1}, observation_event_pos=5,
        ))
        assert reducer.last_received_event_pos == 5

        # Receipt 2: open_time is later, but event_pos is 3 (< 5)
        obs_decreasing = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=2, candle_open_time=c2.open_time,
            source_candle_lookup={2: c2}, observation_event_pos=3,
        )
        with pytest.raises(ValueError, match="Non-strictly-increasing observation_event_pos: 3 <= 5"):
            reducer.reduce(obs_decreasing)

        assert reducer.last_received_event_pos == 5
        assert reducer.last_processed_index == 1

    def test_backward_position_choch_rejected_without_epoch_boundary_mutation(self) -> None:
        """[Directive 3.3] Backward-position CHOCH is rejected without moving the stored epoch boundary or mutating epoch."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))

        # Receipt at event pos 5
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=1, candle_open_time=c1.open_time,
            source_candle_lookup={1: c1}, observation_event_pos=5,
        ))
        assert reducer.structural_epoch == 0
        assert reducer.last_received_event_pos == 5

        # CHOCH observation claiming later open_time but backward event_pos 4!
        obs_bad_choch = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=2, candle_open_time=t0 + timedelta(hours=2),
            is_choch_event=True, new_choch_direction=Direction.DOWNWARD,
            observation_event_pos=4,
        )
        with pytest.raises(ValueError, match="Non-strictly-increasing observation_event_pos: 4 <= 5"):
            reducer.reduce(obs_bad_choch)

        # Assert epoch and epoch CHOCH boundary NOT mutated
        assert reducer.structural_epoch == 0
        assert reducer._epoch_choch_event_pos is None
        assert reducer.last_received_event_pos == 5

    def test_valid_observation_event_pos_gaps_accepted(self) -> None:
        """[Directive 3.4] Gaps in observation_event_pos are strictly accepted as long as positions are strictly increasing."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c2 = _make_candle(2, 1.135, 1.145, 1.134, 1.140, t0 + timedelta(hours=5))
        c3 = _make_candle(3, 1.140, 1.150, 1.138, 1.145, t0 + timedelta(hours=12))

        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=1, candle_open_time=c1.open_time,
            source_candle_lookup={1: c1}, observation_event_pos=0,
        ))
        assert reducer.last_received_event_pos == 0

        # Gap from 0 to 5
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=2, candle_open_time=c2.open_time,
            source_candle_lookup={2: c2}, observation_event_pos=5,
        ))
        assert reducer.last_received_event_pos == 5

        # Gap from 5 to 12
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=3, candle_open_time=c3.open_time,
            source_candle_lookup={3: c3}, observation_event_pos=12,
        ))
        assert reducer.last_received_event_pos == 12

    def test_unresolved_receipt_advances_received_order_metadata_only(self) -> None:
        """[Directive 3.5] Unresolved receipt advances received-order metadata (index, time, event_pos) without mutating live state."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))

        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=1, candle_open_time=c1.open_time,
            source_candle_lookup={1: c1}, observation_event_pos=2,
        ))

        # Unresolved receipt at event pos 6
        snap_unres = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=5, candle_open_time=t0 + timedelta(hours=5),
            is_unresolved=True, unresolved_diagnostic="GAP_AMBIGUITY",
            observation_event_pos=6,
        ))
        assert snap_unres.is_unresolved is True
        assert reducer.last_received_index == 5
        assert reducer.last_processed_index == 1  # Unmutated!
        assert reducer.last_received_event_pos == 6

        # Subsequent receipt cannot re-use event_pos <= 6
        c6 = _make_candle(6, 1.140, 1.150, 1.138, 1.145, t0 + timedelta(hours=6))
        with pytest.raises(ValueError, match="Non-strictly-increasing observation_event_pos: 6 <= 6"):
            reducer.reduce(TJLStructuralObservation(
                source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
                direction=Direction.UPWARD, candle_index=6, candle_open_time=c6.open_time,
                source_candle_lookup={6: c6}, observation_event_pos=6,
            ))

        # Receipt at pos 7 is accepted
        c7 = _make_candle(7, 1.145, 1.155, 1.140, 1.150, t0 + timedelta(hours=7))
        snap_ok = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=7, candle_open_time=c7.open_time,
            source_candle_lookup={7: c7}, observation_event_pos=7,
        ))
        assert reducer.last_received_event_pos == 7

    def test_reset_clears_all_provenance_and_matches_fresh_reference(self) -> None:
        """[Directive 3.6] reset() clears all event provenance, epoch, and position fields; reuse matches a fresh reducer."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.155, t0 + timedelta(hours=5))

        # Build Bullish set
        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)
        c7 = _make_candle(7, 1.145, 1.150, 1.142, 1.146, t0 + timedelta(hours=7))

        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=7, candle_open_time=c7.open_time,
            ch_point=ch, cl_point=cl, tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5, 7: c7},
            observation_event_pos=7, pair_confirmation_event_pos=4, p3_identification_event_pos=7,
        ))

        # CHOCH to DOWNWARD
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=9, candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True, new_choch_direction=Direction.DOWNWARD,
            observation_event_pos=9,
        ))
        assert reducer.structural_epoch == 1
        assert reducer._epoch_choch_event_pos == 9
        assert reducer.last_received_event_pos == 9

        # Call reset()
        reducer.reset()
        assert reducer.structural_epoch == 0
        assert reducer._epoch_choch_event_pos is None
        assert reducer.last_received_event_pos is None
        assert reducer.current_eligible_set is None
        assert reducer._last_choch_time is None
        assert reducer._last_choch_c2_index is None
        assert reducer._last_choch_event_time is None
        assert len(reducer.get_snapshot().transition_history) == 0

        # Feed fresh sequence to reset reducer and to a brand new reducer
        fresh_reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        fresh_obs = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST", symbol_feed_id="FEED_TEST", source_timeframe="H1",
            direction=Direction.UPWARD, candle_index=7, candle_open_time=c7.open_time,
            ch_point=ch, cl_point=cl, tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5, 7: c7},
            observation_event_pos=7, pair_confirmation_event_pos=4, p3_identification_event_pos=7,
        )
        snap_reused = reducer.reduce(fresh_obs)
        snap_fresh = fresh_reducer.reduce(fresh_obs)

        assert snap_reused == snap_fresh

