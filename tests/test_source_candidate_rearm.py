"""Offline source-to-candidate integration proof tests — Rearm Controllers & Generation Sequencing.

Note: These tests verify engine lifecycle transitions and matcher ordering contracts under supplied
synthetic member/evidence contracts. They do not independently establish candle-derived source/confirmation chains.

Covers:
- ACT-01: Rearm Path A (inside-at-cancel):
  * Gen 1 touch inside zone -> external commit event while inside transitions Gen 1 to
    terminal CANCELLED_EXTERNAL_ENTRY (permanently immutable in terminal_activations).
  * Decoupled RearmController spawned with last_observed_position="INSIDE", rearm_armed=False.
  * Fresh outside print strictly later transitions controller to OUT_OF_ZONE_ARMED.
  * Fresh inside retouch print strictly later creates linked Gen 2 ActivationRecord in
    REARMED_PENDING (generation_seq=2, prior_activation_id=act1.activation_id).
  * Stale Gen 1 confirmation rejected fail-closed as PRE_ACTIVATION_CONFIRMATION.
  * Fresh Gen 2 confirmation matches with exact runtime-derived candidate setup key.
- ACT-04: Rearm Path B (already outside at cancellation):
  * Gen 1 touch inside zone -> outside observation -> external commit while outside.
  * Decoupled controller arms directly as OUT_OF_ZONE_ARMED without redundant departure requirement.
  * Subsequent retouch print creates Gen 2 ActivationRecord in REARMED_PENDING.
  * Predecessor record remains permanently immutable in terminal_activations.
  * Fresh Gen 2 confirmation matches with exact runtime-derived candidate setup key.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aladeen.strategy.activation_engine import ActivationEngine, ActivationEngineConfig
from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    ExactPricePrint,
    ExternalCommitEvent,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_member_key,
)
from aladeen.strategy.confirmation_matcher import ConfirmationMatcher
from aladeen.strategy.confirmation_pair_matcher import MatchingContext
from aladeen.strategy.confirmation_types import (
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
    format_candidate_setup_key,
    format_length_prefixed,
)
from aladeen.strategy.tjl_types import StableLevelId, TJLSide
from aladeen.strategy.types import Direction

DEFAULT_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_D1", run_id="RUN_20261001_001")


class TestSourceCandidateRearm:
    """Integration proof tests for rearm controllers and multi-generation activations (ACT-01, ACT-04)."""

    def test_act_01_rearm_path_a_inside_at_cancel_with_immutable_predecessor(self) -> None:
        """ACT-01: Rearm Path A: inside-at-cancel -> outside print -> inside retouch spawns Gen 2 linked record."""
        engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_D1",
                symbol="FEED_EURUSD_D1",
                source_timeframe="D1",
                sequence_domain=DEFAULT_DOMAIN,
                price_basis=PriceBasis.BID,
            )
        )
        lvl = StableLevelId("FEED_EURUSD_D1", "D1", datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        mem = SourceMemberReference(
            engine_id="ENGINE_EURUSD_D1",
            symbol="FEED_EURUSD_D1",
            source_timeframe="D1",
            set_id="SET_1",
            role="TJL1",
            side="HIGH",
            lower_edge=1.1350,
            upper_edge=1.1400,
            is_line=False,
            direction=Direction.DOWNWARD,
            level_id=lvl,
            eligibility_available_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_member(mem)

        # 1. Gen 1 Touch inside zone [1.1350, 1.1400]
        touch1_time = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
        p1 = ExactPricePrint("OBS_01", 1.1375, PriceBasis.BID, touch1_time, DEFAULT_DOMAIN, 1001)
        snap1 = engine.process_event(p1)
        act1 = snap1.active_activations[mem.member_key]
        assert act1.state == ActivationState.PENDING_ACTIVATION
        assert act1.generation_seq == 1
        assert "ACT_G01" in act1.activation_id

        # 2. External commit cancellation while price is inside zone
        cancel_time = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)
        c_evt = ExternalCommitEvent(
            event_id="EVT_EXT_CANCEL",
            timestamp=cancel_time,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1002,
            winning_engine_id="OTHER_ENGINE",
            winning_set_id="SET_OTHER",
            winning_role="OTHER_ROLE",
            cancelled_competing_scope="ENGINE_LOCAL",
            target_engine_id="ENGINE_EURUSD_D1",
            note="Competing entry committed",
        )
        snap2 = engine.process_event(c_evt)
        assert len(snap2.active_activations) == 0
        assert len(snap2.terminal_activations) == 1
        term_act1 = snap2.terminal_activations[0]
        assert term_act1.state == ActivationState.CANCELLED_EXTERNAL_ENTRY
        assert term_act1.generation_seq == 1
        assert term_act1.activation_id == act1.activation_id

        # Decoupled controller spawned referencing prior_activation_id
        assert mem.member_key in snap2.rearm_controllers
        ctrl = snap2.rearm_controllers[mem.member_key]
        assert ctrl.prior_activation_id == act1.activation_id
        assert ctrl.last_observed_position == "INSIDE"
        assert ctrl.rearm_armed is False

        # 3. Fresh outside observation strictly later than cancellation
        out_time = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        p_out = ExactPricePrint("OBS_OUT", 1.1300, PriceBasis.BID, out_time, DEFAULT_DOMAIN, 1003)
        snap3 = engine.process_event(p_out)
        ctrl3 = snap3.rearm_controllers[mem.member_key]
        assert ctrl3.state == ActivationState.OUT_OF_ZONE_ARMED
        assert ctrl3.rearm_armed is True
        # Predecessor permanently immutable
        assert len(snap3.terminal_activations) == 1
        assert snap3.terminal_activations[0] == term_act1

        # 4. Fresh physical inside touch print strictly later than outside observation
        retouch_time = datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
        p_retouch = ExactPricePrint("OBS_RETOUCH", 1.1380, PriceBasis.BID, retouch_time, DEFAULT_DOMAIN, 1004)
        snap4 = engine.process_event(p_retouch)

        # Brand-new linked ActivationRecord Gen 2 in REARMED_PENDING
        assert mem.member_key in snap4.active_activations
        act2 = snap4.active_activations[mem.member_key]
        assert act2.state == ActivationState.REARMED_PENDING
        assert act2.generation_seq == 2
        assert "ACT_G02" in act2.activation_id
        assert act2.prior_activation_id == act1.activation_id
        assert act2.first_touch_time == retouch_time
        assert act2.trigger_observation_id == "OBS_RETOUCH"
        # Predecessor record remains unchanged in terminal_activations
        assert len(snap4.terminal_activations) == 1
        assert snap4.terminal_activations[0] == term_act1

        # 5. Stale Gen 1 confirmation evidence rejects fail-closed as PRE_ACTIVATION_CONFIRMATION
        ev_stale = ConfirmationEvidenceRecord(
            event_id="EVT_STALE",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 1, 8, 15, tzinfo=timezone.utc),  # Before Gen 2 touch (09:30 UTC)!
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )
        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem.member_key: mem},
            source_resolution_status={mem.member_key: True},
            coverage_status=CoverageStatus.COMPLETE,
        )
        matcher = ConfirmationMatcher()
        res_stale = matcher.match(act2, ev_stale, ctx)
        assert res_stale.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res_stale.rejection_reasons
        assert res_stale.candidate_record is None

        # 6. Fresh Gen 2 confirmation matches with exact runtime-derived candidate setup key
        ev_fresh = ConfirmationEvidenceRecord(
            event_id="EVT_FRESH",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_02",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),  # After Gen 2 touch (09:30 UTC)!
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )
        res_fresh = matcher.match(act2, ev_fresh, ctx)
        assert res_fresh.status == ConfirmationMatchStatus.MATCHED
        assert res_fresh.candidate_record is not None
        cand = res_fresh.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.entry_reference_price == 1.1350

        # Assert exact canonical setup key and candidate ID derived at runtime
        expected_setup_key = format_candidate_setup_key(
            domain_session_id=ctx.domain_session_id,
            revision_id=ctx.revision_id,
            activation_id=act2.activation_id,
            source_member_key=act2.member_key,
            confirmation_config_id=ev_fresh.confirmation_config_id,
            confirmation_candle_id=ev_fresh.confirmation_candle_id,
            confirmation_close_iso=ev_fresh.close_timestamp.isoformat(),
        )
        expected_candidate_id = f"CAND{format_length_prefixed(expected_setup_key)}"
        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == expected_candidate_id

    def test_act_04_rearm_path_b_already_outside_at_cancel_with_immutable_predecessor(self) -> None:
        """ACT-04: Rearm Path B: already outside at cancellation -> arms directly -> retouch creates Gen 2."""
        engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_D1",
                symbol="FEED_EURUSD_D1",
                source_timeframe="D1",
                sequence_domain=DEFAULT_DOMAIN,
                price_basis=PriceBasis.BID,
            )
        )
        lvl = StableLevelId("FEED_EURUSD_D1", "D1", datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc), TJLSide.HIGH)
        mem = SourceMemberReference(
            engine_id="ENGINE_EURUSD_D1",
            symbol="FEED_EURUSD_D1",
            source_timeframe="D1",
            set_id="SET_1",
            role="TJL1",
            side="HIGH",
            lower_edge=1.1350,
            upper_edge=1.1400,
            is_line=False,
            direction=Direction.DOWNWARD,
            level_id=lvl,
            eligibility_available_time=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc),
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        engine.register_source_member(mem)

        # 1. Gen 1 Touch
        t1 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
        snap1 = engine.process_event(ExactPricePrint("OBS_01", 1.1375, PriceBasis.BID, t1, DEFAULT_DOMAIN, 1001))
        act1 = snap1.active_activations[mem.member_key]
        assert act1.generation_seq == 1

        # 2. Price observed outside zone before cancellation
        t_out = datetime(2026, 10, 1, 8, 15, tzinfo=timezone.utc)
        engine.process_event(ExactPricePrint("OBS_OUT", 1.1300, PriceBasis.BID, t_out, DEFAULT_DOMAIN, 1002))

        # 3. External commit cancellation occurs when price is already outside
        t_cancel = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)
        c_evt = ExternalCommitEvent(
            event_id="EVT_EXT_CANCEL",
            timestamp=t_cancel,
            sequence_domain=DEFAULT_DOMAIN,
            sequence_ref=1003,
            winning_engine_id="OTHER_ENGINE",
            winning_set_id="SET_OTHER",
            winning_role="OTHER_ROLE",
            cancelled_competing_scope="ENGINE_LOCAL",
            target_engine_id="ENGINE_EURUSD_D1",
        )
        snap_cancel = engine.process_event(c_evt)

        # RearmController is armed directly as OUT_OF_ZONE_ARMED
        assert mem.member_key in snap_cancel.rearm_controllers
        ctrl = snap_cancel.rearm_controllers[mem.member_key]
        assert ctrl.state == ActivationState.OUT_OF_ZONE_ARMED
        assert ctrl.rearm_armed is True
        assert len(snap_cancel.terminal_activations) == 1
        term_act1 = snap_cancel.terminal_activations[0]
        assert term_act1.activation_id == act1.activation_id

        # 4. Fresh inside retouch print strictly later than cancellation
        t_retouch = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
        p_retouch = ExactPricePrint("OBS_RETOUCH_B", 1.1380, PriceBasis.BID, t_retouch, DEFAULT_DOMAIN, 1004)
        snap_retouch = engine.process_event(p_retouch)

        assert mem.member_key in snap_retouch.active_activations
        act2 = snap_retouch.active_activations[mem.member_key]
        assert act2.state == ActivationState.REARMED_PENDING
        assert act2.generation_seq == 2
        assert "ACT_G02" in act2.activation_id
        assert act2.prior_activation_id == act1.activation_id
        assert act2.first_touch_time == t_retouch
        assert len(snap_retouch.terminal_activations) == 1
        assert snap_retouch.terminal_activations[0] == term_act1

        # 5. Matching against Gen 2 activation succeeds with exact setup key
        ev = ConfirmationEvidenceRecord(
            event_id="EVT_GEN2",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_03",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 1, 9, 45, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )
        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
            current_members={mem.member_key: mem},
            source_resolution_status={mem.member_key: True},
            coverage_status=CoverageStatus.COMPLETE,
        )
        matcher = ConfirmationMatcher()
        res = matcher.match(act2, ev, ctx)
        assert res.status == ConfirmationMatchStatus.MATCHED
        assert res.candidate_record is not None
        cand = res.candidate_record

        expected_setup_key = format_candidate_setup_key(
            domain_session_id=ctx.domain_session_id,
            revision_id=ctx.revision_id,
            activation_id=act2.activation_id,
            source_member_key=act2.member_key,
            confirmation_config_id=ev.confirmation_config_id,
            confirmation_candle_id=ev.confirmation_candle_id,
            confirmation_close_iso=ev.close_timestamp.isoformat(),
        )
        expected_candidate_id = f"CAND{format_length_prefixed(expected_setup_key)}"
        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == expected_candidate_id
