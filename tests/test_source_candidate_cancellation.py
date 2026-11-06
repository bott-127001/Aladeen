"""Offline source-to-candidate integration proof tests — Cancellation & Terminal Non-Revival.

Covers:
- ACT-02: Source level set replacement (e.g. pullback replacement in tjl_06) permanently cancels
  outgoing member activations to CANCELLED_SOURCE_REPLACEMENT.
  * Subsequent outside and inside prints never revive outgoing membership or activation.
  * No rearm controller is created for the cancelled member.
  * Terminal predecessor remains immutable.
  * Confirmation matching against cancelled predecessor rejects fail-closed.
- ACT-03: Source main CHOCH invalidation (e.g. tjl_09) permanently cancels active activations
  to CANCELLED_SOURCE_CHOCH.
  * Domain consistency strictly preserved across H1 feed, sequence domain, prints, and matching context.
  * Subsequent outside and inside prints never revive outgoing membership or activation.
  * No rearm controller is created for the cancelled member.
  * Terminal predecessor remains immutable.
  * Confirmation matching rejects fail-closed with INELIGIBLE_ACTIVATION_STATE.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

from aladeen.strategy.activation_adapter import TJLSynchronizer
from aladeen.strategy.activation_engine import ActivationEngine, ActivationEngineConfig
from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationState,
    CoverageStatus,
    ExactPricePrint,
    PriceBasis,
    SequenceDomain,
    UsageEvidenceStatus,
    format_member_key,
)
from aladeen.strategy.confirmation_matcher import ConfirmationMatcher
from aladeen.strategy.confirmation_pair_matcher import MatchingContext
from aladeen.strategy.confirmation_types import (
    ConfirmationEvidenceRecord,
    ConfirmationMatchStatus,
    ConfirmationRejectionReason,
    EvidenceProvenanceType,
)
from aladeen.strategy.tjl_coordinator import TJLCoordinator
from aladeen.strategy.types import Direction, MSMConfig, StrategyCandle

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_D1_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_D1", run_id="RUN_20261001_D1")
FEED_H1_DOMAIN = SequenceDomain(feed_id="FEED_EURUSD_H1", run_id="RUN_20261001_H1")


def load_tjl_fixture(name: str) -> Dict[str, Any]:
    with open(FIXTURES_DIR / "tjl_acceptance.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"][name]


def parse_fixture_candles(raw_candles: List[Dict[str, Any]]) -> List[StrategyCandle]:
    """Parse fixture candles requiring explicit fixture fields without default fallbacks."""
    candles: List[StrategyCandle] = []
    for i, c in enumerate(raw_candles):
        candles.append(
            StrategyCandle(
                index=i,
                open_time=datetime.fromisoformat(c["time"]).astimezone(timezone.utc),
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c["is_forming"]),
                bar_status=str(c["bar_status"]),
                close_time=datetime.fromisoformat(c["close_time"]).astimezone(timezone.utc),
            )
        )
    return candles


class TestSourceCandidateCancellation:
    """Integration proof tests for terminal cancellation and non-revival (ACT-02, ACT-03)."""

    def test_act_02_source_set_replacement_terminal_non_revival(self) -> None:
        """ACT-02: Pullback replacement permanently cancels SET_1 activations.

        Subsequent prints (outside, inside old zone) cannot revive SET_1, cannot create
        rearm controllers, and predecessor record remains immutable in terminal_activations.
        Matching produces no candidates.
        """
        fix = load_tjl_fixture("tjl_06_pullback_t2_replacement_and_cancellation_intent")
        start_time = datetime.fromisoformat(fix["start_candle_time"]).astimezone(timezone.utc)
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.DOWNWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_D1",
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )
        candles = parse_fixture_candles(fix["candles"])

        # Process candles up to SET_1 creation (bar 9)
        for i in range(10):
            coord.process_candle(candles[i])
        snap_s1 = coord.get_snapshot()
        assert snap_s1.current_eligible_set is not None
        assert snap_s1.current_eligible_set.set_id == "SET_1"

        act_engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_D1",
                symbol="FEED_EURUSD_D1",
                source_timeframe="D1",
                sequence_domain=DEFAULT_D1_DOMAIN,
                price_basis=PriceBasis.BID,
            )
        )
        synchronizer = TJLSynchronizer(engine=act_engine)
        usage = {
            snap_s1.current_eligible_set.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            snap_s1.current_eligible_set.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        synchronizer.sync(snap_s1, sequence_ref_start=1001, usage_evidence=usage)

        # Touch SET_1::TJL1 to activate -> PENDING_ACTIVATION
        mem_key_s1 = format_member_key("SET_1", "TJL1")
        print_touch = ExactPricePrint(
            observation_id="OBS_TOUCH_S1",
            price=1.1825,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc),
            sequence_domain=DEFAULT_D1_DOMAIN,
            sequence_ref=1003,
        )
        snap_touched = act_engine.process_event(print_touch)
        act_s1 = snap_touched.active_activations[mem_key_s1]
        assert act_s1.state == ActivationState.PENDING_ACTIVATION

        # Continue processing candles until SET_2 replacement occurs (bar 16)
        for i in range(10, 17):
            coord.process_candle(candles[i])
        snap_s2 = coord.get_snapshot()
        assert snap_s2.current_eligible_set is not None
        assert snap_s2.current_eligible_set.set_id == "SET_2"

        usage_s2 = {
            snap_s2.current_eligible_set.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            snap_s2.current_eligible_set.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        snap_act_replaced = synchronizer.sync(snap_s2, sequence_ref_start=1004, usage_evidence=usage_s2)

        # Assert SET_1 is permanently cancelled
        assert mem_key_s1 not in snap_act_replaced.current_members
        assert mem_key_s1 not in snap_act_replaced.active_activations
        term_s1 = [t for t in snap_act_replaced.terminal_activations if t.activation_id == act_s1.activation_id]
        assert len(term_s1) == 1
        term_record = term_s1[0]
        assert term_record.state == ActivationState.CANCELLED_SOURCE_REPLACEMENT

        # Matcher rejects evidence matching replaced member
        ev = ConfirmationEvidenceRecord(
            event_id="EVT_01",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_09",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1500,
            close_timestamp=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_D1",
            feed_id="FEED_EURUSD_D1",
            sequence_domain=DEFAULT_D1_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )

        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_D1_DOMAIN,
            evaluation_time=datetime(2026, 10, 1, 20, 0, tzinfo=timezone.utc),
            current_members=dict(snap_act_replaced.current_members),  # Only SET_2 members
            source_resolution_status={m_k: True for m_k in snap_act_replaced.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        matcher = ConfirmationMatcher()
        res_initial = matcher.match(act_s1, ev, ctx)
        assert res_initial.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res_initial.rejection_reasons
        assert res_initial.candidate_record is None

        # --- Subsequent Observation Drive: Non-Revival Verification ---
        # 1. Drive an outside print
        print_post_outside = ExactPricePrint(
            observation_id="OBS_POST_OUT_01",
            price=1.1700,  # Below SET_1 zone [1.1800, 1.1850]
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 1, 20, 15, tzinfo=timezone.utc),
            sequence_domain=DEFAULT_D1_DOMAIN,
            sequence_ref=1020,
        )
        snap_post_out = act_engine.process_event(print_post_outside)
        assert mem_key_s1 not in snap_post_out.current_members
        assert mem_key_s1 not in snap_post_out.active_activations
        assert mem_key_s1 not in snap_post_out.rearm_controllers

        # Rebuild context from snap_post_out and assert rejection
        ctx_post_out = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_D1_DOMAIN,
            evaluation_time=print_post_outside.timestamp,
            current_members=dict(snap_post_out.current_members),
            source_resolution_status={m_k: True for m_k in snap_post_out.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_post_out = matcher.match(act_s1, ev, ctx_post_out)
        assert res_post_out.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res_post_out.rejection_reasons
        assert res_post_out.candidate_record is None

        # 2. Drive an inside print at old SET_1 zone [1.1800, 1.1850]
        print_post_inside = ExactPricePrint(
            observation_id="OBS_POST_IN_01",
            price=1.1825,  # Inside old SET_1 zone
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 1, 20, 30, tzinfo=timezone.utc),
            sequence_domain=DEFAULT_D1_DOMAIN,
            sequence_ref=1021,
        )
        snap_post_in = act_engine.process_event(print_post_inside)

        # Decisive non-revival assertions:
        # a) Outgoing member remains absent from current_members
        assert mem_key_s1 not in snap_post_in.current_members
        # b) Outgoing member cannot be in active_activations
        assert mem_key_s1 not in snap_post_in.active_activations
        # c) No rearm controller is created for the cancelled member
        assert mem_key_s1 not in snap_post_in.rearm_controllers
        # d) Terminal predecessor remains exactly unchanged
        term_after = [t for t in snap_post_in.terminal_activations if t.activation_id == act_s1.activation_id]
        assert len(term_after) == 1
        assert term_after[0] == term_record
        assert term_after[0].state == ActivationState.CANCELLED_SOURCE_REPLACEMENT
        # e) Rebuild context from snap_post_in and assert rejection
        ctx_post_in = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=DEFAULT_D1_DOMAIN,
            evaluation_time=print_post_inside.timestamp,
            current_members=dict(snap_post_in.current_members),
            source_resolution_status={m_k: True for m_k in snap_post_in.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_post_in = matcher.match(act_s1, ev, ctx_post_in)
        assert res_post_in.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res_post_in.rejection_reasons
        assert res_post_in.candidate_record is None

    def test_act_03_source_main_choch_invalidation_terminal_non_revival(self) -> None:
        """ACT-03: Source Main CHOCH invalidates pending activation.

        Domain consistency strictly preserved across H1 feed, sequence domain, prints, and matcher.
        Subsequent prints (outside, inside old zone) cannot revive SET_1, cannot create
        rearm controllers, and predecessor record remains immutable in terminal_activations.
        Matching produces no candidates.
        """
        fix = load_tjl_fixture("tjl_09_source_choch_eligibility_invalidation_and_gap")
        start_time = datetime.fromisoformat(fix["start_candle_time"]).astimezone(timezone.utc)
        coord = TJLCoordinator(
            config=MSMConfig(direction=Direction.UPWARD, start_candle_time=start_time),
            symbol_feed_id="FEED_EURUSD_H1",
            source_timeframe="H1",
            source_engine_id="ENGINE_EURUSD_H1",
        )
        candles = parse_fixture_candles(fix["candles"])

        # Process candles up to bar 8 (active SET_1)
        for i in range(8):
            coord.process_candle(candles[i])
        snap_s1 = coord.get_snapshot()
        assert snap_s1.current_eligible_set is not None

        act_engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_H1",
                symbol="FEED_EURUSD_H1",
                source_timeframe="H1",
                sequence_domain=FEED_H1_DOMAIN,
                price_basis=PriceBasis.BID,
            )
        )
        synchronizer = TJLSynchronizer(engine=act_engine)
        usage = {
            snap_s1.current_eligible_set.tjl1_zone.level_id: UsageEvidenceStatus.UNUSED,
            snap_s1.current_eligible_set.tjl2_zone.level_id: UsageEvidenceStatus.UNUSED,
        }
        synchronizer.sync(snap_s1, sequence_ref_start=1001, usage_evidence=usage)

        # In-zone print activates TJL1 -> PENDING_ACTIVATION
        mem_key_tjl1 = format_member_key("SET_1", "TJL1")
        print_touch = ExactPricePrint(
            observation_id="OBS_TOUCH_CH",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 8, 30, tzinfo=timezone.utc),
            sequence_domain=FEED_H1_DOMAIN,
            sequence_ref=1003,
        )
        snap_act = act_engine.process_event(print_touch)
        act_rec = snap_act.active_activations[mem_key_tjl1]
        assert act_rec.state == ActivationState.PENDING_ACTIVATION

        # Candles 8 and 9 Bearish CHOCH confirmation cancels SET_1
        coord.process_candle(candles[8])
        coord.process_candle(candles[9])
        snap_choch = coord.get_snapshot()
        assert snap_choch.current_eligible_set is None

        snap_act_inv = synchronizer.sync(snap_choch, sequence_ref_start=1005)
        assert len(snap_act_inv.current_members) == 0
        assert len(snap_act_inv.active_activations) == 0
        term_acts = snap_act_inv.terminal_activations
        assert len(term_acts) == 1
        term_record = term_acts[0]
        assert term_record.state == ActivationState.CANCELLED_SOURCE_CHOCH

        # Matcher rejects confirmation against invalidated activation
        ev = ConfirmationEvidenceRecord(
            event_id="EVT_CH_01",
            producer_id="PROD_CHOCH",
            confirmation_config_id="CONF_CFG_01",
            confirmation_timeframe="M1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.UPWARD,
            pattern_type="CHOCH",
            close_price=1.1400,
            close_timestamp=datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc),
            symbol="FEED_EURUSD_H1",
            feed_id="FEED_EURUSD_H1",
            sequence_domain=FEED_H1_DOMAIN,
            price_basis=PriceBasis.BID,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )

        ctx = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=FEED_H1_DOMAIN,
            evaluation_time=datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc),
            current_members={},
            source_resolution_status={},
            coverage_status=CoverageStatus.COMPLETE,
        )
        matcher = ConfirmationMatcher()
        res_initial = matcher.match(term_record, ev, ctx)
        assert res_initial.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE in res_initial.rejection_reasons
        assert res_initial.candidate_record is None

        # --- Subsequent Observation Drive: Non-Revival Verification ---
        # 1. Drive an outside print
        print_post_outside = ExactPricePrint(
            observation_id="OBS_POST_OUT_CH",
            price=1.1200,  # Below invalidated zone
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc),
            sequence_domain=FEED_H1_DOMAIN,
            sequence_ref=1020,
        )
        snap_post_out = act_engine.process_event(print_post_outside)
        assert mem_key_tjl1 not in snap_post_out.current_members
        assert mem_key_tjl1 not in snap_post_out.active_activations
        assert mem_key_tjl1 not in snap_post_out.rearm_controllers

        # Rebuild context from snap_post_out and assert rejection
        ctx_post_out = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=FEED_H1_DOMAIN,
            evaluation_time=print_post_outside.timestamp,
            current_members=dict(snap_post_out.current_members),
            source_resolution_status={m_k: True for m_k in snap_post_out.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_post_out = matcher.match(term_record, ev, ctx_post_out)
        assert res_post_out.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE in res_post_out.rejection_reasons
        assert res_post_out.candidate_record is None

        # 2. Drive an inside print at old zone (1.1370)
        print_post_inside = ExactPricePrint(
            observation_id="OBS_POST_IN_CH",
            price=1.1370,
            price_basis=PriceBasis.BID,
            timestamp=datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc),
            sequence_domain=FEED_H1_DOMAIN,
            sequence_ref=1021,
        )
        snap_post_in = act_engine.process_event(print_post_inside)

        # Decisive non-revival assertions:
        # a) Outgoing member remains absent from current_members
        assert mem_key_tjl1 not in snap_post_in.current_members
        # b) Outgoing member cannot be in active_activations
        assert mem_key_tjl1 not in snap_post_in.active_activations
        # c) No rearm controller is created for the cancelled member
        assert mem_key_tjl1 not in snap_post_in.rearm_controllers
        # d) Terminal predecessor remains exactly unchanged
        term_after = [t for t in snap_post_in.terminal_activations if t.activation_id == term_record.activation_id]
        assert len(term_after) == 1
        assert term_after[0] == term_record
        assert term_after[0].state == ActivationState.CANCELLED_SOURCE_CHOCH
        # e) Rebuild context from snap_post_in and assert rejection
        ctx_post_in = MatchingContext(
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PriceBasis.BID,
            expected_confirmation_config_id="CONF_CFG_01",
            matching_sequence_domain=FEED_H1_DOMAIN,
            evaluation_time=print_post_inside.timestamp,
            current_members=dict(snap_post_in.current_members),
            source_resolution_status={m_k: True for m_k in snap_post_in.current_members},
            coverage_status=CoverageStatus.COMPLETE,
        )
        res_post_in = matcher.match(term_record, ev, ctx_post_in)
        assert res_post_in.status == ConfirmationMatchStatus.REJECTED
        assert ConfirmationRejectionReason.INELIGIBLE_ACTIVATION_STATE in res_post_in.rejection_reasons
        assert res_post_in.candidate_record is None
