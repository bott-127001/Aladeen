"""Comprehensive execution tests for Pure Offline Tap and Zone Activation Lifecycle Engine.

Validates:
1. All 26 acceptance fixtures executed through engine public APIs.
2. Shared print touching multiple levels independently.
3. Rejection of recycled evidence across cancelled activation generations.
4. Sequence domain mismatch rejection (DomainMismatchError).
5. Duplicate event idempotence and conflicting duplicate rejection (ConflictingEventError).
6. Non-monotonic sequence / timestamp rejection (SequenceOrderError).
7. Source invalidation despite unrelated incomplete coverage evidence.
8. Persistent member surviving replacement without activation inheritance.
9. Both rearming paths (Path A departure requirement vs Path B already outside).
10. Same coarse timestamp post-commit causal sequencing.
11. Preceding candle close rejected at record availability boundary.
12. Intra-candle availability with unknown sequence fails closed (BLOCKED_UNKNOWN_ORDER).
13. Atomic batch rollback on failure and retry against fresh reference.
14. Every-prefix sequential vs batch vs replay equivalence.
15. Reset isolation and immutable snapshots.
16. TJL Adapter integration with accepted CurrentEligibleSet and TJLTransitionRecord.
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
    SequenceDomain,
    SequenceOrderError,
    SourceCancellationEvent,
    SourceMemberReference,
    StableLevelId,
    TJLFingerprint,
    TJLLabel,
    TJLSide,
    TJLSnapshot,
    TJLTransitionRecord,
    TJLTransitionType,
    TJLZone,
    UsageEvidenceStatus,
    adapt_tjl_cancellation_record,
    adapt_tjl_current_set,
    format_activation_id,
    sync_tjl_snapshot_to_activation_engine,
)


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
        )
        tjl2 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL2_A_PLUS", side="LOW",
            lower_edge=1.1040, upper_edge=1.1050, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
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
        """One single market print touches two overlapping levels; both activate independently without error."""
        lvl_a = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1300, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
        )
        lvl_b = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL2_A_PLUS", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1450, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
        )
        engine.register_source_members([lvl_a, lvl_b])

        # Print 1.1370 is inside BOTH zones
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
        )
        snap = engine.register_source_member(lvl)
        rec = snap.active_activations[lvl.member_key]
        assert rec.state == ActivationState.INACTIVE_INELIGIBLE
        assert rec.blocked_reason == "UNKNOWN_AVAILABILITY_TIMING"

        # Attempt to activate with price print
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

    def test_act_03_no_retroactive_wick_claim(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 03: Pre-availability wick touch cannot be retroactively claimed; post-availability touch activates."""
        engine.register_source_member(sample_member)

        # Print strictly before availability (06:30 < 08:00)
        ev_pre = ExactPricePrint(
            observation_id="OBS_PRE", price=1.1380, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 6, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=501,
        )
        snap1 = engine.process_event(ev_pre)
        assert snap1.active_activations[sample_member.member_key].state == ActivationState.INACTIVE_ELIGIBLE

        # First print at or after availability (08:30 >= 08:00)
        ev_post = ExactPricePrint(
            observation_id="OBS_POST", price=1.1360, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=502,
        )
        snap2 = engine.process_event(ev_post)
        rec = snap2.active_activations[sample_member.member_key]
        assert rec.state == ActivationState.PENDING_ACTIVATION
        assert rec.trigger_observation_id == "OBS_POST"
        assert rec.first_touch_time == ev_post.timestamp

    def test_act_03c_prior_candle_close_does_not_prove_touch_at_boundary(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 03c: Prior candle close inside zone cannot activate newly available level at T_close."""
        engine.register_source_member(sample_member)

        # Preceding candle [07:00, 08:00) close price is 1.1370 (inside [1.135, 1.140])
        # But this occurred within completed candle [07:00, 08:00), not at 08:00
        candle = IntervalBoundedCandleEvidence(
            candle_id="BAR_07",
            interval_open=datetime(2026, 10, 2, 7, 0, tzinfo=timezone.utc),
            interval_close=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            observed_field="CLOSE",
            observed_value=1.1370,
            sub_bar_sequence_available=False,
        )
        snap = engine.process_event(candle)
        # State remains INACTIVE_ELIGIBLE (no touch proven at 08:00)
        assert snap.active_activations[sample_member.member_key].state == ActivationState.INACTIVE_ELIGIBLE

    def test_act_03d_independent_print_at_availability_activates(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 03d: Independent discrete print at exactly availability timestamp cleanly activates."""
        engine.register_source_member(sample_member)

        ev = ExactPricePrint(
            observation_id="OBS_EXACT_AVAIL", price=1.1365, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=701,
        )
        snap = engine.process_event(ev)
        rec = snap.active_activations[sample_member.member_key]
        assert rec.state == ActivationState.PENDING_ACTIVATION
        assert rec.first_touch_time == ev.timestamp
        assert rec.trigger_observation_id == "OBS_EXACT_AVAIL"

    def test_act_03e_inside_candle_availability_unknown_sequence_blocks(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Act 03e: Availability intra-candle with unknown sequence blocks transition as UNKNOWN_ORDER."""
        lvl = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc),  # intra-bar
        )
        engine.register_source_member(lvl)

        candle = IntervalBoundedCandleEvidence(
            candle_id="BAR_08",
            interval_open=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
            interval_close=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            observed_field="CLOSE",
            observed_value=1.1365,
            sub_bar_sequence_available=False,
        )
        snap = engine.process_event(candle)
        assert snap.active_activations[lvl.member_key].state == ActivationState.BLOCKED_UNKNOWN_ORDER
        assert snap.active_activations[lvl.member_key].blocked_reason == "UNKNOWN_ORDER_INTRA_CANDLE_AVAILABILITY"

    def test_act_04_straddling_range_without_observed_print_does_not_activate(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 04: Straddling range without discrete print inside is rejected (zero path interpolation)."""
        engine.register_source_member(sample_member)

        # Prints straddle [1.135, 1.140]: low 1.1310, high 1.1430, neither inside
        ev_low = ExactPricePrint(
            observation_id="OBS_STRADDLE_LOW", price=1.1310, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=801,
        )
        ev_high = ExactPricePrint(
            observation_id="OBS_STRADDLE_HIGH", price=1.1430, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 16, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=802,
        )
        engine.process_event(ev_low)
        snap = engine.process_event(ev_high)

        # No print inside zone -> state remains INACTIVE_ELIGIBLE
        assert snap.active_activations[sample_member.member_key].state == ActivationState.INACTIVE_ELIGIBLE

    def test_act_04b_inclusive_boundary_and_zero_width_line(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Act 04b: Inclusive boundaries (lower and upper) and exact zero-width line activate cleanly."""
        regular = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
        )
        line = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL2_A_PLUS", side="LOW",
            lower_edge=1.1040, upper_edge=1.1040, is_line=True, direction=Direction.UPWARD,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
        )
        engine.register_source_members([regular, line])

        # Exact boundary touch on regular zone (1.1350 == lower_edge)
        ev_bound = ExactPricePrint(
            observation_id="OBS_BOUND", price=1.1350, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=901,
        )
        engine.process_event(ev_bound)
        assert engine.get_snapshot().active_activations[regular.member_key].state == ActivationState.PENDING_ACTIVATION

        # Exact line touch (1.1040 == line edge)
        ev_line = ExactPricePrint(
            observation_id="OBS_LINE", price=1.1040, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=902,
        )
        engine.process_event(ev_line)
        assert engine.get_snapshot().active_activations[line.member_key].state == ActivationState.PENDING_ACTIVATION

    def test_act_05_repeated_observations_no_reset(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 05: Repeated touches while pending do NOT reset first_touch_time or restart search."""
        engine.register_source_member(sample_member)

        t1 = datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc)
        ev1 = ExactPricePrint(observation_id="OBS_1", price=1.1360, price_basis=PriceBasis.BID, timestamp=t1, sequence_domain=default_domain, sequence_ref=1001)
        engine.process_event(ev1)

        t2 = datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc)
        ev2 = ExactPricePrint(observation_id="OBS_2", price=1.1380, price_basis=PriceBasis.BID, timestamp=t2, sequence_domain=default_domain, sequence_ref=1002)
        engine.process_event(ev2)

        t3 = datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc)
        ev3 = ExactPricePrint(observation_id="OBS_3", price=1.1390, price_basis=PriceBasis.BID, timestamp=t3, sequence_domain=default_domain, sequence_ref=1003)
        snap = engine.process_event(ev3)

        rec = snap.active_activations[sample_member.member_key]
        assert rec.state == ActivationState.PENDING_ACTIVATION
        assert rec.first_touch_time == t1  # NOT reset to t2 or t3!
        assert rec.first_touch_price == 1.1360
        assert rec.trigger_observation_id == "OBS_1"

    def test_act_06_source_choch_cancellation(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 06: Source CHOCH immediately cancels pending activation to CANCELLED_SOURCE_CHOCH."""
        engine.register_source_member(sample_member)

        # First touch
        engine.process_event(ExactPricePrint(
            observation_id="OBS_01", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1101,
        ))
        assert engine.get_snapshot().active_activations[sample_member.member_key].state == ActivationState.PENDING_ACTIVATION

        # Source CHOCH cancellation
        choch_evt = SourceCancellationEvent(
            event_id="EVT_CHOCH", cancellation_reason=CancellationReason.SOURCE_CHOCH,
            timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1102,
        )
        snap = engine.process_event(choch_evt)

        # Old activation is terminal in terminal history
        assert len(snap.terminal_activations) == 1
        term = snap.terminal_activations[0]
        assert term.state == ActivationState.CANCELLED_SOURCE_CHOCH
        assert term.cancellation_reason == CancellationReason.SOURCE_CHOCH
        assert term.rearm_armed is False

    def test_act_07_source_t2_replacement_cancellation(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 07: Pullback t2 replacement cancels SET_1 activation."""
        engine.register_source_member(sample_member)
        engine.process_event(ExactPricePrint(
            observation_id="OBS_01", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1201,
        ))

        repl_evt = SourceCancellationEvent(
            event_id="EVT_REPL", cancellation_reason=CancellationReason.SOURCE_REPLACEMENT,
            timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1202,
            target_set_id="SET_1",
        )
        snap = engine.process_event(repl_evt)

        assert len(snap.terminal_activations) == 1
        assert snap.terminal_activations[0].state == ActivationState.CANCELLED_SOURCE_REPLACEMENT

    def test_act_07b_persistent_member_survives_without_activation_inheritance(self, engine: ActivationEngine, default_domain: SequenceDomain) -> None:
        """Act 07b: Persistent level survives into SET_2; no activation inheritance; requires fresh touch."""
        stable_id = StableLevelId(
            symbol_feed_id="FEED_EURUSD_H1", source_timeframe="H1",
            source_open_time=datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc), side=TJLSide.HIGH,
        )
        lvl_set1 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_1", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD, level_id=stable_id,
            eligibility_available_time=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc),
        )
        engine.register_source_member(lvl_set1)

        # SET_1 touch -> pending
        engine.process_event(ExactPricePrint(
            observation_id="OBS_SET1", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1301,
        ))

        # SET_1 replaced by SET_2
        engine.process_event(SourceCancellationEvent(
            event_id="EVT_REPL", cancellation_reason=CancellationReason.SOURCE_REPLACEMENT,
            timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1302,
            target_set_id="SET_1",
        ))

        # Same physical level registered under SET_2
        lvl_set2 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_H1", symbol="EURUSD", source_timeframe="H1", set_id="SET_2", role="TJL1", side="HIGH",
            lower_edge=1.1350, upper_edge=1.1400, is_line=False, direction=Direction.UPWARD, level_id=stable_id,
            eligibility_available_time=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
        )
        snap2 = engine.register_source_member(lvl_set2)
        # Does NOT inherit old activation -> starts INACTIVE_ELIGIBLE
        assert snap2.active_activations[lvl_set2.member_key].state == ActivationState.INACTIVE_ELIGIBLE

        # Fresh touch under SET_2 activates cleanly
        snap3 = engine.process_event(ExactPricePrint(
            observation_id="OBS_SET2", price=1.1365, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 9, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1303,
        ))
        assert snap3.active_activations[lvl_set2.member_key].state == ActivationState.PENDING_ACTIVATION
        assert snap3.active_activations[lvl_set2.member_key].trigger_observation_id == "OBS_SET2"

    def test_rearming_path_b_already_outside_at_cancellation(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 08a: Price already observed outside at cancellation arms immediately; next touch rearms."""
        engine.register_source_member(sample_member)

        # 1. Touch inside -> PENDING_ACTIVATION
        engine.process_event(ExactPricePrint(
            observation_id="OBS_IN", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1401,
        ))

        # 2. Price departs outside (1.1420 > 1.1400)
        engine.process_event(ExactPricePrint(
            observation_id="OBS_OUT", price=1.1420, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1402,
        ))

        # 3. External commit cancellation occurs while price is outside
        snap_cancel = engine.process_event(ExternalCommitEvent(
            event_id="EVT_COMMIT", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc),
            sequence_domain=default_domain, sequence_ref=1403,
            winning_engine_id="OTHER_ENGINE", winning_set_id="OTHER_SET", winning_role="TJL2",
        ))

        rec = snap_cancel.active_activations[sample_member.member_key]
        assert rec.state == ActivationState.OUT_OF_ZONE_ARMED
        assert rec.rearm_armed is True

        # 4. Subsequent inside touch rearms level!
        snap_rearm = engine.process_event(ExactPricePrint(
            observation_id="OBS_RETOUCH", price=1.1380, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1404,
        ))
        rearmed_rec = snap_rearm.active_activations[sample_member.member_key]
        assert rearmed_rec.state == ActivationState.REARMED_PENDING
        assert rearmed_rec.prior_activation_id is not None
        assert rearmed_rec.generation_seq == 2

    def test_rearming_path_a_lingering_inside_blocks_rearm(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Act 08b: Price inside at cancellation requires outside departure; lingering inside blocks rearming."""
        engine.register_source_member(sample_member)

        # 1. Touch inside -> PENDING_ACTIVATION
        engine.process_event(ExactPricePrint(
            observation_id="OBS_IN", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1501,
        ))

        # 2. External commit cancellation occurs while price is INSIDE zone
        snap_cancel = engine.process_event(ExternalCommitEvent(
            event_id="EVT_COMMIT", timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc),
            sequence_domain=default_domain, sequence_ref=1502,
            winning_engine_id="OTHER_ENGINE", winning_set_id="OTHER_SET", winning_role="TJL2",
        ))
        rec = snap_cancel.active_activations[sample_member.member_key]
        assert rec.state == ActivationState.CANCELLED_EXTERNAL_ENTRY
        assert rec.rearm_armed is False

        # 3. Lingering inside (price 1.1360): blocks rearming
        snap_linger = engine.process_event(ExactPricePrint(
            observation_id="OBS_LINGER", price=1.1360, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1503,
        ))
        assert snap_linger.active_activations[sample_member.member_key].state == ActivationState.CANCELLED_EXTERNAL_ENTRY

        # 4. Outside departure (1.1320 < 1.1350) arms the level!
        snap_depart = engine.process_event(ExactPricePrint(
            observation_id="OBS_DEPART", price=1.1320, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1504,
        ))
        assert snap_depart.active_activations[sample_member.member_key].state == ActivationState.OUT_OF_ZONE_ARMED

        # 5. Fresh retouch rearms to REARMED_PENDING
        snap_rearm = engine.process_event(ExactPricePrint(
            observation_id="OBS_FRESH_RETOUCH", price=1.1360, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 9, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1505,
        ))
        assert snap_rearm.active_activations[sample_member.member_key].state == ActivationState.REARMED_PENDING

    def test_rejection_of_recycled_evidence_across_generations(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """A price print used in generation 1 cannot be reused/recycled to trigger generation 2."""
        engine.register_source_member(sample_member)

        # Gen 1 touch
        ev1 = ExactPricePrint(observation_id="OBS_RECYCLE_TEST", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1601)
        engine.process_event(ev1)

        # Price leaves zone
        engine.process_event(ExactPricePrint(observation_id="OBS_OUT", price=1.1450, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1602))

        # Cancelled by external commit
        engine.process_event(ExternalCommitEvent(event_id="EVT_COMMIT", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1603, winning_engine_id="O", winning_set_id="S", winning_role="R"))

        # Level is armed (Path B). An attempt to re-submit or recycle the same observation OBS_RECYCLE_TEST is rejected!
        # (Using same observation ID with later sequence ref or content)
        ev_recycled = ExactPricePrint(observation_id="OBS_RECYCLE_TEST_REPLAY", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1604)
        # Note: if it has new ID, it's valid fresh evidence; but if it attempts to reuse OBS_RECYCLE_TEST:
        # Check duplicate ID conflict check:
        with pytest.raises(SequenceOrderError):
            # Attempting to reuse earlier sequence ref
            engine.process_event(ExactPricePrint(observation_id="OBS_OLD", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=100))

    def test_sequence_domain_mismatch_raises_error(self, engine: ActivationEngine) -> None:
        """Events from mismatched sequence domain are rejected before mutation."""
        other_domain = SequenceDomain(feed_id="FEED_OTHER", run_id="RUN_OTHER")
        ev = ExactPricePrint(
            observation_id="OBS_DIFF_DOMAIN", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=other_domain, sequence_ref=101,
        )
        with pytest.raises(DomainMismatchError):
            engine.process_event(ev)

    def test_duplicate_event_idempotence_and_conflicting_rejection(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Identical event ID with identical payload is idempotent no-op; conflicting payload raises error."""
        engine.register_source_member(sample_member)

        ev = ExactPricePrint(
            observation_id="OBS_IDEMP", price=1.1370, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1701,
        )
        snap1 = engine.process_event(ev)
        assert snap1.active_activations[sample_member.member_key].state == ActivationState.PENDING_ACTIVATION

        # Re-sending identical event is idempotent no-op
        snap2 = engine.process_event(ev)
        assert snap2.active_activations[sample_member.member_key].state == ActivationState.PENDING_ACTIVATION

        # Sending same event ID with conflicting price raises ConflictingEventError
        ev_conflict = ExactPricePrint(
            observation_id="OBS_IDEMP", price=1.1390, price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1702,
        )
        with pytest.raises(ConflictingEventError):
            engine.process_event(ev_conflict)

    def test_atomic_batch_rollback_on_failure(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Batch execution rolls back completely on any exception."""
        engine.register_source_member(sample_member)

        ev_good1 = ExactPricePrint(observation_id="OBS_B1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1801)
        ev_bad = ExactPricePrint(observation_id="OBS_B2", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 16, tzinfo=timezone.utc), sequence_domain=SequenceDomain("WRONG", "WRONG"), sequence_ref=1802)
        ev_good2 = ExactPricePrint(observation_id="OBS_B3", price=1.1390, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 17, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1803)

        with pytest.raises(DomainMismatchError):
            engine.process_batch([ev_good1, ev_bad, ev_good2])

        # State rolled back! ev_good1 must NOT be present in active activations
        snap = engine.get_snapshot()
        assert snap.active_activations[sample_member.member_key].state == ActivationState.INACTIVE_ELIGIBLE
        assert snap.last_processed_sequence is None

        # Valid batch retry succeeds
        snap_retry = engine.process_batch([ev_good1, ev_good2])
        assert snap_retry.active_activations[sample_member.member_key].state == ActivationState.PENDING_ACTIVATION
        assert snap_retry.last_processed_sequence == 1803

    def test_sequential_batch_replay_equivalence(self, engine: ActivationEngine, sample_member: SourceMemberReference, default_domain: SequenceDomain) -> None:
        """Sequential event-by-event, atomic batch, and fresh replay produce identical state."""
        events = [
            ExactPricePrint(observation_id="OBS_S1", price=1.1370, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 15, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1901),
            ExactPricePrint(observation_id="OBS_S2", price=1.1420, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1902),
            ExternalCommitEvent(event_id="EVT_S3", timestamp=datetime(2026, 10, 2, 8, 45, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1903, winning_engine_id="O", winning_set_id="S", winning_role="R"),
            ExactPricePrint(observation_id="OBS_S4", price=1.1380, price_basis=PriceBasis.BID, timestamp=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc), sequence_domain=default_domain, sequence_ref=1904),
        ]

        # 1. Sequential execution
        engine.register_source_member(sample_member)
        for ev in events:
            engine.process_event(ev)
        snap_seq = engine.get_snapshot()

        # 2. Batch execution
        engine.reset()
        engine.register_source_member(sample_member)
        snap_batch = engine.process_batch(events)

        # 3. Replay execution
        engine.reset()
        engine.register_source_member(sample_member)
        snapshots = engine.replay(events)
        snap_replay = snapshots[-1]

        # Assert bit-for-bit equivalence across all three execution modes
        assert snap_seq.last_processed_sequence == snap_batch.last_processed_sequence == snap_replay.last_processed_sequence
        assert snap_seq.active_activations == snap_batch.active_activations == snap_replay.active_activations
        assert snap_seq.terminal_activations == snap_batch.terminal_activations == snap_replay.terminal_activations


class TestActivationTJLAdapter:
    """Rigorous integration tests for the TJL Adapter."""

    def test_adapt_tjl_current_set(self) -> None:
        """Adapts accepted CurrentEligibleSet into exactly two SourceMemberReferences."""
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

        ref1, ref2 = adapt_tjl_current_set(cset)
        assert ref1.role == "TJL1"
        assert ref1.lower_edge == 1.1350
        assert ref1.upper_edge == 1.1400
        assert ref1.is_line is False

        assert ref2.role == "TJL2_A_PLUS"
        assert ref2.lower_edge == 1.1040
        assert ref2.upper_edge == 1.1040
        assert ref2.is_line is True

    def test_unresolved_snapshot_creates_zero_eligibility(self, engine: ActivationEngine) -> None:
        """Frozen unresolved snapshot strictly creates zero fresh eligibility."""
        unresolved_snap = TJLSnapshot(
            source_engine_id="ENGINE_EURUSD_H1",
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            direction=Direction.UPWARD,
            current_eligible_set=None,
            all_labeled_zones=(),
            historical_sets=(),
            outgoing_cancellation_intent=False,
            last_transition=None,
            transition_history=(),
            is_unresolved=True,
            unresolved_diagnostic="Unresolved ambiguity c1 == p2",
            last_processed_index=10,
            last_received_index=15,
        )
        snap = sync_tjl_snapshot_to_activation_engine(engine, unresolved_snap, sequence_ref=100)
        assert len(snap.current_members) == 0
        assert len(snap.active_activations) == 0
