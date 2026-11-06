"""Offline source-to-candidate integration proof tests — Equal-Time Causal Ordering and Determinism.

Note: These tests verify engine lifecycle transitions and matcher ordering contracts under supplied
synthetic member/evidence contracts. They do not independently establish candle-derived source/confirmation chains.

Covers:
- ORD-01: Timestamp tie between physical touch and confirmation evidence with missing sequence
  reference rejects fail-closed as UNKNOWN_ORDER.
- ORD-02: Cross-domain sequence references during timestamp tie reject fail-closed as
  CROSS_DOMAIN_ORDERING_REJECTED.
- ORD-03: Equal-time tie where confirmation sequence <= touch sequence (both equal and strictly earlier)
  rejects fail-closed as PRE_ACTIVATION_CONFIRMATION.
- ORD-04: Equal-time tie where confirmation sequence > touch sequence within the same sequence
  domain matches deterministically.
- Deterministic repeated evaluation: Multiple sequential evaluations under unchanged context yield
  strictly identical complete ConfirmationMatchResult values.
- MatchingContext input immutability: External mutations of caller-supplied mappings do not affect
  the frozen context; re-evaluation produces identical complete ConfirmationMatchResult values.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_activation_id,
)
from aladeen.strategy.confirmation_matcher import ConfirmationMatcher
from aladeen.strategy.confirmation_pair_matcher import MatchingContext
from aladeen.strategy.confirmation_types import (
    CandidateSetupRecord,
    ConfirmationEvidenceRecord,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
    TouchSequenceEvidence,
    format_candidate_setup_key,
    format_length_prefixed,
)
from aladeen.strategy.tjl_types import StableLevelId, TJLSide
from aladeen.strategy.types import Direction

DEFAULT_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_D1", run_id="RUN_20261001_001")


class TestSourceCandidateOrdering:
    """Integration proof tests for equal-time causal ordering, determinism, and immutability."""

    def test_equal_time_causal_ordering_matrix(self) -> None:
        """ORD-01 to ORD-04: Timestamp tie between touch and confirmation evaluated via sequence ordering."""
        matcher = ConfirmationMatcher()
        touch_time = datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc)

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

        act = ActivationRecord(
            activation_id=format_activation_id("ENGINE_EURUSD_D1", "D1", "FEED_EURUSD_D1", "SET_1", "TJL1", 1),
            engine_id="ENGINE_EURUSD_D1",
            symbol="FEED_EURUSD_D1",
            source_timeframe="D1",
            confirmation_timeframe="H1",
            set_id="SET_1",
            role="TJL1",
            level_id=lvl,
            lower_edge=1.1350,
            upper_edge=1.1400,
            state=ActivationState.PENDING_ACTIVATION,
            first_touch_time=touch_time,
            first_touch_price=1.1375,
            trigger_observation_id="OBS_01",
            generation_seq=1,
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )

        # ORD-01: Timestamp tie without sequence reference rejects as UNKNOWN_ORDER
        ev_no_seq = ConfirmationEvidenceRecord(
            event_id="EV_ORD_01",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=touch_time,  # Equal to touch!
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            sequence_ref=None,  # Missing!
        )
        ctx_no_seq = MatchingContext(
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
        res_ord1 = matcher.match(act, ev_no_seq, ctx_no_seq)
        assert res_ord1.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.UNKNOWN_ORDER in res_ord1.rejection_reasons
        assert res_ord1.candidate_record is None

        # ORD-02: Cross-domain sequence references reject as CROSS_DOMAIN_ORDERING_REJECTED
        other_domain = SequenceDomain("FEED_OTHER", "RUN_OTHER")
        ev_cross = ConfirmationEvidenceRecord(
            event_id="EV_ORD_02",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=touch_time,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=other_domain,  # Contradicts matching domain!
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            sequence_ref=1005,
        )
        ctx_with_seq = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members={mem.member_key: mem},
            source_resolution_status={mem.member_key: True},
            touch_sequence_evidence={
                act.activation_id: TouchSequenceEvidence(DEFAULT_DOMAIN, 1002)
            },
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_ord2 = matcher.match(act, ev_cross, ctx_with_seq)
        assert res_ord2.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.CROSS_DOMAIN_ORDERING_REJECTED in res_ord2.rejection_reasons
        assert res_ord2.candidate_record is None

        # ORD-03a: Confirmation sequence == touch sequence rejects as PRE_ACTIVATION_CONFIRMATION
        ev_equal_seq = ConfirmationEvidenceRecord(
            event_id="EV_ORD_03A",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=touch_time,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            sequence_ref=1002,  # Exactly equal to touch sequence ref 1002!
        )
        res_ord3a = matcher.match(act, ev_equal_seq, ctx_with_seq)
        assert res_ord3a.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res_ord3a.rejection_reasons
        assert res_ord3a.candidate_record is None

        # ORD-03b: Confirmation sequence strictly earlier (< 1002) rejects as PRE_ACTIVATION_CONFIRMATION
        ev_earlier_seq = ConfirmationEvidenceRecord(
            event_id="EV_ORD_03B",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=touch_time,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            sequence_ref=1001,  # Strictly earlier than touch sequence ref 1002!
        )
        res_ord3b = matcher.match(act, ev_earlier_seq, ctx_with_seq)
        assert res_ord3b.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.PRE_ACTIVATION_CONFIRMATION in res_ord3b.rejection_reasons
        assert res_ord3b.candidate_record is None

        # ORD-04: Confirmation sequence strictly later (> 1002) in matching domain matches
        ev_later_seq = ConfirmationEvidenceRecord(
            event_id="EV_ORD_04",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=touch_time,
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
            sequence_ref=1005,  # Strictly later than touch sequence ref 1002!
        )
        res_ord4 = matcher.match(act, ev_later_seq, ctx_with_seq)
        assert res_ord4.status == ConfirmationMatchStatus.MATCHED
        assert res_ord4.candidate_record is not None
        cand = res_ord4.candidate_record
        assert cand.signal_side == "SELL"
        assert cand.entry_reference_price == 1.1350

        expected_setup_key = format_candidate_setup_key(
            domain_session_id=ctx_with_seq.domain_session_id,
            revision_id=ctx_with_seq.revision_id,
            activation_id=act.activation_id,
            source_member_key=act.member_key,
            confirmation_config_id=ev_later_seq.confirmation_config_id,
            confirmation_candle_id=ev_later_seq.confirmation_candle_id,
            confirmation_close_iso=ev_later_seq.close_timestamp.isoformat(),
        )
        expected_candidate_id = f"CAND{format_length_prefixed(expected_setup_key)}"
        assert cand.setup_key == expected_setup_key
        assert cand.candidate_id == expected_candidate_id

    def test_repeated_evaluation_and_input_immutability(self) -> None:
        """Deterministic repeated evaluation yields identical complete match results; input mappings remain frozen."""
        matcher = ConfirmationMatcher()
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
        act = ActivationRecord(
            activation_id=format_activation_id("ENGINE_EURUSD_D1", "D1", "FEED_EURUSD_D1", "SET_1", "TJL1", 1),
            engine_id="ENGINE_EURUSD_D1",
            symbol="FEED_EURUSD_D1",
            source_timeframe="D1",
            confirmation_timeframe="H1",
            set_id="SET_1",
            role="TJL1",
            level_id=lvl,
            lower_edge=1.1350,
            upper_edge=1.1400,
            state=ActivationState.PENDING_ACTIVATION,
            first_touch_time=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
            first_touch_price=1.1375,
            trigger_observation_id="OBS_01",
            generation_seq=1,
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        ev = ConfirmationEvidenceRecord(
            event_id="EV_REP",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )

        members_map = {mem.member_key: mem}
        res_map = {mem.member_key: True}
        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            current_members=members_map,
            source_resolution_status=res_map,
            coverage_status=CoverageStatus.COMPLETE,
        )

        res1 = matcher.match(act, ev, ctx)
        res2 = matcher.match(act, ev, ctx)
        res3 = matcher.match(act, ev, ctx)

        # Full ConfirmationMatchResult equality across repeated evaluations
        assert res1 == res2 == res3
        assert res1.status == ConfirmationMatchStatus.MATCHED
        assert res1.candidate_record is not None

        # External dictionary mutation has zero effect on frozen context; re-evaluation produces identical complete result
        members_map.clear()
        res_map[mem.member_key] = False
        assert mem.member_key in ctx.current_members
        assert ctx.source_resolution_status[mem.member_key] is True

        res_mut = matcher.match(act, ev, ctx)
        assert res_mut == res1
