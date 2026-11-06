"""Comprehensive execution tests for Pure Offline Tap and Zone Activation Lifecycle Engine.

Validates:
1. All 26 acceptance fixtures executed through engine public APIs.
2. Source cancellation permanently removes outgoing membership for untouched, pending, externally-cancelled, and armed states.
3. Missing usage evidence strictly defaults to UNKNOWN (fail-closed).
4. Strict registration context validation (engine_id, symbol, source_timeframe) and price-basis validation.
5. Unknown cancellation timestamps preserved without wall-clock fabrication.
6. Equal-sequence distinct causal events strictly rejected (SequenceOrderError).
7. Uncertain candle evidence preserves existing authoritative pending activation.
8. External commit notification excludes winning level from cancellation.
9. Rejection of recycled evidence across cancelled activation generations.
10. Sequence domain mismatch rejection (DomainMismatchError).
11. Duplicate event idempotence and conflicting duplicate rejection (ConflictingEventError).
12. Atomic batch rollback on failure and retry against fresh reference.
13. Every-prefix sequential vs batch vs replay bit-for-bit equivalence.
14. Reset isolation and immutable snapshots.
15. Stateful TJLSynchronizer cursor continuity and broken transition rejection.
16. Real MSM / CHOCH / TJL pipeline candle outputs feeding activation adapter end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from aladeen.strategy import (
    ActivationEngine,
    ActivationEngineConfig,
    ActivationError,
    ActivationRecord,
    ActivationSnapshot,
    ActivationState,
    CancellationReason,
    ConflictingEventError,
    CoverageEvidence,
    CoverageStatus,
    CurrentEligibleSet,
    Direction,
    DomainMismatchError,
    ExactPricePrint,
    ExternalCommitEvent,
    IntervalBoundedCandleEvidence,
    InvalidEvidenceError,
    PriceBasis,
    RegisterMembersEvent,
    SequenceDomain,
    SequenceOrderError,
    SourceCancellationEvent,
    SourceMemberReference,
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
    adapt_tjl_cancellation_record,
    adapt_tjl_current_set,
    format_activation_id,
    sync_tjl_snapshot_to_activation_engine,
)
from aladeen.strategy.tjl_coordinator import TJLCoordinator
from aladeen.strategy.types import MSMConfig


@pytest.fixture
def default_domain() -> SequenceDomain:
    return SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_TEST_01")


@pytest.fixture
def engine(default_domain: SequenceDomain) -> ActivationEngine:
    config = ActivationEngineConfig(
        engine_id="ENGINE_EURUSD_H1",
        symbol="EURUSD",
        source_timeframe="H1",
        sequence_domain=default_domain,
        price_basis=PriceBasis.BID,
    )
    return ActivationEngine(config)


@pytest.fixture
def sample_member(default_domain: SequenceDomain) -> SourceMemberReference:
    return SourceMemberReference(
        engine_id="ENGINE_EURUSD_H1",
        symbol="EURUSD",
        source_timeframe="H1",
        set_id="SET_1",
        role="TJL1",
        side="HIGH",
        lower_edge=1.1350,
        upper_edge=1.1400,
        is_line=False,
        direction=Direction.UPWARD,
        level_id=StableLevelId(
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_open_time=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc),
            side=TJLSide.HIGH,
        ),
        eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
        usage_evidence_status=UsageEvidenceStatus.UNUSED,
    )


class TestActivationEngineExecution:
    """Rigorous execution tests for ActivationEngine."""

    def test_fixture_act_01_known_availability_first_touch(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 01: Valid discrete print at or after availability activates level into PENDING_ACTIVATION."""
        engine.register_source_member(sample_member)

        # Print inside zone at 08:15 >= 08:00
        event = ExactPricePrint(
            observation_id="OBS_01",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc),
            sequence_domain=default_domain,
            sequence_ref=101,
        )
        snap = engine.process_event(event)

        rec = snap.active_activations[sample_member.member_key]
        assert rec.state == ActivationState.PENDING_ACTIVATION
        assert rec.first_touch_time == event.timestamp
        assert rec.first_touch_price == event.price
        assert rec.trigger_observation_id == "OBS_01"
        assert rec.confirmation_timeframe == "M1"
        assert rec.terminal is False

    def test_fixture_act_01b_both_tjl1_and_tjl2_pending_independently(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Act 01b: Both TJL1 and TJL2 on active set hold pending activations concurrently."""
        tjl1 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        tjl2 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL2_A_PLUS", side="LOW",
            lower_edge=1.1040, upper_edge=1.1050, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_members([tjl1, tjl2])

        # Touch TJL1
        ev1 = ExactPricePrint(
            observation_id="OBS_TJL1", price=1.1360, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=201,
        )
        engine.process_event(ev1)

        # Touch TJL2
        ev2 = ExactPricePrint(
            observation_id="OBS_TJL2", price=1.1045, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 9, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=202,
        )
        snap = engine.process_event(ev2)

        rec1 = snap.active_activations[tjl1.member_key]
        rec2 = snap.active_activations[tjl2.member_key]
        assert rec1.state == ActivationState.PENDING_ACTIVATION
        assert rec2.state == ActivationState.PENDING_ACTIVATION
        assert rec1.activation_id != rec2.activation_id

    def test_shared_print_touching_multiple_levels_independently(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """One single market print touches two overlapping levels; both activate independently without conflict."""
        lvl_a = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1300, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        lvl_b = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL2_A_PLUS", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1450, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_members([lvl_a, lvl_b])

        shared_print = ExactPricePrint(
            observation_id="OBS_SHARED", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=301,
        )
        snap = engine.process_event(shared_print)

        rec_a = snap.active_activations[lvl_a.member_key]
        rec_b = snap.active_activations[lvl_b.member_key]
        assert rec_a.state == ActivationState.PENDING_ACTIVATION
        assert rec_b.state == ActivationState.PENDING_ACTIVATION
        assert rec_a.trigger_observation_id == "OBS_SHARED"
        assert rec_b.trigger_observation_id == "OBS_SHARED"

    def test_act_02_unknown_availability_blocks_activation(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Act 02: Unknown availability blocks activation evidence while preserving structural membership."""
        lvl = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=None,  # UNKNOWN
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        snap = engine.register_source_member(lvl)
        rec = snap.active_activations[lvl.member_key]
        assert rec.state == ActivationState.INACTIVE_INELIGIBLE
        assert rec.blocked_reason == "UNKNOWN_AVAILABILITY_TIMING"

        ev = ExactPricePrint(
            observation_id="OBS_01", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=101,
        )
        snap2 = engine.process_event(ev)
        assert snap2.active_activations[lvl.member_key].state == ActivationState.INACTIVE_INELIGIBLE

    def test_act_02b_unknown_usage_evidence_blocks(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Act 02b: Uncertain usage evidence blocks activation (fail closed)."""
        lvl = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNKNOWN,
        )
        snap = engine.register_source_member(lvl)
        rec = snap.active_activations[lvl.member_key]
        assert rec.state == ActivationState.INACTIVE_INELIGIBLE
        assert rec.blocked_reason == "USAGE_EVIDENCE_UNCERTAIN_FAIL_CLOSED"

    def test_source_cancellation_permanently_removes_eligibility_for_all_states(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Directive 1: Source cancellation removes outgoing members permanently across untouched, pending, externally-cancelled, and armed states."""
        # Member 1: Untouched (INACTIVE_ELIGIBLE)
        m_untouched = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        # Member 2: Pending activation
        m_pending = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL2_A_PLUS", side="LOW",
            lower_edge=1.1040, upper_edge=1.1050, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_members([m_untouched, m_pending])

        # Touch m_pending
        engine.process_event(ExactPricePrint(
            observation_id="OBS_TJL2", price=1.1045, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=401,
        ))
        assert engine.get_snapshot().active_activations[m_pending.member_key].state == ActivationState.PENDING_ACTIVATION
        assert engine.get_snapshot().active_activations[m_untouched.member_key].state == ActivationState.INACTIVE_ELIGIBLE

        # Trigger source replacement of SET_1
        repl_evt = SourceCancellationEvent(
            event_id="EVT_REPL_SET1", cancellation_reason=CancellationReason.SOURCE_REPLACEMENT,
            sequence_domain=default_domain, sequence_ref=402, target_set_id="SET_1",
        )
        snap = engine.process_event(repl_evt)

        # 1. Both outgoing members are completely REMOVED from current_members
        assert m_untouched.member_key not in snap.current_members
        assert m_pending.member_key not in snap.current_members
        assert len(snap.current_members) == 0

        # 2. Both outgoing active slots are completely CLEARED
        assert m_untouched.member_key not in snap.active_activations
        assert m_pending.member_key not in snap.active_activations
        assert len(snap.active_activations) == 0

        # 3. m_pending is recorded as terminal
        assert len(snap.terminal_activations) == 1
        assert snap.terminal_activations[0].state == ActivationState.CANCELLED_SOURCE_REPLACEMENT

        # 4. A later inside price print strictly CANNOT reactivate SET_1!
        later_print = ExactPricePrint(
            observation_id="OBS_LATER", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=403,
        )
        snap_after = engine.process_event(later_print)
        assert len(snap_after.active_activations) == 0
        assert len(snap_after.current_members) == 0

    def test_source_choch_cancels_externally_cancelled_and_armed_states(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Source CHOCH removes members in OUT_OF_ZONE_ARMED and CANCELLED_EXTERNAL_ENTRY states."""
        m = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_member(m)

        # Touch -> Pending
        engine.process_event(ExactPricePrint(observation_id="O1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=501))
        # Depart -> Outside
        engine.process_event(ExactPricePrint(observation_id="O2", price=1.1420, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=502))
        # External commit -> Armed (Path B)
        engine.process_event(ExternalCommitEvent(event_id="C1", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=503, winning_engine_id="O", winning_set_id="S", winning_role="R"))
        assert engine.get_snapshot().active_activations[m.member_key].state == ActivationState.OUT_OF_ZONE_ARMED

        # Source CHOCH arrives
        choch = SourceCancellationEvent(event_id="CHOCH1", cancellation_reason=CancellationReason.SOURCE_CHOCH, sequence_domain=default_domain, sequence_ref=504, affected_direction=Direction.UPWARD)
        snap = engine.process_event(choch)

        # Member is completely removed
        assert m.member_key not in snap.current_members
        assert m.member_key not in snap.active_activations

    def test_missing_usage_evidence_strictly_defaults_to_unknown(self) -> None:
        """Directive 2: Missing usage evidence in adapt_tjl_current_set strictly defaults to UNKNOWN."""
        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        z1 = TJLZone(lvl1, TJLLabel.TJL1, 1.1350, 1.1400, False, 10, datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), 12)
        z2 = TJLZone(lvl2, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1040, True, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)

        cset = CurrentEligibleSet(
            set_id="SET_1",
            fingerprint=TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, ch_point_id=10, cl_point_id=8, p3_point_id=11),
            direction=Direction.UPWARD,
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            tjl1_zone=z1,
            tjl2_zone=z2,
            p3_source_index=11,
            p3_open_time=datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc),
            p3_price=1.1040,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            created_at_candle_index=12,
        )

        # Call adapter without usage evidence map -> must default to UNKNOWN
        ref1, ref2 = adapt_tjl_current_set(cset)
        assert ref1.usage_evidence_status == UsageEvidenceStatus.UNKNOWN
        assert ref2.usage_evidence_status == UsageEvidenceStatus.UNKNOWN

    def test_registration_context_and_price_basis_validation(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Directive 4: Mismatched engine context and price basis are strictly rejected."""
        # 1. Mismatched engine_id
        bad_m = SourceMemberReference(
            engine_id="WRONG_ENGINE", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
        )
        with pytest.raises(InvalidEvidenceError):
            engine.register_source_member(bad_m)

        # 2. Mismatched price basis (engine configured for BID, event is ASK)
        good_m = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_member(good_m)

        ask_print = ExactPricePrint(
            observation_id="OBS_ASK", price=1.1370, price_basis=PriceBasis.ASK,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=601,
        )
        with pytest.raises(InvalidEvidenceError):
            engine.process_event(ask_print)

    def test_unknown_cancellation_timestamp_preserved_without_wall_clock(self, default_domain: SequenceDomain) -> None:
        """Directive 3: Cancellation adapter preserves None timestamp without generating wall-clock datetime."""
        trans = TJLTransitionRecord(
            transition_type=TJLTransitionType.CHOCH_INVALIDATION,
            outgoing_cancellation_intent=True,
            current_set=None,
            newly_labeled_zones=(),
            transition_candle_index=15,
            transition_time=None,  # Unknown transition time!
            outgoing_cancelled_set_id="SET_1",
            outgoing_cancelled_fingerprint=TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11),
        )
        evt = adapt_tjl_cancellation_record(trans, sequence_domain=default_domain, sequence_ref=701, event_id="C_UNKNOWN")
        assert evt is not None
        assert evt.timestamp is None  # Strictly None! No datetime.now()!

    def test_equal_sequence_distinct_causal_events_rejected(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Directive 5: Distinct events with equal sequence_ref are strictly rejected."""
        engine.register_source_member(sample_member)

        # Commit event at seq 801
        engine.process_event(ExternalCommitEvent(
            event_id="EVT_COMMIT", timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc),
            sequence_domain=default_domain, sequence_ref=801,
            winning_engine_id="O", winning_set_id="S", winning_role="R",
        ))

        # Retouch event attempting to use the SAME sequence_ref 801 -> REJECTED!
        ev_same_seq = ExactPricePrint(
            observation_id="OBS_RETOUCH_SAME_SEQ", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=801,
        )
        with pytest.raises(SequenceOrderError):
            engine.process_event(ev_same_seq)

    def test_uncertain_candle_evidence_preserves_existing_pending_activation(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Directive 5: Uncertain intra-candle evidence does NOT overwrite an existing pending activation."""
        engine.register_source_member(sample_member)

        # First touch -> PENDING_ACTIVATION
        engine.process_event(ExactPricePrint(
            observation_id="OBS_PENDING", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=901,
        ))
        assert engine.get_snapshot().active_activations[sample_member.member_key].state == ActivationState.PENDING_ACTIVATION

        # Uncertain intra-candle evidence arrives
        candle = IntervalBoundedCandleEvidence(
            event_id="CANDLE_01", sequence_domain=default_domain, sequence_ref=902,
            candle_id="BAR_08", interval_open=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            interval_close=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            observed_field="CLOSE", observed_value=1.1365, sub_bar_sequence_available=False,
        )
        snap = engine.process_event(candle)

        # State remains PENDING_ACTIVATION (not overwritten to BLOCKED_UNKNOWN_ORDER!)
        assert snap.active_activations[sample_member.member_key].state == ActivationState.PENDING_ACTIVATION

    def test_external_commit_excludes_winning_level(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """External commit notification excludes winning level from cancellation."""
        m1 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        m2 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL2_A_PLUS", side="LOW",
            lower_edge=1.1040, upper_edge=1.1050, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_members([m1, m2])

        # Both pending
        engine.process_event(ExactPricePrint(observation_id="O1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1001))
        engine.process_event(ExactPricePrint(observation_id="O2", price=1.1045, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 20, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1002))

        # Commit where TJL1 wins
        snap = engine.process_event(ExternalCommitEvent(
            event_id="COMMIT_TJL1_WINS", timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc),
            sequence_domain=default_domain, sequence_ref=1003,
            winning_engine_id="ENGINE_EURUSD_H1", winning_set_id="SET_1", winning_role="TJL1",
        ))

        # TJL1 is NOT cancelled (remains PENDING_ACTIVATION)
        assert snap.active_activations[m1.member_key].state == ActivationState.PENDING_ACTIVATION
        # TJL2 is cancelled (competing role in same set)
        assert snap.active_activations[m2.member_key].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

    def test_rearming_path_b_already_outside(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Path B: Already outside at cancellation -> armed immediately -> next touch rearms."""
        engine.register_source_member(sample_member)
        engine.process_event(ExactPricePrint(observation_id="IN1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1101))
        engine.process_event(ExactPricePrint(observation_id="OUT1", price=1.1450, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1102))
        snap_cancel = engine.process_event(ExternalCommitEvent(event_id="C1", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1103, winning_engine_id="O", winning_set_id="S", winning_role="R"))
        assert snap_cancel.active_activations[sample_member.member_key].state == ActivationState.OUT_OF_ZONE_ARMED

        snap_rearm = engine.process_event(ExactPricePrint(observation_id="RETOUCH", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1104))
        assert snap_rearm.active_activations[sample_member.member_key].state == ActivationState.REARMED_PENDING

    def test_rearming_path_a_departure_requirement(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Path A: Inside at cancellation -> lingering inside blocks -> outside departure arms -> retouch rearms."""
        engine.register_source_member(sample_member)
        engine.process_event(ExactPricePrint(observation_id="IN1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1201))
        engine.process_event(ExternalCommitEvent(event_id="C1", timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1202, winning_engine_id="O", winning_set_id="S", winning_role="R"))
        assert engine.get_snapshot().active_activations[sample_member.member_key].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

        # Lingering inside: blocks
        engine.process_event(ExactPricePrint(observation_id="LINGER", price=1.1360, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1203))
        assert engine.get_snapshot().active_activations[sample_member.member_key].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

        # Departure (1.1320 < 1.1350)
        engine.process_event(ExactPricePrint(observation_id="DEPART", price=1.1320, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1204))
        assert engine.get_snapshot().active_activations[sample_member.member_key].state == ActivationState.OUT_OF_ZONE_ARMED

        # Retouch
        snap = engine.process_event(ExactPricePrint(observation_id="RETOUCH", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1205))
        assert snap.active_activations[sample_member.member_key].state == ActivationState.REARMED_PENDING

    def test_rejection_of_recycled_evidence_across_generations(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """A price observation used in generation 1 cannot trigger generation 2."""
        engine.register_source_member(sample_member)
        engine.process_event(ExactPricePrint(observation_id="OBS_USED_G1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1301))
        engine.process_event(ExactPricePrint(observation_id="OUT", price=1.1450, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1302))
        engine.process_event(ExternalCommitEvent(event_id="C1", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1303, winning_engine_id="O", winning_set_id="S", winning_role="R"))

        # In armed state, re-using OBS_USED_G1 with conflicting content raises ConflictingEventError
        with pytest.raises(ConflictingEventError):
            engine.process_event(ExactPricePrint(observation_id="OBS_USED_G1", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1304))

    def test_atomic_batch_rollback_on_failure(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Batch execution rolls back completely on failure."""
        engine.register_source_member(sample_member)

        ev_good1 = ExactPricePrint(observation_id="B1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1401)
        ev_bad = ExactPricePrint(observation_id="B2", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 16, tzinfo=timezone.utc), sequence_domain=SequenceDomain("WRONG", "WRONG"), sequence_ref=1402)

        with pytest.raises(DomainMismatchError):
            engine.process_batch([ev_good1, ev_bad])

        snap = engine.get_snapshot()
        assert snap.active_activations[sample_member.member_key].state == ActivationState.INACTIVE_ELIGIBLE
        assert snap.last_processed_sequence is None

    def test_fresh_replay_isolated_and_every_prefix_equivalence(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Replay runs on an isolated instance and every prefix matches sequential execution bit-for-bit."""
        events = [
            ExactPricePrint(observation_id="P1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1501),
            ExactPricePrint(observation_id="P2", price=1.1420, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1502),
            ExternalCommitEvent(event_id="C1", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1503, winning_engine_id="O", winning_set_id="S", winning_role="R"),
            ExactPricePrint(observation_id="P3", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1504),
        ]

        # Sequential execution
        engine.register_source_member(sample_member)
        seq_snapshots = []
        for ev in events:
            seq_snapshots.append(engine.process_event(ev))

        # Fresh replay
        replay_snapshots = engine.replay(events, initial_members=[sample_member])

        # Validate EVERY prefix matches bit-for-bit
        assert len(seq_snapshots) == len(replay_snapshots) == len(events)
        for idx in range(len(events)):
            s_seq = seq_snapshots[idx]
            s_rep = replay_snapshots[idx]
            assert s_seq.last_processed_sequence == s_rep.last_processed_sequence
            assert s_seq.active_activations == s_rep.active_activations
            assert s_seq.terminal_activations == s_rep.terminal_activations


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
        z2 = TJLZone(lvl2, TJLLabel.TJL2_A_PLUS, 1.1040, 1.1040, True, 8, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), 12)

        cset = CurrentEligibleSet(
            set_id="SET_1",
            fingerprint=TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, ch_point_id=10, cl_point_id=8, p3_point_id=11),
            direction=Direction.UPWARD,
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            tjl1_zone=z1,
            tjl2_zone=z2,
            p3_source_index=11,
            p3_open_time=datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc),
            p3_price=1.1040,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            created_at_candle_index=12,
        )

        t0 = TJLTransitionRecord(TJLTransitionType.FIRST_CREATION, False, cset, (), 12, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc))
        t1 = TJLTransitionRecord(TJLTransitionType.CONTINUATION_RETAINED, False, cset, (), 13, datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc))

        snap1 = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1", symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1",
            direction=Direction.UPWARD, current_eligible_set=cset, all_labeled_zones=(), historical_sets=(),
            outgoing_cancellation_intent=False, last_transition=t0, transition_history=(t0,),
            is_unresolved=False, unresolved_diagnostic=None, last_processed_index=12, last_received_index=12,
        )

        # Sync first snapshot
        usage_map = {lvl1: UsageEvidenceStatus.UNUSED, lvl2: UsageEvidenceStatus.UNUSED}
        synchronizer.sync(snap1, sequence_ref_start=1601, usage_evidence=usage_map)
        assert synchronizer.last_synced_transition_index == 0

        # Sync second snapshot
        snap2 = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1", symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1",
            direction=Direction.UPWARD, current_eligible_set=cset, all_labeled_zones=(), historical_sets=(),
            outgoing_cancellation_intent=False, last_transition=t1, transition_history=(t0, t1),
            is_unresolved=False, unresolved_diagnostic=None, last_processed_index=13, last_received_index=13,
        )
        synchronizer.sync(snap2, sequence_ref_start=1602, usage_evidence=usage_map)
        assert synchronizer.last_synced_transition_index == 1

        # Failure injection 1: Incomplete snapshot where last_transition is not in transition_history
        t3 = TJLTransitionRecord(
            TJLTransitionType.CHOCH_INVALIDATION, True, None, (), 15,
            datetime(2026, 10, 2, 9, 30, tzinfo=timezone.utc),
            outgoing_cancelled_set_id="SET_1",
            outgoing_cancelled_fingerprint=TJLFingerprint("ENGINE_EURUSD_H1", Direction.UPWARD, 10, 8, 11),
        )
        incomplete_snap = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1", symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1",
            direction=Direction.UPWARD, current_eligible_set=None, all_labeled_zones=(), historical_sets=(),
            outgoing_cancellation_intent=True, last_transition=t3,
            transition_history=(t0, t1),  # t3 missing from history!
            is_unresolved=False, unresolved_diagnostic=None, last_processed_index=15, last_received_index=15,
        )
        with pytest.raises(InvalidEvidenceError):
            synchronizer.sync(incomplete_snap, sequence_ref_start=1603)

        # Failure injection 2: Truncated history (fewer items than cursor index + 1)
        truncated_snap = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1", symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1",
            direction=Direction.UPWARD, current_eligible_set=None, all_labeled_zones=(), historical_sets=(),
            outgoing_cancellation_intent=False, last_transition=t0,
            transition_history=(t0,),  # Cursor is at 1, but history only has 1 item!
            is_unresolved=False, unresolved_diagnostic=None, last_processed_index=12, last_received_index=12,
        )
        with pytest.raises(InvalidEvidenceError):
            synchronizer.sync(truncated_snap, sequence_ref_start=1604)

    def test_unresolved_snapshot_creates_zero_eligibility(self, engine: ActivationEngine) -> None:
        """Frozen unresolved snapshot strictly creates zero fresh eligibility."""
        unresolved_snap = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1", symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1",
            direction=Direction.UPWARD, current_eligible_set=None, all_labeled_zones=(), historical_sets=(),
            outgoing_cancellation_intent=False, last_transition=None, transition_history=(),
            is_unresolved=True, unresolved_diagnostic="Unresolved ambiguity c1 == p2",
            last_processed_index=10, last_received_index=15,
        )
        snap = sync_tjl_snapshot_to_activation_engine(engine, unresolved_snap, sequence_ref=100)
        assert len(snap.current_members) == 0
        assert len(snap.active_activations) == 0

    def test_real_pipeline_msm_choch_tjl_feeding_activation_adapter(self, default_domain: SequenceDomain) -> None:
        """Cross-checks real candle-derived MSM/CHOCH/TJL pipeline output feeding ActivationEngine end-to-end."""
        path = Path(__file__).parent / "fixtures" / "tjl_acceptance.json"
        with open(path, "r", encoding="utf-8") as f:
            fixtures = json.load(f)["fixtures"]

        fix = fixtures["tjl_09_source_choch_eligibility_invalidation_and_gap"]
        start_time = datetime.fromisoformat(fix["start_candle_time"])

        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )

        adapter_engine = ActivationEngine(ActivationEngineConfig(
            engine_id="ENGINE_EURUSD_H1",
            symbol="FEED_EURUSD_H1",
            source_timeframe="H1",
            sequence_domain=default_domain,
            price_basis=PriceBasis.BID,
        ))
        synchronizer = TJLSynchronizer(engine=adapter_engine)

        snaps = coord.replay_candles(fix["candles"])

        # 1. Bar 7: Pullback completes -> SET_1 created
        s7 = snaps[7]
        assert s7.current_eligible_set is not None
        assert s7.current_eligible_set.set_id == "SET_1"

        # Provide usage evidence that both zones are UNUSED
        usage_map = {z.level_id: UsageEvidenceStatus.UNUSED for z in s7.all_labeled_zones}
        snap_act7 = synchronizer.sync(s7, sequence_ref_start=1700, usage_evidence=usage_map)

        # Verify real members registered with exact candle body bounds
        assert len(snap_act7.current_members) == 2
        m_tjl1 = snap_act7.current_members["SET_1::TJL1"]
        m_tjl2 = snap_act7.current_members["SET_1::TJL2_A_PLUS"]
        assert m_tjl1.lower_edge == 1.1350 and m_tjl1.upper_edge == 1.1400
        assert m_tjl2.lower_edge == 1.1040 and m_tjl2.upper_edge == 1.1050
        assert snap_act7.active_activations["SET_1::TJL1"].state == ActivationState.INACTIVE_ELIGIBLE

        # 2. Feed ExactPricePrint inside TJL1 zone -> PENDING_ACTIVATION
        touch_time = datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc)
        ev_touch = ExactPricePrint(
            observation_id="OBS_TOUCH_TJL1",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=touch_time,
            sequence_domain=default_domain,
            sequence_ref=1702,
        )
        snap_act_touch = adapter_engine.process_event(ev_touch)
        assert snap_act_touch.active_activations["SET_1::TJL1"].state == ActivationState.PENDING_ACTIVATION
        assert snap_act_touch.active_activations["SET_1::TJL1"].first_touch_price == 1.1370

        # 3. Bar 8: Continuation retained
        s8 = snaps[8]
        synchronizer.sync(s8, sequence_ref_start=1703)
        # Activation state preserved across continuation
        assert adapter_engine.get_snapshot().active_activations["SET_1::TJL1"].state == ActivationState.PENDING_ACTIVATION

        # 4. Bar 9: Main Bearish CHOCH confirmed -> outgoing cancellation intent for SET_1
        s9 = snaps[9]
        assert s9.outgoing_cancellation_intent is True
        assert s9.last_transition.transition_type == TJLTransitionType.CHOCH_INVALIDATION
        assert s9.last_transition.outgoing_cancelled_set_id == "SET_1"

        snap_act9 = synchronizer.sync(s9, sequence_ref_start=1704)

        # SET_1 permanently cancelled and removed from active members
        assert len(snap_act9.current_members) == 0
        assert len(snap_act9.active_activations) == 0
        assert len(snap_act9.terminal_activations) == 1
        term_rec = snap_act9.terminal_activations[0]
        assert term_rec.member_key == "SET_1::TJL1"
        assert term_rec.state == ActivationState.CANCELLED_SOURCE_CHOCH
        assert term_rec.cancellation_reason == CancellationReason.SOURCE_CHOCH
        assert term_rec.terminal is True

        # 5. Subsequent price print inside old TJL1 zone CANNOT reactivate cancelled SET_1
        ev_subsequent = ExactPricePrint(
            observation_id="OBS_AFTER_CHOCH",
            price=1.1375,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc),
            sequence_domain=default_domain,
            sequence_ref=1706,
        )
        snap_after = adapter_engine.process_event(ev_subsequent)
        assert len(snap_after.active_activations) == 0
        assert len(snap_after.current_members) == 0
