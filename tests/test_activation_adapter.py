"""Comprehensive tests for TJL Activation Adapter and TJLSynchronizer.

Scope & Coverage:
-----------------
1. Stateful cursor continuity over transition history.
2. Complete semantic equality verification over consumed history (timestamps, geometry, cancellation intent).
3. Transactional staging: atomic rollback on sync failure and valid retry equality.
4. Transactional context binding (first sync failure leaves binding unmutated).
5. Unresolved snapshot processing: finalized cancellations applied while fresh eligibility suppressed.
6. Production contract: real TJLReducer unresolved snapshot has last_transition=BLOCKED_UNRESOLVED
   distinct from authoritative history tail; lagged synchronizer applies cancellation cleanly.
7. Public API requirement: sync_tjl_snapshot_to_activation_engine requires caller-retained synchronizer.
8. Real candle-derived MSM / CHOCH / TJL pipeline feeding activation engine end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Mapping, Optional

import pytest

from aladeen.strategy import (
    ActivationEngine,
    ActivationEngineConfig,
    ActivationSnapshot,
    ActivationState,
    CurrentEligibleSet,
    Direction,
    ExactPricePrint,
    InvalidEvidenceError,
    PriceBasis,
    SequenceDomain,
    StableLevelId,
    StrategyCandle,
    TJLFingerprint,
    TJLLabel,
    TJLSide,
    TJLSnapshot,
    TJLSynchronizer,
    TJLTransitionRecord,
    TJLTransitionType,
    TJLZone,
    UsageEvidenceStatus,
    sync_tjl_snapshot_to_activation_engine,
)
from aladeen.strategy.tjl_coordinator import TJLCoordinator
from aladeen.strategy.tjl_reducer import TJLReducer
from aladeen.strategy.tjl_types import TJLStructuralObservation
from aladeen.strategy.types import CandleColor, MSMConfig


@pytest.fixture
def default_domain() -> SequenceDomain:
    return SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_TEST_01")


class TestActivationTJLAdapter:
    """Rigorous integration tests for the TJL Adapter and TJLSynchronizer."""

    def test_tjl_synchronizer_continuity_and_cursor(self, default_domain: SequenceDomain) -> None:
        """TJLSynchronizer maintains an explicit cursor and rejects broken transition continuity."""
        adapter_engine = ActivationEngine(ActivationEngineConfig(
            engine_id="ENGINE_EURUSD_H1",
            symbol="FEED_EURUSD_H1",
            source_timeframe="H1",
            sequence_domain=default_domain,
            price_basis=PriceBasis.BID,
        ))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1 = TJLZone(lvl1, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2 = TJLZone(lvl2, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1050, False, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)
        cset = CurrentEligibleSet(
            "SET_1",
            TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11),
            Direction.UPWARD,
            "ENGINE_EURUSD_H1",
            "FEED_EURUSD_H1",
            "H1",
            z1,
            z2,
            11,
            datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc),
            1.1040,
            datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            12,
        )

        t0 = TJLTransitionRecord(
            transition_type=TJLTransitionType.FIRST_CREATION,
            outgoing_cancellation_intent=False,
            current_set=cset,
            newly_labeled_zones=(),
            transition_candle_index=12,
            transition_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
        )

        snap1 = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            current_eligible_set=cset,
            all_labeled_zones=(z1, z2),
            historical_sets=(),
            outgoing_cancellation_intent=False,
            last_transition=t0,
            transition_history=(t0,),
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=12,
            last_received_index=12,
        )

        usage = {lvl1: UsageEvidenceStatus.UNUSED, lvl2: UsageEvidenceStatus.UNUSED}
        snap_act1 = synchronizer.sync(snap1, sequence_ref_start=1501, usage_evidence=usage)
        assert len(snap_act1.current_members) == 2
        assert synchronizer.last_synced_transition_index == 0

        # Disconnected snapshot where last_transition does not match tail of history
        t_bad = TJLTransitionRecord(
            transition_type=TJLTransitionType.CHOCH_INVALIDATION,
            outgoing_cancellation_intent=True,
            current_set=None,
            newly_labeled_zones=(),
            transition_candle_index=15,
            transition_time=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
            outgoing_cancelled_set_id="SET_1",
            outgoing_cancelled_fingerprint=cset.fingerprint,
        )
        disconnected_snap = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            current_eligible_set=cset,
            all_labeled_zones=(),
            historical_sets=(),
            outgoing_cancellation_intent=True,
            last_transition=t_bad,
            transition_history=(t0,),  # Missing t_bad!
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=15,
            last_received_index=15,
        )
        with pytest.raises(InvalidEvidenceError, match="last_transition does not match the tail"):
            synchronizer.sync(disconnected_snap, sequence_ref_start=1601)

        # Truncated history strictly rejected
        truncated_snap = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            current_eligible_set=cset,
            all_labeled_zones=(),
            historical_sets=(),
            outgoing_cancellation_intent=False,
            last_transition=None,
            transition_history=(),  # Truncated to empty!
            is_unresolved=False,
            unresolved_diagnostic=None,
            last_processed_index=12,
            last_received_index=12,
        )
        with pytest.raises(InvalidEvidenceError, match="Transition history truncated"):
            synchronizer.sync(truncated_snap, sequence_ref_start=1604)

    def test_unresolved_snapshot_creates_zero_eligibility(self, default_domain: SequenceDomain) -> None:
        """Frozen unresolved snapshot strictly creates zero fresh eligibility."""
        sync_engine = ActivationEngine(ActivationEngineConfig(
            engine_id="ENGINE_EURUSD_H1",
            symbol="FEED_EURUSD_H1",
            source_timeframe="H1",
            sequence_domain=default_domain,
            price_basis=PriceBasis.BID,
        ))
        unresolved_snap = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1", symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1",
            direction=Direction.UPWARD, current_eligible_set=None, all_labeled_zones=(), historical_sets=(),
            outgoing_cancellation_intent=False, last_transition=None, transition_history=(),
            is_unresolved=True, unresolved_diagnostic="Unresolved ambiguity c1 == p2",
            last_processed_index=10, last_received_index=15,
        )
        synchronizer = TJLSynchronizer(engine=sync_engine)
        snap = sync_tjl_snapshot_to_activation_engine(synchronizer, unresolved_snap, sequence_ref=100)
        assert len(snap.current_members) == 0
        assert len(snap.active_activations) == 0

    def test_real_pipeline_msm_choch_tjl_feeding_activation_adapter(self, default_domain: SequenceDomain) -> None:
        """Cross-checks real candle-derived MSM/CHOCH/TJL pipeline output feeding ActivationEngine end-to-end."""
        from aladeen.strategy.validator import adapt_candles
        path = Path(__file__).parent / "fixtures" / "tjl_acceptance.json"
        with open(path, "r", encoding="utf-8") as f:
            fixtures = json.load(f)["fixtures"]

        fix = fixtures["tjl_09_source_choch_eligibility_invalidation_and_gap"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])
        candles = adapt_candles(fix["candles"])

        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )

        for i in range(8):
            coord.process_candle(candles[i])
        s7 = coord.get_snapshot()
        assert s7.current_eligible_set is not None
        assert s7.current_eligible_set.set_id == "SET_1"

        adapter_engine = ActivationEngine(ActivationEngineConfig(
            engine_id="ENGINE_EURUSD_H1",
            symbol="FEED_EURUSD_H1",
            source_timeframe="H1",
            sequence_domain=default_domain,
            price_basis=PriceBasis.BID,
        ))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        usage_s7 = {
            s7.current_eligible_set.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            s7.current_eligible_set.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        snap_act = synchronizer.sync(s7, sequence_ref_start=1701, usage_evidence=usage_s7)
        assert len(snap_act.current_members) == 2
        m_tjl1 = snap_act.current_members["SET_1::TJL1"]
        assert m_tjl1.lower_edge == pytest.approx(1.1350)
        assert m_tjl1.upper_edge == pytest.approx(1.1400)

        # In-zone print activates TJL1
        print_in_zone = ExactPricePrint(
            observation_id="OBS_REAL_01",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=s7.current_eligible_set.eligibility_available_time + timedelta(minutes=15),
            sequence_domain=default_domain,
            sequence_ref=1703,
        )
        snap_touch = adapter_engine.process_event(print_in_zone)
        assert snap_touch.active_activations["SET_1::TJL1"].state == ActivationState.PENDING_ACTIVATION

        # Bar 8 continuation
        coord.process_candle(candles[8])
        s8 = coord.get_snapshot()
        snap_act8 = synchronizer.sync(s8, sequence_ref_start=1704)
        assert snap_act8.active_activations["SET_1::TJL1"].state == ActivationState.PENDING_ACTIVATION

        # Bar 9 Bearish CHOCH confirmation cancels SET_1
        coord.process_candle(candles[9])
        s9 = coord.get_snapshot()
        assert s9.current_eligible_set is None

        snap_act9 = synchronizer.sync(s9, sequence_ref_start=1705)
        assert len(snap_act9.current_members) == 0
        assert len(snap_act9.active_activations) == 0
        assert len(snap_act9.terminal_activations) == 1
        assert snap_act9.terminal_activations[0].state == ActivationState.CANCELLED_SOURCE_CHOCH

        # Subsequent print inside old zone cannot reactivate
        print_after = ExactPricePrint(
            observation_id="OBS_REAL_02",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=s9.last_transition.transition_time + timedelta(hours=1),
            sequence_domain=default_domain,
            sequence_ref=1706,
        )
        snap_after = adapter_engine.process_event(print_after)
        assert len(snap_after.active_activations) == 0

    def test_tjl_synchronizer_failure_rollback_and_valid_retry(self, default_domain: SequenceDomain) -> None:
        """Directive 1: Complete rollback on sync failure and valid retry equality with independent reference."""
        adapter_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1 = TJLZone(lvl1, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2 = TJLZone(lvl2, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1050, False, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)

        cset1 = CurrentEligibleSet("SET_1", TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11), Direction.UPWARD, "ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", z1, z2, 11, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.1040, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 12)
        t0 = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset1, (), 12, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))

        snap1 = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset1, (), (), False, t0, (t0,), False, None, 12, 12)
        usage = {lvl1: UsageEvidenceStatus.UNUSED, lvl2: UsageEvidenceStatus.UNUSED}
        synchronizer.sync(snap1, sequence_ref_start=1001, usage_evidence=usage)

        pre_fail_cursor = synchronizer.last_synced_transition_index
        pre_fail_usage = dict(synchronizer._usage_cache)
        pre_fail_transitions = list(synchronizer._consumed_transitions)
        pre_fail_engine_snap = adapter_engine.get_snapshot()

        # Construct snap2 with cancellation AND invalid set whose member symbol does not match engine
        t1 = TJLTransitionRecord(
            TJLTransitionType.CHOCH_INVALIDATION, True, None, (), 14,
            datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            outgoing_cancelled_set_id="SET_1",
            outgoing_cancelled_fingerprint=cset1.fingerprint,
        )
        lvl1_other = StableLevelId("FEED_OTHER_SYMBOL", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2_other = StableLevelId("FEED_OTHER_SYMBOL", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1_other = TJLZone(lvl1_other, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2_other = TJLZone(lvl2_other, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1050, False, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)
        cset_bad = CurrentEligibleSet("SET_2", TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11), Direction.UPWARD, "ENGINE_EURUSD_H1", "FEED_OTHER_SYMBOL", "H1", z1_other, z2_other, 11, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.1040, datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), 14)
        snap2_failing = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset_bad, (), (), True, t1, (t0, t1), False, None, 14, 14)

        with pytest.raises(InvalidEvidenceError):
            synchronizer.sync(snap2_failing, sequence_ref_start=1002)

        # 100% COMPLETE ROLLBACK VERIFICATION
        assert synchronizer.last_synced_transition_index == pre_fail_cursor
        assert synchronizer._usage_cache == pre_fail_usage
        assert synchronizer._consumed_transitions == pre_fail_transitions
        assert adapter_engine.get_snapshot().active_activations == pre_fail_engine_snap.active_activations
        assert adapter_engine.get_snapshot().current_members == pre_fail_engine_snap.current_members
        assert adapter_engine.get_snapshot().terminal_activations == pre_fail_engine_snap.terminal_activations

        # VALID RETRY with correct snap2
        snap2_valid = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, None, (), (), True, t1, (t0, t1), False, None, 14, 14)
        snap_post_retry = synchronizer.sync(snap2_valid, sequence_ref_start=1002)

        # Independent reference comparison
        ref_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        ref_sync = TJLSynchronizer(engine=ref_engine)
        ref_sync.sync(snap1, sequence_ref_start=1001, usage_evidence=usage)
        snap_ref = ref_sync.sync(snap2_valid, sequence_ref_start=1002)

        assert snap_post_retry.active_activations == snap_ref.active_activations
        assert snap_post_retry.current_members == snap_ref.current_members
        assert snap_post_retry.terminal_activations == snap_ref.terminal_activations

    def test_tjl_synchronizer_rejects_changed_history_prefix(self, default_domain: SequenceDomain) -> None:
        """Directive 2: Synchronizer strictly rejects rewritten history with modified prefix."""
        adapter_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1 = TJLZone(lvl1, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2 = TJLZone(lvl2, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1050, False, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)
        cset = CurrentEligibleSet("SET_1", TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11), Direction.UPWARD, "ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", z1, z2, 11, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.1040, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 12)

        t0 = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset, (), 12, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        snap1 = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset, (), (), False, t0, (t0,), False, None, 12, 12)
        synchronizer.sync(snap1, sequence_ref_start=1001)

        # Rewritten t0 (different candle index: 99 instead of 12)
        t0_rewritten = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset, (), 99, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        t1 = TJLTransitionRecord(TJLTransitionType.CONTINUATION_RETAINED, False, cset, (), 13, datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc))
        snap_rewritten = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset, (), (), False, t1, (t0_rewritten, t1), False, None, 13, 13)

        with pytest.raises(InvalidEvidenceError, match="Consumed transition history mismatch"):
            synchronizer.sync(snap_rewritten, sequence_ref_start=1002)

    def test_tjl_synchronizer_rejects_altered_transition_timestamp(self, default_domain: SequenceDomain) -> None:
        """Directive 1 & 5: Synchronizer rejects snapshot when only transition timestamp is altered."""
        adapter_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1 = TJLZone(lvl1, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2 = TJLZone(lvl2, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1050, False, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)
        cset = CurrentEligibleSet("SET_1", TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11), Direction.UPWARD, "ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", z1, z2, 11, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.1040, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 12)

        t0 = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset, (), 12, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        snap1 = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset, (), (), False, t0, (t0,), False, None, 12, 12)
        synchronizer.sync(snap1, sequence_ref_start=1001)

        # Retain identical (type, candle_index, outgoing_set), but alter transition_time
        t0_altered_time = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset, (), 12, datetime(2026, 10, 2, 8, 5, tzinfo=timezone.utc))
        t1 = TJLTransitionRecord(TJLTransitionType.CONTINUATION_RETAINED, False, cset, (), 13, datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc))
        snap_altered = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset, (), (), False, t1, (t0_altered_time, t1), False, None, 13, 13)

        with pytest.raises(InvalidEvidenceError, match="Consumed transition history mismatch"):
            synchronizer.sync(snap_altered, sequence_ref_start=1002)

    def test_tjl_synchronizer_rejects_altered_resulting_set_geometry(self, default_domain: SequenceDomain) -> None:
        """Directive 1 & 5: Synchronizer rejects snapshot when only resulting set geometry is altered."""
        adapter_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1 = TJLZone(lvl1, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2 = TJLZone(lvl2, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1050, False, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)
        cset = CurrentEligibleSet("SET_1", TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11), Direction.UPWARD, "ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", z1, z2, 11, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.1040, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 12)

        t0 = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset, (), 12, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        snap1 = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset, (), (), False, t0, (t0,), False, None, 12, 12)
        synchronizer.sync(snap1, sequence_ref_start=1001)

        # Alter zone geometry in resulting set (e.g. 1.1350 -> 1.1360)
        z1_altered = TJLZone(lvl1, TJLLabel.TJL1, 1.1360, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        cset_altered = CurrentEligibleSet("SET_1", TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11), Direction.UPWARD, "ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", z1_altered, z2, 11, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.1040, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 12)
        t0_altered_geom = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset_altered, (), 12, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        t1 = TJLTransitionRecord(TJLTransitionType.CONTINUATION_RETAINED, False, cset, (), 13, datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc))
        snap_altered = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset, (), (), False, t1, (t0_altered_geom, t1), False, None, 13, 13)

        with pytest.raises(InvalidEvidenceError, match="Consumed transition history mismatch"):
            synchronizer.sync(snap_altered, sequence_ref_start=1002)

    def test_tjl_synchronizer_failed_first_sync_leaves_binding_unmutated(self, default_domain: SequenceDomain) -> None:
        """Directive 3 & 5: Failure on first sync leaves binding, cursor, cache, and history 100% unmutated."""
        adapter_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        assert synchronizer._bound_engine_id is None
        assert synchronizer._bound_symbol_feed_id is None
        assert synchronizer._bound_source_timeframe is None
        assert synchronizer.last_synced_transition_index == -1
        assert len(synchronizer._consumed_transitions) == 0

        # Snapshot with bad member symbol triggers error during member registration
        lvl1_bad = StableLevelId("FEED_WRONG", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2_bad = StableLevelId("FEED_WRONG", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1_bad = TJLZone(lvl1_bad, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2_bad = TJLZone(lvl2_bad, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1050, False, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)
        cset_bad = CurrentEligibleSet("SET_1", TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11), Direction.UPWARD, "ENGINE_EURUSD_H1", "FEED_WRONG", "H1", z1_bad, z2_bad, 11, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.1040, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 12)
        t0 = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset_bad, (), 12, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        snap_failing = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset_bad, (), (), False, t0, (t0,), False, None, 12, 12)

        with pytest.raises(InvalidEvidenceError):
            synchronizer.sync(snap_failing, sequence_ref_start=1001)

        # Assert every single synchronizer field remains pristine
        assert synchronizer._bound_engine_id is None
        assert synchronizer._bound_symbol_feed_id is None
        assert synchronizer._bound_source_timeframe is None
        assert synchronizer.last_synced_transition_index == -1
        assert len(synchronizer._consumed_transitions) == 0
        assert len(synchronizer._usage_cache) == 0

    def test_tjl_synchronizer_processes_cancellation_from_unresolved_snapshot(self, default_domain: SequenceDomain) -> None:
        """Directive 4 & 5: Consumer lagging behind finalized cancellation applies it even if latest snapshot is unresolved."""
        adapter_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1 = TJLZone(lvl1, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2 = TJLZone(lvl2, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1050, False, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)
        cset1 = CurrentEligibleSet("SET_1", TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11), Direction.UPWARD, "ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", z1, z2, 11, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.1040, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 12)

        t0 = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset1, (), 12, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        snap1 = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset1, (), (), False, t0, (t0,), False, None, 12, 12)
        usage = {lvl1: UsageEvidenceStatus.UNUSED, lvl2: UsageEvidenceStatus.UNUSED}
        synchronizer.sync(snap1, sequence_ref_start=1001, usage_evidence=usage)

        # In-zone print activates TJL1 to PENDING_ACTIVATION
        adapter_engine.process_event(ExactPricePrint(
            observation_id="OBS_1",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc),
            sequence_domain=default_domain,
            sequence_ref=1002,
        ))
        assert adapter_engine.get_snapshot().active_activations["SET_1::TJL1"].state == ActivationState.PENDING_ACTIVATION
        assert adapter_engine.get_snapshot().active_activations["SET_1::TJL2_A_PLUS"].state == ActivationState.INACTIVE_ELIGIBLE
        assert len(adapter_engine.get_snapshot().active_activations) == 2

        # Finalized CHOCH invalidation transition occurs in market, but engine becomes unresolved
        t1 = TJLTransitionRecord(
            TJLTransitionType.CHOCH_INVALIDATION, True, None, (), 14,
            datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            outgoing_cancelled_set_id="SET_1",
            outgoing_cancelled_fingerprint=cset1.fingerprint,
        )
        unresolved_snap = TJLSnapshot(
            "ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD,
            None, (), (), True, t1, (t0, t1),
            is_unresolved=True, unresolved_diagnostic="Frozen on c1 == p2 ambiguity",
            last_processed_index=14, last_received_index=15,
        )

        snap_res = synchronizer.sync(unresolved_snap, sequence_ref_start=1003)

        # 1. Finalized cancellation WAS processed: SET_1 removed from current_members
        assert len(snap_res.current_members) == 0
        # 2. In-flight activation was terminalized cleanly with CANCELLED_SOURCE_CHOCH
        assert len(snap_res.active_activations) == 0
        assert len(snap_res.terminal_activations) == 1
        assert snap_res.terminal_activations[0].state == ActivationState.CANCELLED_SOURCE_CHOCH
        # 3. Synchronizer cursor advanced and transition consumed
        assert synchronizer.last_synced_transition_index == 1
        assert len(synchronizer._consumed_transitions) == 2

    def test_sync_tjl_snapshot_to_activation_engine_requires_retained_synchronizer(self, default_domain: SequenceDomain) -> None:
        """Directive 2 & 5: sync_tjl_snapshot_to_activation_engine requires retained TJLSynchronizer."""
        adapter_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        snap = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, None, (), (), False, None, (), False, None, 1, 1)

        # Passing bare engine raises TypeError
        with pytest.raises(TypeError, match="requires a persistent, retained TJLSynchronizer"):
            sync_tjl_snapshot_to_activation_engine(adapter_engine, snap, sequence_ref=100)

        # Passing retained synchronizer succeeds
        synchronizer = TJLSynchronizer(engine=adapter_engine)
        res = sync_tjl_snapshot_to_activation_engine(synchronizer, snap, sequence_ref=100)
        assert res.engine_id == "ENGINE_EURUSD_H1"

    def test_tjl_synchronizer_rejects_cross_context_snapshot(self, default_domain: SequenceDomain) -> None:
        """Directive 2: Synchronizer strictly rejects snapshots from different engine/symbol/timeframe."""
        adapter_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        # Mismatched symbol
        snap_bad_symbol = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_GBPUSD_H1", "H1", Direction.UPWARD, None, (), (), False, None, (), False, None, 1, 1)
        with pytest.raises(InvalidEvidenceError, match="Cross-symbol snapshot rejected"):
            synchronizer.sync(snap_bad_symbol, sequence_ref_start=100)

        # Mismatched engine
        snap_bad_engine = TJLSnapshot("ENGINE_OTHER", "FEED_EURUSD_H1", "H1", Direction.UPWARD, None, (), (), False, None, (), False, None, 1, 1)
        with pytest.raises(InvalidEvidenceError, match="Cross-engine snapshot rejected"):
            synchronizer.sync(snap_bad_engine, sequence_ref_start=100)

        # Mismatched timeframe
        snap_bad_tf = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "D1", Direction.UPWARD, None, (), (), False, None, (), False, None, 1, 1)
        with pytest.raises(InvalidEvidenceError, match="Cross-timeframe snapshot rejected"):
            synchronizer.sync(snap_bad_tf, sequence_ref_start=100)

    def test_tjl_synchronizer_repeated_sync_is_idempotent(self, default_domain: SequenceDomain) -> None:
        """Directive 6: Repeating synchronization on same snapshot is an idempotent no-op."""
        adapter_engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1 = TJLZone(lvl1, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2 = TJLZone(lvl2, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1050, False, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)
        cset = CurrentEligibleSet("SET_1", TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11), Direction.UPWARD, "ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", z1, z2, 11, datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), 1.1040, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), 12)

        t0 = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset, (), 12, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        snap = TJLSnapshot("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", Direction.UPWARD, cset, (), (), False, t0, (t0,), False, None, 12, 12)

        s1 = synchronizer.sync(snap, sequence_ref_start=1001)
        s2 = synchronizer.sync(snap, sequence_ref_start=1001)
        assert s1.current_members == s2.current_members
        assert s1.active_activations == s2.active_activations
        assert synchronizer.last_synced_transition_index == 0

    def test_tjl_reducer_unresolved_snapshot_with_lagged_cancellation(self, default_domain: SequenceDomain) -> None:
        """Directive 2: Real TJL reducer unresolved snapshot has last_transition=BLOCKED_UNRESOLVED, which differs from authoritative history tail; lagged synchronizer consumes cancellation cleanly."""
        from aladeen.strategy.types import SwingPoint
        t0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        reducer = TJLReducer(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
        )

        c1 = StrategyCandle(1, t0 + timedelta(hours=1), 1.130, 1.140, 1.129, 1.135, False, "CONFIRMED_COMPLETED")
        c4 = StrategyCandle(4, t0 + timedelta(hours=4), 1.110, 1.115, 1.104, 1.105, False, "CONFIRMED_COMPLETED")
        c5 = StrategyCandle(5, t0 + timedelta(hours=5), 1.140, 1.155, 1.139, 1.155, False, "CONFIRMED_COMPLETED")

        # 1. Initial Set 1 produced by reducer
        snap1 = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
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
        assert snap1.current_eligible_set is not None

        # Synchronize Set 1 to activation engine
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        synchronizer = TJLSynchronizer(engine=eng)
        usage_snap1 = {
            snap1.current_eligible_set.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            snap1.current_eligible_set.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        synchronizer.sync(snap1, sequence_ref_start=1001, usage_evidence=usage_snap1)

        # In-zone print activates TJL1
        eng.process_event(ExactPricePrint("OBS_TOUCH", 1.1370, PriceBasis.BID, t0 + timedelta(hours=8, minutes=15), default_domain, 1002))
        assert eng.get_snapshot().active_activations["SET_1::TJL1"].state == ActivationState.PENDING_ACTIVATION

        # 2. CHOCH event at Bar 9 emits authoritative cancellation in market
        snap_choch = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            candle_index=9,
            candle_open_time=t0 + timedelta(hours=9),
            is_choch_event=True,
            new_choch_direction=Direction.DOWNWARD,
            observation_event_pos=9,
        ))
        assert snap_choch.outgoing_cancellation_intent is True

        # 3. Subsequent unresolved observation at Bar 10
        snap_unres = reducer.reduce(TJLStructuralObservation(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
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

        # Assert production contract properties
        assert snap_unres.is_unresolved is True
        assert snap_unres.last_transition is not None
        assert snap_unres.last_transition.transition_type == TJLTransitionType.BLOCKED_UNRESOLVED
        assert len(snap_unres.transition_history) == 2
        assert snap_unres.transition_history[-1].transition_type == TJLTransitionType.CHOCH_INVALIDATION
        # Key upstream contract: receipt diagnostic is NOT equal to authoritative history tail!
        assert snap_unres.last_transition != snap_unres.transition_history[-1]

        # Lagged synchronizer consumes the unresolved snapshot
        snap_final = synchronizer.sync(snap_unres, sequence_ref_start=1003)

        # Asserts:
        # 1. Authoritative cancellation was applied: SET_1 removed from active membership
        assert len(snap_final.current_members) == 0
        # 2. In-flight activation terminalized with CANCELLED_SOURCE_CHOCH
        assert len(snap_final.active_activations) == 0
        assert len(snap_final.terminal_activations) == 1
        assert snap_final.terminal_activations[0].state == ActivationState.CANCELLED_SOURCE_CHOCH
        # 3. Synchronizer cursor advanced and transition consumed
        assert synchronizer.last_synced_transition_index == 1
        assert len(synchronizer._consumed_transitions) == 2
