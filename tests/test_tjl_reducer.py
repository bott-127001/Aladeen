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
            candle_time=t0 + timedelta(hours=5),
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

    def test_first_set_creation_on_p3_identification(self) -> None:
        """First set is created when CH, CL, and active tentative P3 are all present."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.150, t0 + timedelta(hours=5))

        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)

        # Pullback completes at Bar 7
        t7 = t0 + timedelta(hours=7)
        obs = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=7,
            candle_time=t7,
            ch_point=ch,
            cl_point=cl,
            tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5},
        )

        snap = reducer.reduce(obs)
        assert snap.current_eligible_set is not None
        curr = snap.current_eligible_set
        assert curr.set_id == "SET_1"
        assert curr.fingerprint == ("ENGINE_TEST", "UPWARD", 1, 4, 5)
        assert curr.tjl1_zone.source_candle_index == 1
        assert curr.tjl2_zone.source_candle_index == 4
        assert curr.p3_source_index == 5
        assert curr.eligibility_available_time == t7
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
            candle_time=t0 + timedelta(hours=9),
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
            candle_time=t0 + timedelta(hours=14),
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
        # But newly confirmed points are labeled
        assert len(snap2.all_labeled_zones) == 4

    def test_t2_pullback_replacement_and_cancellation_intent(self) -> None:
        """At t2 pullback completion, new fingerprint replaces set and emits outgoing cancellation intent."""
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
            candle_time=t0 + timedelta(hours=9),
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
            candle_time=t0 + timedelta(hours=14),
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
            candle_time=t16,
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
        assert len(snap.historical_sets) == 2

    def test_case_b_persistent_confirmed_member_across_replacement(self) -> None:
        """[Case B & C] Persistent confirmed member retains identical StableLevelId across replacement."""
        reducer = TJLReducer("ENGINE_SYNTH", "FEED_SYNTH", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.150, t0 + timedelta(hours=5))

        ch1 = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl1 = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        p3_1 = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)

        # Set 1: CH1=1, CL1=4, P3=5
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_SYNTH",
            symbol_feed_id="FEED_SYNTH",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=7,
            candle_time=t0 + timedelta(hours=7),
            ch_point=ch1,
            cl_point=cl1,
            tentative_p3=p3_1,
            source_candle_lookup={1: c1, 4: c4, 5: c5},
        ))
        set1 = reducer.current_eligible_set
        assert set1 is not None

        # Set 2: Higher High CH2=9 confirmed, but CL1=4 unbroken and shared!
        c9 = _make_candle(9, 1.160, 1.170, 1.159, 1.165, t0 + timedelta(hours=9))
        c11 = _make_candle(11, 1.175, 1.185, 1.174, 1.180, t0 + timedelta(hours=11))
        ch2 = SwingPoint(price=1.165, candle_index=9, candle_open_time=c9.open_time, identified_bar_index=9, confirmed_bar_index=10)
        p3_2 = SwingPoint(price=1.180, candle_index=11, candle_open_time=c11.open_time, identified_bar_index=13)

        snap = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_SYNTH",
            symbol_feed_id="FEED_SYNTH",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=13,
            candle_time=t0 + timedelta(hours=13),
            ch_point=ch2,
            cl_point=cl1,  # Identical unbroken low!
            tentative_p3=p3_2,
            source_candle_lookup={1: c1, 4: c4, 5: c5, 9: c9, 11: c11},
        ))

        set2 = snap.current_eligible_set
        assert set2 is not None
        assert set2.fingerprint == ("ENGINE_SYNTH", "UPWARD", 9, 4, 11)

        # Surviving confirmed member (CL1) preserves exact level ID
        assert set1.tjl2_zone.level_id == set2.tjl2_zone.level_id
        assert set2.tjl2_zone.level_id == ["FEED_SYNTH", "H1", c4.open_time.isoformat(), "LOW"]

        # Case C: Outgoing cancellation intent emitted for the outgoing set
        assert snap.outgoing_cancellation_intent is True

    def test_idempotent_reobservation_same_fingerprint(self) -> None:
        """Identical fingerprint re-observation produces no new sets, no cancellation, and preserves availability timestamp."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.150, t0 + timedelta(hours=5))

        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)

        # Bar 7: Creation
        t7 = t0 + timedelta(hours=7)
        snap1 = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=7,
            candle_time=t7,
            ch_point=ch,
            cl_point=cl,
            tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5},
        ))
        orig_avail = snap1.current_eligible_set.eligibility_available_time

        # Bar 8: Next candle arrives, structural points unchanged
        t8 = t0 + timedelta(hours=8)
        snap2 = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=8,
            candle_time=t8,
            ch_point=ch,
            cl_point=cl,
            tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5},
        ))

        assert snap2.current_eligible_set.set_id == "SET_1"
        assert snap2.current_eligible_set.eligibility_available_time == orig_avail  # NOT refreshed!
        assert snap2.outgoing_cancellation_intent is False
        assert snap2.last_transition.transition_type == TJLTransitionType.IDEMPOTENT_NO_OP
        assert len(snap2.historical_sets) == 1

    def test_source_choch_invalidation_and_gap(self) -> None:
        """Source CHOCH immediately removes current eligibility, emits cancellation intent, and leaves current_set None."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.150, t0 + timedelta(hours=5))

        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)

        # Active set at Bar 7
        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=7,
            candle_time=t0 + timedelta(hours=7),
            ch_point=ch,
            cl_point=cl,
            tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5},
        ))

        # Bar 9: CHOCH confirmed!
        snap_choch = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.DOWNWARD,
            candle_index=9,
            candle_time=t0 + timedelta(hours=9),
            is_choch_event=True,
            new_choch_direction=Direction.DOWNWARD,
        ))

        assert snap_choch.current_eligible_set is None
        assert snap_choch.outgoing_cancellation_intent is True
        assert snap_choch.last_transition.transition_type == TJLTransitionType.CHOCH_INVALIDATION
        # Historical zones and historical sets preserved
        assert len(snap_choch.all_labeled_zones) == 2
        assert len(snap_choch.historical_sets) == 1

    def test_unresolved_containment_freezes_state(self) -> None:
        """Unresolved source status freezes last_processed_index and blocks set replacement."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))
        c4 = _make_candle(4, 1.110, 1.115, 1.104, 1.105, t0 + timedelta(hours=4))
        c5 = _make_candle(5, 1.140, 1.155, 1.139, 1.150, t0 + timedelta(hours=5))

        ch = SwingPoint(price=1.135, candle_index=1, candle_open_time=c1.open_time, identified_bar_index=1, confirmed_bar_index=4)
        cl = SwingPoint(price=1.105, candle_index=4, candle_open_time=c4.open_time, identified_bar_index=4, confirmed_bar_index=4)
        p3 = SwingPoint(price=1.155, candle_index=5, candle_open_time=c5.open_time, identified_bar_index=7)

        reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=7,
            candle_time=t0 + timedelta(hours=7),
            ch_point=ch,
            cl_point=cl,
            tentative_p3=p3,
            source_candle_lookup={1: c1, 4: c4, 5: c5},
        ))

        # Bar 8 is unresolved (e.g. c1 == p2)
        snap_unresolved = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=8,
            candle_time=t0 + timedelta(hours=8),
            is_unresolved=True,
            unresolved_diagnostic="CHOCH_SAME_CLOSE_AMBIGUITY",
        ))

        assert snap_unresolved.is_unresolved is True
        assert snap_unresolved.unresolved_diagnostic == "CHOCH_SAME_CLOSE_AMBIGUITY"
        assert snap_unresolved.last_processed_index == 7  # FROZEN at 7!
        assert snap_unresolved.last_received_index == 8   # ADVANCED to 8!
        assert snap_unresolved.current_eligible_set is not None  # Preserved!

    def test_duplicate_candle_index_raises_and_rolls_back(self) -> None:
        """Duplicate candle index raises ValueError and leaves previous state unmodified."""
        reducer = TJLReducer("ENGINE_TEST", "FEED_TEST", "H1")
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        c1 = _make_candle(1, 1.130, 1.140, 1.129, 1.135, t0 + timedelta(hours=1))

        obs = TJLStructuralObservation(
            source_engine_id="ENGINE_TEST",
            symbol_feed_id="FEED_TEST",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=1,
            candle_time=t0 + timedelta(hours=1),
            source_candle_lookup={1: c1},
        )
        reducer.reduce(obs)

        # Deliver same index again
        with pytest.raises(ValueError, match="Duplicate observation candle index"):
            reducer.reduce(obs)

        assert reducer.last_processed_index == 1
