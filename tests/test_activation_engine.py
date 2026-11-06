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
        assert engine.get_snapshot().rearm_controllers[m.member_key].state == ActivationState.OUT_OF_ZONE_ARMED
        assert m.member_key not in engine.get_snapshot().active_activations
        assert len(engine.get_snapshot().terminal_activations) == 1
        assert engine.get_snapshot().terminal_activations[0].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

        # Source CHOCH arrives
        choch = SourceCancellationEvent(event_id="CHOCH1", cancellation_reason=CancellationReason.SOURCE_CHOCH, sequence_domain=default_domain, sequence_ref=504, affected_direction=Direction.UPWARD)
        snap = engine.process_event(choch)

        # Member is completely removed from current members, active activations, and rearm controllers
        assert m.member_key not in snap.current_members
        assert m.member_key not in snap.active_activations
        assert m.member_key not in snap.rearm_controllers
        # Zero duplicate terminal record created for the old activation ID!
        assert len(snap.terminal_activations) == 1

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
        # TJL2 is cancelled (competing role in same set): terminalized and moved to rearm controller
        assert m2.member_key not in snap.active_activations
        assert snap.rearm_controllers[m2.member_key].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

    def test_rearming_path_b_already_outside(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Path B: Already outside at cancellation -> armed immediately -> next touch rearms."""
        engine.register_source_member(sample_member)
        engine.process_event(ExactPricePrint(observation_id="IN1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1101))
        engine.process_event(ExactPricePrint(observation_id="OUT1", price=1.1450, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1102))
        snap_cancel = engine.process_event(ExternalCommitEvent(event_id="C1", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1103, winning_engine_id="O", winning_set_id="S", winning_role="R"))
        assert sample_member.member_key not in snap_cancel.active_activations
        assert snap_cancel.rearm_controllers[sample_member.member_key].state == ActivationState.OUT_OF_ZONE_ARMED
        assert snap_cancel.rearm_controllers[sample_member.member_key].rearm_armed is True

        snap_rearm = engine.process_event(ExactPricePrint(observation_id="RETOUCH", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1104))
        assert snap_rearm.active_activations[sample_member.member_key].state == ActivationState.REARMED_PENDING
        assert sample_member.member_key not in snap_rearm.rearm_controllers

    def test_rearming_path_a_departure_requirement(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Path A: Inside at cancellation -> lingering inside blocks -> outside departure arms -> retouch rearms."""
        engine.register_source_member(sample_member)
        engine.process_event(ExactPricePrint(observation_id="IN1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1201))
        engine.process_event(ExternalCommitEvent(event_id="C1", timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1202, winning_engine_id="O", winning_set_id="S", winning_role="R"))
        assert sample_member.member_key not in engine.get_snapshot().active_activations
        assert engine.get_snapshot().rearm_controllers[sample_member.member_key].state == ActivationState.CANCELLED_EXTERNAL_ENTRY
        assert engine.get_snapshot().rearm_controllers[sample_member.member_key].rearm_armed is False

        # Lingering inside: blocks
        engine.process_event(ExactPricePrint(observation_id="LINGER", price=1.1360, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1203))
        assert engine.get_snapshot().rearm_controllers[sample_member.member_key].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

        # Departure (1.1320 < 1.1350)
        engine.process_event(ExactPricePrint(observation_id="DEPART", price=1.1320, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1204))
        assert engine.get_snapshot().rearm_controllers[sample_member.member_key].state == ActivationState.OUT_OF_ZONE_ARMED
        assert engine.get_snapshot().rearm_controllers[sample_member.member_key].rearm_armed is True

        # Retouch
        snap = engine.process_event(ExactPricePrint(observation_id="RETOUCH", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1205))
        assert snap.active_activations[sample_member.member_key].state == ActivationState.REARMED_PENDING
        assert sample_member.member_key not in snap.rearm_controllers

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

    def test_full_registration_replacement_cancellation_rearm_prefix_replay(self, default_domain: SequenceDomain) -> None:
        """Directive 6: Full multi-phase lifecycle replay matches sequential execution across every prefix bit-for-bit."""
        m_set1_tjl1 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        m_set1_tjl2 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL2_A_PLUS", side="LOW",
            lower_edge=1.1040, upper_edge=1.1050, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        m_set2_tjl1 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_2", role="TJL1", side="HIGH",
            lower_edge=1.1550, upper_edge=1.1600, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc), usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )

        events = [
            RegisterMembersEvent("EVT_REG_1", default_domain, 2001, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), (m_set1_tjl1, m_set1_tjl2)),
            ExactPricePrint("OBS_TOUCH_1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 2002),
            ExactPricePrint("OBS_OUT_1", 1.1420, PriceBasis.BID, datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), default_domain, 2003),
            ExternalCommitEvent("EVT_COMMIT", datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), default_domain, 2004, winning_engine_id="OTHER", winning_set_id="OTHER", winning_role="OTHER"),
            ExactPricePrint("OBS_RETOUCH_1", 1.1380, PriceBasis.BID, datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), default_domain, 2005),
            SourceCancellationEvent(
                event_id="EVT_REPL_SET1",
                cancellation_reason=CancellationReason.SOURCE_REPLACEMENT,
                sequence_domain=default_domain,
                sequence_ref=2006,
                timestamp=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
                target_set_id="SET_1",
            ),
            RegisterMembersEvent("EVT_REG_2", default_domain, 2007, datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc), (m_set2_tjl1,)),
        ]

        engine = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "EURUSD", "H1", default_domain, PriceBasis.BID))
        seq_snapshots = []
        for ev in events:
            seq_snapshots.append(engine.process_event(ev))

        # Isolated replay from baseline
        replay_snapshots = engine.replay(events)

        assert len(seq_snapshots) == len(replay_snapshots) == len(events)
        for idx in range(len(events)):
            s_seq = seq_snapshots[idx]
            s_rep = replay_snapshots[idx]
            assert s_seq.last_processed_sequence == s_rep.last_processed_sequence
            assert s_seq.active_activations == s_rep.active_activations
            assert s_seq.terminal_activations == s_rep.terminal_activations
            assert s_seq.current_members == s_rep.current_members
            assert s_seq.rearm_controllers == s_rep.rearm_controllers


    def test_single_event_failure_leaves_envelope_unconsumed(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Directive 3: Failed single event processing leaves the event envelope completely unconsumed."""
        m_good = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_member(m_good)

        # Baseline sequence ref: None
        assert engine.get_snapshot().last_processed_sequence is None

        # Create invalid RegisterMembersEvent: symbol mismatch
        m_bad = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="WRONG_SYMBOL", source_timeframe="H1", set_id="SET_2", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        bad_event = RegisterMembersEvent(
            event_id="EVT_BAD_REG", sequence_domain=default_domain, sequence_ref=101,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), members=(m_bad,),
        )

        with pytest.raises(InvalidEvidenceError):
            engine.process_event(bad_event)

        # Verification: Envelope is 100% UNCONSUMED
        snap_after_fail = engine.get_snapshot()
        assert snap_after_fail.last_processed_sequence is None
        assert snap_after_fail.last_processed_timestamp is None
        assert "EVT_BAD_REG" not in engine._processed_events

        # Retry at the EXACT SAME sequence ref 101 with a valid event
        m_corrected = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_2", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        good_event = RegisterMembersEvent(
            event_id="EVT_CORRECTED_REG", sequence_domain=default_domain, sequence_ref=101,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), members=(m_corrected,),
        )
        snap_after_retry = engine.process_event(good_event)
        assert snap_after_retry.last_processed_sequence == 101
        assert m_corrected.member_key in snap_after_retry.current_members

        # Fresh reference comparison
        ref_engine = ActivationEngine(engine.config)
        ref_engine.register_source_member(m_good)
        snap_ref = ref_engine.process_event(good_event)
        assert snap_after_retry.active_activations == snap_ref.active_activations
        assert snap_after_retry.current_members == snap_ref.current_members
        assert snap_after_retry.last_processed_sequence == snap_ref.last_processed_sequence

    def test_conflicting_member_registration_rejected_without_mutation(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Directive 4: Conflicting geometry or availability registration for existing member is rejected without mutation."""
        engine.register_source_member(sample_member)
        # Touch -> PENDING_ACTIVATION
        engine.process_event(ExactPricePrint(
            observation_id="OBS_1", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=201,
        ))
        assert engine.get_snapshot().active_activations[sample_member.member_key].state == ActivationState.PENDING_ACTIVATION

        # Conflicting bounds for the same member_key
        conflicting_member = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1200, upper_edge=1.1500,  # CONFLICTING BOUNDS!
            is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=sample_member.eligibility_available_time,
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        with pytest.raises(InvalidEvidenceError):
            engine.register_source_member(conflicting_member)

        # Assert zero mutation: bounds and pending activation intact
        snap = engine.get_snapshot()
        assert snap.current_members[sample_member.member_key].lower_edge == 1.1350
        assert snap.current_members[sample_member.member_key].upper_edge == 1.1400
        assert snap.active_activations[sample_member.member_key].state == ActivationState.PENDING_ACTIVATION

    def test_terminal_activation_ids_remain_globally_unique(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Directive 5: Terminal activation IDs remain globally unique across commit -> arm -> source invalidation."""
        engine.register_source_member(sample_member)
        engine.process_event(ExactPricePrint(observation_id="O1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=301))
        engine.process_event(ExactPricePrint(observation_id="O2", price=1.1420, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=302))

        # External commit -> terminalizes ACT::...::01, arms controller for gen 2
        engine.process_event(ExternalCommitEvent(event_id="C1", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=303, winning_engine_id="O", winning_set_id="S", winning_role="R"))

        # Source CHOCH invalidation arrives
        engine.process_event(SourceCancellationEvent(event_id="CH1", cancellation_reason=CancellationReason.SOURCE_CHOCH, sequence_domain=default_domain, sequence_ref=304, affected_direction=Direction.UPWARD))

        snap = engine.get_snapshot()
        term_ids = [a.activation_id for a in snap.terminal_activations]
        assert len(term_ids) == 1
        assert len(term_ids) == len(set(term_ids))
        assert term_ids[0] == format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 1)

    def test_rearm_controller_retouch_creates_linked_new_generation(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Directive 5: Qualifying retouch after departure creates a brand-new activation ID linked to prior."""
        engine.register_source_member(sample_member)
        # Gen 1 touch
        engine.process_event(ExactPricePrint(observation_id="O1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=401))
        # Commit while inside
        engine.process_event(ExternalCommitEvent(event_id="C1", timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=402, winning_engine_id="O", winning_set_id="S", winning_role="R"))

        # Depart outside
        engine.process_event(ExactPricePrint(observation_id="O_DEP", price=1.1300, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=403))
        # Retouch inside
        snap = engine.process_event(ExactPricePrint(observation_id="O_RET", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=404))

        act_gen2 = snap.active_activations[sample_member.member_key]
        assert act_gen2.generation_seq == 2
        assert act_gen2.activation_id == format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 2)
        assert act_gen2.prior_activation_id == format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 1)
        assert act_gen2.state == ActivationState.REARMED_PENDING

        # Terminal history contains gen 1
        assert len(snap.terminal_activations) == 1
        assert snap.terminal_activations[0].generation_seq == 1
        assert snap.terminal_activations[0].activation_id == format_activation_id("ENGINE_EURUSD_H1", "H1", "EURUSD", "SET_1", "TJL1", 1)

    def test_exact_price_print_before_vs_at_availability(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Direct Assertion: Pre-availability print produces zero activation; print exactly at availability activates."""
        from datetime import timedelta
        engine.register_source_member(sample_member)
        avail_time = sample_member.eligibility_available_time

        # Print 1 second before availability
        snap_before = engine.process_event(ExactPricePrint(
            observation_id="OBS_PRE",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=avail_time - timedelta(seconds=1),
            sequence_domain=default_domain,
            sequence_ref=101,
        ))
        # Member remains INACTIVE_ELIGIBLE; zero active activation
        assert snap_before.active_activations[sample_member.member_key].state == ActivationState.INACTIVE_ELIGIBLE

        # Print exactly at availability timestamp
        snap_at = engine.process_event(ExactPricePrint(
            observation_id="OBS_AT",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=avail_time,
            sequence_domain=default_domain,
            sequence_ref=102,
        ))
        # Member transitions to PENDING_ACTIVATION
        act = snap_at.active_activations[sample_member.member_key]
        assert act.state == ActivationState.PENDING_ACTIVATION
        assert act.first_touch_time == avail_time
        assert act.first_touch_price == 1.1370

    @pytest.mark.parametrize(
        "lower_edge,upper_edge,is_line,test_price,should_activate",
        [
            (1.1350, 1.1400, False, 1.1350, True),     # Exact lower boundary
            (1.1350, 1.1400, False, 1.1400, True),     # Exact upper boundary
            (1.1350, 1.1350, True, 1.1350, True),      # Exact zero-width line
            (1.1350, 1.1400, False, 1.13499, False),   # Strictly below lower boundary
            (1.1350, 1.1400, False, 1.14001, False),   # Strictly above upper boundary
        ],
    )
    def test_exact_price_print_boundaries_and_zero_width(
        self, default_domain: SequenceDomain, lower_edge: float, upper_edge: float, is_line: bool, test_price: float, should_activate: bool
    ) -> None:
        """Direct Assertion: Exact upper/lower boundaries and zero-width lines activate cleanly; outside prices do not."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        member = SourceMemberReference(
            engine_id="ENGINE_TEST", symbol="FEED_EURUSD_H1", source_timeframe="H1", set_id="SET_1", role="TJL1",
            side="HIGH", lower_edge=lower_edge, upper_edge=upper_edge, is_line=is_line, direction=Direction.UPWARD,
            level_id=lvl, eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        eng.register_source_member(member)
        snap = eng.process_event(ExactPricePrint(
            observation_id="OBS_TEST",
            price=test_price,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc),
            sequence_domain=default_domain,
            sequence_ref=201,
        ))
        act = snap.active_activations[member.member_key]
        if should_activate:
            assert act.state == ActivationState.PENDING_ACTIVATION
            assert act.first_touch_price == test_price
        else:
            assert act.state == ActivationState.INACTIVE_ELIGIBLE

    def test_prior_candle_close_and_range_only_evidence_produces_zero_activation(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Direct Assertion: Prior completed-candle close and candidate range straddle without discrete print produce zero activation."""
        from datetime import timedelta
        engine.register_source_member(sample_member)
        avail_time = sample_member.eligibility_available_time

        # Prior completed candle close at 07:59:59 (before level availability)
        snap1 = engine.process_event(ExactPricePrint(
            observation_id="OBS_PRIOR_CLOSE",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=avail_time - timedelta(seconds=1),
            sequence_domain=default_domain,
            sequence_ref=301,
        ))
        assert snap1.active_activations[sample_member.member_key].state == ActivationState.INACTIVE_ELIGIBLE

        # Candidate range straddle without observed discrete print inside zone:
        snap2 = engine.process_event(ExactPricePrint(
            observation_id="OBS_ABOVE",
            price=1.1410,
            price_basis=PriceBasis.BID,
            timestamp=avail_time + timedelta(minutes=5),
            sequence_domain=default_domain,
            sequence_ref=302,
        ))
        assert snap2.active_activations[sample_member.member_key].state == ActivationState.INACTIVE_ELIGIBLE

        snap3 = engine.process_event(ExactPricePrint(
            observation_id="OBS_BELOW",
            price=1.1340,
            price_basis=PriceBasis.BID,
            timestamp=avail_time + timedelta(minutes=10),
            sequence_domain=default_domain,
            sequence_ref=303,
        ))
        assert snap3.active_activations[sample_member.member_key].state == ActivationState.INACTIVE_ELIGIBLE

    def test_unknown_interval_order_fresh_vs_pending_members(self, default_domain: SequenceDomain) -> None:
        """Direct Assertion: Unknown interval ordering blocks fresh activation fail-closed, while preserving existing pending activation."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        avail = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        m1 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl1, avail, UsageEvidenceStatus.UNUSED)
        m2 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL2_A_PLUS", "LOW", 1.1040, 1.1050, False, Direction.UPWARD, lvl2, avail, UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m1, m2])

        # Touch m1 with authoritative discrete print at availability -> PENDING_ACTIVATION
        eng.process_event(ExactPricePrint("OBS_1", 1.1370, PriceBasis.BID, avail, default_domain, 401))
        assert eng.get_snapshot().active_activations[m1.member_key].state == ActivationState.PENDING_ACTIVATION
        # m2 is fresh (INACTIVE_ELIGIBLE)
        assert eng.get_snapshot().active_activations[m2.member_key].state == ActivationState.INACTIVE_ELIGIBLE

        # Intra-candle availability with unknown sub-bar sequence arrives at 08:35 close
        candle = IntervalBoundedCandleEvidence(
            event_id="CANDLE_TEST_01",
            sequence_domain=default_domain,
            sequence_ref=402,
            candle_id="BAR_15",
            interval_open=datetime(2026, 10, 2, 8, 25, tzinfo=timezone.utc),
            interval_close=datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc),
            observed_field="LOW",
            observed_value=1.1000,
            sub_bar_sequence_available=False,
        )
        snap_candle = eng.process_event(candle)

        # 1. m1 retains authoritative PENDING_ACTIVATION (not downgraded!)
        assert snap_candle.active_activations[m1.member_key].state == ActivationState.PENDING_ACTIVATION
        # 2. Fresh m2 fails closed with BLOCKED_UNKNOWN_ORDER (zero speculative activation!)
        assert snap_candle.active_activations[m2.member_key].state == ActivationState.BLOCKED_UNKNOWN_ORDER

    def test_two_reactivations_at_same_coarse_timestamp_with_distinct_sequence_refs(self, default_domain: SequenceDomain) -> None:
        """Directive 3: Two distinct reactivations sharing coarse timestamp T create distinct linked new generation IDs ordered by sequence."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        lvl2 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc), TJLSide.LOW)
        m1 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl1, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        m2 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL2_A_PLUS", "LOW", 1.1040, 1.1050, False, Direction.UPWARD, lvl2, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m1, m2])

        # Gen 1 touches
        eng.process_event(ExactPricePrint("O1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 501))
        eng.process_event(ExactPricePrint("O2", 1.1045, PriceBasis.BID, datetime(2026, 10, 2, 8, 20, tzinfo=timezone.utc), default_domain, 502))
        # Commit / external cancellation -> terminalizes gen 1 for both
        eng.process_event(ExternalCommitEvent("C1", datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), default_domain, 503, winning_engine_id="OTHER", winning_set_id="SET_X", winning_role="R"))

        # Outside departure for both
        eng.process_event(ExactPricePrint("O_DEP", 1.1200, PriceBasis.BID, datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), default_domain, 504))

        # At identical coarse timestamp T = 09:00:00 UTC, retouch m1 at seq 505, and retouch m2 at seq 506
        t_shared = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
        eng.process_event(ExactPricePrint("O_RET1", 1.1370, PriceBasis.BID, t_shared, default_domain, 505))
        snap = eng.process_event(ExactPricePrint("O_RET2", 1.1045, PriceBasis.BID, t_shared, default_domain, 506))

        # Both are REARMED_PENDING in generation 2 with distinct IDs and correct prior linkages
        act1 = snap.active_activations[m1.member_key]
        assert act1.generation_seq == 2
        assert act1.state == ActivationState.REARMED_PENDING
        assert act1.activation_id == format_activation_id("ENGINE_TEST", "H1", "FEED_EURUSD_H1", "SET_1", "TJL1", 2)
        assert act1.prior_activation_id == format_activation_id("ENGINE_TEST", "H1", "FEED_EURUSD_H1", "SET_1", "TJL1", 1)

        act2 = snap.active_activations[m2.member_key]
        assert act2.generation_seq == 2
        assert act2.state == ActivationState.REARMED_PENDING
        assert act2.activation_id == format_activation_id("ENGINE_TEST", "H1", "FEED_EURUSD_H1", "SET_1", "TJL2_A_PLUS", 2)
        assert act2.prior_activation_id == format_activation_id("ENGINE_TEST", "H1", "FEED_EURUSD_H1", "SET_1", "TJL2_A_PLUS", 1)


    def test_rearm_controller_inside_at_cancel_incomplete_coverage_departure_blocks_rearm(self, default_domain: SequenceDomain) -> None:
        """Directive 2: Departure under incomplete coverage fails closed; does not arm and blocks subsequent retouch."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m1 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl1, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m1])

        # Touch at 08:15 -> PENDING_ACTIVATION
        eng.process_event(ExactPricePrint("O1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 601))
        # Commit at 08:30 -> CANCELLED_EXTERNAL_ENTRY (inside at cancel)
        eng.process_event(ExternalCommitEvent("C1", datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), default_domain, 602, winning_engine_id="OTHER", winning_set_id="SET_X", winning_role="R"))
        assert m1.member_key in eng.get_snapshot().rearm_controllers
        assert eng.get_snapshot().rearm_controllers[m1.member_key].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

        # Incomplete coverage event arrives
        eng.process_event(CoverageEvidence("COV_INC", default_domain, 603, CoverageStatus.INCOMPLETE, "FEED_EURUSD_H1", missing_gap_count=1, timestamp=datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc)))

        # Outside departure print under incomplete coverage
        eng.process_event(ExactPricePrint("O_DEP_INC", 1.1200, PriceBasis.BID, datetime(2026, 10, 2, 8, 40, tzinfo=timezone.utc), default_domain, 604))
        # Controller MUST NOT be armed! Remains in CANCELLED_EXTERNAL_ENTRY
        ctrl = eng.get_snapshot().rearm_controllers[m1.member_key]
        assert ctrl.state == ActivationState.CANCELLED_EXTERNAL_ENTRY
        assert ctrl.rearm_armed is False

        # Subsequent inside print must NOT rearm
        eng.process_event(ExactPricePrint("O_RET_INC", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), default_domain, 605))
        assert len(eng.get_snapshot().active_activations) == 0

    def test_rearm_controller_already_armed_incomplete_coverage_retouch_blocks_rearm(self, default_domain: SequenceDomain) -> None:
        """Directive 2: An already-armed controller under incomplete coverage fails closed upon retouch."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m1 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl1, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m1])

        # Touch -> Commit -> Valid outside departure under COMPLETE coverage
        eng.process_event(ExactPricePrint("O1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 701))
        eng.process_event(ExternalCommitEvent("C1", datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), default_domain, 702, winning_engine_id="OTHER", winning_set_id="SET_X", winning_role="R"))
        eng.process_event(ExactPricePrint("O_DEP", 1.1200, PriceBasis.BID, datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc), default_domain, 703))
        assert eng.get_snapshot().rearm_controllers[m1.member_key].state == ActivationState.OUT_OF_ZONE_ARMED

        # Incomplete coverage arrives
        eng.process_event(CoverageEvidence("COV_INC", default_domain, 704, CoverageStatus.INCOMPLETE, "FEED_EURUSD_H1", missing_gap_count=1, timestamp=datetime(2026, 10, 2, 8, 40, tzinfo=timezone.utc)))

        # Inside retouch print under incomplete coverage MUST NOT create REARMED_PENDING
        eng.process_event(ExactPricePrint("O_RET", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), default_domain, 705))
        assert len(eng.get_snapshot().active_activations) == 0
        # Controller remains preserved
        assert eng.get_snapshot().rearm_controllers[m1.member_key].state == ActivationState.OUT_OF_ZONE_ARMED

    def test_rearm_controller_with_unknown_or_used_usage_blocks_rearm(self, default_domain: SequenceDomain) -> None:
        """Directive 2: A controller whose member usage changed to UNKNOWN or USED blocks new rearmed activation."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m1 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl1, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m1])

        # Touch -> Commit -> Valid outside departure
        eng.process_event(ExactPricePrint("O1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 801))
        eng.process_event(ExternalCommitEvent("C1", datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), default_domain, 802, winning_engine_id="OTHER", winning_set_id="SET_X", winning_role="R"))
        eng.process_event(ExactPricePrint("O_DEP", 1.1200, PriceBasis.BID, datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc), default_domain, 803))
        assert eng.get_snapshot().rearm_controllers[m1.member_key].state == ActivationState.OUT_OF_ZONE_ARMED

        # Member usage changes to UNKNOWN
        m_unknown = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl1, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNKNOWN)
        eng.register_source_members([m_unknown])

        # Touch while usage is UNKNOWN -> blocked! Controller remains preserved and no rearmed activation created
        eng.process_event(ExactPricePrint("O_RET_UNK", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 40, tzinfo=timezone.utc), default_domain, 804))
        snap_unk = eng.get_snapshot()
        assert snap_unk.rearm_controllers[m1.member_key].state == ActivationState.OUT_OF_ZONE_ARMED
        assert snap_unk.active_activations[m1.member_key].state != ActivationState.REARMED_PENDING

        # Member usage changes to USED
        m_used = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl1, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.USED)
        eng.register_source_members([m_used])

        # Touch while usage is USED -> blocked! Controller remains preserved and no rearmed activation created
        eng.process_event(ExactPricePrint("O_RET_USED", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), default_domain, 805))
        snap_used = eng.get_snapshot()
        assert snap_used.rearm_controllers[m1.member_key].state == ActivationState.OUT_OF_ZONE_ARMED
        assert snap_used.active_activations[m1.member_key].state != ActivationState.REARMED_PENDING

    def test_rearm_controller_valid_later_evidence_activates_cleanly_without_recycled_blocked_evidence(self, default_domain: SequenceDomain) -> None:
        """Directive 2: When valid coverage and unused evidence arrive later, controller transitions cleanly without recycling blocked observations."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl1 = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m1 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl1, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m1])

        # Touch at 08:15 -> Commit at 08:30 (inside at cancel)
        eng.process_event(ExactPricePrint("O1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 901))
        eng.process_event(ExternalCommitEvent("C1", datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), default_domain, 902, winning_engine_id="OTHER", winning_set_id="SET_X", winning_role="R"))

        # Incomplete coverage
        eng.process_event(CoverageEvidence("COV_INC", default_domain, 903, CoverageStatus.INCOMPLETE, "FEED_EURUSD_H1", timestamp=datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc)))
        # Blocked departure
        eng.process_event(ExactPricePrint("O_DEP_BLOCKED", 1.1200, PriceBasis.BID, datetime(2026, 10, 2, 8, 40, tzinfo=timezone.utc), default_domain, 904))
        assert eng.get_snapshot().rearm_controllers[m1.member_key].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

        # Coverage restored to COMPLETE
        eng.process_event(CoverageEvidence("COV_OK", default_domain, 905, CoverageStatus.COMPLETE, "FEED_EURUSD_H1", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc)))
        # Valid outside departure under COMPLETE coverage
        eng.process_event(ExactPricePrint("O_DEP_VALID", 1.1200, PriceBasis.BID, datetime(2026, 10, 2, 8, 50, tzinfo=timezone.utc), default_domain, 906))
        assert eng.get_snapshot().rearm_controllers[m1.member_key].state == ActivationState.OUT_OF_ZONE_ARMED

        # Fresh inside retouch print
        snap = eng.process_event(ExactPricePrint("O_RET_VALID", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 55, tzinfo=timezone.utc), default_domain, 907))
        assert m1.member_key in snap.active_activations
        act = snap.active_activations[m1.member_key]
        assert act.state == ActivationState.REARMED_PENDING
        assert act.generation_seq == 2
        assert act.prior_activation_id == format_activation_id("ENGINE_TEST", "H1", "FEED_EURUSD_H1", "SET_1", "TJL1", 1)

    def test_external_commit_unsupported_scope_fails_closed_and_retry_succeeds(self, default_domain: SequenceDomain) -> None:
        """Directive 1 & 3: Unsupported commit scope leaves full checkpoint unchanged; valid retry at unconsumed sequence succeeds."""
        config = ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID)
        eng = ActivationEngine(config)
        lvl = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m1 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        m2 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_2", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m1, m2])
        eng.process_event(ExactPricePrint("OBS_1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 100))

        # Capture baseline checkpoint
        pre_fail_cp = eng.create_checkpoint()

        # 1. Unsupported cancellation scope fails closed with InvalidEvidenceError
        bad_commit = ExternalCommitEvent(
            event_id="COMMIT_BAD", timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc),
            sequence_domain=default_domain, sequence_ref=200, winning_engine_id="OTHER",
            winning_set_id="OTHER_SET", winning_role="TJL1", cancelled_competing_scope="UNSUPPORTED_GLOBAL"
        )
        with pytest.raises(InvalidEvidenceError, match="Unsupported external commit scope"):
            eng.process_event(bad_commit)

        # 2. Checkpoint is completely unchanged; sequence 200 was unconsumed
        assert eng.create_checkpoint() == pre_fail_cp
        assert "COMMIT_BAD" not in eng._processed_events
        assert eng._last_processed_sequence == 100

        # 3. Valid retry at unconsumed sequence 200 succeeds without sequence error
        good_commit = ExternalCommitEvent(
            event_id="COMMIT_GOOD", timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc),
            sequence_domain=default_domain, sequence_ref=200, winning_engine_id="ENGINE_TEST",
            winning_set_id="SET_1", winning_role="TJL1", cancelled_competing_scope="SAME_SOURCE_TIMEFRAME"
        )
        snap = eng.process_event(good_commit)
        # Winner (SET_1) preserved in active; competitor (SET_2) terminalized to CANCELLED_EXTERNAL_ENTRY
        assert m1.member_key in snap.active_activations
        assert snap.active_activations[m1.member_key].state == ActivationState.PENDING_ACTIVATION
        assert m2.member_key not in snap.active_activations
        assert len(snap.terminal_activations) == 1
        assert snap.terminal_activations[0].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

    def test_source_cancellation_unsupported_role_and_contradictory_targets_rejected(self, default_domain: SequenceDomain) -> None:
        """Directive 2 & 3: Partial-role target and contradictory target combinations reject atomically."""
        config = ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID)
        eng = ActivationEngine(config)
        lvl = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        eng.register_source_member(m)

        cp = eng.create_checkpoint()

        # 1. Partial-role targeting rejected
        bad_role_ev = SourceCancellationEvent("CAN_ROLE", CancellationReason.SOURCE_CHOCH, default_domain, 101, datetime(2026, 10, 2, 8, 10, tzinfo=timezone.utc), target_role="TJL1", affected_direction=Direction.UPWARD)
        with pytest.raises(InvalidEvidenceError, match="Partial-role targeting is not supported"):
            eng.process_event(bad_role_ev)
        assert eng.create_checkpoint() == cp

        # 2. SOURCE_REPLACEMENT without target_set_id rejected
        bad_repl = SourceCancellationEvent("CAN_REPL", CancellationReason.SOURCE_REPLACEMENT, default_domain, 102, datetime(2026, 10, 2, 8, 10, tzinfo=timezone.utc), target_set_id=None)
        with pytest.raises(InvalidEvidenceError, match="requires non-empty target_set_id"):
            eng.process_event(bad_repl)
        assert eng.create_checkpoint() == cp

        # 3. SOURCE_CHOCH without target_set_id or direction rejected
        bad_choch = SourceCancellationEvent("CAN_CHOCH", CancellationReason.SOURCE_CHOCH, default_domain, 103, datetime(2026, 10, 2, 8, 10, tzinfo=timezone.utc), target_set_id=None, affected_direction=None)
        with pytest.raises(InvalidEvidenceError, match="requires target_set_id and/or affected_direction"):
            eng.process_event(bad_choch)
        assert eng.create_checkpoint() == cp

        # 4. Contradictory targets: SET_1 is UPWARD, declaring affected_direction DOWNWARD rejects
        bad_contra = SourceCancellationEvent("CAN_CONTRA", CancellationReason.SOURCE_CHOCH, default_domain, 104, datetime(2026, 10, 2, 8, 10, tzinfo=timezone.utc), target_set_id="SET_1", affected_direction=Direction.DOWNWARD)
        with pytest.raises(InvalidEvidenceError, match="Contradictory cancellation targets"):
            eng.process_event(bad_contra)
        assert eng.create_checkpoint() == cp

    def test_targeted_source_cancellation_cannot_affect_unrelated_set(self, default_domain: SequenceDomain) -> None:
        """Directive 2 & 3: Targeted cancellation affects only declared target; unrelated set preserved."""
        config = ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID)
        eng = ActivationEngine(config)
        lvl = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m1 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        m2 = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_2", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m1, m2])
        eng.process_event(ExactPricePrint("OBS_1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 100))

        # Target SET_1 for replacement
        snap = eng.process_event(SourceCancellationEvent("CAN_SET1", CancellationReason.SOURCE_REPLACEMENT, default_domain, 101, datetime(2026, 10, 2, 8, 20, tzinfo=timezone.utc), target_set_id="SET_1"))
        assert m1.member_key not in snap.current_members
        assert m1.member_key not in snap.active_activations
        # SET_2 completely preserved!
        assert m2.member_key in snap.current_members
        assert m2.member_key in snap.active_activations
        assert snap.active_activations[m2.member_key].state == ActivationState.PENDING_ACTIVATION

    def test_supported_roles_validation(self) -> None:
        """Directive 3: Validates supported roles and rejects undocumented roles."""
        from aladeen.strategy.activation_types import SUPPORTED_SOURCE_ROLES
        assert SUPPORTED_SOURCE_ROLES == frozenset({"TJL1", "TJL2_A_PLUS"})

        # Valid roles succeed
        m1 = SourceMemberReference("E", "S", "H1", "SET_1", "TJL1", "HIGH", 1.10, 1.20, False, Direction.UPWARD)
        m2 = SourceMemberReference("E", "S", "H1", "SET_1", "TJL2_A_PLUS", "LOW", 1.10, 1.20, False, Direction.UPWARD)
        assert m1.role == "TJL1"
        assert m2.role == "TJL2_A_PLUS"

        # Invalid roles fail closed with ValueError
        for bad_role in ("INVALID", "CH1", "CL1", "TJL3", ""):
            with pytest.raises(ValueError, match="Unsupported role"):
                SourceMemberReference("E", "S", "H1", "SET_1", bad_role, "HIGH", 1.10, 1.20, False, Direction.UPWARD)

    def test_conflicting_duplicate_members_in_same_batch_rejected_before_mutation(self, default_domain: SequenceDomain) -> None:
        """Directive 4: Prevalidates conflicting duplicate keys within one registration call and asserts complete rollback."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m_good = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        m_conflict = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1200, 1.1300, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)

        # Batch contains conflicting duplicates for the same member key
        with pytest.raises(InvalidEvidenceError, match="Conflicting member registration within submitted batch"):
            eng.register_source_members([m_good, m_conflict])

        # Assert 100% no-mutation rollback: zero members registered
        assert len(eng.get_snapshot().current_members) == 0
        assert len(eng.get_snapshot().active_activations) == 0

    def test_identical_duplicate_members_in_same_batch_coalesced(self, default_domain: SequenceDomain) -> None:
        """Directive 4: Identical duplicate candidates within the same registration call are coalesced cleanly."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_TEST", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m = SourceMemberReference("ENGINE_TEST", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)

        snap = eng.register_source_members([m, m, m])
        assert len(snap.current_members) == 1
        assert m.member_key in snap.current_members


    def test_coverage_evidence_scope_and_stale_rejection(self, default_domain: SequenceDomain) -> None:
        """Directive 4: Coverage evidence respects scope filtering, enforces monotonic ordering, and enables ordered restoration."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        m = SourceMemberReference("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl, datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m])

        # 1. Coverage evidence with unrelated scope does not affect this engine
        eng.process_event(CoverageEvidence("COV_OTHER", default_domain, 201, CoverageStatus.INCOMPLETE, scope="GBPUSD_H1", missing_gap_count=5, timestamp=datetime(2026, 10, 2, 8, 5, tzinfo=timezone.utc)))
        assert eng.get_snapshot().coverage_status == CoverageStatus.COMPLETE

        # 2. Coverage evidence matching symbol/timeframe sets coverage to INCOMPLETE
        eng.process_event(CoverageEvidence("COV_INCOMPLETE", default_domain, 202, CoverageStatus.INCOMPLETE, scope="FEED_EURUSD_H1", missing_gap_count=1, timestamp=datetime(2026, 10, 2, 8, 10, tzinfo=timezone.utc)))
        assert eng.get_snapshot().coverage_status == CoverageStatus.INCOMPLETE

        # While incomplete, inside print produces zero activation (remains INACTIVE_ELIGIBLE)
        eng.process_event(ExactPricePrint("O1", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), default_domain, 203))
        assert eng.get_snapshot().active_activations[m.member_key].state == ActivationState.INACTIVE_ELIGIBLE

        # 3. Stale / out-of-order sequence ref rejected with SequenceOrderError
        with pytest.raises(SequenceOrderError):
            eng.process_event(CoverageEvidence("COV_STALE", default_domain, 202, CoverageStatus.COMPLETE, scope="FEED_EURUSD_H1", timestamp=datetime(2026, 10, 2, 8, 16, tzinfo=timezone.utc)))

        # 4. Ordered restoration back to COMPLETE restores activation capability
        eng.process_event(CoverageEvidence("COV_RESTORED", default_domain, 204, CoverageStatus.COMPLETE, scope="FEED_EURUSD_H1", timestamp=datetime(2026, 10, 2, 8, 20, tzinfo=timezone.utc)))
        assert eng.get_snapshot().coverage_status == CoverageStatus.COMPLETE

        snap_act = eng.process_event(ExactPricePrint("O2", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 25, tzinfo=timezone.utc), default_domain, 205))
        assert snap_act.active_activations[m.member_key].state == ActivationState.PENDING_ACTIVATION

    def test_unknown_order_recovery_with_subsequent_exact_print(self, default_domain: SequenceDomain) -> None:
        """Directive 4: A member placed into BLOCKED_UNKNOWN_ORDER by uncertain candle evidence recovers cleanly upon subsequent exact print."""
        eng = ActivationEngine(ActivationEngineConfig("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", default_domain, PriceBasis.BID))
        lvl = StableLevelId("FEED_EURUSD_H1", "H1", datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        avail = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        m = SourceMemberReference("ENGINE_EURUSD_H1", "FEED_EURUSD_H1", "H1", "SET_1", "TJL1", "HIGH", 1.1350, 1.1400, False, Direction.UPWARD, lvl, avail, UsageEvidenceStatus.UNUSED)
        eng.register_source_members([m])

        # Candle straddles availability with unknown intra-bar sequence -> BLOCKED_UNKNOWN_ORDER
        candle = IntervalBoundedCandleEvidence(
            event_id="CANDLE_01",
            sequence_domain=default_domain,
            sequence_ref=301,
            candle_id="BAR_10",
            interval_open=datetime(2026, 10, 2, 8, 25, tzinfo=timezone.utc),
            interval_close=datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc),
            observed_field="HIGH",
            observed_value=1.1450,
            sub_bar_sequence_available=False,
        )
        snap_candle = eng.process_event(candle)
        assert snap_candle.active_activations[m.member_key].state == ActivationState.BLOCKED_UNKNOWN_ORDER

        # Subsequent discrete price print inside zone at 08:35 recovers the blocked level cleanly
        print_recovery = ExactPricePrint("O_REC", 1.1370, PriceBasis.BID, datetime(2026, 10, 2, 8, 35, tzinfo=timezone.utc), default_domain, 302)
        snap_rec = eng.process_event(print_recovery)
        assert snap_rec.active_activations[m.member_key].state == ActivationState.PENDING_ACTIVATION
        assert snap_rec.active_activations[m.member_key].generation_seq == 1
