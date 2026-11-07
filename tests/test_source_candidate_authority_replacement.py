"""Offline source-to-candidate integration proof tests — Replacement Lifecycle.

Covers Milestone 36 Directive (HANDOFF-122):
- Honest separation of genuine source replacement integration from synthetic same-level contracts:
  1. Genuine Source Replacement Integration:
     * TJLCoordinator processes daily candles 0..16 from tjl_06_pullback_t2_replacement_and_cancellation_intent.
     * Candles 0..9 form genuine SET_1; synchronized into ActivationEngine.
     * ExactPricePrint touches TJL1 zone -> PENDING_ACTIVATION.
     * Candles 10..16 form genuine SET_2 with cancellation intent for SET_1.
     * TJLSynchronizer.sync() adapts cancellation transition into SourceCancellationEvent and registers SET_2.
     * SET_1 activation transitions to CANCELLED_SOURCE_REPLACEMENT in terminal_activations.
     * Outgoing SET_1 cannot be revived: re-registration raises InvalidEvidenceError.
     * Outgoing and incoming physical level IDs are compared explicitly:
       In genuine fixture tjl_06, all level IDs differ (no physical persistence between SET_1 and SET_2);
       physical level persistence is marked unproven on this source fixture.
     * Evaluating old SET_1 activation against updated context rejects fail-closed with MEMBERSHIP_CANCELLED_OR_REPLACED.
  2. Synthetic Same-Level Replacement Contract:
     * Separately labeled synthetic specification contract where a physical level ID is shared across sets.
     * Resolves physical usage USED through AuthorityContextBuilder.
     * Incoming membership for SET_2 retains the physical-level USED status.
     * Matcher evaluation rejects incoming activation fail-closed with STALE_EVIDENCE_FOR_GENERATION.
     * Illegal successor proposal attempting to reset terminal USED to UNUSED is rejected with USAGE_USED_TERMINAL.
  3. Synthetic Activation Terminal USED Consistency Contract:
     * Separately labeled synthetic composition contract:
     * Synthetic activation with terminal USED history blocks context composition (raises ValueError) when authority resolves UNUSED.
"""

from __future__ import annotations

from dataclasses import replace
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
import pytest

from aladeen.strategy.activation_adapter import TJLSynchronizer
from aladeen.strategy.activation_engine import ActivationEngine, ActivationEngineConfig
from aladeen.strategy.activation_types import (
    ActivationRecord,
    ActivationState,
    CancellationReason,
    CoverageStatus,
    ExactPricePrint,
    InvalidEvidenceError,
    PriceBasis,
    SequenceDomain,
    SourceMemberReference,
    UsageEvidenceStatus,
    format_member_key,
)
from aladeen.strategy.authority_context_builder import AuthorityContextBuilder
from aladeen.strategy.authority_types import (
    AuthorityDiagnosticReason,
    ProposedFeedCoverageRecord,
    ProposedUsageEvidenceRecord,
    TrustConfiguration,
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
from aladeen.strategy.tjl_types import StableLevelId, TJLSide
from aladeen.strategy.types import Direction, MSMConfig, StrategyCandle

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FEED_ID = "FEED_EURUSD_D1"
CONF_CFG = "CONF_CFG_01"
DEFAULT_DOMAIN = SequenceDomain(feed_id=FEED_ID, run_id="RUN_20261001_001")
PRICE_BASIS = PriceBasis.BID

DEFAULT_TRUST = TrustConfiguration(
    trusted_usage_issuers=("UPSTREAM_TRADE_LEDGER_OFFLINE",),
    trusted_coverage_issuers=("OFFLINE_FEED_AUDITOR_v1",),
)


def load_tjl_fixture(name: str) -> Dict[str, Any]:
    with open(FIXTURES_DIR / "tjl_acceptance.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["fixtures"][name]


def build_synthesized_daily_source_candles(
    raw_fixture_candles: List[Dict[str, Any]],
    start_date: datetime,
) -> List[StrategyCandle]:
    daily_candles: List[StrategyCandle] = []
    day_step = timedelta(days=1)
    for i, c in enumerate(raw_fixture_candles):
        open_time = start_date + (day_step * i)
        close_time = start_date + (day_step * (i + 1))
        daily_candles.append(
            StrategyCandle(
                index=i,
                open_time=open_time,
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
                is_forming=bool(c["is_forming"]),
                bar_status=str(c["bar_status"]),
                close_time=close_time,
            )
        )
    return daily_candles


class TestSourceCandidateAuthorityReplacement:
    """Honest separation of genuine source replacement integration from synthetic same-level contracts."""

    def test_genuine_source_replacement_integration(self) -> None:
        """Genuine source replacement integration through TJLCoordinator and TJLSynchronizer:
        - Obtains SET_1 and SET_2 from genuine fixture tjl_06_pullback_t2_replacement_and_cancellation_intent.
        - Synchronizes through accepted TJLSynchronizer.
        - Explicitly compares outgoing/incoming physical IDs.
        - Physical level persistence is marked unproven on this genuine fixture (all IDs differ).
        - Outgoing SET_1 is transitioned to CANCELLED_SOURCE_REPLACEMENT; cannot be revived.
        - Matching old SET_1 activation against updated context rejects with MEMBERSHIP_CANCELLED_OR_REPLACED.
        """
        fix_tjl = load_tjl_fixture("tjl_06_pullback_t2_replacement_and_cancellation_intent")
        start_date = datetime.fromisoformat(fix_tjl["start_candle_time"])
        source_candles = build_synthesized_daily_source_candles(fix_tjl["candles"], start_date=start_date)

        source_coord = TJLCoordinator(
            config=MSMConfig(start_candle_time=start_date, direction=Direction.DOWNWARD),
            symbol_feed_id=FEED_ID,
            source_timeframe="D1",
            source_engine_id="ENGINE_EURUSD_D1",
        )
        act_engine = ActivationEngine(
            ActivationEngineConfig(
                engine_id="ENGINE_EURUSD_D1",
                symbol=FEED_ID,
                source_timeframe="D1",
                sequence_domain=DEFAULT_DOMAIN,
                price_basis=PRICE_BASIS,
            )
        )
        synchronizer = TJLSynchronizer(engine=act_engine)
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()

        # 1. Process candles 0..9 to form genuine SET_1
        for i in range(10):
            source_coord.process_candle(source_candles[i])
        snap_tjl_set1 = source_coord.get_snapshot()
        cset_set1 = snap_tjl_set1.current_eligible_set
        assert cset_set1 is not None
        assert cset_set1.set_id == "SET_1"
        assert cset_set1.eligibility_available_time == source_candles[9].close_time
        t_set1_avail = cset_set1.eligibility_available_time

        lvl1_set1 = cset_set1.tjl1_zone.level_id
        lvl2_set1 = cset_set1.tjl2_zone.level_id
        t0 = start_date

        # Authority-backed registration for SET_1 evaluated at snapshot availability boundary
        usg_set1_1 = ProposedUsageEvidenceRecord(
            record_id="USG_SET1_1",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1_set1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_001",
        )
        usg_set1_2 = ProposedUsageEvidenceRecord(
            record_id="USG_SET1_2",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl2_set1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_002",
        )
        auth_set1 = builder.validate_and_build(
            coverage_records=(),
            usage_records=(usg_set1_1, usg_set1_2),
            evaluation_time=t_set1_avail,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_set1_avail,
            physical_levels=(lvl1_set1, lvl2_set1),
        )
        snap_act_set1 = synchronizer.sync(
            snap_tjl_set1,
            sequence_ref_start=1001,
            usage_evidence=auth_set1.resolved_usage_statuses,
        )
        mem_key_set1_tjl1 = format_member_key("SET_1", "TJL1")
        assert mem_key_set1_tjl1 in snap_act_set1.active_activations

        # 2. Touch SET_1 TJL1 inside zone strictly after SET_1 availability -> transitions to PENDING_ACTIVATION
        z1 = cset_set1.tjl1_zone
        touch_price = (z1.lower_price + z1.upper_price) / 2.0
        t_touch = t_set1_avail + timedelta(hours=12)
        p_touch = ExactPricePrint("OBS_TOUCH_SET1", touch_price, PRICE_BASIS, t_touch, DEFAULT_DOMAIN, 1005)
        act_engine.process_event(p_touch)
        act_rec_set1_tjl1 = act_engine.get_snapshot().active_activations[mem_key_set1_tjl1]
        assert act_rec_set1_tjl1.state == ActivationState.PENDING_ACTIVATION

        # 3. Process candles 10..16 to form genuine SET_2 with cancellation intent for SET_1
        for i in range(10, 17):
            source_coord.process_candle(source_candles[i])
        snap_tjl_set2 = source_coord.get_snapshot()
        cset_set2 = snap_tjl_set2.current_eligible_set
        assert cset_set2 is not None
        assert cset_set2.set_id == "SET_2"
        assert cset_set2.eligibility_available_time == source_candles[16].close_time
        t_set2_avail = cset_set2.eligibility_available_time

        lvl1_set2 = cset_set2.tjl1_zone.level_id
        lvl2_set2 = cset_set2.tjl2_zone.level_id

        # Explicit comparison of outgoing and incoming physical level IDs:
        # Full set comparison proves all physical level IDs differ across both same-role and cross-role checks
        set1_physical_ids = {lvl1_set1, lvl2_set1}
        set2_physical_ids = {lvl1_set2, lvl2_set2}
        assert set1_physical_ids.isdisjoint(set2_physical_ids)
        assert len(set1_physical_ids & set2_physical_ids) == 0
        assert lvl1_set1 != lvl1_set2
        assert lvl2_set1 != lvl2_set2
        assert lvl1_set1 != lvl2_set2
        assert lvl2_set1 != lvl1_set2
        # Note: In genuine fixture tjl_06, all level IDs differ (disjoint physical ID sets).
        # Physical level persistence across replacement cannot be proven on this genuine source fixture and is marked unproven here.
        # (The synthetic same-level case below is a typed authority/matcher specification contract under tjl_07b, but does not itself execute an engine replacement).

        # Authority-backed registration for SET_2 evaluated at snapshot availability boundary
        usg_set2_1 = ProposedUsageEvidenceRecord(
            record_id="USG_SET2_1",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1_set2,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t_set2_avail,
            provenance_ref="LEDGER_003",
        )
        usg_set2_2 = ProposedUsageEvidenceRecord(
            record_id="USG_SET2_2",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl2_set2,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t_set2_avail,
            provenance_ref="LEDGER_004",
        )
        auth_set2 = builder.validate_and_build(
            coverage_records=(),
            usage_records=(usg_set2_1, usg_set2_2),
            evaluation_time=t_set2_avail,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t_set2_avail,
            physical_levels=(lvl1_set2, lvl2_set2),
        )

        # Synchronize SET_2 through accepted adapter
        snap_act_set2 = synchronizer.sync(
            snap_tjl_set2,
            sequence_ref_start=2001,
            usage_evidence=auth_set2.resolved_usage_statuses,
        )
        mem_key_set2_tjl1 = format_member_key("SET_2", "TJL1")

        # SET_1 activation was moved to terminal_activations
        assert mem_key_set1_tjl1 not in snap_act_set2.active_activations
        assert mem_key_set1_tjl1 not in snap_act_set2.current_members
        assert len(snap_act_set2.terminal_activations) >= 1
        term_rec_set1 = [t for t in snap_act_set2.terminal_activations if t.member_key == mem_key_set1_tjl1][-1]
        assert term_rec_set1.state == ActivationState.CANCELLED_SOURCE_REPLACEMENT
        assert term_rec_set1.terminal is True

        # SET_2 is active
        assert mem_key_set2_tjl1 in snap_act_set2.active_activations
        assert snap_act_set2.active_activations[mem_key_set2_tjl1].state == ActivationState.INACTIVE_ELIGIBLE

        # Outgoing SET_1 cannot be revived: re-registration raises InvalidEvidenceError
        with pytest.raises(InvalidEvidenceError, match="Source cancellations permanently retire outgoing set identities"):
            act_engine.register_source_members([snap_act_set1.current_members[mem_key_set1_tjl1]])

        # 4. Evaluating cancelled SET_1 against updated context fails closed
        eval_time = t_set2_avail + timedelta(hours=12)
        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=eval_time,
            status=CoverageStatus.COMPLETE,
            issued_time=eval_time,
            available_time=eval_time,
            revision_seq=1,
        )
        auth_eval = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_set2_1, usg_set2_2),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=eval_time,
            physical_levels=(lvl1_set2, lvl2_set2),
        )
        synthetic_source_res = {m_k: True for m_k in snap_act_set2.current_members}
        ctx_replaced, _ = builder.build_matching_context(
            authority_result=auth_eval,
            base_members=snap_act_set2.current_members,
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=t0,
            expected_interval_end=eval_time,
            source_resolution_status=synthetic_source_res,
            active_activations=snap_act_set2.active_activations,
        )

        dummy_evidence = ConfirmationEvidenceRecord(
            event_id="EV_DUMMY",
            producer_id="PROD_CHOCH",
            confirmation_config_id=CONF_CFG,
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=t0 + timedelta(days=12),
            symbol=FEED_ID,
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PRICE_BASIS,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )

        res_old = matcher.match(term_rec_set1, dummy_evidence, ctx_replaced)
        assert res_old.status == ConfirmationMatchStatus.REJECTED
        assert res_old.candidate_record is None
        assert ConfirmationRejectionReason.MEMBERSHIP_CANCELLED_OR_REPLACED in res_old.rejection_reasons

    def test_synthetic_same_level_replacement_contract(self) -> None:
        """Synthetic Same-Level Replacement Contract:
        - Separately labeled synthetic specification contract where a physical level ID is shared across sets.
        - Resolves physical usage USED through AuthorityContextBuilder.
        - Incoming membership for SET_2 retains the physical-level USED status.
        - Matcher evaluation rejects incoming activation fail-closed with STALE_EVIDENCE_FOR_GENERATION.
        - Illegal successor proposal attempting to reset terminal USED to UNUSED is rejected with USAGE_USED_TERMINAL.
        """
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        matcher = ConfirmationMatcher()
        t0 = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
        eval_time = datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc)

        # Shared physical level across sets (Case B & C contract)
        shared_lvl = StableLevelId(
            symbol_feed_id=FEED_ID,
            source_timeframe="D1",
            source_open_time=t0,
            side=TJLSide.LOW,
        )

        # 1. Authority Terminal USED Retention:
        usg_root_used = ProposedUsageEvidenceRecord(
            record_id="USG_USED_TERMINAL_ROOT",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=shared_lvl,
            status=UsageEvidenceStatus.USED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_USED",
        )
        usg_illegal_reset = ProposedUsageEvidenceRecord(
            record_id="USG_ILLEGAL_RESET",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=shared_lvl,
            status=UsageEvidenceStatus.UNUSED,
            established_time=datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc),
            available_time=datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc),
            predecessor_record_id="USG_USED_TERMINAL_ROOT",
            provenance_ref="LEDGER_RESET",
        )
        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=t0 + timedelta(hours=10),
            status=CoverageStatus.COMPLETE,
            issued_time=t0 + timedelta(hours=10),
            available_time=t0 + timedelta(hours=10),
            revision_seq=1,
        )
        auth_used_chain = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_root_used, usg_illegal_reset),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t0 + timedelta(hours=10),
            physical_levels=(shared_lvl,),
        )
        assert auth_used_chain.resolved_usage_statuses[shared_lvl] == UsageEvidenceStatus.USED
        assert any(
            d.entity_key == "USG_ILLEGAL_RESET" and d.diagnostic_reason == AuthorityDiagnosticReason.USAGE_USED_TERMINAL
            for d in auth_used_chain.diagnostics
        )

        # 2. Incoming membership for SET_2 inherits and retains physical-level USED
        m_set2_shared = SourceMemberReference(
            engine_id="ENGINE_EURUSD_D1",
            symbol=FEED_ID,
            source_timeframe="D1",
            set_id="SET_2",
            role="TJL1",
            side="LOW",
            lower_edge=1.1810,
            upper_edge=1.1860,
            is_line=False,
            direction=Direction.DOWNWARD,
            level_id=shared_lvl,
            eligibility_available_time=t0,
            usage_evidence_status=UsageEvidenceStatus.USED,  # Retains physical level usage
        )
        act_set2_shared = ActivationRecord(
            activation_id="ACT_SET2_TJL1",
            engine_id="ENGINE_EURUSD_D1",
            symbol=FEED_ID,
            source_timeframe="D1",
            confirmation_timeframe="H1",
            set_id="SET_2",
            role="TJL1",
            level_id=shared_lvl,
            lower_edge=1.1810,
            upper_edge=1.1860,
            state=ActivationState.PENDING_ACTIVATION,
            first_touch_time=datetime(2026, 10, 11, 8, 30, tzinfo=timezone.utc),
            first_touch_price=1.1825,
            trigger_observation_id="OBS_01",
            generation_seq=1,
            usage_evidence_status=UsageEvidenceStatus.USED,
        )

        ctx_shared, _ = builder.build_matching_context(
            authority_result=auth_used_chain,
            base_members={m_set2_shared.member_key: m_set2_shared},
            domain_session_id="SESS_01",
            revision_id="REV_01",
            expected_price_basis=PRICE_BASIS,
            expected_confirmation_config_id=CONF_CFG,
            matching_sequence_domain=DEFAULT_DOMAIN,
            evaluation_time=eval_time,
            expected_timeframe="H1",
            expected_interval_start=t0,
            expected_interval_end=t0 + timedelta(hours=10),
            source_resolution_status={m_set2_shared.member_key: True},
            active_activations={m_set2_shared.member_key: act_set2_shared},
        )

        dummy_evidence = ConfirmationEvidenceRecord(
            event_id="EV_DUMMY",
            producer_id="PROD_CHOCH",
            confirmation_config_id=CONF_CFG,
            confirmation_timeframe="H1",
            confirmation_candle_id="CANDLE_01",
            direction=Direction.DOWNWARD,
            pattern_type="CHOCH",
            close_price=1.1350,
            close_timestamp=t0 + timedelta(hours=9),
            symbol=FEED_ID,
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            price_basis=PRICE_BASIS,
            provenance_type=EvidenceProvenanceType.SYNTHETIC_TYPED,
            structural_dependency_references=("DEP_01",),
        )

        # Matcher evaluation with USED status fails closed
        res_shared = matcher.match(act_set2_shared, dummy_evidence, ctx_shared)
        assert res_shared.status == ConfirmationMatchStatus.REJECTED
        assert res_shared.candidate_record is None
        assert ConfirmationRejectionReason.STALE_EVIDENCE_FOR_GENERATION in res_shared.rejection_reasons

    def test_synthetic_activation_used_metadata_consistency_contract(self) -> None:
        """Synthetic Activation USED Metadata Consistency Contract:
        - Separately labeled synthetic composition contract:
        - Synthetic immutable usage-metadata consistency check.
        - Proves rejection of USED activation metadata against UNUSED authority (not archival terminal-history behavior).
        """
        builder = AuthorityContextBuilder(trust_config=DEFAULT_TRUST)
        t0 = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)
        eval_time = datetime(2026, 10, 11, 10, 30, tzinfo=timezone.utc)

        lvl1 = StableLevelId(
            symbol_feed_id=FEED_ID,
            source_timeframe="D1",
            source_open_time=t0,
            side=TJLSide.LOW,
        )
        mem1 = SourceMemberReference(
            engine_id="ENGINE_EURUSD_D1",
            symbol=FEED_ID,
            source_timeframe="D1",
            set_id="SET_1",
            role="TJL1",
            side="LOW",
            lower_edge=1.18,
            upper_edge=1.185,
            is_line=False,
            direction=Direction.DOWNWARD,
            level_id=lvl1,
            eligibility_available_time=t0,
            usage_evidence_status=UsageEvidenceStatus.UNUSED,
        )
        act_used_synthetic = ActivationRecord(
            activation_id="ACT_SYNTHETIC_USED",
            engine_id="ENGINE_EURUSD_D1",
            symbol=FEED_ID,
            source_timeframe="D1",
            confirmation_timeframe="H1",
            set_id="SET_1",
            role="TJL1",
            level_id=lvl1,
            lower_edge=1.18,
            upper_edge=1.185,
            state=ActivationState.INACTIVE_INELIGIBLE,
            usage_evidence_status=UsageEvidenceStatus.USED,  # Synthetic terminal USED
        )

        cov_rec = ProposedFeedCoverageRecord(
            record_id="COV_01",
            schema_version="v1",
            issuer_id="OFFLINE_FEED_AUDITOR_v1",
            feed_id=FEED_ID,
            sequence_domain=DEFAULT_DOMAIN,
            timeframe="H1",
            confirmation_config_id=CONF_CFG,
            covered_interval_start=t0,
            covered_interval_end=t0 + timedelta(hours=10),
            status=CoverageStatus.COMPLETE,
            issued_time=t0 + timedelta(hours=10),
            available_time=t0 + timedelta(hours=10),
            revision_seq=1,
        )
        usg_unused_eval = ProposedUsageEvidenceRecord(
            record_id="USG_UNUSED_EVAL",
            schema_version="v1",
            issuer_id="UPSTREAM_TRADE_LEDGER_OFFLINE",
            level_id=lvl1,
            status=UsageEvidenceStatus.UNUSED,
            established_time=t0,
            available_time=t0,
            provenance_ref="LEDGER_UNUSED",
        )
        auth_eval_unused = builder.validate_and_build(
            coverage_records=(cov_rec,),
            usage_records=(usg_unused_eval,),
            evaluation_time=eval_time,
            target_feed_id=FEED_ID,
            target_sequence_domain=DEFAULT_DOMAIN,
            target_timeframe="H1",
            target_confirmation_config_id=CONF_CFG,
            required_interval_start=t0,
            required_interval_end=t0 + timedelta(hours=10),
            physical_levels=(lvl1,),
        )
        assert auth_eval_unused.resolved_usage_statuses[lvl1] == UsageEvidenceStatus.UNUSED

        with pytest.raises(ValueError, match="contradicts immutable activation history"):
            builder.build_matching_context(
                authority_result=auth_eval_unused,
                base_members={mem1.member_key: mem1},
                domain_session_id="SESS_01",
                revision_id="REV_01",
                expected_price_basis=PRICE_BASIS,
                expected_confirmation_config_id=CONF_CFG,
                matching_sequence_domain=DEFAULT_DOMAIN,
                evaluation_time=eval_time,
                expected_timeframe="H1",
                expected_interval_start=t0,
                expected_interval_end=t0 + timedelta(hours=10),
                source_resolution_status={mem1.member_key: True},
                active_activations={mem1.member_key: act_used_synthetic},
            )
