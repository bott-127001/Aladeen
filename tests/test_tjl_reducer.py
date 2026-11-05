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
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.150, t0 + timedelta(hours=5))
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
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.150, t0 + timedelta(hours=5))

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
        ))
        assert snap1.current_eligible_set.tjl1_zone.level_id == ["FEED_CROSS", "H1", c1.open_time.isoformat(), "HIGH"]
        assert snap1.current_eligible_set.tjl1_zone.label == TJLLabel.TJL1

        # 2. CHOCH event to DOWNWARD at Bar 9
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_CROSS",
            symbol_feed_id="FEED_CROSS",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=9,
            candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True,
            new_choch_direction=Direction.DOWNWARD,
        ))

        # 3. DOWNWARD structure: candle 1 is confirmed as Lower Resistance (CH) in DOWNWARD -> receives TJL2_A_PLUS role!
        c10 = _make_candle(10, 1.090, 1.095, 1.080, 1.085, t0 + timedelta(hours=10))
        c12 = _make_candle(12, 1.070, 1.075, 1.060, 1.065, t0 + timedelta(hours=12))
        ch_down = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=10)
        cl_down = SwingPoint(price=1.085, candle_index=10, candle_open_time=c10.open_time, identified_bar_index=10, confirmed_bar_index=10)
        p3_down = SwingPoint(price=1.065, candle_index=12, candle_open_time=c12.open_time, identified_bar_index=14)

        snap2 = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_CROSS",
            symbol_feed_id="FEED_CROSS",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=14,
            candle_open_time=t0 + timedelta(hours=14),
            availability_time=t0 + timedelta(hours=15),
            ch_point=ch_down,
            cl_point=cl_down,
            tentative_p3=p3_down,
            source_candle_lookup={1: c1, 10: c10, 12: c12},
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
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.150, t0 + timedelta(hours=5))

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
        ))

        # 2. CHOCH event at Bar 9 emits cancellation
        snap_choch = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=9,
            candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True,
            new_choch_direction=Direction.DOWNWARD,
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
            ))
